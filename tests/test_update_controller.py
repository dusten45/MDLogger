"""업데이트 승인과 안전한 종료 인계를 실제 설치 없이 검증한다."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from mdlogger.update_controller import UpdateController


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def wait_until(qapp: QApplication, predicate) -> None:
    end = time.monotonic() + 3
    while not predicate() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.001)
    assert predicate(), "업데이트 작업이 제시간에 완료되지 않았습니다."


@pytest.fixture
def update_controller(qapp: QApplication, tmp_path: Path):
    created: list[UpdateController] = []

    def make(**overrides):
        plan: Any = SimpleNamespace(version="2.2.0")
        downloaded: Any = SimpleNamespace(installer_path=tmp_path / "installer.exe")
        options: dict[str, Any] = {
            "parent_window": lambda: None,
            "ready_to_install": lambda: True,
            "pause": lambda: True,
            "resume": lambda: None,
            "data_dir": tmp_path,
            "check": lambda: plan,
            "download": lambda *args, **kwargs: downloaded,
            "launch": lambda *args, **kwargs: object(),
            "enabled": True,
        }
        options.update(overrides)
        controller = UpdateController("2.1.0", **options)
        created.append(controller)
        return controller

    yield make
    for controller in created:
        controller.close()
        if controller._dialog is not None:
            controller._dialog.hide()
            controller._dialog.deleteLater()
        controller.deleteLater()
    qapp.processEvents()


def test_install_only_after_explicit_approval_and_helper_ready(
    qapp, update_controller, monkeypatch
):
    operations = []
    monkeypatch.setattr(QApplication, "exit", lambda code: operations.append("quit"))
    controller = update_controller(
        pause=lambda: operations.append("pause") or True,
        launch=lambda *args, **kwargs: operations.append("launch") or object(),
    )
    controller.check_for_updates(manual=True)
    wait_until(qapp, lambda: controller._dialog is not None)
    assert operations == []
    controller._begin_install()
    wait_until(qapp, lambda: "quit" in operations)
    assert operations == ["pause", "launch", "quit"]


def test_busy_input_never_launches_installer(qapp, update_controller, monkeypatch):
    operations = []
    monkeypatch.setattr(QApplication, "exit", lambda code: operations.append("quit"))
    controller = update_controller(
        ready_to_install=lambda: False,
        launch=lambda *args, **kwargs: operations.append("launch"),
    )
    controller.check_for_updates(manual=True)
    wait_until(qapp, lambda: controller._dialog is not None)
    controller._begin_install()
    wait_until(qapp, lambda: not controller._busy)
    assert operations == []
    assert controller._dialog is not None
    assert "입력 중인 전적" in controller._dialog._status.text()


def test_failed_helper_launch_resumes_sync(qapp, update_controller, monkeypatch):
    operations = []

    def fail(*args, **kwargs):
        raise OSError("실행기를 시작할 수 없습니다.")

    monkeypatch.setattr(QApplication, "exit", lambda code: operations.append("quit"))
    controller = update_controller(
        pause=lambda: operations.append("pause") or True,
        resume=lambda: operations.append("resume"),
        launch=fail,
    )
    controller.check_for_updates(manual=True)
    wait_until(qapp, lambda: controller._dialog is not None)
    controller._begin_install()
    wait_until(qapp, lambda: "resume" in operations)
    assert operations == ["pause", "resume"]
    assert controller._dialog is not None
    assert controller._dialog._install.isEnabled()


def test_unsupported_platform_does_not_contact_release_server(
    update_controller, monkeypatch
):
    notices = []
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: notices.append(args))
    controller = update_controller(enabled=False, check=lambda: calls.append(True))
    controller.check_for_updates()
    assert notices == []
    controller.check_for_updates(manual=True)
    assert calls == []
    assert "Linux" in notices[0][2]


def test_startup_offer_waits_for_input_to_finish(qapp, update_controller):
    controller = update_controller(ready_to_install=lambda: False)
    controller.check_for_updates()
    wait_until(qapp, lambda: not controller._busy)
    assert controller._dialog is None
    assert controller._deferred_offer.isActive()


def test_successful_handoff_exits_real_qt_loop(tmp_path: Path):
    script = textwrap.dedent(
        """
        import json
        import sys
        from pathlib import Path
        from types import SimpleNamespace
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QWidget
        from mdlogger.update_controller import UpdateController

        app = QApplication([])
        window = QWidget()
        window.show()
        operations = []
        app.aboutToQuit.connect(lambda: operations.append('about-to-quit'))
        controller = UpdateController(
            '2.1.0', parent_window=lambda: window,
            ready_to_install=lambda: True,
            pause=lambda: operations.append('pause') or True,
            resume=lambda: operations.append('resume'),
            data_dir=Path(sys.argv[1]),
            check=lambda: SimpleNamespace(version='2.2.0'),
            download=lambda *args, **kwargs: object(),
            launch=lambda *args, **kwargs: operations.append('launch') or object(),
            enabled=True,
        )
        begin = QTimer()
        def approve():
            if controller._dialog is not None:
                begin.stop()
                controller._begin_install()
        begin.timeout.connect(approve)
        begin.start(5)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: app.exit(91))
        watchdog.start(3000)
        controller.check_for_updates(manual=True)
        code = app.exec()
        controller.close()
        print(json.dumps({
            'code': code, 'operations': operations,
            'dialog_visible': controller._dialog.isVisible(),
        }))
        sys.exit(code)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = json.loads(result.stdout.strip().splitlines()[-1])
    assert outcome["operations"] == ["pause", "launch", "about-to-quit"]
    assert outcome["dialog_visible"] is False


def test_failed_handoff_downloads_a_fresh_job_on_retry(qapp, update_controller):
    downloads = []
    resumed = []

    def download(*args, **kwargs):
        downloads.append(object())
        return downloads[-1]

    def launch(*args, **kwargs):
        raise OSError("실행기 인계 실패")

    controller = update_controller(
        download=download, launch=launch, resume=lambda: resumed.append(True)
    )
    controller.check_for_updates(manual=True)
    wait_until(qapp, lambda: controller._dialog is not None)
    controller._begin_install()
    wait_until(qapp, lambda: len(resumed) == 1)
    assert controller._downloaded is None
    controller._begin_install()
    wait_until(qapp, lambda: len(resumed) == 2)
    assert len(downloads) == 2
