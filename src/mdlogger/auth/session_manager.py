"""오프라인 시작과 세션 복구 상태 머신(로드맵 단계 5, 결정 A).

상태 의미:

- ``SIGNED_OUT``: 이 장치에 저장된 세션이 없다. 온라인 기능은 로그인 필요.
- ``AUTHENTICATED``: 유효한 세션이 메모리에 있다.
- ``OFFLINE``: 저장된 refresh token은 있으나 지금은 서버를 확인할 수 없다.
  로컬 기록은 기간 제한 없이 계속 허용하고 동기화만 멈춘다.
- ``REAUTH_REQUIRED``: 서버가 token 폐기·만료를 확인해 줬다. 업로드를 멈추고
  재로그인을 요구하되 로컬 기록과 DB는 보존한다.

access token은 메모리에서만 사용하고, refresh token의 영구 저장은 OS 자격 증명
저장소로만 제한한다. 회전 후 저장 실패는 메모리에서 보류하며 비밀번호는 저장하지 않는다.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Condition, RLock

from .credential_store import CredentialStore, CredentialStoreBusy, CredentialStoreError
from .models import (
    AccountDeletionResult,
    AccountExportData,
    AuthError,
    AuthErrorKind,
    AuthSession,
    SignUpResult,
)
from .service import AccountService


class SessionState(StrEnum):
    SIGNED_OUT = "signed_out"
    AUTHENTICATED = "authenticated"
    OFFLINE = "offline"
    REAUTH_REQUIRED = "reauth_required"


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """상태 머신의 현재 관측값."""

    state: SessionState
    session: AuthSession | None = None
    error: AuthError | None = None
    retry_at: float | None = None


@dataclass(slots=True)
class _PendingRotation:
    """회전 성공 후 키링 저장만 실패한 토큰은 메모리에서만 보존한다."""

    session: AuthSession = field(repr=False)
    original_token: str = field(repr=False)
    guard: AbstractContextManager[None] = field(repr=False)


class SessionManager:
    """등록 계정 세션의 저장·복구·폐기를 관리한다."""

    def __init__(
        self,
        service: AccountService,
        store: CredentialStore,
        *,
        now: Callable[[], float] = time.monotonic,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        self._service = service
        self._store = store
        self._snapshot = SessionSnapshot(state=SessionState.SIGNED_OUT)
        # UI thread와 sync worker가 세션/저장소를 동시에 읽고 쓰므로
        # 상태 전이와 keyring 쓰기를 직렬화한다(P1-6).
        self._lock = RLock()
        # 로그아웃/계정 삭제가 in-flight refresh보다 늦게 끝나 그 결과가 되살아나는
        # 경쟁을 막기 위한 세대 표식(B-1). restore()는 네트워크 호출 전 값을 읽고
        # 결과 저장 직전에 값이 바뀌었으면 폐기한다.
        self._logout_generation = 0
        self._condition = Condition(self._lock)
        self._account_id: str | None = None
        self._blocked_accounts: set[str] = set()
        self._revoked_accounts: dict[str, AuthError] = {}
        self._refreshing = False
        self._refreshing_account: str | None = None
        self._pending_rotation: _PendingRotation | None = None
        self._failure_count = 0
        self._retry_at = 0.0
        self._now = now
        # 인증 난수가 아니라 재시도 분산용 지터다.
        self._jitter = jitter or (lambda upper: random.uniform(0, upper))

    @property
    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def state(self) -> SessionState:
        with self._lock:
            return self._snapshot.state

    @property
    def session(self) -> AuthSession | None:
        with self._lock:
            return self._snapshot.session

    def register(self, email: str, password: str) -> SignUpResult:
        """회원가입 요청만 수행하고 세션 저장은 프로필 전환 확정 뒤로 미룬다."""
        return self._service.sign_up(email, password)

    def authenticate(self, email: str, password: str) -> AuthSession:
        """자격 증명만 확인하고 refresh token은 아직 저장하지 않는다."""
        return self._service.sign_in(email, password)

    def activate(self, session: AuthSession) -> SessionSnapshot:
        """사용자 선택과 프로필 열기가 끝난 인증 세션을 안전하게 저장한다."""
        account_id = session.account.user_id
        with self._store.transaction(account_id), self._condition:
            self._logout_generation += 1
            self._discard_pending_rotation()
            self._account_id = account_id
            self._blocked_accounts.discard(account_id)
            self._revoked_accounts.pop(account_id, None)
            self._snapshot = SessionSnapshot(state=SessionState.SIGNED_OUT)
            self._condition.notify_all()
            self._store.save_refresh_token(account_id, session.tokens.refresh_token)
            self._remember_session(session)
            self._condition.notify_all()
            return self._snapshot

    def sign_up(self, email: str, password: str) -> SignUpResult:
        """회원가입하고 즉시 세션이 발급되면 안전하게 저장한다."""
        result = self.register(email, password)
        if result.session is not None:
            self.activate(result.session)
        return result

    def sign_in(self, email: str, password: str) -> SessionSnapshot:
        """온라인 로그인. 성공하면 refresh token을 OS 저장소에 보관한다."""
        return self.activate(self.authenticate(email, password))

    def resend_verification_email(self, email: str) -> None:
        self._service.resend_verification_email(email)

    def request_password_reset(self, email: str) -> None:
        self._service.request_password_reset(email)

    def restore(self, account_id: str) -> SessionSnapshot:
        """명시적으로 선택된 계정만 복구하며 일시 장애의 재시도 시각을 지킨다."""
        with self._condition:
            if account_id in self._blocked_accounts:
                return SessionSnapshot(state=SessionState.SIGNED_OUT)
            if account_id in self._revoked_accounts:
                return SessionSnapshot(
                    state=SessionState.REAUTH_REQUIRED,
                    error=self._revoked_accounts[account_id],
                )
            if self._account_id != account_id:
                self._logout_generation += 1
                self._discard_pending_rotation()
                self._account_id = account_id
                self._snapshot = SessionSnapshot(state=SessionState.OFFLINE)
                self._retry_at = 0
                self._failure_count = 0
                self._condition.notify_all()
        return self.session_for_sync(account_id)

    def session_for_sync(
        self, account_id: str, *, rejected_access_token: str | None = None
    ) -> SessionSnapshot:
        """현재 계정의 갱신을 합치고 복구 가능한 오프라인 상태만 재시도한다."""
        with self._condition:
            if self._account_id != account_id or account_id in self._blocked_accounts:
                return SessionSnapshot(state=SessionState.SIGNED_OUT)
            generation = self._logout_generation
            session = self._snapshot.session
            if (
                self._snapshot.state is SessionState.AUTHENTICATED
                and session is not None
            ):
                if (
                    rejected_access_token is None
                    or session.tokens.access_token != rejected_access_token
                ):
                    return self._snapshot
            if self._refreshing:
                same_account = self._refreshing_account == account_id
                self._condition.wait_for(
                    lambda: (
                        not self._refreshing or self._logout_generation != generation
                    )
                )
                if self._logout_generation != generation:
                    return SessionSnapshot(state=SessionState.SIGNED_OUT)
                if same_account:
                    return self._snapshot
            if self._snapshot.state in (
                SessionState.SIGNED_OUT,
                SessionState.REAUTH_REQUIRED,
            ):
                return self._snapshot
            if self._now() < self._retry_at:
                return self._snapshot
            self._refreshing = True
            self._refreshing_account = account_id
            pending, self._pending_rotation = self._pending_rotation, None
        try:
            return self._refresh(account_id, generation, pending)
        finally:
            with self._condition:
                self._refreshing = False
                self._refreshing_account = None
                self._condition.notify_all()

    def _refresh(
        self, account_id: str, generation: int, pending: _PendingRotation | None
    ) -> SessionSnapshot:
        guard = (
            pending.guard
            if pending is not None
            else self._store.refresh_lock(account_id)
        )
        entered = pending is not None
        keep_guard = False
        token: str | None = pending.original_token if pending is not None else None
        session = pending.session if pending is not None else None
        try:
            if not entered:
                guard.__enter__()
                entered = True
                with self._store.transaction(account_id):
                    token = self._store.load_refresh_token(account_id)
            with self._condition:
                if not self._is_current(account_id, generation):
                    return SessionSnapshot(state=SessionState.SIGNED_OUT)
                if token is None:
                    self._snapshot = SessionSnapshot(state=SessionState.SIGNED_OUT)
                    return self._snapshot
            auth_error = None
            if session is None:
                try:
                    session = self._service.refresh_session(token)
                except AuthError as error:
                    auth_error = error
            with self._store.transaction(account_id), self._condition:
                if not self._is_current(account_id, generation):
                    return SessionSnapshot(state=SessionState.SIGNED_OUT)
                current = self._store.load_refresh_token(account_id)
                # 로그아웃/새 로그인은 갱신 중에도 가능하다. 이전 토큰만 교체한다.
                acceptable = (token, session.tokens.refresh_token if session else token)
                if current not in acceptable:
                    if current is None:
                        self._snapshot = SessionSnapshot(state=SessionState.SIGNED_OUT)
                    else:
                        self._offline(
                            AuthError(
                                AuthErrorKind.NETWORK,
                                "다른 창에서 세션이 변경되어 다시 확인합니다.",
                                code="credentials_changed",
                            )
                        )
                    return self._snapshot
                if auth_error is not None:
                    if auth_error.kind in (
                        AuthErrorKind.TOKEN_EXPIRED,
                        AuthErrorKind.CREDENTIALS,
                    ):
                        self._revoked_accounts[account_id] = auth_error
                        self._snapshot = SessionSnapshot(
                            state=SessionState.REAUTH_REQUIRED, error=auth_error
                        )
                        # 삭제 실패도 이미 확인된 폐기 상태를 되돌리지 않는다.
                        try:
                            self._store.delete_refresh_token(account_id)
                        except CredentialStoreError:
                            pass
                    else:
                        self._offline(auth_error)
                    return self._snapshot
                assert session is not None
                if session.account.user_id != account_id:
                    error = AuthError(
                        AuthErrorKind.SERVER_REJECTED,
                        "저장된 계정과 복구된 세션이 일치하지 않습니다.",
                        code="account_mismatch",
                    )
                    self._revoked_accounts[account_id] = error
                    self._snapshot = SessionSnapshot(
                        state=SessionState.REAUTH_REQUIRED,
                        error=error,
                    )
                    try:
                        self._store.delete_refresh_token(account_id)
                    except CredentialStoreError:
                        pass
                    return self._snapshot
                self._store.save_refresh_token(account_id, session.tokens.refresh_token)
                self._remember_session(session)
                return self._snapshot
        except CredentialStoreError as error:
            with self._condition:
                if not self._is_current(account_id, generation):
                    return SessionSnapshot(state=SessionState.SIGNED_OUT)
                if session is not None and token is not None and entered:
                    self._pending_rotation = _PendingRotation(session, token, guard)
                    keep_guard = True
                self._offline(
                    AuthError(
                        AuthErrorKind.NETWORK
                        if isinstance(error, CredentialStoreBusy)
                        else AuthErrorKind.SERVER_REJECTED,
                        "다른 창의 세션 갱신을 기다립니다."
                        if isinstance(error, CredentialStoreBusy)
                        else "OS 자격 증명 저장소를 사용할 수 없습니다. 잠금과 권한을 확인해 주세요.",
                        code="credentials_busy"
                        if isinstance(error, CredentialStoreBusy)
                        else "credential_store_unavailable",
                    )
                )
                return self._snapshot
        finally:
            if entered and not keep_guard:
                guard.__exit__(None, None, None)

    def _is_current(self, account_id: str, generation: int) -> bool:
        return (
            self._logout_generation == generation
            and self._account_id == account_id
            and account_id not in self._blocked_accounts
        )

    def _offline(self, error: AuthError) -> None:
        self._failure_count += 1
        base = min(2 ** min(self._failure_count, 9), 300)
        retry_after = getattr(error, "retry_after_seconds", None)
        minimum = (
            retry_after if isinstance(retry_after, int) and retry_after >= 0 else 0
        )
        delay = max(base, minimum) + max(0.0, self._jitter(min(base * 0.25, 15)))
        self._retry_at = self._now() + delay
        self._snapshot = SessionSnapshot(
            state=SessionState.OFFLINE, error=error, retry_at=self._retry_at
        )

    def _discard_pending_rotation(self) -> None:
        if self._pending_rotation is not None:
            pending, self._pending_rotation = self._pending_rotation, None
            pending.guard.__exit__(None, None, None)

    def refresh_for_sync(self, account_id: str) -> AuthSession | None:
        """push 중 401을 받은 등록 계정 세션을 한 번 갱신한다."""
        current = self.session
        rejected = current.tokens.access_token if current is not None else None
        snapshot = self.session_for_sync(account_id, rejected_access_token=rejected)
        return (
            snapshot.session if snapshot.state is SessionState.AUTHENTICATED else None
        )

    def sign_out(self, account_id: str) -> SessionSnapshot:
        """로그아웃. 서버 폐기 실패와 무관하게 로컬 refresh token은 제거한다."""
        session = self.session
        self._end_session(account_id)
        self._store.delete_refresh_token(account_id)
        if session is not None and session.account.user_id == account_id:
            try:
                self._service.sign_out(session.tokens.access_token)
            except Exception:  # noqa: BLE001 - 오프라인 로그아웃도 로컬에서 완료한다
                pass
        return self.snapshot

    def _end_session(self, account_id: str) -> None:
        with self._condition:
            self._blocked_accounts.add(account_id)
            if self._account_id == account_id:
                self._logout_generation += 1
                self._snapshot = SessionSnapshot(state=SessionState.SIGNED_OUT)
                self._discard_pending_rotation()
                self._retry_at = 0
            self._condition.notify_all()

    def export_account_data(self) -> AccountExportData:
        """본인 개인 데이터를 내려받는다. 인증된 세션이 필요하다."""
        session = self._require_session()
        return self._service.export_account_data(session.tokens.access_token)

    def sign_out_all_devices(self) -> int:
        """모든 장치에서 로그아웃하고 해제된 장치 수를 돌려준다.

        서버 ``revoke-sessions`` Edge Function이 요청자 본인의 **모든 세션·refresh
        token을 실제로 폐기**(D-6)하고 등록 장치 행을 정리한다. 성공하면 이 기기의
        저장된 refresh token도 즉시 제거하고 세션을 종료한다(클라이언트 계약).
        다시 로그인하려면 로그인 창에서 로그인해야 한다. access token(JWT)은 만료
        전까지 무효화할 수 없지만 refresh token이 서버에서 제거되어 재로그인을
        강제한다.
        """
        session = self._require_session()
        count = self._service.sign_out_all_devices(session.tokens.access_token)
        self._end_session(session.account.user_id)
        self._store.delete_refresh_token(session.account.user_id)
        return count

    def delete_account(self) -> AccountDeletionResult:
        """계정 삭제를 요청한다(클라이언트 secret 없이 서버에서 수행).

        성공하면 저장된 refresh token을 제거하고 세션을 종료한다.
        """
        session = self._require_session()
        result = self._service.delete_account(session.tokens.access_token)
        self._end_session(session.account.user_id)
        self._store.delete_refresh_token(session.account.user_id)
        return result

    def _require_session(self) -> AuthSession:
        with self._lock:
            session = self._snapshot.session
            if session is None:
                raise AuthError(
                    AuthErrorKind.TOKEN_EXPIRED,
                    "세션이 만료되었습니다. 다시 로그인해 주세요.",
                )
            return session

    def _remember_session(self, session: AuthSession) -> None:
        with self._lock:
            self._failure_count = 0
            self._retry_at = 0
            self._snapshot = SessionSnapshot(
                state=SessionState.AUTHENTICATED, session=session
            )
