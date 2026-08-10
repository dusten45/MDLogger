"""AppController의 프로필 전환 및 Qt 창/DB 수명 주기 테스트."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mdlogger.app_controller import AppController
from mdlogger.game_service import GameService
from mdlogger.game_sync.models import SyncPhase, SyncStatus
from mdlogger.profiles import ProfileContext, ProfileKind, ProfileManager
from mdlogger.ui.main_window import MainWindow

ACCOUNT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ACCOUNT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def sample(note: str) -> dict:
    return {
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "테스트 덱",
        "opp_deck": "상대 덱",
        "turns": 4,
        "end_reason": "regular",
        "score_after": 1500,
        "note": note,
    }


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


class FakeSync:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.requests: list[bool] = []
        self.status = SyncStatus(SyncPhase.PENDING, 1, 0)

    def start(self) -> None:
        self.started = True

    def request_sync(self, *, retry_failed: bool = False) -> None:
        self.requests.append(retry_failed)

    def list_conflicts(self) -> list:
        return []

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: dict | None = None,
        *,
        expected_remote_version: int | None = None,
    ) -> None:
        pass

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self.stopped = True


class TrackingWindow:
    def __init__(self, games: GameService):
        self.games = games
        self.shown = False
        self.closed = False
        self.connection_was_open_when_closed = False
        self.sync: FakeSync | None = None
        self.sync_was_stopped_when_closed = False

    def set_sync_coordinator(self, sync: FakeSync) -> None:
        self.sync = sync

    def show(self) -> None:
        self.shown = True

    def close_profile_windows(self) -> None:
        self.connection_was_open_when_closed = self.games.count_games() >= 0
        self.sync_was_stopped_when_closed = self.sync is None or self.sync.stopped
        self.closed = True


def make_controller(
    manager: ProfileManager,
    services: list[GameService],
    windows: list[TrackingWindow],
) -> AppController:
    def service_factory(profile: ProfileContext) -> GameService:
        games = GameService.open(profile.database_path)
        services.append(games)
        return games

    def window_factory(games: GameService, profile: ProfileContext) -> TrackingWindow:
        window = TrackingWindow(games)
        windows.append(window)
        return window

    return AppController(manager, service_factory, window_factory)


def test_login_logout_switches_scopes_without_deleting_local_databases(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    services: list[GameService] = []
    windows: list[TrackingWindow] = []
    controller = make_controller(manager, services, windows)

    controller.start_guest()
    guest_path = manager.guest().database_path
    services[-1].insert_game(sample("guest"))
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.GUEST

    controller.login_registered(ACCOUNT_A, "계정 A")
    account_a_path = manager.registered(ACCOUNT_A, "계정 A").database_path
    services[-1].insert_game(sample("account-a"))
    first_service = services[0]
    assert windows[0].closed
    assert windows[0].connection_was_open_when_closed
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        first_service.count_games()

    controller.logout()
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.GUEST
    assert guest_path.exists()
    assert account_a_path.exists()
    guest_record = services[-1].get_last_game()
    assert guest_record is not None
    assert guest_record["note"] == "guest"

    controller.login_registered(ACCOUNT_A, "계정 A")
    account_record = services[-1].get_last_game()
    assert account_record is not None
    assert account_record["note"] == "account-a"
    controller.login_registered(ACCOUNT_B, "계정 B")
    controller.logout()
    controller.close()

    assert all(window.shown and window.closed for window in windows)
    for service in services:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            service.count_games()


def test_failed_switch_preserves_current_scope(tmp_path: Path):
    """B-2: 새 프로필 DB 준비가 실패해도 기존 scope가 닫히지 않아, 사용자가
    화면 없는 상태로 남지 않는다."""
    manager = ProfileManager(tmp_path)
    services: list[GameService] = []
    windows: list[TrackingWindow] = []
    controller = make_controller(manager, services, windows)

    controller.start_guest()
    services[-1].insert_game(sample("guest"))
    guest_window = windows[0]
    guest_service = services[0]

    # 게스트 상태에서, 소유권이 어긋난 등록 프로필로 전환을 시도한다.
    # 어긋난 소유권을 만들기 위해 대상 DB를 손상시킨다.
    profile_a = manager.registered(ACCOUNT_A, "계정 A")
    manager.prepare_database(profile_a)  # 정상 준비(소유권 귀속)
    import sqlite3 as _sqlite3

    connection = _sqlite3.connect(profile_a.database_path)
    try:
        connection.execute("UPDATE database_metadata SET owner_id=?", (ACCOUNT_B,))
        connection.commit()
    finally:
        connection.close()

    # 소유권 불일치로 switch가 실패해야 한다.
    with pytest.raises(Exception):
        controller.switch_profile(profile_a)

    # 기존 게스트 scope가 그대로 유지된다.
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.GUEST
    assert not guest_window.closed
    assert guest_service.count_games() == 1

    controller.close()


def test_switch_closes_visible_stats_window_before_old_connection(
    qapp: QApplication, tmp_path: Path
):
    manager = ProfileManager(tmp_path)
    services: list[GameService] = []
    windows: list[MainWindow] = []

    def service_factory(profile: ProfileContext) -> GameService:
        games = GameService.open(profile.database_path)
        services.append(games)
        return games

    def window_factory(games: GameService, profile: ProfileContext) -> MainWindow:
        window = MainWindow(games, ["테스트 덱"], profile)
        windows.append(window)
        return window

    controller = AppController(manager, service_factory, window_factory)
    controller.start_guest()
    guest_window = windows[0]
    guest_window.open_stats()
    stats_window = guest_window._stats
    assert stats_window is not None
    assert stats_window.isVisible()

    controller.login_registered(ACCOUNT_A, "계정 A")
    qapp.processEvents()

    assert not guest_window.isVisible()
    assert not stats_window.isVisible()
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        services[0].count_games()

    controller.close()


def test_profile_switch_stops_sync_before_closing_window(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    services: list[GameService] = []
    windows: list[TrackingWindow] = []
    syncs: list[FakeSync] = []

    controller = make_controller(manager, services, windows)

    def sync_factory(_profile: ProfileContext) -> FakeSync:
        sync = FakeSync()
        syncs.append(sync)
        return sync

    controller._sync_factory = sync_factory
    controller.start_guest()

    assert syncs[0].started
    assert windows[0].sync is syncs[0]
    controller.request_sync(retry_failed=True)
    assert syncs[0].requests == [True]

    controller.login_registered(ACCOUNT_A, "계정 A")

    assert syncs[0].stopped
    assert windows[0].sync_was_stopped_when_closed
    controller.close()


def test_close_releases_all_resources_even_when_stop_raises(tmp_path: Path):
    """P1-9: sync.stop 예외가 나도 창과 DB 연결을 반드시 해제한다."""
    manager = ProfileManager(tmp_path)
    services: list[GameService] = []
    windows: list[TrackingWindow] = []

    class ExplodingSync(FakeSync):
        def stop(self, *, timeout_seconds: float = 5.0) -> None:
            raise RuntimeError("stop 실패")

    def sync_factory(_profile: ProfileContext) -> ExplodingSync:
        return ExplodingSync()

    controller = make_controller(manager, services, windows)
    controller._sync_factory = sync_factory
    controller.start_guest()
    first_service = services[0]
    first_window = windows[0]

    with pytest.raises(RuntimeError, match="stop 실패"):
        controller.close()

    # stop()이 실패해도 창과 DB 연결은 반드시 닫힌다(P1-9).
    assert first_window.closed
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        first_service.count_games()


def test_profile_switch_schedules_window_deletion(qapp: QApplication, tmp_path: Path):
    """P1-10: 프로필 전환 시 닫힌 MainWindow가 deleteLater로 삭제 예약된다."""
    manager = ProfileManager(tmp_path)
    services: list[GameService] = []
    windows: list[MainWindow] = []

    def service_factory(profile: ProfileContext) -> GameService:
        games = GameService.open(profile.database_path)
        services.append(games)
        return games

    def window_factory(games: GameService, profile: ProfileContext) -> MainWindow:
        window = MainWindow(games, ["테스트 덱"], profile)
        windows.append(window)
        return window

    controller = AppController(manager, service_factory, window_factory)
    controller.start_guest()
    guest_window = windows[0]
    guest_window.open_stats()

    controller.login_registered(ACCOUNT_A, "계정 A")

    # switch_profile이 이전 창에 deleteLater를 예약해, 이벤트 루프가 처리하면
    # C++ 객체가 소멸된다(P1-10).
    from PySide6.QtCore import QEvent
    from shiboken6 import isValid

    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(guest_window)
    controller.close()
