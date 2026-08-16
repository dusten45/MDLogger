"""단계 6 시작 라우터와 등록/게스트 전체 UI 여정 테스트."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from mdlogger.app_controller import AppController
from mdlogger.auth.credential_store import InMemoryCredentialStore
from mdlogger.auth.models import (
    AccountDeletionResult,
    AccountInfo,
    AuthError,
    AuthErrorKind,
    AuthSession,
    AuthTokens,
    SignUpResult,
)
from mdlogger.auth.service import AccountService
from mdlogger.auth.session_manager import SessionManager, SessionState
from mdlogger.game_service import GameService
from mdlogger.profile_router import CONSENT_VERSION, ProfileRouter
from mdlogger.profiles import ProfileContext, ProfileKind, ProfileManager
from mdlogger.ui.account_views import AccountDialog, AuthWindow, GuestRecordChoice

USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def make_session(*, refresh_token: str = "refresh-1") -> AuthSession:
    return AuthSession(
        account=AccountInfo(user_id=USER_ID, email="a@test.local", email_verified=True),
        tokens=AuthTokens(
            access_token="access-1", refresh_token=refresh_token, expires_in=3600
        ),
    )


class FakeAccountService(AccountService):
    def __init__(self) -> None:
        self.sign_in_result: AuthSession | AuthError = make_session()
        self.sign_up_result: SignUpResult | AuthError = SignUpResult(
            account=AccountInfo(
                user_id=USER_ID,
                email="a@test.local",
                email_verified=False,
            ),
            session=None,
        )
        self.refresh_result: AuthSession | AuthError = make_session(
            refresh_token="refresh-2"
        )
        self.resend_calls: list[str] = []
        self.reset_calls: list[str] = []
        self.sign_in_gate: Event | None = None
        self.sign_out_all_count: int = 0

    def sign_up(self, email: str, password: str) -> SignUpResult:
        if isinstance(self.sign_up_result, AuthError):
            raise self.sign_up_result
        return self.sign_up_result

    def sign_in(self, email: str, password: str) -> AuthSession:
        if self.sign_in_gate is not None:
            self.sign_in_gate.wait(timeout=2)
        if isinstance(self.sign_in_result, AuthError):
            raise self.sign_in_result
        return self.sign_in_result

    def refresh_session(self, refresh_token: str) -> AuthSession:
        if isinstance(self.refresh_result, AuthError):
            raise self.refresh_result
        return self.refresh_result

    def sign_out(self, access_token: str) -> None:
        return None

    def resend_verification_email(self, email: str) -> None:
        self.resend_calls.append(email)

    def request_password_reset(self, email: str) -> None:
        self.reset_calls.append(email)

    def export_account_data(self, access_token: str):
        raise NotImplementedError

    def sign_out_all_devices(self, access_token: str) -> int:
        return self.sign_out_all_count

    def delete_account(
        self, access_token: str, user_id: str | None = None
    ) -> AccountDeletionResult:
        return AccountDeletionResult(
            deleted_games=0,
            deleted_devices=0,
            deleted_profiles=0,
            deleted_auth_user=True,
        )


class TrackingWindow:
    def __init__(self, games: GameService, profile: ProfileContext) -> None:
        self.games = games
        self.profile = profile
        self.visible = False
        self.closed = False

    def show(self) -> None:
        self.visible = True

    def close_profile_windows(self) -> None:
        self.visible = False
        self.closed = True


def make_router(tmp_path: Path, auth_window: AuthWindow | None = None):
    profiles = ProfileManager(tmp_path)
    services: list[GameService] = []
    windows: list[TrackingWindow] = []

    def service_factory(profile: ProfileContext) -> GameService:
        games = GameService.open(profile.database_path)
        services.append(games)
        return games

    def window_factory(games: GameService, profile: ProfileContext) -> TrackingWindow:
        window = TrackingWindow(games, profile)
        windows.append(window)
        return window

    app_controller = AppController(profiles, service_factory, window_factory)
    account_service = FakeAccountService()
    store = InMemoryCredentialStore()
    sessions = SessionManager(account_service, store)
    router = ProfileRouter(
        profiles,
        app_controller,
        sessions,
        auth_window=auth_window,
        consent_prompt=lambda registered, parent: True,
        guest_records_prompt=lambda count, parent: GuestRecordChoice.KEEP,
        import_result_prompt=lambda result, error, parent: True,
    )
    return (
        router,
        profiles,
        app_controller,
        account_service,
        store,
        services,
        windows,
    )


def sample(note: str) -> dict:
    return {
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "테스트 덱",
        "opp_deck": "상대 덱",
        "turns": 4,
        "end_reason": "regular",
        "standing_kind": "event_points",
        "play_context_id": "dc_cup_2026_08",
        "event_points_before": 0,
        "event_points_after": 1500,
        "note": note,
    }


def test_first_start_shows_choice_then_guest_consent_is_not_repeated(
    qapp: QApplication, tmp_path: Path
):
    prompts: list[bool] = []
    values = make_router(tmp_path)
    router, profiles, controller = values[:3]
    router._consent_prompt = lambda registered, parent: (
        prompts.append(registered) or True
    )

    router.start()
    assert router.auth_window.isVisible()
    assert controller.current_profile is None

    router.request_guest()
    assert prompts == [False]
    assert profiles.has_data_consent(CONSENT_VERSION)
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.GUEST

    router.close()
    controller.close()

    second_values = make_router(tmp_path)
    second_router, _, second_controller = second_values[:3]
    second_router._consent_prompt = lambda registered, parent: pytest.fail(
        "저장된 동의는 다시 묻지 않아야 합니다."
    )
    second_router.start()
    assert second_controller.current_profile is not None
    assert second_controller.current_profile.kind is ProfileKind.GUEST
    second_router.close()
    second_controller.close()


def test_saved_registered_session_restores_without_login_window(
    qapp: QApplication, tmp_path: Path
):
    values = make_router(tmp_path)
    router, profiles, controller, _, store = values[:5]
    profiles.accept_data_consent(CONSENT_VERSION)
    profiles.remember_profile(profiles.registered(USER_ID, "a@test.local"))
    store.save_refresh_token(USER_ID, "refresh-1")

    router.start()

    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.REGISTERED
    assert controller.current_profile.session_state == "authenticated"
    assert not router.auth_window.isVisible()
    assert store.load_refresh_token(USER_ID) == "refresh-2"
    router.close()
    controller.close()


def test_saved_registered_profile_opens_local_data_when_network_is_offline(
    qapp: QApplication, tmp_path: Path
):
    values = make_router(tmp_path)
    router, profiles, controller, account_service, store = values[:5]
    profiles.accept_data_consent(CONSENT_VERSION)
    profiles.remember_profile(profiles.registered(USER_ID, "a@test.local"))
    store.save_refresh_token(USER_ID, "refresh-1")
    account_service.refresh_result = AuthError(AuthErrorKind.NETWORK, "offline")

    router.start()

    assert controller.current_profile is not None
    assert controller.current_profile.session_state == "offline"
    assert store.load_refresh_token(USER_ID) == "refresh-1"
    assert not router.auth_window.isVisible()
    router.close()
    controller.close()


def test_guest_login_imports_records_into_registered_home_and_preserves_guest(
    qapp: QApplication, tmp_path: Path
):
    values = make_router(tmp_path)
    router, profiles, controller, _, _, services = values[:6]
    choices: list[int] = []
    router._guest_records_prompt = lambda count, parent: (
        choices.append(count) or GuestRecordChoice.IMPORT
    )

    router.request_guest()
    services[-1].insert_game(sample("guest-original"))
    guest_path = profiles.guest().database_path
    guest_sync_id = services[-1].get_last_game()["sync_id"]

    router.sign_in("a@test.local", "password")

    assert choices == [1]
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.REGISTERED
    assert services[-1].count_games() == 1
    imported = services[-1].get_last_game()
    assert imported["note"] == "guest-original"
    assert imported["sync_id"] == guest_sync_id
    assert imported["sync_status"] == "pending"

    # 원본 게스트 DB는 삭제되지 않고 기록이 보존된다.
    guest_games = GameService.open(guest_path)
    guest_record = guest_games.get_last_game()
    assert guest_record is not None
    assert guest_record["note"] == "guest-original"
    guest_games.close()
    router.close()
    controller.close()


def test_cancelled_guest_record_choice_does_not_commit_authenticated_session(
    qapp: QApplication, tmp_path: Path
):
    values = make_router(tmp_path)
    router, _, controller, _, store, services = values[:6]
    router._guest_records_prompt = lambda count, parent: GuestRecordChoice.LATER
    router.request_guest()
    services[-1].insert_game(sample("guest"))

    router.sign_in("a@test.local", "password")

    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.GUEST
    assert store.load_refresh_token(USER_ID) is None
    assert router._sessions is not None
    assert router._sessions.state is SessionState.SIGNED_OUT
    router.close()
    controller.close()


def test_profile_open_failure_restores_previous_profile_without_committing_session(
    qapp: QApplication, tmp_path: Path
):
    values = make_router(tmp_path)
    router, _, controller, _, store = values[:5]
    router.request_guest()
    original_factory = controller._service_factory

    def fail_registered(profile: ProfileContext) -> GameService:
        if profile.kind is ProfileKind.REGISTERED:
            raise RuntimeError("injected open failure")
        return original_factory(profile)

    controller._service_factory = fail_registered
    router.sign_in("a@test.local", "password")

    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.GUEST
    assert store.load_refresh_token(USER_ID) is None
    assert router.auth_window.isVisible()
    assert "프로필을 열 수 없습니다" in router.auth_window._status.text()
    router.close()
    controller.close()


def test_revoked_saved_session_shows_login_but_keeps_local_profile_available(
    qapp: QApplication, tmp_path: Path
):
    values = make_router(tmp_path)
    router, profiles, controller, account_service, store = values[:5]
    profiles.accept_data_consent(CONSENT_VERSION)
    profiles.remember_profile(profiles.registered(USER_ID, "a@test.local"))
    store.save_refresh_token(USER_ID, "refresh-1")
    account_service.refresh_result = AuthError(AuthErrorKind.TOKEN_EXPIRED, "revoked")

    router.start()

    assert controller.current_profile is not None
    assert controller.current_profile.session_state == "reauth_required"
    assert router.auth_window.isVisible()
    assert "다시 로그인" in router.auth_window._status.text()
    router.close()
    controller.close()


def test_signed_out_state_starts_with_clean_login_window(
    qapp: QApplication, tmp_path: Path
):
    """로그아웃 상태(session_state='signed_out')가 영속화되어 있으면 다음 시작 시
    등록 프로필을 열지 않고 깨끗한 로그인 창으로만 시작한다. 잔존 refresh token이
    있어도 로그아웃 상태가 우선한다."""
    values = make_router(tmp_path)
    router, profiles, controller, _, store = values[:5]
    profiles.accept_data_consent(CONSENT_VERSION)
    profiles.remember_profile(profiles.registered(USER_ID, "a@test.local"))
    store.save_refresh_token(USER_ID, "refresh-1")
    profiles.set_session_state("signed_out")

    router.start()

    assert controller.current_profile is None
    assert controller.current_window is None
    assert router.auth_window.isVisible()
    assert "로그아웃" in router.auth_window._status.text()
    router.close()
    controller.close()


def test_logout_returns_to_login_window_and_marks_session_signed_out(
    qapp: QApplication, tmp_path: Path
):
    """등록 계정 로그아웃 시 게스트로 전환하지 않고 로그인 창으로 돌아가며,
    저장된 세션 상태를 '로그아웃됨'으로 갱신한다."""
    values = make_router(tmp_path)
    router, profiles, controller, _, _ = values[:5]
    profiles.accept_data_consent(CONSENT_VERSION)
    router.sign_in("a@test.local", "password")
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.REGISTERED

    router._logout_from_dialog(
        AccountDialog("a@test.local", "로그인됨", registered=True)
    )

    assert controller.current_profile is None
    assert profiles.last_profile() is not None
    assert profiles.last_profile().session_state == "signed_out"
    assert controller.current_window is None
    assert router.auth_window.isVisible()
    router.close()
    controller.close()


def test_sign_out_all_devices_returns_to_login_window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """모든 기기에서 로그아웃도 게스트가 아닌 로그인 창으로 돌아간다."""
    values = make_router(tmp_path)
    router, profiles, controller, account_service, _ = values[:5]
    profiles.accept_data_consent(CONSENT_VERSION)
    router.sign_in("a@test.local", "password")
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.REGISTERED

    account_service.sign_out_all_count = 2
    monkeypatch.setattr(
        "mdlogger.profile_router.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    notices: list[str] = []
    monkeypatch.setattr(
        "mdlogger.profile_router.QMessageBox.information",
        lambda *args, **kwargs: notices.append(str(args[2])),
    )
    router._sign_out_all_devices(
        AccountDialog("a@test.local", "로그인됨", registered=True)
    )

    assert controller.current_profile is None
    assert controller.current_window is None
    assert router.auth_window.isVisible()
    assert profiles.last_profile().session_state == "signed_out"
    # 로그인 창 위에 해제된 기기 수 알림이 표시된다.
    assert notices == ["2대의 기기에서 로그아웃하였습니다."]
    router.close()
    controller.close()


def test_delete_account_returns_to_login_window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """계정 삭제 후에도 게스트가 아닌 로그인 창으로 돌아간다."""
    values = make_router(tmp_path)
    router, profiles, controller, _, _ = values[:5]
    profiles.accept_data_consent(CONSENT_VERSION)
    router.sign_in("a@test.local", "password")
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.REGISTERED

    monkeypatch.setattr(
        "mdlogger.profile_router.QMessageBox.warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "mdlogger.profile_router.QMessageBox.information",
        lambda *args, **kwargs: None,
    )
    router._delete_account(AccountDialog("a@test.local", "로그인됨", registered=True))

    assert controller.current_profile is None
    assert controller.current_window is None
    assert router.auth_window.isVisible()
    assert profiles.last_profile().session_state == "signed_out"
    router.close()
    controller.close()


def test_reopening_auth_window_reenables_guest_and_password_toggle(
    qapp: QApplication, tmp_path: Path
):
    """P0-6: 요청 중 비활성화된 게스트/비밀번호 표시가 창을 다시 열면 되살아난다.

    set_busy(True)는 _guest/_show_password까지 비활성화하지만 set_online_available은
    이 둘을 재활성화하지 않는다. show_auth가 set_busy(False)로 먼저 되돌려야 한다.
    """
    auth_window = AuthWindow()
    values = make_router(tmp_path, auth_window)
    router, controller = values[0], values[2]

    router.show_auth()
    router._auth.set_busy(True)
    assert router._auth._guest.isEnabled() is False
    assert router._auth._show_password.isEnabled() is False

    # 요청 중 창을 닫았다(취소) 다시 열어도 재활성화되어야 한다.
    router._cancel_auth_flow()
    router.show_auth()

    assert router._auth._guest.isEnabled() is True
    assert router._auth._show_password.isEnabled() is True
    router.close()
    controller.close()


def test_auth_window_signal_runs_network_request_without_blocking_gui_thread(
    qapp: QApplication, tmp_path: Path
):
    auth_window = AuthWindow()
    values = make_router(tmp_path, auth_window)
    router, _, controller, account_service = values[:4]
    gate = Event()
    account_service.sign_in_gate = gate
    router.show_auth()
    auth_window._email.setText("a@test.local")
    auth_window._password.setText("password")

    started = time.monotonic()
    auth_window._submit.click()
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert not auth_window._submit.isEnabled()
    assert controller.current_profile is None

    gate.set()
    deadline = time.monotonic() + 2
    while controller.current_profile is None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.REGISTERED
    router.close()
    controller.close()


def test_closing_auth_window_discards_late_successful_account_switch(
    qapp: QApplication, tmp_path: Path
):
    auth_window = AuthWindow()
    values = make_router(tmp_path, auth_window)
    router, _, controller, account_service, store = values[:5]
    router.request_guest()
    gate = Event()
    account_service.sign_in_gate = gate
    router.show_auth()
    auth_window._email.setText("a@test.local")
    auth_window._password.setText("password")
    auth_window._submit.click()

    auth_window.close()
    gate.set()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.GUEST
    assert store.load_refresh_token(USER_ID) is None
    router.close()
    controller.close()


def test_signup_verification_resend_and_password_reset_ui_paths(
    qapp: QApplication, tmp_path: Path
):
    auth_window = AuthWindow()
    values = make_router(tmp_path, auth_window)
    router, _, controller, account_service = values[:4]
    router.show_auth()

    router.sign_up("a@test.local", "password")
    assert auth_window._stack.currentWidget() is auth_window._verification_page

    router.resend_verification("a@test.local")
    assert account_service.resend_calls == ["a@test.local"]
    assert "다시 보냈습니다" in auth_window._verification_status.text()

    auth_window.show_login()
    router.request_password_reset("a@test.local")
    assert account_service.reset_calls == ["a@test.local"]
    assert "메일함" in auth_window._status.text()
    router.close()
    controller.close()


def test_credentials_and_network_errors_have_distinct_recovery_messages(
    qapp: QApplication, tmp_path: Path
):
    auth_window = AuthWindow()
    values = make_router(tmp_path, auth_window)
    router, _, controller, account_service = values[:4]
    router.show_auth()

    account_service.sign_in_result = AuthError(AuthErrorKind.CREDENTIALS, "invalid")
    router.sign_in("a@test.local", "password")
    assert auth_window._password_error.isVisible()
    assert "이메일 또는 비밀번호" in auth_window._password_error.text()

    account_service.sign_in_result = AuthError(AuthErrorKind.NETWORK, "offline")
    router.sign_in("a@test.local", "password")
    assert "네트워크" in auth_window._status.text()
    assert "게스트" in auth_window._status.text()

    account_service.sign_up_result = AuthError(
        AuthErrorKind.CREDENTIALS, "exists", code="email_exists"
    )
    router.sign_up("a@test.local", "password")
    assert auth_window._email_error.isVisible()
    assert "이미 가입" in auth_window._email_error.text()

    account_service.sign_up_result = AuthError(
        AuthErrorKind.CREDENTIALS,
        "unauthorized",
        code="email_address_not_authorized",
    )
    router.sign_up("blocked@test.local", "password")
    assert "가입에 사용할 수 없습니다" in auth_window._email_error.text()
    router.close()
    controller.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX 파일 권한 테스트")
def test_prepare_database_secures_profile_db_sidecars(tmp_path: Path):
    """P2-4: 프로필 DB(기본 DB_PATH 외)의 -wal/-shm 사이드카도 0600으로 보호된다."""
    profiles = ProfileManager(tmp_path)

    guest = profiles.guest()
    profiles.prepare_database(guest)
    assert guest.database_path.exists()
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = guest.database_path.with_name(guest.database_path.name + suffix)
        if sidecar.exists():
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600

    registered = profiles.registered(
        USER_ID, "account@example.com", session_state="offline"
    )
    profiles.prepare_database(registered)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = registered.database_path.with_name(
            registered.database_path.name + suffix
        )
        if sidecar.exists():
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_auth_error_message_rate_limited_and_code_hint():
    """RATE_LIMITED는 재시도 안내로, 분류 못 한 서버 오류는 원인 코드를 함께 보인다."""
    rate_message = ProfileRouter._auth_error_message(
        AuthError(AuthErrorKind.RATE_LIMITED, "제한됨")
    )
    assert "잠시 후 다시 시도" in rate_message

    unknown = ProfileRouter._auth_error_message(
        AuthError(
            AuthErrorKind.SERVER_REJECTED,
            "거부됨",
            code="over_email_send_rate_limit",
        )
    )
    assert "over_email_send_rate_limit" in unknown

    no_code = ProfileRouter._auth_error_message(
        AuthError(AuthErrorKind.SERVER_REJECTED, "거부됨")
    )
    assert "(코드:" not in no_code
