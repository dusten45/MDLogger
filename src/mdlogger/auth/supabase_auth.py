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
        # GoTrue 공식 error code 레지스트리는 위 코드를 쓰며 invalid_grant를
        # 만들지 않는다. 다만 OAuth 스타일 프록시/게이트웨이가 만료·폐기된
        # refresh token에 invalid_grant를 돌려줄 수 있어 방어적으로 TOKEN_EXPIRED로
        # 분류한다(B-5-2).
        "invalid_grant",
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

    def export_account_data(self, access_token: str) -> AccountExportData:
        body = self._rpc("export_account_data", None, access_token)
        return self._export_from_body(body)

    def list_devices(self, access_token: str) -> list[DeviceInfo]:
        body = self._rpc("list_user_devices", None, access_token)
        if not isinstance(body, list):
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "장치 목록 응답 형식이 올바르지 않습니다.",
            )
        try:
            return [self._device_from_row(row) for row in body]
        except (KeyError, TypeError, ValueError) as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "장치 목록 응답 형식이 올바르지 않습니다.",
            ) from error

    def revoke_device(self, access_token: str, installation_id: str) -> None:
        self._rpc("revoke_device", {"installation_id": installation_id}, access_token)

    def sign_out_all_devices(self, access_token: str) -> int:
        body = self._rpc("revoke_all_devices", None, access_token)
        if not isinstance(body, dict):
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "장치 해제 응답 형식이 올바르지 않습니다.",
            )
        try:
            return int(body.get("revoked_devices", 0))
        except (TypeError, ValueError) as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "장치 해제 응답 형식이 올바르지 않습니다.",
            ) from error

    def delete_account(
        self, access_token: str, user_id: str | None = None
    ) -> AccountDeletionResult:
        payload = {"user_id": user_id} if user_id is not None else None
        response = self._client.post_json(
            f"{self._config.functions_url}/account-delete",
            payload,
            {
                "apikey": self._config.anon_key,
                "Authorization": f"Bearer {access_token}",
            },
        )
        if response.status == 401:
            raise AuthError(
                AuthErrorKind.TOKEN_EXPIRED,
                "세션이 만료되었습니다. 다시 로그인해 주세요.",
            )
        if response.status == 403:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "이 계정은 이 장치에서 삭제할 수 없습니다.",
                code="target_mismatch",
            )
        if response.status >= 400:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                f"계정 삭제 요청이 거부되었습니다. (HTTP {response.status})",
            )
        try:
            body = response.json()
        except ResponseFormatError as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED, "계정 삭제 응답을 해석할 수 없습니다."
            ) from error
        if not isinstance(body, dict) or body.get("code") != "account_deleted":
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "계정 삭제 응답 형식이 올바르지 않습니다.",
            )
        try:
            return AccountDeletionResult(
                deleted_games=int(body.get("deleted_games", 0)),
                deleted_devices=int(body.get("deleted_devices", 0)),
                deleted_profiles=int(body.get("deleted_profiles", 0)),
                deleted_auth_user=bool(body.get("deleted_auth_user")),
            )
        except (TypeError, ValueError) as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "계정 삭제 응답 형식이 올바르지 않습니다.",
            ) from error

    def _rpc(
        self,
        function_name: str,
        payload: dict[str, Any] | None,
        access_token: str,
    ) -> Any:
        headers = {
            "apikey": self._config.anon_key,
            "Authorization": f"Bearer {access_token}",
        }
        try:
            response = self._client.post_json(
                f"{self._config.rest_url}/rpc/{function_name}", payload, headers
            )
        except NetworkError as error:
            raise AuthError(
                AuthErrorKind.NETWORK, "서버에 연결할 수 없습니다."
            ) from error
        if response.status == 401:
            raise AuthError(
                AuthErrorKind.TOKEN_EXPIRED,
                "세션이 만료되었습니다. 다시 로그인해 주세요.",
            )
        if response.status >= 400:
            raise self._classify_error(response)
        try:
            return response.json()
        except ResponseFormatError as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED, "서버 응답을 해석할 수 없습니다."
            ) from error

    @staticmethod
    def _device_from_row(row: Any) -> DeviceInfo:
        if not isinstance(row, dict):
            raise TypeError
        acknowledged = row.get("last_acknowledged_version")
        return DeviceInfo(
            id=str(row["id"]),
            installation_id=str(row["installation_id"]),
            display_name=row.get("display_name"),
            client_version=row.get("client_version"),
            created_at=row.get("created_at"),
            last_seen_at=row.get("last_seen_at"),
            last_acknowledged_version=int(acknowledged)
            if acknowledged is not None
            else None,
        )

    @staticmethod
    def _export_from_body(body: Any) -> AccountExportData:
        if not isinstance(body, dict):
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "데이터 내보내기 응답 형식이 올바르지 않습니다.",
            )
        try:
            games = body.get("games")
            devices = body.get("devices")
            games = tuple(games) if isinstance(games, list) else ()
            device_rows = devices if isinstance(devices, list) else []
        except TypeError as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "데이터 내보내기 응답 형식이 올바르지 않습니다.",
            ) from error
        try:
            device_infos = tuple(
                SupabaseAccountService._device_from_row(row) for row in device_rows
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AuthError(
                AuthErrorKind.SERVER_REJECTED,
                "데이터 내보내기 응답 형식이 올바르지 않습니다.",
            ) from error
        profile = body.get("profile")
        return AccountExportData(
            games=games,
            devices=device_infos,
            profile=profile if isinstance(profile, dict) else None,
        )

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
        # GoTrue는 항상 ``error_code`` 문자열을 포함한다(공식 문서 확인, B-5-2).
        # ``code``는 HTTP 상태 코드(정수)라 문자열 set 비교에 쓰면 안 되므로
        # error_code만 읽는다. OAuth 스타일 응답도 ``error`` 필드 대신 여기서
        # 다룬다.
        code = body.get("error_code")
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
        # 자격 증명 오류는 error_code로만 판단한다. 인식되지 않는 400/401/422를
        # 전부 "이메일 또는 비밀번호 오류"로 오분류하지 않도록 상태 코드 폴백은
        # 제거한다. (GoTrue는 로그인 실패를 invalid_credentials 등 code로 반환)
        if code in _CREDENTIAL_CODES:
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
