"""단계 6 시작 라우터와 등록/게스트 전체 UI 여정 테스트."""

from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mdlogger.app_controller import AppController
from mdlogger.auth.credential_store import InMemoryCredentialStore
from mdlogger.auth.models import (
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
from mdlogger.ui.account_views import AuthWindow

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
        guest_records_prompt=lambda count, parent: True,
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
        "score_after": 1500,
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


def test_guest_login_asks_about_records_but_does_not_import_before_stage_nine(
    qapp: QApplication, tmp_path: Path
):
    values = make_router(tmp_path)
    router, profiles, controller, _, _, services = values[:6]
    choices: list[int] = []
    router._guest_records_prompt = lambda count, parent: choices.append(count) or True

    router.request_guest()
    services[-1].insert_game(sample("guest-original"))
    guest_path = profiles.guest().database_path

    router.sign_in("a@test.local", "password")

    assert choices == [1]
    assert controller.current_profile is not None
    assert controller.current_profile.kind is ProfileKind.REGISTERED
    assert services[-1].count_games() == 0

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
    router._guest_records_prompt = lambda count, parent: False
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
