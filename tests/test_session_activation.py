"""실제 프로필 전환과 세션 활성화 실패의 경계를 검사한다."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_profile_router import make_router
from test_session_manager import OTHER_USER_ID, USER_ID, make_session, other_session
from test_sync_engine import CONFIG, RegisteredTransport, outbox_rows, sample

from mdlogger.auth.credential_store import CredentialStoreError
from mdlogger.auth.models import AuthTokens
from mdlogger.auth.session_manager import SessionManager, SessionState
from mdlogger.game_service import GameService
from mdlogger.game_sync.engine import SyncEngine
from mdlogger.game_sync.models import SyncPhase
from mdlogger.profiles import ProfileError
from mdlogger.remote.client import JsonHttpClient
from mdlogger.remote.games import RegisteredGamesClient


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.mark.parametrize("failure", ["credentials", "profile"])
def test_failed_account_switch_preserves_profile_session_and_working_sync(
    qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
):
    router, profiles, controller, account_service, store, services, _ = make_router(
        tmp_path
    )
    sessions = router._sessions
    assert sessions is not None
    router._finish_registered_sign_in(make_session())
    previous = controller.current_profile
    assert previous is not None
    original = sessions.snapshot
    services[-1].insert_game(sample("이전 계정의 미전송 기록"))
    other = profiles.registered(OTHER_USER_ID, "b@test.local")
    profiles.prepare_database(other)
    existing_other_games = GameService.open(other.database_path)
    existing_other_games.insert_game(sample("다른 계정의 기존 기록"))
    existing_other_games.close()
    store.save_refresh_token(OTHER_USER_ID, "다른 계정의 기존 토큰")

    original_save = store.save_refresh_token
    original_prepare = profiles.prepare_database

    def fail_save(account_id, refresh_token):
        if account_id == OTHER_USER_ID:
            raise CredentialStoreError("새 계정 저장 실패")
        original_save(account_id, refresh_token)

    def fail_prepare(profile):
        if profile.remote_user_id == OTHER_USER_ID:
            raise ProfileError("새 계정 프로필 열기 실패")
        original_prepare(profile)

    if failure == "credentials":
        monkeypatch.setattr(store, "save_refresh_token", fail_save)
    else:
        monkeypatch.setattr(profiles, "prepare_database", fail_prepare)
    account_service.sign_in_result = other_session()
    try:
        router._finish_registered_sign_in(sessions.authenticate("b@test.local", "암호"))

        assert controller.current_profile is previous
        assert sessions.snapshot is original
        assert sessions.session_for_sync(USER_ID).state is SessionState.AUTHENTICATED
        assert store.load_refresh_token(OTHER_USER_ID) == "다른 계정의 기존 토큰"
        assert router.auth_window.isVisible()
        transport = RegisteredTransport()
        engine = SyncEngine(
            previous,
            registered_client=RegisteredGamesClient(
                CONFIG, client=JsonHttpClient(transport)
            ),
            session_manager=sessions,
            can_sync=lambda: controller.current_profile is previous,
        )
        assert engine.run_once().phase is SyncPhase.SYNCED
        assert outbox_rows(previous) == []
        assert all(
            request["headers"]["Authorization"] == "Bearer access-1"
            for request in transport.requests
        )
        assert len(outbox_rows(other)) == 1
    finally:
        router.close()
        controller.close()


@pytest.mark.parametrize("save_fails", [False, True])
def test_logout_during_activation_does_not_reopen_previous_profile(
    qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, save_fails: bool
):
    router, _, controller, _, store, _, _ = make_router(tmp_path)
    sessions = router._sessions
    assert sessions is not None
    router._finish_registered_sign_in(make_session())
    original_save = store.save_refresh_token

    def logout_during_save(account_id, refresh_token):
        assert account_id == OTHER_USER_ID
        sessions.sign_out(USER_ID)
        if save_fails:
            raise CredentialStoreError("로그아웃 도중 저장 실패")
        original_save(account_id, refresh_token)

    monkeypatch.setattr(store, "save_refresh_token", logout_during_save)
    try:
        router._finish_registered_sign_in(other_session())
        assert controller.current_profile is None
        assert sessions.state is SessionState.SIGNED_OUT
        assert sessions.session_for_sync(USER_ID).session is None
        assert sessions.session_for_sync(OTHER_USER_ID).session is None
        assert router.auth_window.isVisible()
    finally:
        router.close()
        controller.close()


@pytest.mark.parametrize("same_account", [False, True])
def test_newer_routed_activation_is_not_overwritten_by_old_activation_failure(
    qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_account: bool
):
    router, profiles, controller, _, store, _, _ = make_router(tmp_path)
    sessions = router._sessions
    assert sessions is not None
    router._finish_registered_sign_in(make_session())
    original_save = store.save_refresh_token
    newer = replace(
        other_session() if same_account else make_session(),
        tokens=AuthTokens("새 접근 토큰", "새 갱신 토큰", 3600),
    )

    def switch_during_save(account_id, refresh_token):
        assert account_id == OTHER_USER_ID
        monkeypatch.setattr(store, "save_refresh_token", original_save)
        router._finish_registered_sign_in(newer)
        raise CredentialStoreError("이전 로그인 저장 실패")

    monkeypatch.setattr(store, "save_refresh_token", switch_during_save)
    try:
        router._finish_registered_sign_in(other_session())
        assert controller.current_profile is not None
        assert controller.current_profile.remote_user_id == newer.account.user_id
        assert sessions.session is newer
        assert sessions.state is SessionState.AUTHENTICATED
        assert not router.auth_window.isVisible()
        assert store.load_refresh_token(newer.account.user_id) == "새 갱신 토큰"
        remembered = profiles.last_profile()
        assert remembered is not None
        assert remembered.remote_user_id == newer.account.user_id
        assert remembered.session_state == "authenticated"
    finally:
        router.close()
        controller.close()


def test_logout_while_waiting_for_keyring_lock_does_not_restore_previous_profile(
    qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    router, _, controller, _, store, _, _ = make_router(tmp_path)
    sessions = router._sessions
    assert sessions is not None
    router._finish_registered_sign_in(make_session())
    original_transaction = store.transaction

    @contextmanager
    def logout_during_lock(account_id):
        if account_id == OTHER_USER_ID:
            sessions.sign_out(USER_ID)
            raise CredentialStoreError("키링 잠금 획득 실패")
        with original_transaction(account_id):
            yield

    monkeypatch.setattr(store, "transaction", logout_during_lock)
    try:
        router._finish_registered_sign_in(other_session())
        assert controller.current_profile is None
        assert sessions.state is SessionState.SIGNED_OUT
        assert router.auth_window.isVisible()
    finally:
        router.close()
        controller.close()


@pytest.mark.parametrize("superseded", [False, True])
@pytest.mark.parametrize("state_write_fails", [False, True])
def test_abandoned_activation_cannot_restore_saved_candidate_on_restart(
    qapp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    superseded: bool,
    state_write_fails: bool,
):
    router, profiles, controller, _, store, _, _ = make_router(tmp_path)
    sessions = router._sessions
    assert sessions is not None
    if superseded:
        router._finish_registered_sign_in(make_session())
    original_save = store.save_refresh_token

    if state_write_fails:

        def fail_state_write(_state):
            raise ProfileError("세션 상태 기록 실패")

        monkeypatch.setattr(profiles, "set_session_state", fail_state_write)

    def save_after_logout(account_id, refresh_token):
        if superseded:
            sessions.sign_out(USER_ID)
        original_save(account_id, refresh_token)
        if not superseded:
            raise CredentialStoreError("저장 결과 확인 실패")

    monkeypatch.setattr(store, "save_refresh_token", save_after_logout)
    try:
        router._finish_registered_sign_in(other_session())
        assert sessions.state is SessionState.SIGNED_OUT
        assert controller.current_profile is None
        assert store.load_refresh_token(OTHER_USER_ID) == "다른 갱신 토큰"
    finally:
        router.close()
        controller.close()
    monkeypatch.setattr(store, "save_refresh_token", original_save)

    restarted, _, restarted_app, service, _, _, _ = make_router(tmp_path)
    restarted._sessions = SessionManager(service, store)
    restarted._credential_store = store
    refresh_calls = []

    def refresh_candidate(token):
        refresh_calls.append(token)
        return other_session()

    monkeypatch.setattr(service, "refresh_session", refresh_candidate)
    try:
        restarted.start()
        assert refresh_calls == [], (
            "취소된 로그인 토큰은 재시작해도 자동 사용하지 않습니다."
        )
        assert restarted_app.current_profile is None
        assert restarted._sessions.state is SessionState.SIGNED_OUT
        assert restarted.auth_window.isVisible()
    finally:
        restarted.close()
        restarted_app.close()


def test_successful_login_survives_automatic_restore_preference_failure(
    qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    router, profiles, controller, _, store, _, _ = make_router(tmp_path)
    notices = []

    def fail_state_write(_state):
        raise ProfileError("세션 상태 기록 실패")

    monkeypatch.setattr(profiles, "set_session_state", fail_state_write)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: notices.append(args))
    try:
        router._finish_registered_sign_in(other_session())
        assert router._sessions is not None
        assert router._sessions.state is SessionState.AUTHENTICATED
        assert controller.current_profile is not None
        assert controller.current_profile.remote_user_id == OTHER_USER_ID
        assert not router.auth_window.isVisible()
        assert store.load_refresh_token(OTHER_USER_ID) == "다른 갱신 토큰"
        remembered = profiles.last_profile()
        assert remembered is not None and remembered.session_state == "signed_out"
        assert "로그인은 완료" in notices[0][2]
    finally:
        router.close()
        controller.close()
