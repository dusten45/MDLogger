"""업데이트 승인과 안전한 종료 인계를 실제 설치 없이 검증한다."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from mdlogger.app_controller import AppController
from mdlogger.app_settings import MemorySettingsStore
from mdlogger.game_service import GameService
from mdlogger.profile_router import CONSENT_VERSION, ProfileRouter
from mdlogger.profiles import ProfileManager
from mdlogger.ui.main_window import MainWindow
from mdlogger.update_controller import UpdateController
from mdlogger.updater import UpdateJob, _write_json, authorize_update, cancel_update


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
            "begin_handoff": lambda: True,
            "handoff_is_current": lambda: True,
            "end_handoff": lambda: None,
            "pause": lambda: True,
            "resume": lambda: None,
            "data_dir": tmp_path,
            "check": lambda: plan,
            "download": lambda *args, **kwargs: downloaded,
            "launch": lambda *args, **kwargs: object(),
            "authorize": lambda job: None,
            "cancel": lambda job: None,
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
            begin_handoff=lambda: True,
            handoff_is_current=lambda: True,
            end_handoff=lambda: None,
            pause=lambda: operations.append('pause') or True,
            resume=lambda: operations.append('resume'),
            data_dir=Path(sys.argv[1]),
            check=lambda: SimpleNamespace(version='2.2.0'),
            download=lambda *args, **kwargs: object(),
            launch=lambda *args, **kwargs: operations.append('launch') or object(),
            authorize=lambda job: None,
            cancel=lambda job: operations.append('cancel'),
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


def test_update_offer_is_application_modal_with_independent_window(
    qapp, update_controller
):
    main = QWidget()
    auth = QWidget()
    main.show()
    auth.show()
    controller = update_controller(parent_window=lambda: main)
    controller.check_for_updates(manual=True)
    wait_until(qapp, lambda: controller._dialog is not None)
    assert controller._dialog.windowModality() is Qt.WindowModality.ApplicationModal
    assert QApplication.activeModalWidget() is controller._dialog


def test_input_changed_during_helper_preparation_does_not_exit(
    qapp, update_controller, monkeypatch
):
    entered, release = Event(), Event()
    operations = []
    ready = True

    def launch(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return object()

    monkeypatch.setattr(QApplication, "exit", lambda code: operations.append("quit"))
    controller = update_controller(
        ready_to_install=lambda: ready,
        launch=launch,
        resume=lambda: operations.append("resume"),
    )
    controller.check_for_updates(manual=True)
    wait_until(qapp, lambda: controller._dialog is not None)
    controller._begin_install()
    try:
        wait_until(qapp, entered.is_set)
        ready = False
    finally:
        release.set()
    wait_until(qapp, lambda: not controller._busy)
    assert "quit" not in operations
    assert operations == ["resume"]


@pytest.fixture
def desktop_update(qapp, update_controller, tmp_path):
    profiles = ProfileManager(tmp_path)
    profiles.accept_data_consent(CONSENT_VERSION)
    controller = AppController(
        profiles,
        service_factory=lambda profile: GameService.open(profile.database_path),
        window_factory=lambda games, profile: MainWindow(games, ["테스트 덱"], profile),
    )
    router = ProfileRouter(
        profiles, controller, None, settings_store=MemorySettingsStore()
    )
    router.request_guest()
    router.show_auth()

    def make(**overrides):
        return update_controller(
            parent_window=lambda: controller.current_window,
            ready_to_install=router.ready_for_update,
            begin_handoff=router.begin_update,
            handoff_is_current=router.update_is_current,
            end_handoff=router.end_update,
            pause=controller.pause_for_update,
            resume=controller.resume_after_update,
            **overrides,
        )

    yield controller, router, make
    router.close()
    controller.close()


def test_real_router_blocks_programmatic_switches_during_handoff(
    qapp, desktop_update, monkeypatch
):
    controller, router, make = desktop_update
    entered, release = Event(), Event()
    operations = []
    blocked = set()

    class WatchBlocked(QObject):
        def eventFilter(self, watched, event):
            if event.type() is QEvent.Type.WindowBlocked:
                blocked.add(watched)
            return False

    watcher = WatchBlocked()
    window = controller.current_window
    window.installEventFilter(watcher)
    router.auth_window.installEventFilter(watcher)

    def launch(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return object()

    monkeypatch.setattr(QApplication, "exit", lambda code: operations.append("quit"))
    updates = make(launch=launch, authorize=lambda job: operations.append("authorize"))
    updates.check_for_updates(manual=True)
    wait_until(qapp, lambda: updates._dialog is not None)
    assert {window, router.auth_window} <= blocked
    updates._begin_install()
    try:
        wait_until(qapp, entered.is_set)
        assert controller.update_in_progress
        router.request_guest()
        router.auth_window._guest.click()
        router.sign_in("test@example.invalid", "unused")
        router._start_sign_in("test@example.invalid", "unused")
        router._reset_application()
        assert controller.current_window is window
        assert not router._pending
        with pytest.raises(RuntimeError, match="업데이트 준비"):
            controller.start_guest()
    finally:
        release.set()
    wait_until(qapp, lambda: "quit" in operations)
    assert operations == ["authorize", "quit"]
    updates.close()
    assert operations == ["authorize", "quit"]


@pytest.mark.parametrize("stage", ["download", "pause", "launch"])
def test_input_is_preserved_and_handoff_cancelled_at_each_stage(
    qapp, desktop_update, monkeypatch, stage
):
    controller, router, make = desktop_update
    entered, release = Event(), Event()
    operations = []

    def delay(result):
        entered.set()
        assert release.wait(3)
        return result

    updates = make(
        download=lambda *args, **kwargs: (
            delay(object()) if stage == "download" else object()
        ),
        launch=lambda *args, **kwargs: (
            delay(object()) if stage == "launch" else object()
        ),
        authorize=lambda job: operations.append("authorize"),
        cancel=lambda job: operations.append("cancel"),
    )
    if stage == "pause":
        updates._pause = lambda: delay(True)
    monkeypatch.setattr(QApplication, "exit", lambda code: operations.append("quit"))
    updates.check_for_updates(manual=True)
    wait_until(qapp, lambda: updates._dialog is not None)
    updates._begin_install()
    try:
        wait_until(qapp, entered.is_set)
        router.auth_window._email.setText("preserved@example.invalid")
    finally:
        release.set()
    wait_until(qapp, lambda: not updates._busy)
    assert "authorize" not in operations and "quit" not in operations
    assert operations == (["cancel"] if stage == "launch" else [])
    assert not controller.update_in_progress
    assert router.auth_window._email.text() == "preserved@example.invalid"
    assert updates._dialog._install.isEnabled()


@pytest.mark.parametrize("destroy", ["dialog", "profile", "controller"])
def test_destroyed_scope_cancels_late_helper_without_authorization(
    qapp, desktop_update, monkeypatch, destroy
):
    controller, router, make = desktop_update
    entered, release = Event(), Event()
    operations = []

    def launch(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return object()

    updates = make(
        launch=launch,
        authorize=lambda job: operations.append("authorize"),
        cancel=lambda job: operations.append("cancel"),
    )
    monkeypatch.setattr(QApplication, "exit", lambda code: operations.append("quit"))
    updates.check_for_updates(manual=True)
    wait_until(qapp, lambda: updates._dialog is not None)
    updates._begin_install()
    try:
        wait_until(qapp, entered.is_set)
        if destroy == "dialog":
            updates._dialog.deleteLater()
        elif destroy == "profile":
            controller.close()
        else:
            updates.close()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        release.set()
    wait_until(qapp, lambda: not updates._busy)
    assert operations == ["cancel"]
    assert not controller.update_in_progress
    assert updates._downloaded is None
    if destroy != "controller":
        router.request_guest()
        assert controller.current_profile is not None


def test_timeout_releases_handoff_and_resumes_only_captured_worker(
    qapp, desktop_update
):
    controller, router, make = desktop_update
    operations = []
    original: Any = SimpleNamespace(
        stop=lambda: False, resume=lambda: operations.append("resume-original")
    )
    controller._sync = original
    updates = make()
    updates.check_for_updates(manual=True)
    wait_until(qapp, lambda: updates._dialog is not None)
    updates._begin_install()
    wait_until(qapp, lambda: not updates._busy)
    assert operations == ["resume-original"]
    assert not controller.update_in_progress
    assert updates._dialog._install.isEnabled()

    assert router.begin_update()
    controller.close()
    router.end_update()
    replacement: Any = SimpleNamespace(
        stop=lambda: True, resume=lambda: operations.append("resume-replacement")
    )
    controller._sync = replacement
    controller.resume_after_update()
    assert operations == ["resume-original"]


def test_cancelled_prepared_helper_requires_fresh_download_on_retry(
    qapp, update_controller, monkeypatch
):
    entered, release = Event(), Event()
    downloads, launched, cancelled, authorized = [], [], [], []
    ready = True
    exits = []

    def download(*args, **kwargs):
        result = object()
        downloads.append(result)
        return result

    def launch(downloaded, *args, **kwargs):
        launched.append(downloaded)
        if len(launched) == 1:
            entered.set()
            assert release.wait(3)
        return downloaded

    updates = update_controller(
        ready_to_install=lambda: ready,
        download=download,
        launch=launch,
        cancel=cancelled.append,
        authorize=authorized.append,
    )
    monkeypatch.setattr(QApplication, "exit", exits.append)
    updates.check_for_updates(manual=True)
    wait_until(qapp, lambda: updates._dialog is not None)
    updates._begin_install()
    try:
        wait_until(qapp, entered.is_set)
        ready = False
    finally:
        release.set()
    wait_until(qapp, lambda: not updates._busy)
    assert cancelled == [downloads[0]] and not authorized and not exits
    ready = True
    updates._begin_install()
    wait_until(qapp, lambda: bool(exits))
    assert len(downloads) == 2 and downloads[0] is not downloads[1]
    assert launched == downloads
    assert authorized == [downloads[1]]
    updates.close()
    assert cancelled == [downloads[0]]


def test_obsolete_completion_cancels_only_its_own_helper(qapp, update_controller):
    cancelled = []
    updates = update_controller(cancel=cancelled.append)
    updates.check_for_updates(manual=True)
    wait_until(qapp, lambda: updates._dialog is not None)
    old_job: Any = object()
    current_job: Any = object()
    updates._job = current_job
    updates._busy = True
    updates._on_completed(updates._generation - 1, "launch", old_job, None)
    updates._on_progress(updates._generation - 1, 100, 100)
    assert cancelled == [old_job]
    assert updates._job is current_job and updates._busy
    assert updates._dialog._progress.value() == 0
    updates._busy = False


@pytest.mark.parametrize("phase", ["failed", "cancelled"])
def test_terminal_helper_can_be_retired_and_retried(
    qapp, update_controller, monkeypatch, tmp_path, phase
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    downloads = []
    exits = []
    monkeypatch.setattr(QApplication, "exit", exits.append)

    def download(*args, **kwargs):
        directory = tmp_path / "MDLogger" / "updates" / f"{len(downloads):032x}"
        directory.mkdir(parents=True)
        item = SimpleNamespace(directory=directory)
        downloads.append(item)
        return item

    def launch(item, *args, **kwargs):
        job = UpdateJob(item.directory, "a" * 64, 123)
        _write_json(
            item.directory / "job.json", {"token": job.token, "version": "2.1.1"}
        )
        _write_json(
            item.directory / "state.json",
            {"token": job.token, "phase": phase if len(downloads) == 1 else "ready"},
        )
        return job

    updates = update_controller(
        download=download,
        launch=launch,
        authorize=authorize_update,
        cancel=cancel_update,
    )
    updates.check_for_updates(manual=True)
    wait_until(qapp, lambda: updates._dialog is not None)
    updates._begin_install()
    wait_until(qapp, lambda: not updates._busy)
    assert not exits
    assert not (downloads[0].directory / "install-authorized.json").exists()
    updates._begin_install()
    wait_until(qapp, lambda: bool(exits))
    assert len(downloads) == 2
    assert (downloads[1].directory / "install-authorized.json").exists()
