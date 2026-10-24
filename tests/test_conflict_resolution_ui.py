"""실제 네트워크 없이 충돌 해결의 비동기 화면과 수명 주기를 검증한다."""

from __future__ import annotations

import os
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Thread
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    SIGNAL,
    QCoreApplication,
    QEvent,
    QObject,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton
from shiboken6 import isValid

from mdlogger.app_controller import AppController
from mdlogger.app_settings import MemorySettingsStore
from mdlogger.game_sync.models import ConflictResolutionResult, SyncConflict
from mdlogger.profile_router import ProfileRouter
from mdlogger.profiles import ProfileContext, ProfileManager
from mdlogger.ui.account_views import ConflictDialog

USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
GAME_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        application = QApplication([])
    yield application


def make_conflict() -> SyncConflict:
    return SyncConflict(
        id=1,
        game_sync_id=GAME_ID,
        local_payload={
            "id": GAME_ID,
            "note": "이 장치 메모",
            "turns": 4,
            "my_deck": "기존 덱",
        },
        remote_payload={
            "id": GAME_ID,
            "note": "서버 메모",
            "turns": 7,
            "my_deck": "기존 덱",
            "change_version": 7,
        },
        base_remote_version=6,
        local_revision="local-revision-1",
    )


class FakeController(QObject):
    resolution_finished = Signal(object)
    profile_closing = Signal()

    def __init__(self, profile: ProfileContext) -> None:
        super().__init__()
        self.current_profile: ProfileContext | None = profile
        self.current_window = None
        self.conflicts = [make_conflict()]
        self.requests: list[dict[str, Any]] = []
        self.submit_error: Exception | None = None
        self.list_error: Exception | None = None
        self.on_submit: Callable[[str, int], None] | None = None
        self.list_calls = 0

    def list_conflicts(self) -> list[SyncConflict]:
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return list(self.conflicts)

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: dict | None = None,
        *,
        expected_remote_version: int | None = None,
        expected_local_revision: str,
    ) -> str:
        if self.submit_error is not None:
            raise self.submit_error
        request_id = f"request-{len(self.requests) + 1}"
        self.requests.append(
            {
                "request_id": request_id,
                "conflict_id": conflict_id,
                "resolution": resolution,
                "merged_payload": deepcopy(merged_payload),
                "expected_remote_version": expected_remote_version,
                "expected_local_revision": expected_local_revision,
            }
        )
        if self.on_submit is not None:
            self.on_submit(request_id, conflict_id)
        return request_id

    def close_profile(self) -> None:
        self.profile_closing.emit()
        self.current_profile = None

    def receiver_count(self) -> int:
        return self.receivers(SIGNAL("resolution_finished(PyObject)"))


@pytest.fixture
def flow(qapp: QApplication, tmp_path: Path):
    profiles = ProfileManager(tmp_path)
    controller = FakeController(profiles.registered(USER_ID, "a@test.local"))
    router = ProfileRouter(
        profiles,
        cast(AppController, controller),
        None,
        settings_store=MemorySettingsStore(),
    )
    account = QDialog()
    account.show()
    yield router, controller, account
    router.close()
    controller.close_profile()
    if isValid(account):
        account.close()


def visible_dialog(qapp: QApplication) -> ConflictDialog:
    dialogs = [
        widget
        for widget in qapp.topLevelWidgets()
        if isinstance(widget, ConflictDialog) and widget.isVisible()
    ]
    assert len(dialogs) == 1
    return dialogs[0]


def button(dialog: ConflictDialog, text: str = "선택 내용 적용") -> QPushButton:
    return next(
        item for item in dialog.findChildren(QPushButton) if item.text() == text
    )


def test_resolution_waits_for_matching_result_and_prevents_closing(
    qapp: QApplication, flow
):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))
    assert controller.receiver_count() == 1
    dialog._choices["turns"].setCurrentIndex(1)
    button(dialog).click()

    assert len(controller.requests) == 1
    request = controller.requests[0]
    assert request["expected_remote_version"] == 7
    assert request["expected_local_revision"] == "local-revision-1"
    assert request["merged_payload"]["note"] == "이 장치 메모"
    assert request["merged_payload"]["turns"] == 7
    assert dialog.isVisible()
    assert "닫을 수 없습니다" in dialog._status.text()
    assert all(not item.isEnabled() for item in dialog.findChildren(QPushButton))
    assert all(not choice.isEnabled() for choice in dialog._choices.values())

    button(dialog).click()
    dialog.resolution_requested.emit()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    dialog.reject()
    dialog.done(QDialog.DialogCode.Rejected)
    dialog.accept()
    assert not dialog.close()
    assert dialog.isVisible()
    assert accepted == []
    assert len(controller.requests) == 1

    controller.resolution_finished.emit(ConflictResolutionResult("unrelated", 1, True))
    controller.resolution_finished.emit(ConflictResolutionResult("request-1", 99, True))
    qapp.processEvents()
    assert dialog.isVisible()
    assert not button(dialog).isEnabled()
    assert accepted == []

    controller.conflicts.clear()
    controller.resolution_finished.emit(ConflictResolutionResult("request-1", 1, True))
    qapp.processEvents()
    assert accepted == [True]
    assert controller.receiver_count() == 0


def test_failure_retains_choices_and_draft_and_ignores_late_previous_success(
    qapp: QApplication, flow
):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    dialog._choices["note"].setCurrentIndex(1)
    button(dialog).click()
    draft = deepcopy(dialog.merged_payload)
    controller.resolution_finished.emit(
        ConflictResolutionResult(
            "request-1", 1, False, "네트워크 연결을 확인해 주세요.", retryable=True
        )
    )
    qapp.processEvents()

    assert dialog.isVisible()
    assert button(dialog).isEnabled()
    assert dialog.resolution == "merged"
    assert dialog.merged_payload == draft
    assert dialog._choices["note"].currentData() == "remote"
    assert "선택 내용은 유지됩니다" in dialog._status.text()
    assert "다시 적용" in dialog._status.text()
    button(dialog).click()
    assert len(controller.requests) == 2
    assert controller.requests[1]["merged_payload"] == draft

    controller.resolution_finished.emit(ConflictResolutionResult("request-1", 1, True))
    qapp.processEvents()
    assert dialog.isVisible()
    assert not button(dialog).isEnabled()
    controller.resolution_finished.emit(
        ConflictResolutionResult("request-2", 1, False, "다시 로그인해 주세요.")
    )
    qapp.processEvents()
    button(dialog, "나중에 해결").click()
    assert controller.receiver_count() == 0
    controller.resolution_finished.emit(ConflictResolutionResult("request-2", 1, True))
    qapp.processEvents()
    assert len(controller.requests) == 2


def test_stale_result_refreshes_comparison_preserves_values_and_requires_reconfirmation(
    qapp: QApplication, flow
):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    dialog._choices["turns"].setCurrentIndex(1)
    button(dialog).click()
    draft = deepcopy(dialog.merged_payload)
    old = controller.conflicts[0]
    fresh = replace(
        old,
        local_payload={**old.local_payload, "note": "새 장치 메모", "my_deck": "새 덱"},
        remote_payload={
            **old.remote_payload,
            "turns": 9,
            "my_deck": "새 덱",
            "change_version": 8,
        },
        local_revision="local-revision-2",
    )
    controller.conflicts = [fresh]
    controller.resolution_finished.emit(
        ConflictResolutionResult("request-1", 1, False, stale=True)
    )
    qapp.processEvents()

    assert dialog.isVisible()
    assert dialog.conflict == fresh
    assert dialog.merged_payload == draft
    assert dialog._choices["note"].currentData() == "draft"
    assert "이 장치 메모" in dialog._choices["note"].currentText()
    assert dialog._choices["turns"].currentData() == "draft"
    assert dialog._choices["my_deck"].currentData() == "draft"
    assert dialog._confirmation.isVisible()
    assert not dialog._confirmation.isChecked()
    comparison: list[str] = []
    for row in range(dialog._table.rowCount()):
        for column in (1, 2):
            item = dialog._table.item(row, column)
            assert item is not None
            comparison.append(item.text())
    assert "새 장치 메모" in comparison
    assert "9" in comparison
    for action in dialog._apply_buttons:
        assert not action.isEnabled()
        action.click()
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert len(controller.requests) == 1

    QTest.keyClick(dialog._confirmation, Qt.Key.Key_Space)
    assert dialog._confirmation.isChecked()
    button(dialog).click()
    assert len(controller.requests) == 2
    request = controller.requests[1]
    assert request["expected_remote_version"] == 8
    assert request["expected_local_revision"] == "local-revision-2"
    assert request["merged_payload"]["note"] == "이 장치 메모"
    assert request["merged_payload"]["turns"] == 7
    assert request["merged_payload"]["my_deck"] == "기존 덱"
    assert request["merged_payload"]["change_version"] == 8
    controller.resolution_finished.emit(ConflictResolutionResult("request-2", 1, True))
    qapp.processEvents()


def test_disappeared_conflict_cannot_be_reapplied_or_reported_as_accepted(
    qapp: QApplication, flow
):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))
    button(dialog).click()
    controller.conflicts.clear()
    controller.resolution_finished.emit(
        ConflictResolutionResult("request-1", 1, False, stale=True)
    )
    qapp.processEvents()

    assert "이미 해결되었거나" in dialog._status.text()
    assert all(not action.isEnabled() for action in dialog._apply_buttons)
    assert dialog.isVisible()
    assert accepted == []
    button(dialog, "닫기").click()
    assert accepted == []
    assert controller.receiver_count() == 0


def test_missing_remote_queues_none_version_and_explains_deletion(
    qapp: QApplication, flow
):
    router, controller, account = flow
    controller.conflicts = [
        replace(make_conflict(), remote_payload={"id": GAME_ID, "missing": True})
    ]
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    assert "이 장치의 기록도 삭제됩니다" in dialog._remote_notice.text()
    button(dialog, "서버 버전 사용").click()

    assert controller.requests[0]["expected_remote_version"] is None
    assert controller.requests[0]["expected_local_revision"] == "local-revision-1"
    assert controller.requests[0]["resolution"] == "remote"
    assert controller.requests[0]["merged_payload"] is None
    assert dialog.isVisible()


def test_queue_error_preserves_draft_and_allows_explicit_retry(
    qapp: QApplication, flow
):
    router, controller, account = flow
    controller.submit_error = RuntimeError("종료 중인 작업입니다.")
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    dialog._choices["note"].setCurrentIndex(1)
    button(dialog).click()

    assert dialog.isVisible()
    assert dialog.merged_payload is not None
    assert dialog.merged_payload["note"] == "서버 메모"
    assert "요청을 시작하지 못했습니다" in dialog._status.text()
    assert button(dialog).isEnabled()
    assert controller.requests == []
    controller.submit_error = None
    button(dialog).click()
    assert len(controller.requests) == 1


def test_failed_stale_reload_preserves_draft_but_blocks_old_snapshot(
    qapp: QApplication, flow
):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    button(dialog).click()
    draft = deepcopy(dialog.merged_payload)
    controller.list_error = OSError("충돌 정보를 읽을 수 없습니다.")
    controller.resolution_finished.emit(
        ConflictResolutionResult("request-1", 1, False, stale=True)
    )
    qapp.processEvents()

    assert dialog.merged_payload == draft
    assert "다시 열어 주세요" in dialog._status.text()
    assert all(not action.isEnabled() for action in dialog._apply_buttons)
    assert button(dialog, "닫기").isEnabled()
    button(dialog, "닫기").click()
    assert controller.receiver_count() == 0


@pytest.mark.parametrize("closing", ["profile", "router", "application", "account"])
def test_scope_close_disconnects_and_ignores_already_queued_results(
    qapp: QApplication, flow, closing: str
):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))
    button(dialog).click()
    controller.resolution_finished.emit(ConflictResolutionResult("request-1", 1, True))
    reads = controller.list_calls
    if closing == "profile":
        controller.close_profile()
    elif closing == "router":
        router.close()
    elif closing == "application":
        qapp.aboutToQuit.emit()
    else:
        account.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    assert accepted == []
    assert controller.receiver_count() == 0
    assert controller.receivers(SIGNAL("profile_closing()")) == 0
    assert not isValid(dialog) or not dialog.isVisible()
    controller.resolution_finished.emit(
        ConflictResolutionResult("request-1", 1, False, stale=True)
    )
    qapp.processEvents()
    assert controller.list_calls == reads


def test_destroyed_dialog_disconnects_the_worker_callback(qapp: QApplication, flow):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    button(dialog).click()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert controller.receiver_count() == 0
    assert controller.receivers(SIGNAL("profile_closing()")) == 0
    controller.resolution_finished.emit(
        ConflictResolutionResult("request-1", 1, False, stale=True)
    )
    qapp.processEvents()


def test_profile_replacement_invalidates_result_even_before_close_notification(
    qapp: QApplication, flow
):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    button(dialog).click()
    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))
    reads = controller.list_calls
    controller.current_profile = None
    controller.resolution_finished.emit(
        ConflictResolutionResult("request-1", 1, False, stale=True)
    )
    qapp.processEvents()

    assert accepted == []
    assert controller.list_calls == reads
    assert controller.receiver_count() == 0


def test_immediate_result_is_queued_until_request_id_is_captured(
    qapp: QApplication, flow
):
    router, controller, account = flow
    controller.on_submit = lambda request_id, conflict_id: (
        controller.resolution_finished.emit(
            ConflictResolutionResult(request_id, conflict_id, True)
        )
    )
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))
    button(dialog, "이 장치 버전 사용").click()
    assert accepted == []
    assert dialog.isVisible()
    qapp.processEvents()
    assert accepted == [True]
    assert controller.receiver_count() == 0


def test_worker_signal_finishes_dialog_only_on_gui_thread(qapp: QApplication, flow):
    router, controller, account = flow
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    threads: list[QThread] = []
    dialog.accepted.connect(lambda: threads.append(QThread.currentThread()))
    button(dialog).click()
    worker = Thread(
        target=lambda: controller.resolution_finished.emit(
            ConflictResolutionResult("request-1", 1, True)
        )
    )
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert threads == []
    qapp.processEvents()
    assert threads == [qapp.thread()]


@pytest.mark.parametrize("still_present", [True, False])
def test_next_conflict_uses_latest_local_snapshot_or_skips_resolved(
    qapp: QApplication, flow, still_present: bool
):
    router, controller, account = flow
    second = replace(make_conflict(), id=2, local_revision="second-original")
    controller.conflicts.append(second)
    router._open_conflicts(account)
    dialog = visible_dialog(qapp)
    button(dialog).click()
    latest = replace(
        second,
        remote_payload={**second.remote_payload, "change_version": 10},
        local_revision="second-latest",
    )
    controller.conflicts = [latest] if still_present else []
    controller.resolution_finished.emit(ConflictResolutionResult("request-1", 1, True))
    qapp.processEvents()
    qapp.processEvents()

    if still_present:
        next_dialog = visible_dialog(qapp)
        assert next_dialog is not dialog
        assert next_dialog.conflict == latest
        button(next_dialog, "서버 버전 사용").click()
        assert controller.requests[1]["expected_remote_version"] == 10
        assert controller.requests[1]["expected_local_revision"] == "second-latest"
    else:
        assert account.result() == QDialog.DialogCode.Accepted
        assert controller.receiver_count() == 0


def test_empty_conflict_list_closes_account_without_opening_comparison(
    qapp: QApplication, flow
):
    router, controller, account = flow
    controller.conflicts.clear()
    router._open_conflicts(account)
    assert account.result() == QDialog.DialogCode.Accepted
    assert controller.receiver_count() == 0


def test_initial_read_failure_keeps_account_open(
    qapp: QApplication, flow, monkeypatch: pytest.MonkeyPatch
):
    router, controller, account = flow
    controller.list_error = OSError("충돌 정보를 읽을 수 없습니다.")
    notices: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _parent, _title, text: notices.append(text)
    )
    router._open_conflicts(account)
    assert account.isVisible()
    assert controller.receiver_count() == 0
    assert notices == ["충돌 정보를 불러오지 못했습니다. 잠시 후 다시 열어 주세요."]
