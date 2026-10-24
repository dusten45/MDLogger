"""업데이트 확인과 설치 인계를 UI 스레드에서 분리한다."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from .ui.update_dialog import UpdateDialog

if TYPE_CHECKING:
    from .updater import DownloadedUpdate, UpdatePlan


class UpdateController(QObject):
    """다운로드가 검증되고 실행기가 준비된 경우에만 앱 종료를 요청한다."""

    _completed = Signal(str, object, object)
    _progress = Signal(int, int)

    def __init__(
        self,
        version: str,
        *,
        parent_window: Callable[[], QWidget | None],
        ready_to_install: Callable[[], bool],
        pause: Callable[[], bool],
        resume: Callable[[], None],
        data_dir: Path,
        check: Callable[[], UpdatePlan | None],
        download: Callable[..., DownloadedUpdate],
        launch: Callable[..., Any],
        enabled: bool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._version = version
        self._parent_window = parent_window
        self._ready_to_install = ready_to_install
        self._pause = pause
        self._resume = resume
        self._data_dir = data_dir
        self._check = check
        self._download = download
        self._launch = launch
        self._enabled = (
            sys.platform == "win32" and bool(getattr(sys, "frozen", False))
            if enabled is None
            else enabled
        )
        self._dialog: UpdateDialog | None = None
        self._plan: UpdatePlan | None = None
        self._downloaded: DownloadedUpdate | None = None
        self._cancelled = Event()
        self._thread: Thread | None = None
        self._busy = False
        self._manual = False
        self._closed = False
        self._paused = False
        self._deferred_offer = QTimer(self)
        self._deferred_offer.setSingleShot(True)
        self._deferred_offer.timeout.connect(self._show_offer)
        self._completed.connect(self._on_completed)
        self._progress.connect(self._on_progress)

    def check_for_updates(self, *, manual: bool = False) -> None:
        if self._closed:
            return
        if not self._enabled:
            if manual:
                QMessageBox.information(
                    self._parent_window(),
                    "수동 업데이트",
                    "자동 업데이트는 설치된 Windows 앱에서만 지원합니다. "
                    "Linux에서는 새 설치 파일을 받아 수동으로 업데이트해 주세요.",
                )
            return
        if self._busy:
            if self._dialog is not None:
                self._dialog.raise_()
            return
        self._cancelled.clear()
        self._deferred_offer.stop()
        self._manual = manual
        self._run("check", self._check)

    def close(self) -> None:
        self._closed = True
        self._cancelled.set()
        self._deferred_offer.stop()

    def _run(self, stage: str, operation: Callable[[], Any]) -> None:
        self._busy = True

        def run() -> None:
            try:
                result = operation()
            except Exception as error:
                self._completed.emit(stage, None, error)
            else:
                self._completed.emit(stage, result, None)

        self._thread = Thread(target=run, name=f"mdlogger-update-{stage}", daemon=True)
        self._thread.start()

    @Slot(str, object, object)
    def _on_completed(self, stage: str, result: Any, error: Exception | None) -> None:
        self._busy = False
        if self._closed:
            return
        if error is not None:
            if stage == "launch":
                # 실행기가 한 번 사용한 디렉터리는 새 인계 작업에 재사용하지 않는다.
                self._downloaded = None
            if self._paused or stage == "pause":
                self._resume()
                self._paused = False
            if self._cancelled.is_set():
                return
            message = f"업데이트를 완료하지 못했습니다.\n{error}"
            if stage == "check":
                if self._manual:
                    QMessageBox.warning(
                        self._parent_window(), "업데이트 확인 실패", message
                    )
            elif self._dialog is not None:
                self._dialog.set_error(message)
            return
        if stage == "check":
            if result is None:
                if self._manual:
                    QMessageBox.information(
                        self._parent_window(), "업데이트", "최신 버전을 사용 중입니다."
                    )
                return
            self._plan = result
            self._downloaded = None
            self._show_offer()
        elif stage == "download":
            if self._cancelled.is_set():
                return
            self._downloaded = result
            self._handoff()
        elif stage == "pause":
            if result is not True:
                self._resume()
                if self._dialog is not None:
                    self._dialog.set_error(
                        "진행 중인 작업을 아직 종료하지 못했습니다. "
                        "잠시 후 다시 시도해 주세요."
                    )
                return
            self._paused = True
            downloaded = self._downloaded
            if downloaded is None:
                self._resume()
                self._paused = False
                return
            self._run(
                "launch",
                lambda: self._launch(downloaded, os.getpid(), data_dir=self._data_dir),
            )
        elif stage == "launch":
            if self._dialog is not None:
                self._dialog.finish_handoff()
            # 입력과 작업 정지를 확인한 종료다. 일반 창의 닫기 거부와 분리하고,
            # app.main의 finally에서 연결·창을 정리한 뒤 실제 프로세스가 끝난다.
            QApplication.exit(0)

    @Slot()
    def _show_offer(self) -> None:
        if self._closed or self._busy or self._plan is None:
            return
        if not self._manual and (
            QApplication.activeModalWidget() is not None or not self._ready_to_install()
        ):
            self._deferred_offer.start(30_000)
            return
        if self._dialog is not None:
            self._dialog.hide()
            self._dialog.deleteLater()
        self._dialog = UpdateDialog(
            self._version, self._plan.version, self._parent_window()
        )
        self._dialog.install_requested.connect(self._begin_install)
        self._dialog.cancellation_requested.connect(self._cancelled.set)
        self._dialog.open()

    @Slot(int, int)
    def _on_progress(self, received: int, total: int) -> None:
        if not self._closed and self._dialog is not None:
            self._dialog.set_progress(received, total)

    @Slot()
    def _begin_install(self) -> None:
        if self._busy or self._plan is None or self._dialog is None:
            return
        self._cancelled.clear()
        if self._downloaded is not None:
            self._handoff()
            return
        plan = self._plan
        self._dialog.set_downloading()
        self._run(
            "download",
            lambda: self._download(
                plan,
                progress=self._progress.emit,
                cancelled=self._cancelled.is_set,
            ),
        )

    def _handoff(self) -> None:
        dialog = self._dialog
        downloaded = self._downloaded
        if dialog is None or downloaded is None:
            return
        if not self._ready_to_install():
            dialog.set_error(
                "입력 중인 전적이나 열린 편집 창을 먼저 정리해 주세요. "
                "다운로드한 설치 파일은 보존됩니다."
            )
            return
        dialog.set_installing()
        self._run("pause", self._pause)
