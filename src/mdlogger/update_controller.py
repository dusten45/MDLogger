"""업데이트 확인과 설치 인계를 UI 스레드에서 분리한다."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from threading import Event, RLock, Thread
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from shiboken6 import isValid

from .ui.update_dialog import UpdateDialog

if TYPE_CHECKING:
    from .updater import DownloadedUpdate, UpdateJob, UpdatePlan

_log = logging.getLogger(__name__)


class UpdateController(QObject):
    """다운로드가 검증되고 실행기가 준비된 경우에만 앱 종료를 요청한다."""

    _completed = Signal(int, str, object, object)
    _progress = Signal(int, int, int)

    def __init__(
        self,
        version: str,
        *,
        parent_window: Callable[[], QWidget | None],
        ready_to_install: Callable[[], bool],
        begin_handoff: Callable[[], bool],
        handoff_is_current: Callable[[], bool],
        end_handoff: Callable[[], None],
        pause: Callable[[], bool],
        resume: Callable[[], None],
        data_dir: Path,
        check: Callable[[], UpdatePlan | None],
        download: Callable[..., DownloadedUpdate],
        launch: Callable[..., UpdateJob],
        authorize: Callable[[UpdateJob], None],
        cancel: Callable[[UpdateJob], None],
        enabled: bool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._version = version
        self._parent_window = parent_window
        self._ready_to_install = ready_to_install
        self._begin_handoff = begin_handoff
        self._handoff_is_current = handoff_is_current
        self._end_handoff = end_handoff
        self._pause = pause
        self._resume = resume
        self._data_dir = data_dir
        self._check = check
        self._download = download
        self._launch = launch
        self._authorize = authorize
        self._cancel = cancel
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
        self._handoff_started = False
        self._handoff_committed = False
        self._generation = 0
        self._job: UpdateJob | None = None
        self._job_lock = RLock()
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
        if self._busy or (self._dialog is not None and self._dialog.isVisible()):
            if self._dialog is not None:
                self._dialog.raise_()
            return
        self._generation += 1
        self._cancelled.clear()
        self._deferred_offer.stop()
        self._manual = manual
        self._run("check", self._check)

    def close(self) -> None:
        with self._job_lock:
            self._closed = True
            if not self._handoff_committed:
                self._cancelled.set()
                try:
                    self._cancel_job()
                except Exception:
                    # 승인 전 작업이므로 이후 평범한 종료로 설치가 시작되지는 않는다.
                    _log.warning(
                        "승인 전 업데이트 작업의 취소 표식을 기록하지 못했습니다."
                    )
        self._deferred_offer.stop()
        if not self._busy and not self._handoff_committed:
            self._release_handoff()

    def _cancel_job(self) -> None:
        with self._job_lock:
            if self._job is not None:
                self._downloaded = None
                self._cancel(self._job)
                self._job = None

    def _release_handoff(self) -> None:
        if not self._handoff_started:
            return
        try:
            if self._paused and not self._closed:
                self._resume()
        finally:
            self._paused = False
            self._handoff_started = False
            self._end_handoff()

    def _fail_handoff(self, message: str) -> None:
        try:
            self._cancel_job()
        except Exception:
            message += "\n업데이트 준비 취소를 확인하지 못했습니다. 다시 시도해 주세요."
        self._release_handoff()
        if not self._closed and self._dialog is not None:
            self._dialog.set_error(message)

    def _handoff_valid(self) -> bool:
        return (
            not self._closed
            and not self._cancelled.is_set()
            and self._dialog is not None
            and isValid(self._dialog)
            and self._dialog.isVisible()
            and self._handoff_is_current()
            and self._ready_to_install()
        )

    def _run(self, stage: str, operation: Callable[[], Any]) -> None:
        self._busy = True
        generation = self._generation

        def run() -> None:
            try:
                result = operation()
                if stage == "launch":
                    with self._job_lock:
                        self._job = result
                        if self._closed or self._cancelled.is_set():
                            self._cancel_job()
            except Exception as error:
                if isValid(self):
                    self._completed.emit(generation, stage, None, error)
            else:
                if isValid(self):
                    self._completed.emit(generation, stage, result, None)

        self._thread = Thread(target=run, name=f"mdlogger-update-{stage}", daemon=True)
        self._thread.start()

    @Slot(int, str, object, object)
    def _on_completed(
        self, generation: int, stage: str, result: Any, error: Exception | None
    ) -> None:
        if generation != self._generation:
            if stage == "launch" and result is not None:
                with self._job_lock:
                    try:
                        self._cancel(result)
                    except Exception:
                        _log.warning(
                            "이전 업데이트 작업의 취소 표식을 기록하지 못했습니다."
                        )
                    else:
                        if self._job is result:
                            self._job = None
            return
        self._busy = False
        if self._closed:
            self._release_handoff()
            return
        if error is not None:
            if stage == "launch":
                # 실행기가 한 번 사용한 디렉터리는 새 인계 작업에 재사용하지 않는다.
                self._downloaded = None
            message = f"업데이트를 완료하지 못했습니다.\n{error}"
            if stage == "check":
                if self._manual:
                    QMessageBox.warning(
                        self._parent_window(), "업데이트 확인 실패", message
                    )
            else:
                self._fail_handoff(message)
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
            if not self._handoff_valid():
                self._fail_handoff(
                    "입력이나 프로필 상태가 변경되어 업데이트 준비를 취소했습니다."
                )
                return
            if result is not True:
                self._fail_handoff(
                    "진행 중인 작업을 아직 종료하지 못했습니다. "
                    "잠시 후 다시 시도해 주세요."
                )
                return
            downloaded = self._downloaded
            if downloaded is None:
                self._fail_handoff("업데이트 설치 파일을 다시 내려받아 주세요.")
                return
            self._run(
                "launch",
                lambda: self._launch(downloaded, os.getpid(), data_dir=self._data_dir),
            )
        elif stage == "launch":
            if not self._handoff_valid():
                self._fail_handoff(
                    "입력이나 프로필 상태가 변경되어 업데이트 준비를 취소했습니다."
                )
                return
            try:
                with self._job_lock:
                    self._authorize(result)
                    self._handoff_committed = True
                    self._job = None
            except Exception as failure:
                self._fail_handoff(f"업데이트 설치를 승인하지 못했습니다.\n{failure}")
                return
            assert self._dialog is not None
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
        dialog = self._dialog

        def destroyed() -> None:
            if self._dialog is dialog:
                self._dialog = None
                if not self._handoff_committed:
                    self._cancelled.set()
                    if not self._busy:
                        self._fail_handoff("")

        dialog.destroyed.connect(destroyed)
        # open()은 WindowModal로 바꾸므로 명시한 ApplicationModal을 유지한다.
        dialog.show()

    @Slot(int, int, int)
    def _on_progress(self, generation: int, received: int, total: int) -> None:
        if (
            not self._closed
            and not self._cancelled.is_set()
            and generation == self._generation
            and self._dialog is not None
        ):
            self._dialog.set_progress(received, total)

    @Slot()
    def _begin_install(self) -> None:
        if self._closed or self._busy or self._plan is None or self._dialog is None:
            return
        try:
            self._cancel_job()
        except Exception:
            self._dialog.set_error(
                "이전 업데이트 준비를 취소하지 못했습니다. 잠시 후 다시 시도해 주세요."
            )
            return
        self._generation += 1
        generation = self._generation
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
                progress=lambda received, total: self._progress.emit(
                    generation, received, total
                ),
                cancelled=self._cancelled.is_set,
            ),
        )

    def _handoff(self) -> None:
        dialog = self._dialog
        downloaded = self._downloaded
        if dialog is None or downloaded is None:
            return
        if not self._ready_to_install() or not self._begin_handoff():
            dialog.set_error(
                "입력 중인 전적이나 열린 편집 창을 먼저 정리해 주세요. "
                "다운로드한 설치 파일은 보존됩니다."
            )
            return
        self._handoff_started = True
        self._paused = True
        dialog.set_installing()
        self._run("pause", self._pause)
