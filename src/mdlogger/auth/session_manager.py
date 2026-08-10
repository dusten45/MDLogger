"""오프라인 시작과 세션 복구 상태 머신(로드맵 단계 5, 결정 A).

상태 의미:

- ``SIGNED_OUT``: 이 장치에 저장된 세션이 없다. 온라인 기능은 로그인 필요.
- ``AUTHENTICATED``: 유효한 세션이 메모리에 있다.
- ``OFFLINE``: 저장된 refresh token은 있으나 지금은 서버를 확인할 수 없다.
  로컬 기록은 기간 제한 없이 계속 허용하고 동기화만 멈춘다.
- ``REAUTH_REQUIRED``: 서버가 token 폐기·만료를 확인해 줬다. 업로드를 멈추고
  재로그인을 요구하되 로컬 기록과 DB는 보존한다.

access token은 이 객체의 메모리에만 있고, refresh token은 OS 자격 증명
저장소에만 있다. 비밀번호는 어디에도 저장하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from .credential_store import CredentialStore, CredentialStoreError
from .models import (
    AccountDeletionResult,
    AccountExportData,
    AuthError,
    AuthErrorKind,
    AuthSession,
    DeviceInfo,
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


class SessionManager:
    """등록 계정 세션의 저장·복구·폐기를 관리한다."""

    def __init__(self, service: AccountService, store: CredentialStore) -> None:
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
        with self._lock:
            self._remember_session(session)
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
        """앱 시작 시 저장된 refresh token으로 세션을 복구한다.

        - 저장된 token 없음 → ``SIGNED_OUT``
        - 네트워크/일시적 서버 오류 → ``OFFLINE`` (token 보존, 로컬 사용 계속)
        - 서버가 token 폐기·만료 확인 → token 제거 후 ``REAUTH_REQUIRED``
        """
        # 네트워크 refresh 동안 로그아웃/삭제가 끼어들 수 있으므로 현재 세대를
        # 기록하고, 결과 저장 직전에 세대가 바뀐 경우 저장을 포기한다(B-1).
        # token을 읽기 **전에** 세대를 기록해야 한다. 순서가 반대면 load와
        # 세대 기록 사이에 끼어든 로그아웃이 이미 증가한 세대를 읽게 되어
        # 비교를 통과하고, 방금 지운 token을 다시 저장한다.
        generation = self._logout_generation

        refresh_token = self._store.load_refresh_token(account_id)
        if refresh_token is None:
            with self._lock:
                self._snapshot = SessionSnapshot(state=SessionState.SIGNED_OUT)
            return self._snapshot

        try:
            session = self._service.refresh_session(refresh_token)
        except AuthError as error:
            with self._lock:
                if self._logout_generation != generation:
                    return self._snapshot
                if error.kind is AuthErrorKind.NETWORK:
                    self._snapshot = SessionSnapshot(
                        state=SessionState.OFFLINE, error=error
                    )
                elif error.kind in (
                    AuthErrorKind.TOKEN_EXPIRED,
                    AuthErrorKind.CREDENTIALS,
                ):
                    # 폐기가 확인된 token만 제거한다. 로컬 DB는 보존된다.
                    self._store.delete_refresh_token(account_id)
                    self._snapshot = SessionSnapshot(
                        state=SessionState.REAUTH_REQUIRED, error=error
                    )
                else:
                    # 서버 오류 등: 폐기가 확인되지 않았으므로 token을 보존하고
                    # 오프라인과 같은 방식으로 동기화만 멈춘다.
                    self._snapshot = SessionSnapshot(
                        state=SessionState.OFFLINE, error=error
                    )
            return self._snapshot

        if session.account.user_id != account_id:
            with self._lock:
                if self._logout_generation != generation:
                    return self._snapshot
                self._store.delete_refresh_token(account_id)
                error = AuthError(
                    AuthErrorKind.SERVER_REJECTED,
                    "저장된 계정과 복구된 세션이 일치하지 않습니다.",
                    code="account_mismatch",
                )
                self._snapshot = SessionSnapshot(
                    state=SessionState.REAUTH_REQUIRED, error=error
                )
            return self._snapshot

        # Supabase는 refresh token을 회전하므로 같은 계정 키에 다시 저장한다.
        with self._lock:
            if self._logout_generation != generation:
                return self._snapshot
            self._store.save_refresh_token(account_id, session.tokens.refresh_token)
            self._snapshot = SessionSnapshot(
                state=SessionState.AUTHENTICATED, session=session
            )
        return self._snapshot

    def refresh_for_sync(self, account_id: str) -> AuthSession | None:
        """push 중 401을 받은 등록 계정 세션을 한 번 갱신한다."""
        try:
            snapshot = self.restore(account_id)
        except CredentialStoreError:
            return None
        return (
            snapshot.session if snapshot.state is SessionState.AUTHENTICATED else None
        )

    def sign_out(self, account_id: str) -> SessionSnapshot:
        """로그아웃. 서버 폐기 실패와 무관하게 로컬 refresh token은 제거한다."""
        with self._lock:
            session = self._snapshot.session
            if session is not None:
                try:
                    self._service.sign_out(session.tokens.access_token)
                except Exception:  # noqa: BLE001 - 어떤 원인이든 로컬 토큰 제거는 보장
                    # 오프라인 로그아웃도 허용한다. 서버 세션은 이후 만료된다.
                    pass
            self._store.delete_refresh_token(account_id)
            self._snapshot = SessionSnapshot(state=SessionState.SIGNED_OUT)
            self._logout_generation += 1
            return self._snapshot

    def export_account_data(self) -> AccountExportData:
        """본인 개인 데이터를 내려받는다. 인증된 세션이 필요하다."""
        session = self._require_session()
        return self._service.export_account_data(session.tokens.access_token)

    def list_devices(self) -> list[DeviceInfo]:
        """등록된 장치 목록을 조회한다."""
        session = self._require_session()
        return self._service.list_devices(session.tokens.access_token)

    def revoke_device(self, installation_id: str) -> None:
        """특정 장치를 해제한다."""
        session = self._require_session()
        self._service.revoke_device(session.tokens.access_token, installation_id)

    def sign_out_all_devices(self) -> int:
        """모든 장치에서 로그아웃하고 해제된 장치 수를 돌려준다.

        이 장치의 로컬 세션은 유지한다. 서버에서 다른 장치와 이 장치의
        refresh token이 폐기되므로 다음 시작 시 재로그인이 필요하다.
        """
        session = self._require_session()
        return self._service.sign_out_all_devices(session.tokens.access_token)

    def delete_account(self) -> AccountDeletionResult:
        """계정 삭제를 요청한다(클라이언트 secret 없이 서버에서 수행).

        성공하면 저장된 refresh token을 제거하고 세션을 종료한다.
        """
        session = self._require_session()
        result = self._service.delete_account(session.tokens.access_token)
        with self._lock:
            self._store.delete_refresh_token(session.account.user_id)
            self._snapshot = SessionSnapshot(state=SessionState.SIGNED_OUT)
            self._logout_generation += 1
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
            self._store.save_refresh_token(
                session.account.user_id, session.tokens.refresh_token
            )
            self._snapshot = SessionSnapshot(
                state=SessionState.AUTHENTICATED, session=session
            )
