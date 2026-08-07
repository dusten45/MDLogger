"""Supabase Auth(GoTrue) REST adapter.

publishable(anon) key만 사용하며 service-role key는 앱에 존재하지 않는다.
서버 오류는 ``error_code`` 기준으로 네트워크, 자격 증명, 이메일 미인증,
token 만료, 서버 거부로 분류한다(로드맵 단계 5).
"""

from __future__ import annotations

from typing import Any

from ..remote.client import HttpResponse, JsonHttpClient
from ..remote.config import RemoteConfig
from ..remote.errors import NetworkError, ResponseFormatError
from .models import (
    AccountInfo,
    AuthError,
    AuthErrorKind,
    AuthSession,
    AuthTokens,
    SignUpResult,
)
from .service import AccountService

# GoTrue error_code → 오류 분류.
_CREDENTIAL_CODES = frozenset(
    {
        "invalid_credentials",
        "user_not_found",
        "user_banned",
        "email_exists",
        "user_already_exists",
        "email_address_invalid",
        "email_address_not_authorized",
        "weak_password",
        "validation_failed",
        "signup_disabled",
    }
)
_EMAIL_UNVERIFIED_CODES = frozenset({"email_not_confirmed"})
_TOKEN_EXPIRED_CODES = frozenset(
    {
        "refresh_token_not_found",
        "refresh_token_already_used",
        "session_not_found",
        "session_expired",
        "bad_jwt",
    }
)


class SupabaseAccountService(AccountService):
    """Supabase Auth REST 엔드포인트 기반 :class:`AccountService` 구현."""

    def __init__(
        self, config: RemoteConfig, client: JsonHttpClient | None = None
    ) -> None:
        self._config = config
        self._client = client or JsonHttpClient()

    def sign_up(self, email: str, password: str) -> SignUpResult:
        body = self._post(
            f"{self._config.auth_url}/signup",
            {"email": email, "password": password},
        )
        # 이메일 인증이 꺼진 서버는 signup 응답에 바로 세션을 포함한다.
        if isinstance(body, dict) and "access_token" in body:
            session = self._session_from_body(body)
            return SignUpResult(account=session.account, session=session)
        account = self._account_from_user(body)
        return SignUpResult(account=account, session=None)

    def sign_in(self, email: str, password: str) -> AuthSession:
        body = self._post(
            f"{self._config.auth_url}/token?grant_type=password",
            {"email": email, "password": password},
        )
        return self._session_from_body(body)

    def refresh_session(self, refresh_token: str) -> AuthSession:
        body = self._post(
            f"{self._config.auth_url}/token?grant_type=refresh_token",
            {"refresh_token": refresh_token},
        )
        return self._session_from_body(body)

    def sign_out(self, access_token: str) -> None:
        self._post(
            f"{self._config.auth_url}/logout",
            None,
            extra_headers={"Authorization": f"Bearer {access_token}"},
        )

    def resend_verification_email(self, email: str) -> None:
        self._post(
            f"{self._config.auth_url}/resend",
            {"type": "signup", "email": email},
        )

    def request_password_reset(self, email: str) -> None:
        self._post(f"{self._config.auth_url}/recover", {"email": email})

    def _post(
        self,
        url: str,
        payload: dict[str, Any] | None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        headers = {"apikey": self._config.anon_key}
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = self._client.post_json(url, payload, headers)
        except NetworkError as error:
            raise AuthError(
                AuthErrorKind.NETWORK, "인증 서버에 연결할 수 없습니다."
            ) from error
        if response.status >= 400:
            raise self._classify_error(response)
        try:
            return response.json()
        except ResponseFormatError as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "인증 서버 응답을 해석할 수 없습니다.",
            ) from error

    @staticmethod
    def _classify_error(response: HttpResponse) -> AuthError:
        try:
            body = response.json()
        except ResponseFormatError:
            body = None
        body = body if isinstance(body, dict) else {}
        code = body.get("error_code") or body.get("code")
        code = str(code) if code is not None else None

        if code in _EMAIL_UNVERIFIED_CODES:
            return AuthError(
                AuthErrorKind.EMAIL_UNVERIFIED,
                "이메일 인증이 완료되지 않았습니다.",
                code=code,
            )
        if code in _TOKEN_EXPIRED_CODES:
            return AuthError(
                AuthErrorKind.TOKEN_EXPIRED,
                "세션이 만료되었거나 폐기되었습니다.",
                code=code,
            )
        if code in _CREDENTIAL_CODES or response.status in (400, 401, 422):
            return AuthError(
                AuthErrorKind.CREDENTIALS,
                "이메일 또는 비밀번호를 확인해 주세요.",
                code=code,
            )
        return AuthError(
            AuthErrorKind.SERVER_REJECTED,
            f"인증 서버가 요청을 거부했습니다. (HTTP {response.status})",
            code=code,
        )

    @classmethod
    def _session_from_body(cls, body: Any) -> AuthSession:
        if not isinstance(body, dict):
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED, "인증 응답 형식이 올바르지 않습니다."
            )
        try:
            tokens = AuthTokens(
                access_token=str(body["access_token"]),
                refresh_token=str(body["refresh_token"]),
                expires_in=int(body["expires_in"]),
            )
            account = cls._account_from_user(body["user"])
        except (KeyError, TypeError, ValueError) as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED, "인증 응답 형식이 올바르지 않습니다."
            ) from error
        return AuthSession(account=account, tokens=tokens)

    @staticmethod
    def _account_from_user(user: Any) -> AccountInfo:
        if not isinstance(user, dict):
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED, "사용자 응답 형식이 올바르지 않습니다."
            )
        try:
            return AccountInfo(
                user_id=str(user["id"]),
                email=str(user.get("email") or ""),
                email_verified=bool(user.get("email_confirmed_at")),
            )
        except KeyError as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED, "사용자 응답 형식이 올바르지 않습니다."
            ) from error
