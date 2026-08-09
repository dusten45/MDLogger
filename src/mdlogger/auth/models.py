"""인증 도메인 모델과 오류 분류.

토큰 값은 어떤 경우에도 repr/str/로그에 노출하지 않는다(로드맵 12.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AuthErrorKind(StrEnum):
    """인증 오류 분류(로드맵 단계 5).

    네트워크 실패와 만료·폐기된 token, 자격 증명 오류를 구분해야
    오프라인과 재로그인 필요 상태를 나눌 수 있다.
    """

    NETWORK = "network"
    CREDENTIALS = "credentials"
    EMAIL_UNVERIFIED = "email_unverified"
    TOKEN_EXPIRED = "token_expired"
    SERVER_REJECTED = "server_rejected"


class AuthError(Exception):
    """분류된 인증 실패. 메시지에 토큰·비밀번호를 포함하지 않는다."""

    def __init__(
        self, kind: AuthErrorKind, message: str, *, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code


@dataclass(frozen=True, slots=True)
class AuthTokens:
    """세션 토큰 쌍. access token은 메모리에만 존재한다(로드맵 5.3)."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """서버가 확인해 준 계정의 비민감 정보."""

    user_id: str
    email: str
    email_verified: bool


@dataclass(frozen=True, slots=True)
class AuthSession:
    """로그인 또는 refresh로 얻은 유효한 세션."""

    account: AccountInfo
    tokens: AuthTokens


@dataclass(frozen=True, slots=True)
class SignUpResult:
    """회원가입 결과.

    이메일 인증이 필요한 서버 설정에서는 세션 없이 인증 대기 상태가 된다.
    """

    account: AccountInfo
    session: AuthSession | None

    @property
    def needs_email_verification(self) -> bool:
        return self.session is None and not self.account.email_verified


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """등록된 장치 한 대의 비민감 표시 정보(로드맵 단계 11)."""

    id: str
    installation_id: str
    display_name: str | None
    client_version: str | None
    created_at: str | None
    last_seen_at: str | None
    last_acknowledged_version: int | None


@dataclass(frozen=True, slots=True)
class AccountExportData:
    """사용자가 내보낼 수 있는 개인 데이터(로드맵 12.4).

    분석용 비식별 데이터(duel_observations)는 포함하지 않는다.
    사용자 ID를 제외한 서버가 반환한 개인 데이터를 담는다.
    """

    games: tuple[dict, ...]
    devices: tuple[DeviceInfo, ...]
    profile: dict | None


@dataclass(frozen=True, slots=True)
class AccountDeletionResult:
    """계정 삭제 서버 처리 요약(로드맵 단계 11)."""

    deleted_games: int
    deleted_devices: int
    deleted_profiles: int
    deleted_auth_user: bool
