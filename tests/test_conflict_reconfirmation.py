"""실제 작업 스레드의 pull과 Qt 재확인 순서를 조합해 초안 수명을 검증한다."""

from __future__ import annotations

import os
from pathlib import Path
from queue import Queue
from threading import Event, Semaphore

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import isValid
from test_conflict_resolution_ui import button, visible_dialog
from test_sync_engine import conflicted_engine, outbox_rows, sample

from mdlogger.app_controller import AppController
from mdlogger.app_settings import MemorySettingsStore
from mdlogger.game_service import GameService
from mdlogger.game_sync.coordinator import SyncCoordinator
from mdlogger.game_sync.models import ConflictResolutionResult, SyncPhase, SyncStatus
from mdlogger.profile_router import ProfileRouter
from mdlogger.profiles import ProfileManager


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        application = QApplication([])
    yield application


class ProfileWindow(QWidget):
    def close_profile_windows(self) -> None:
        self.close()


class LiveConflictFlow:
    """결과 전달만 잠시 멈추고 실제 coordinator의 다음 사이클을 그대로 실행한다."""

    def __init__(self, qapp: QApplication, tmp_path: Path) -> None:
        self.qapp = qapp
        (
            self.profile,
            self.games,
            self.transport,
            self.engine,
            self.game_id,
        ) = conflicted_engine(tmp_path)
        self.profiles = ProfileManager(tmp_path)
        self.coordinator = SyncCoordinator(self.engine, interval_seconds=60)
        self.controller = AppController(
            self.profiles,
            lambda profile: GameService.open(profile.database_path),
            lambda *_: ProfileWindow(),
        )
        self.controller.switch_profile(self.profile)
        # 충돌 창의 첫 요청을 넣은 뒤 실제 작업 스레드를 시작한다.
        self.controller._sync = self.coordinator
        self.router = ProfileRouter(
            self.profiles, self.controller, None, settings_store=MemorySettingsStore()
        )
        self.account = QDialog()
        self.account.show()
        self.router._open_conflicts(self.account)
        self.dialog = visible_dialog(qapp)
        self.sync_id = self.dialog.conflict.game_sync_id
        self.results: Queue[ConflictResolutionResult] = Queue()
        self.statuses: Queue[SyncStatus] = Queue()
        self.continue_worker = Semaphore(0)
        self.barrier_failed = Event()
        self.holding_result = False
        self.accepted: list[bool] = []
        self.dialog.accepted.connect(lambda: self.accepted.append(True))
        self.coordinator.resolution_finished.connect(
            self.on_result, Qt.ConnectionType.DirectConnection
        )
        self.coordinator.status_changed.connect(
            self.on_status, Qt.ConnectionType.DirectConnection
        )

    def on_result(self, result: ConflictResolutionResult) -> None:
        self.results.put(result)
        if not self.continue_worker.acquire(timeout=5):
            self.barrier_failed.set()

    def on_status(self, status: SyncStatus) -> None:
        if status.phase is not SyncPhase.SYNCING:
            self.statuses.put(status)

    def submit(self, resolution: str = "merged", *, process: bool = True):
        if self.dialog._confirmation.isVisible():
            assert not self.dialog._confirmation.isChecked()
            assert not button(self.dialog).isEnabled()
            self.dialog._confirmation.setChecked(True)
        label = {
            "local": "이 장치 버전 사용",
            "remote": "서버 버전 사용",
            "merged": "선택 내용 적용",
        }[resolution]
        assert button(self.dialog, label).isEnabled()
        button(self.dialog, label).click()
        self.release_result()
        self.coordinator.start()
        return self.receive_result(process=process)

    def receive_result(self, *, process: bool = True):
        result = self.results.get(timeout=5)
        self.holding_result = True
        if process:
            self.qapp.processEvents()
        return result

    def release_result(self) -> None:
        if self.holding_result:
            self.holding_result = False
            self.continue_worker.release()

    def wait_pull(self, version: int) -> SyncStatus:
        while True:
            status = self.statuses.get(timeout=5)
            if status.last_pulled_version >= version:
                return status

    def change_remote(self, note: str, *, operation: str = "update") -> int:
        result = self.transport._apply(
            {
                "op": operation,
                "id": self.sync_id,
                "expected_change_version": self.transport.remote_games[self.sync_id][
                    "change_version"
                ],
                "payload": sample(note),
            }
        )
        assert result["status"] == "applied"
        return result["change_version"]

    def draft(self, note: str) -> None:
        self.dialog._populate_comparison(
            {**self.dialog.conflict.local_payload, "note": note}
        )

    def converge(self, *, pull_first: bool, resolution: str = "merged"):
        self.change_remote("로컬 수정")
        result = self.submit(resolution, process=False)
        assert result.stale
        assert self.engine.status().last_pulled_version == 2
        if not pull_first:
            self.qapp.processEvents()
        self.release_result()
        self.wait_pull(3)
        if pull_first:
            self.qapp.processEvents()
        assert self.engine.list_conflicts() == []
        assert outbox_rows(self.profile) == []
        assert self.accepted == []
        assert self.dialog._confirmation.isVisible()

    def refresh_after_pull(self):
        result = self.submit()
        assert result.stale
        assert self.dialog.conflict.resolved
        assert self.dialog.conflict.remote_payload["change_version"] == 3
        assert self.accepted == []

    def close(self) -> None:
        self.continue_worker.release()
        assert self.coordinator.stop()
        self.router.close()
        self.controller.close()
        if isValid(self.account):
            self.account.close()
        self.games.close()
        assert not self.barrier_failed.is_set(), (
            "테스트가 작업 스레드를 재개하지 않았습니다."
        )


@pytest.fixture
def live_flow(qapp, tmp_path):
    flow = LiveConflictFlow(qapp, tmp_path)
    try:
        yield flow
    finally:
        flow.close()


@pytest.mark.parametrize("pull_first", [False, True])
@pytest.mark.parametrize("resolution", ["local", "remote", "merged"])
@pytest.mark.parametrize("equal", [False, True])
def test_converging_pull_keeps_live_draft_reconfirmation(
    live_flow, pull_first, resolution, equal
):
    flow = live_flow
    draft_note = {"local": "로컬 수정", "remote": "서버 수정", "merged": "병합 초안"}[
        resolution
    ]
    if resolution == "merged":
        flow.draft(draft_note)
    latest_note = draft_note if equal else "수렴한 기록"
    if latest_note != "로컬 수정":
        flow.games.update_game(flow.game_id, sample(latest_note))
    flow.change_remote(latest_note)
    result = flow.submit(resolution, process=False)
    assert flow.engine.status().last_pulled_version == 2
    if not pull_first:
        flow.qapp.processEvents()
    flow.release_result()
    flow.wait_pull(3)
    assert flow.engine.list_conflicts() == []
    assert outbox_rows(flow.profile) == []
    if pull_first:
        flow.qapp.processEvents()

    if result.succeeded:
        assert equal and resolution == "local"
        assert flow.accepted == [True]
        return

    assert result.stale
    for _ in range(3):
        assert flow.accepted == []
        assert flow.dialog._confirmation.isVisible()
        assert flow.dialog._selected_payload()["note"] == draft_note
        assert flow.games.get_game(flow.game_id)["note"] == latest_note
        result = flow.submit()
        if result.succeeded:
            break
        assert result.stale
    assert result.succeeded
    assert flow.accepted == [True]
    assert flow.games.get_game(flow.game_id)["note"] == draft_note
    assert flow.engine.status().last_pulled_version == 3
    pending = outbox_rows(flow.profile)
    assert len(pending) == (0 if equal else 1)
    if not equal:
        assert flow.games.get_game(flow.game_id)["remote_version"] == 3
        flow.release_result()
        flow.wait_pull(4)
        assert flow.transport.remote_games[flow.sync_id]["note"] == draft_note
        assert outbox_rows(flow.profile) == []


@pytest.mark.parametrize("pull_first", [False, True])
def test_converged_draft_can_be_explicitly_discarded(live_flow, pull_first):
    flow = live_flow
    flow.draft("버릴 초안")
    flow.converge(pull_first=pull_first)
    button(flow.dialog, "초안 버리고 닫기").click()
    flow.qapp.processEvents()
    assert flow.accepted == []
    assert flow.games.get_game(flow.game_id)["note"] == "로컬 수정"
    assert flow.engine.list_conflicts() == []
    assert outbox_rows(flow.profile) == []


def test_pull_can_retire_conflict_before_first_submission(live_flow):
    flow = live_flow
    flow.change_remote("로컬 수정")
    flow.coordinator.start()
    flow.wait_pull(3)
    assert flow.engine.list_conflicts() == []
    assert flow.submit("remote").stale
    assert flow.dialog.conflict.resolved
    assert flow.dialog._selected_payload()["note"] == "서버 수정"
    assert flow.games.get_game(flow.game_id)["note"] == "로컬 수정"
    assert flow.submit().succeeded
    assert flow.games.get_game(flow.game_id)["note"] == "서버 수정"
    assert flow.games.get_game(flow.game_id)["remote_version"] == 3
    assert flow.engine.status().last_pulled_version == 3
    assert len(outbox_rows(flow.profile)) == 1


@pytest.mark.parametrize("pull_first", [False, True])
def test_latest_equal_draft_does_not_queue_redundant_upload(live_flow, pull_first):
    flow = live_flow
    flow.draft("서버 수정")
    flow.change_remote("서버 수정")
    assert flow.submit(process=False).stale
    if not pull_first:
        flow.qapp.processEvents()
    flow.release_result()
    flow.wait_pull(3)
    if pull_first:
        flow.qapp.processEvents()
    assert len(flow.engine.list_conflicts()) == 1
    assert flow.games.get_game(flow.game_id)["note"] == "로컬 수정"
    assert flow.submit().succeeded
    assert flow.games.get_game(flow.game_id)["note"] == "서버 수정"
    assert outbox_rows(flow.profile) == []


@pytest.mark.parametrize("pull_first", [False, True])
def test_open_draft_does_not_keep_unrelated_converged_conflicts(live_flow, pull_first):
    flow = live_flow
    flow.draft("보존할 초안")
    other_id = "22222222-2222-4222-8222-222222222222"
    flow.transport._apply(
        {"op": "create", "id": other_id, "payload": sample("다른 기준")}
    )
    flow.engine.run_once()
    other_game_id = flow.games.get_last_game()["id"]
    assert other_game_id != flow.game_id
    flow.games.update_game(other_game_id, sample("다른 로컬"))
    flow.transport._apply(
        {
            "op": "update",
            "id": other_id,
            "expected_change_version": 3,
            "payload": sample("다른 서버"),
        }
    )
    flow.engine.run_once()
    assert len(flow.engine.list_conflicts()) == 2
    assert flow.change_remote("로컬 수정") == 5
    flow.transport._apply(
        {
            "op": "update",
            "id": other_id,
            "expected_change_version": 4,
            "payload": sample("다른 로컬"),
        }
    )
    assert flow.submit(process=False).stale
    assert flow.engine.status().last_pulled_version == 4
    if not pull_first:
        flow.qapp.processEvents()
    flow.release_result()
    flow.wait_pull(6)
    if pull_first:
        flow.qapp.processEvents()
    assert flow.engine.list_conflicts() == []
    assert outbox_rows(flow.profile) == []
    assert flow.games.get_game(other_game_id)["note"] == "다른 로컬"
    assert flow.dialog._selected_payload()["note"] == "보존할 초안"
    assert flow.submit().stale
    assert flow.submit().succeeded
    assert flow.games.get_game(flow.game_id)["remote_version"] == 5
    assert flow.engine.status().last_pulled_version == 6
    assert [row["game_sync_id"] for row in outbox_rows(flow.profile)] == [flow.sync_id]


@pytest.mark.parametrize("pull_first", [False, True])
@pytest.mark.parametrize(
    "change",
    ["local_edit", "local_delete", "remote_edit", "remote_delete", "remote_missing"],
)
def test_reconfirmation_rechecks_additional_edits_and_deletes(
    live_flow, pull_first, change
):
    flow = live_flow
    flow.draft("보존할 초안")
    flow.converge(pull_first=pull_first)
    flow.refresh_after_pull()
    if change == "local_edit":
        flow.games.update_game(flow.game_id, sample("추가 로컬 수정"))
    elif change == "local_delete":
        flow.games.delete_game(flow.game_id)
    elif change == "remote_missing":
        flow.transport.remote_games.clear()
    else:
        flow.change_remote(
            "추가 서버 수정",
            operation="delete" if change == "remote_delete" else "update",
        )
    before = flow.games.get_game(flow.game_id)
    pending_before = [dict(row) for row in outbox_rows(flow.profile)]
    result = flow.submit()
    assert result.stale
    assert flow.accepted == []
    assert flow.games.get_game(flow.game_id) == before
    assert [dict(row) for row in outbox_rows(flow.profile)] == pending_before
    assert flow.dialog._selected_payload()["note"] == "보존할 초안"
    assert flow.engine.status().last_pulled_version == 3
    result = flow.submit()
    assert result.succeeded
    row = flow.games.get_game(flow.game_id)
    assert row["note"] == "보존할 초안"
    assert row["deleted_at"] is None
    assert row["remote_version"] == (
        None if change == "remote_missing" else 4 if change.startswith("remote") else 3
    )
    pending = outbox_rows(flow.profile)
    assert len(pending) == 1
    assert pending[0]["operation"] == (
        "restore" if change == "remote_delete" else "upsert"
    )


@pytest.mark.parametrize("delete", [False, True])
def test_local_change_during_reconfirmation_fetch_has_no_write_lock(live_flow, delete):
    flow = live_flow
    flow.draft("보존할 초안")
    flow.converge(pull_first=True)
    flow.refresh_after_pull()

    def change_local():
        games = GameService.open(flow.profile.database_path)
        try:
            if delete:
                games.delete_game(flow.game_id)
            else:
                games.update_game(flow.game_id, sample("조회 도중 로컬 수정"))
        finally:
            games.close()

    flow.transport.on_fetch = change_local
    result = flow.submit()
    assert result.stale
    assert flow.dialog._selected_payload()["note"] == "보존할 초안"
    if delete:
        assert flow.games.get_game(flow.game_id) is None
    else:
        assert flow.games.get_game(flow.game_id)["note"] == "조회 도중 로컬 수정"
    assert flow.submit().succeeded
    assert flow.games.get_game(flow.game_id)["note"] == "보존할 초안"


def test_reconfirmed_draft_keeps_point_cursor_and_later_push_cas(live_flow):
    flow = live_flow
    flow.draft("보존할 초안")
    flow.converge(pull_first=True)
    flow.refresh_after_pull()
    other_id = "22222222-2222-4222-8222-222222222222"
    flow.transport._apply(
        {"op": "create", "id": other_id, "payload": sample("다른 경기")}
    )
    assert flow.change_remote("최신 비교") == 5
    assert flow.submit().stale
    assert flow.engine.status().last_pulled_version == 3
    assert flow.dialog.conflict.remote_payload["change_version"] == 5
    assert flow.submit().succeeded
    assert flow.games.get_game(flow.game_id)["remote_version"] == 5
    assert flow.engine.status().last_pulled_version == 3
    assert flow.change_remote("확인 이후 새 수정") == 6
    flow.release_result()
    status = flow.wait_pull(6)
    assert status.conflict_count == 1
    assert flow.games.count_games() == 2
    assert flow.games.get_game(flow.game_id)["note"] == "보존할 초안"
    assert flow.transport.remote_games[flow.sync_id]["note"] == "확인 이후 새 수정"
    assert flow.engine.list_conflicts()[0].remote_payload["change_version"] == 6
    assert len(outbox_rows(flow.profile)) == 1


@pytest.mark.parametrize("closing", ["router", "profile", "dialog", "account"])
def test_real_queued_stale_result_is_ignored_after_scope_closure(live_flow, closing):
    flow = live_flow
    flow.draft("닫힌 창의 초안")
    flow.change_remote("로컬 수정")
    result = flow.submit(process=False)
    assert result.stale
    flow.release_result()
    if closing == "router":
        flow.router.close()
    elif closing == "profile":
        flow.controller.switch_profile(
            flow.profiles.registered(
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "다른 계정"
            )
        )
    else:
        target = flow.dialog if closing == "dialog" else flow.account
        target.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    flow.qapp.processEvents()
    assert flow.accepted == []
    assert not isValid(flow.dialog) or not flow.dialog.isVisible()
    flow.coordinator.resolution_finished.disconnect(flow.on_result)
    flow.coordinator.resolution_finished.emit(result)
    flow.qapp.processEvents()
    assert flow.accepted == []
    if closing == "profile":
        assert flow.controller.current_game_count == 0


def test_closing_profile_cancels_late_reconfirmation_fetch(live_flow):
    flow = live_flow
    flow.draft("취소할 초안")
    flow.converge(pull_first=True)
    flow.refresh_after_pull()
    entered, release = Event(), Event()

    def delay_fetch():
        entered.set()
        assert release.wait(5), "서버 확인 대기를 해제하지 않았습니다."

    flow.transport.on_fetch = delay_fetch
    flow.dialog._confirmation.setChecked(True)
    button(flow.dialog).click()
    flow.release_result()
    try:
        assert entered.wait(5)
        assert flow.coordinator.stop(timeout_seconds=0) is False
        release.set()
        flow.controller.close()
        flow.qapp.processEvents()
        assert flow.accepted == []
        assert flow.results.empty()
        assert flow.games.get_game(flow.game_id)["note"] == "로컬 수정"
        assert outbox_rows(flow.profile) == []
    finally:
        release.set()
