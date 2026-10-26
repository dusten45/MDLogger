"""로그아웃 뒤의 등록 요청 승인과 늦은 응답 격리를 실제 엔진으로 검사한다."""

import threading
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from test_profile_router import make_router
from test_session_manager import (
    USER_ID,
    FakeAccountService,
    make_session,
    other_session,
)
from test_sync_engine import (
    CONFIG,
    GuestTransport,
    RegisteredTransport,
    conflicted_engine,
    outbox_rows,
    prepare_registered,
    sample,
)

from mdlogger.auth.credential_store import CredentialStoreError, InMemoryCredentialStore
from mdlogger.auth.models import AuthError, AuthErrorKind, AuthTokens
from mdlogger.auth.session_manager import SessionManager, SessionState
from mdlogger.game_sync.engine import SyncEngine
from mdlogger.game_sync.models import SyncPhase
from mdlogger.profile_router import CONSENT_VERSION
from mdlogger.remote.client import JsonHttpClient
from mdlogger.remote.games import RegisteredGamesClient, RegisteredGamesError
from mdlogger.remote.guest_ingest import GuestIngestClient


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.mark.parametrize("step", ["register", "push", "pull", "cursor"])
@pytest.mark.parametrize("server_failure", [False, True])
def test_router_logout_denies_followup_while_profile_and_remote_logout_remain_open(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
    server_failure: bool,
):
    entered, release = threading.Event(), threading.Event()
    router, profiles, controller, account_service, _, services, _ = make_router(
        tmp_path
    )
    sessions = router._sessions
    assert sessions is not None
    router._finish_registered_sign_in(make_session())
    profile = controller.current_profile
    assert profile is not None
    services[-1].insert_game(sample())
    original_outbox = [dict(row) for row in outbox_rows(profile)]
    suffix = {
        "register": "/rpc/register_or_touch_device",
        "push": "/rpc/apply_game_changes",
        "pull": "/games?",
        "cursor": "/rpc/acknowledge_device_version",
    }[step]

    class DelayedTransport(RegisteredTransport):
        delay = True

        def request(self, method, url, headers, body, timeout):
            result = super().request(method, url, headers, body, timeout)
            if self.delay and suffix in url:
                self.delay = False
                entered.set()
                assert release.wait(5)
            return result

    transport = DelayedTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=sessions,
        can_sync=lambda: (
            profiles.has_data_consent(CONSENT_VERSION)
            and controller.current_profile is profile
        ),
    )
    results = []
    worker = threading.Thread(target=lambda: results.append(engine.run_once()))
    during_logout = []

    def delayed_logout(access_token):
        assert access_token == "access-1"
        assert sessions.state is SessionState.SIGNED_OUT
        assert controller.current_profile is profile
        release.set()
        worker.join(5)
        assert not worker.is_alive(), "네트워크 대기 중 세션 잠금을 보유하면 안 됩니다."
        assert controller.current_profile is profile
        during_logout.extend(transport.requests)
        if server_failure:
            raise AuthError(AuthErrorKind.NETWORK, "서버 로그아웃 실패")

    monkeypatch.setattr(account_service, "sign_out", delayed_logout)
    worker.start()
    try:
        assert entered.wait(2)
        router._logout_from_dialog(QDialog())
        expected_count = ["register", "push", "pull", "cursor"].index(step) + 1
        assert len(during_logout) == expected_count
        assert results[0].phase is SyncPhase.REAUTH_REQUIRED
        assert controller.current_profile is None
        assert sessions.state is SessionState.SIGNED_OUT
        if step in ("register", "push"):
            assert [dict(row) for row in outbox_rows(profile)] == original_outbox
        if step != "cursor":
            assert engine.status().last_pulled_version == 0

        router._finish_registered_sign_in(make_session())
        resumed = SyncEngine(
            controller.current_profile,
            registered_client=RegisteredGamesClient(
                CONFIG, client=JsonHttpClient(transport)
            ),
            session_manager=sessions,
        )
        assert resumed.run_once().phase is SyncPhase.SYNCED
        assert outbox_rows(profile) == []
        assert len(transport.remote_games) == 1
    finally:
        release.set()
        worker.join(5)
        router.close()
        controller.close()


@pytest.mark.parametrize("step", [1, 2, 3, 4])
def test_logout_immediately_before_request_admission_denies_that_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: int
):
    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    games.close()
    original_outbox = [dict(row) for row in outbox_rows(profile)]
    manager = SessionManager(FakeAccountService(), InMemoryCredentialStore())
    manager.activate(make_session())
    transport = RegisteredTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=manager,
    )
    original_request = manager.run_sync_request
    admissions = 0

    def logout_before_admission(permission, request):
        nonlocal admissions
        admissions += 1
        if admissions == step:
            manager.sign_out(USER_ID)
        return original_request(permission, request)

    monkeypatch.setattr(manager, "run_sync_request", logout_before_admission)
    assert engine.run_once().phase is SyncPhase.REAUTH_REQUIRED
    assert len(transport.requests) == step - 1
    if step <= 2:
        assert [dict(row) for row in outbox_rows(profile)] == original_outbox


def test_keyring_delete_failure_still_denies_next_request_and_preserves_outbox(
    tmp_path: Path,
):
    class DeleteFailureStore(InMemoryCredentialStore):
        def delete_refresh_token(self, account_id):
            raise CredentialStoreError("키링 삭제 실패")

    service = FakeAccountService()
    manager = SessionManager(service, DeleteFailureStore())
    manager.activate(make_session())
    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    games.close()
    original_outbox = [dict(row) for row in outbox_rows(profile)]

    class LoggingOutTransport(RegisteredTransport):
        def request(self, method, url, headers, body, timeout):
            result = super().request(method, url, headers, body, timeout)
            with pytest.raises(CredentialStoreError):
                manager.sign_out(USER_ID)
            return result

    transport = LoggingOutTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=manager,
    )
    assert engine.run_once().phase is SyncPhase.REAUTH_REQUIRED
    assert engine.run_once().phase is SyncPhase.REAUTH_REQUIRED
    assert len(transport.requests) == 1
    assert [dict(row) for row in outbox_rows(profile)] == original_outbox
    assert manager.restore(USER_ID).state is SessionState.SIGNED_OUT
    assert service.refresh_calls == []


@pytest.mark.parametrize("same_account", [False, True])
@pytest.mark.parametrize("rejected", [False, True])
@pytest.mark.parametrize("during_push", [False, True])
def test_new_login_invalidates_old_response_without_using_new_account_token(
    tmp_path: Path, same_account: bool, rejected: bool, during_push: bool
):
    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    games.close()
    original_outbox = [dict(row) for row in outbox_rows(profile)]
    service = FakeAccountService()
    manager = SessionManager(service, InMemoryCredentialStore())
    manager.activate(make_session())
    newer = replace(
        make_session() if same_account else other_session(),
        tokens=AuthTokens("새 접근 토큰", "새 갱신 토큰", 3600),
    )

    class SwitchingTransport(RegisteredTransport):
        switch = True

        def request(self, method, url, headers, body, timeout):
            switching = self.switch and (
                not during_push or url.endswith("/rpc/apply_game_changes")
            )
            if switching:
                self.reject_first_request = rejected
            result = super().request(method, url, headers, body, timeout)
            if switching:
                self.switch = False
                manager.activate(newer)
            return result

    transport = SwitchingTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=manager,
    )
    assert engine.run_once().phase is SyncPhase.REAUTH_REQUIRED
    old_request_count = 2 if during_push else 1
    assert len(transport.requests) == old_request_count
    assert manager.session is newer
    assert service.refresh_calls == []
    assert [dict(row) for row in outbox_rows(profile)] == original_outbox
    if same_account:
        assert engine.run_once().phase is SyncPhase.SYNCED
        assert all(
            request["headers"]["Authorization"] == "Bearer 새 접근 토큰"
            for request in transport.requests[old_request_count:]
        )
    else:
        assert engine.run_once().phase is SyncPhase.REAUTH_REQUIRED
        assert len(transport.requests) == old_request_count


@pytest.mark.parametrize("during_response", [False, True])
def test_logout_denies_conflict_read_or_discards_its_late_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, during_response: bool
):
    profile, games, transport, original, game_id = conflicted_engine(tmp_path)
    conflict = original.list_conflicts()[0]
    original_outbox = [dict(row) for row in outbox_rows(profile)]
    manager = SessionManager(FakeAccountService(), InMemoryCredentialStore())
    manager.activate(make_session())
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=manager,
    )
    count = len(transport.requests)
    if during_response:
        transport.on_fetch = lambda: manager.sign_out(USER_ID)
    else:
        original_request = manager.run_sync_request

        def logout_before_admission(permission, request):
            manager.sign_out(USER_ID)
            return original_request(permission, request)

        monkeypatch.setattr(manager, "run_sync_request", logout_before_admission)
    try:
        with pytest.raises(RegisteredGamesError) as error:
            engine.resolve_conflict(
                conflict.id,
                "remote",
                expected_remote_version=2,
                expected_local_revision=conflict.local_revision,
            )
        assert error.value.code == "session_changed"
        assert len(transport.requests) == count + int(during_response)
        assert engine.list_conflicts() == [conflict]
        assert games.get_game(game_id)["note"] == "로컬 수정"
        assert [dict(row) for row in outbox_rows(profile)] == original_outbox
        assert engine.status().last_pulled_version == 2
    finally:
        games.close()


def test_consented_guest_route_still_uploads_with_signed_out_session(
    qapp, tmp_path: Path
):
    router, profiles, controller, _, _, services, _ = make_router(tmp_path)
    sessions = router._sessions
    assert sessions is not None
    sessions.sign_out(USER_ID)
    router.request_guest()
    profile = controller.current_profile
    assert profile is not None
    services[-1].insert_game(sample())
    transport = GuestTransport()
    engine = SyncEngine(
        profile,
        guest_client=GuestIngestClient(
            CONFIG, profile.installation_id, client=JsonHttpClient(transport)
        ),
        session_manager=sessions,
        can_sync=lambda: (
            profiles.has_data_consent(CONSENT_VERSION)
            and controller.current_profile is profile
        ),
    )
    try:
        assert engine.run_once().phase is SyncPhase.SYNCED
        assert len(transport.requests) == 1
        assert outbox_rows(profile) == []
    finally:
        router.close()
        controller.close()
