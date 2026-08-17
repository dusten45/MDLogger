"""취향 설정 동기화 클라이언트 (계획 2, spec §4.3).

설정 동기화는 수동 업로드/다운로드다(게임 동기화처럼 자동 push/pull이 아니다).
``PREFERENCE_KEYS``(취향 설정)만 직렬화·전송하고, ``DEVICE_KEYS``(기기 특성)는
어떤 경로로도 전송하지 않는다(클라이언트 하드 차단). 서버도 동일 allowlist를
검증한다(spec §4.2).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..app_settings import PREFERENCE_KEYS
from .client import HttpResponse, JsonHttpClient
from .config import RemoteConfig
from .errors import NetworkError, RemoteError, ResponseFormatError


class SettingsSyncError(RemoteError):
    """설정 동기화 실패."""


class SettingsSyncClient:
    """취향 설정의 업로드/다운로드 (등록 프로필 전용, access token 필요)."""

    def __init__(
        self, config: RemoteConfig, *, client: JsonHttpClient | None = None
    ) -> None:
        self._config = config
        self._client = client or JsonHttpClient()

    def upload(self, preferences: Mapping[str, Any], access_token: str) -> None:
        """``PREFERENCE_KEYS``만 추출해 업로드한다. ``DEVICE_KEYS``는 무조건 제거."""
        filtered = {
            key: preferences[key] for key in PREFERENCE_KEYS if key in preferences
        }
        response = self._request(
            "POST",
            f"{self._config.rest_url}/rpc/upsert_user_settings",
            {"preferences": filtered},
            access_token,
            action="업로드",
        )
        if response.status not in (200, 201, 204):
            raise SettingsSyncError(
                f"설정 업로드가 거부되었습니다. (HTTP {response.status})"
            )

    def download(self, access_token: str) -> dict[str, Any] | None:
        """서버 설정에서 ``PREFERENCE_KEYS``만 취한다. 행이 없으면 ``None``."""
        response = self._request(
            "GET",
            f"{self._config.rest_url}/user_settings?select=preferences",
            None,
            access_token,
            action="다운로드",
        )
        if response.status not in (200, 201, 204):
            raise SettingsSyncError(
                f"설정 다운로드가 거부되었습니다. (HTTP {response.status})"
            )
        body = self._json(response)
        if not isinstance(body, list) or not body:
            return None
        first = body[0]
        preferences = first.get("preferences") if isinstance(first, dict) else None
        if not isinstance(preferences, dict):
            return None
        return {
            key: value for key, value in preferences.items() if key in PREFERENCE_KEYS
        }

    def _request(
        self,
        method: str,
        url: str,
        payload: Any,
        access_token: str,
        *,
        action: str,
    ) -> HttpResponse:
        headers = {
            "apikey": self._config.anon_key,
            "Authorization": f"Bearer {access_token}",
        }
        try:
            return self._client.request_json(method, url, payload, headers)
        except NetworkError as error:
            raise SettingsSyncError(
                f"네트워크 오류로 설정 {action}을 완료하지 못했습니다."
            ) from error

    @staticmethod
    def _json(response: HttpResponse) -> Any:
        try:
            return response.json()
        except ResponseFormatError as error:
            raise SettingsSyncError("설정 서버 응답을 해석할 수 없습니다.") from error
