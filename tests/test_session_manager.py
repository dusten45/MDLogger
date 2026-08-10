"""오프라인 시작·세션 복구 상태 머신 테스트."""

from __future__ import annotations

import threading

import pytest

from mdlogger.auth.credential_store import InMemoryCredentialStore
from mdlogger.auth.models import (
    AccountDeletionResult,
    AccountExportData,
    AccountInfo,
    AuthError,
    AuthErrorKind,
    AuthSession,
    AuthTokens,
    DeviceInfo,
    SignUpResult,
)
from mdlogger.auth.service import AccountService
from mdlogger.auth.session_manager import (
    SessionManager,
    SessionSnapshot,
    SessionState,
)

USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def make_session(refresh_token: str = "refresh-1") -> AuthSession:
    return AuthSession(
        account=AccountInfo(user_id=USER_ID, email="a@test.local", email_verified=True),
        tokens=AuthTokens(
            access_token="access-1", refresh_token=refresh_token, expires_in=3600
        ),
    )


class FakeAccountService(AccountService):
    """호출을 기록하고 준비된 결과를 돌려주는 fake."""

    def __init__(self):
        self.sign_up_result: SignUpResult | AuthError = SignUpResult(
            account=make_session().account, session=make_session()
        )
        self.sign_in_result: AuthSession | AuthError = make_session()
        self.refresh_result: AuthSession | AuthError = make_session("refresh-2")
        self.sign_out_error: AuthError | None = None
        self.sign_out_calls: list[str] = []
        self.refresh_calls: list[str] = []

    def sign_up(self, email: str, password: str) -> SignUpResult:
        if isinstance(self.sign_up_result, AuthError):
            raise self.sign_up_result
        return self.sign_up_result

    def sign_in(self, email: str, password: str) -> AuthSession:
        if isinstance(self.sign_in_result, AuthError):
            raise self.sign_in_result
        return self.sign_in_result

    def refresh_session(self, refresh_token: str) -> AuthSession:
        self.refresh_calls.append(refresh_token)
        if isinstance(self.refresh_result, AuthError):
            raise self.refresh_result
        return self.refresh_result

    def sign_out(self, access_token: str) -> None:
        self.sign_out_calls.append(access_token)
        if self.sign_out_error is not None:
            raise self.sign_out_error

    def resend_verification_email(self, email: str) -> None:
        raise NotImplementedError

    def request_password_reset(self, email: str) -> None:
        raise NotImplementedError

    def export_account_data(self, access_token: str) -> AccountExportData:
        raise NotImplementedError

    def list_devices(self, access_token: str) -> list[DeviceInfo]:
        raise NotImplementedError

    def revoke_device(self, access_token: str, installation_id: str) -> None:
        raise NotImplementedError

    def sign_out_all_devices(self, access_token: str) -> int:
        raise NotImplementedError

    def delete_account(
        self, access_token: str, user_id: str | None = None
    ) -> AccountDeletionResult:
        raise NotImplementedError


def make_manager() -> tuple[
    SessionManager, FakeAccountService, InMemoryCredentialStore
]:
    service = FakeAccountService()
    store = InMemoryCredentialStore()
    return SessionManager(service, store), service, store


def test_sign_up_with_immediate_session_stores_refresh_token():
    manager, _, store = make_manager()

    result = manager.sign_up("a@test.local", "password")

    assert result.session is not None
    assert manager.state is SessionState.AUTHENTICATED
    assert store.load_refresh_token(USER_ID) == "refresh-1"


def test_sign_in_stores_refresh_token_and_authenticates():
    manager, _, store = make_manager()

    snapshot = manager.sign_in("a@test.local", "pw")

    assert snapshot.state is SessionState.AUTHENTICATED
    assert store.load_refresh_token(USER_ID) == "refresh-1"
    assert manager.session is not None


def test_restore_without_stored_token_is_signed_out():
    manager, service, _ = make_manager()

    snapshot = manager.restore(USER_ID)

    assert snapshot.state is SessionState.SIGNED_OUT
    assert service.refresh_calls == []


def test_restore_success_rotates_stored_refresh_token():
    manager, service, store = make_manager()
    store.save_refresh_token(USER_ID, "refresh-1")

    snapshot = manager.restore(USER_ID)

    assert snapshot.state is SessionState.AUTHENTICATED
    assert service.refresh_calls == ["refresh-1"]
    assert store.load_refresh_token(USER_ID) == "refresh-2"


def test_restore_rejects_mismatched_account_before_storing_rotated_token():
    manager, service, store = make_manager()
    store.save_refresh_token(USER_ID, "refresh-1")
    other_user_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    service.refresh_result = AuthSession(
        account=AccountInfo(
            user_id=other_user_id,
            email="b@test.local",
            email_verified=True,
        ),
        tokens=AuthTokens(
            access_token="access-b",
            refresh_token="refresh-b",
            expires_in=3600,
        ),
    )

    snapshot = manager.restore(USER_ID)

    assert snapshot.state is SessionState.REAUTH_REQUIRED
    assert snapshot.error is not None
    assert snapshot.error.code == "account_mismatch"
    assert store.load_refresh_token(USER_ID) is None
    assert store.load_refresh_token(other_user_id) is None


def test_restore_network_failure_keeps_token_and_goes_offline():
    manager, service, store = make_manager()
    store.save_refresh_token(USER_ID, "refresh-1")
    service.refresh_result = AuthError(AuthErrorKind.NETWORK, "오프라인")

    snapshot = manager.restore(USER_ID)

    assert snapshot.state is SessionState.OFFLINE
    assert snapshot.error is not None
    assert snapshot.error.kind is AuthErrorKind.NETWORK
    # 오프라인은 재로그인 사유가 아니다: token과 로컬 사용을 유지한다.
    assert store.load_refresh_token(USER_ID) == "refresh-1"


def test_restore_revoked_token_requires_reauth_and_removes_token():
    manager, service, store = make_manager()
    store.save_refresh_token(USER_ID, "refresh-1")
    service.refresh_result = AuthError(
        AuthErrorKind.TOKEN_EXPIRED, "폐기됨", code="refresh_token_not_found"
    )

    snapshot = manager.restore(USER_ID)

    assert snapshot.state is SessionState.REAUTH_REQUIRED
    assert store.load_refresh_token(USER_ID) is None


def test_restore_server_error_keeps_token_and_pauses_sync():
    manager, service, store = make_manager()
    store.save_refresh_token(USER_ID, "refresh-1")
    service.refresh_result = AuthError(AuthErrorKind.SERVER_REJECTED, "서버 오류")

    snapshot = manager.restore(USER_ID)

    # 폐기가 확인되지 않았으므로 재로그인을 강요하지 않는다.
    assert snapshot.state is SessionState.OFFLINE
    assert store.load_refresh_token(USER_ID) == "refresh-1"


def test_sign_out_revokes_server_session_and_removes_token():
    manager, service, store = make_manager()
    manager.sign_in("a@test.local", "pw")

    snapshot = manager.sign_out(USER_ID)

    assert snapshot.state is SessionState.SIGNED_OUT
    assert service.sign_out_calls == ["access-1"]
    assert store.load_refresh_token(USER_ID) is None


def test_sign_out_removes_token_even_when_server_call_fails():
    manager, service, store = make_manager()
    manager.sign_in("a@test.local", "pw")
    service.sign_out_error = AuthError(AuthErrorKind.NETWORK, "오프라인")

    snapshot = manager.sign_out(USER_ID)

    assert snapshot.state is SessionState.SIGNED_OUT
    assert store.load_refresh_token(USER_ID) is None


def test_sign_out_removes_token_even_on_non_auth_error():
    """B-5-1: AuthError가 아닌 예외(예: 보안 저장소 오류)가 나도 로컬 토큰은
    지워진다. 로그아웃의 로컬 토큰 제거는 원인과 무관하게 보장돼야 한다."""

    class ExplodingSignOutService(FakeAccountService):
        def sign_out(self, access_token: str) -> None:
            raise RuntimeError("예상치 못한 로그아웃 오류")

    service = ExplodingSignOutService()
    store = InMemoryCredentialStore()
    manager = SessionManager(service, store)
    manager.sign_in("a@test.local", "pw")

    snapshot = manager.sign_out(USER_ID)

    assert snapshot.state is SessionState.SIGNED_OUT
    assert store.load_refresh_token(USER_ID) is None


def test_logout_during_refresh_discards_rotated_token():
    """B-1(a): refresh가 진행 중인 동안 로그아웃이 끼어들면, refresh가 늦게
    끝나도 회전된 토큰을 다시 저장하지 않고 SIGNED_OUT을 유지한다."""

    class DelayedRefreshService(FakeAccountService):
        def __init__(self) -> None:
            super().__init__()
            self._entered: threading.Event | None = None
            self._release: threading.Event | None = None

        def set_delay(self, entered: threading.Event, release: threading.Event):
            self._entered = entered
            self._release = release

        def refresh_session(self, refresh_token: str) -> AuthSession:
            entered = self._entered
            release = self._release
            if entered is not None and release is not None:
                entered.set()
                release.wait()
            return super().refresh_session(refresh_token)

    service = DelayedRefreshService()
    store = InMemoryCredentialStore()
    manager = SessionManager(service, store)
    store.save_refresh_token(USER_ID, "refresh-1")

    entered = threading.Event()
    release = threading.Event()
    service.set_delay(entered, release)

    result: list[SessionSnapshot] = []

    def run_refresh():
        result.append(manager.restore(USER_ID))

    refresh_thread = threading.Thread(target=run_refresh)
    refresh_thread.start()
    assert entered.wait(2.0)

    # refresh가 in-flight인 동안 로그아웃한다.
    manager.sign_out(USER_ID)
    release.set()
    refresh_thread.join()

    snapshot = result[0]
    assert snapshot.state is SessionState.SIGNED_OUT
    # 회전된 토큰(refresh-2)이 다시 저장되지 않아야 한다.
    assert store.load_refresh_token(USER_ID) is None


def test_account_operations_require_active_session():
    manager, service, store = make_manager()

    with pytest.raises(AuthError) as exc_info:
        manager.export_account_data()
    assert exc_info.value.kind is AuthErrorKind.TOKEN_EXPIRED

    with pytest.raises(AuthError):
        manager.list_devices()
    with pytest.raises(AuthError):
        manager.sign_out_all_devices()
    with pytest.raises(AuthError):
        manager.delete_account()


def test_concurrent_access_keeps_state_consistent():
    """P1-6: UI thread와 sync worker가 동시에 접근해도 상태가 일관되게 유지된다."""
    manager, service, store = make_manager()
    store.save_refresh_token(USER_ID, "refresh-1")
    errors: list[Exception] = []

    def reader():
        for _ in range(200):
            try:
                manager.state
                manager.session
                manager.snapshot
            except Exception as error:  # noqa: BLE001
                errors.append(error)

    def writer():
        for _ in range(200):
            try:
                manager.restore(USER_ID)
            except Exception as error:  # noqa: BLE001
                errors.append(error)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    threads += [threading.Thread(target=writer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    # writer가 마지막으로 restore한 상태는 항상 유효한 스냅샷이다.
    state = manager.state
    assert state in (
        SessionState.AUTHENTICATED,
        SessionState.OFFLINE,
        SessionState.REAUTH_REQUIRED,
    )
