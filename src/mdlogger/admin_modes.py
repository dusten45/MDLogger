"""관리자용 서버 ``game_modes`` 기준정보 client.

일반 앱의 publishable key 경로와 분리해 service-role key를 환경 변수에서만 읽는다.
이 모듈은 관리자 실행 파일에서만 사용하며, 사용자 빌드 설정에 자격 증명을 포함하지 않는다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .game_sync.modes import GAME_MODES_FIELDS
from .remote.client import HttpResponse, JsonHttpClient
from .remote.errors import NetworkError, RemoteError, ResponseFormatError

_ADMIN_URL_ENV = "MDLOGGER_SUPABASE_URL"
_SERVICE_ROLE_KEY_ENV = "MDLOGGER_SERVICE_ROLE_KEY"


class AdminConfigurationError(ValueError):
    """관리자 앱 실행에 필요한 환경 변수가 없거나 올바르지 않다."""


class AdminModesError(RemoteError):
    """관리자 모드 기준정보 요청 실패."""


class AdminModesClient:
    """service-role key로 서버 ``game_modes`` 기준정보를 관리한다."""

    def __init__(
        self,
        base_url: str,
        service_role_key: str,
        *,
        client: JsonHttpClient | None = None,
    ) -> None:
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url.startswith(("https://", "http://")):
            raise AdminConfigurationError("Supabase URL은 http(s) URL이어야 합니다.")
        if not service_role_key.strip():
            raise AdminConfigurationError("service-role key가 비어 있습니다.")
        self._base_url = normalized_url
        self._service_role_key = service_role_key.strip()
        self._client = client or JsonHttpClient()

    @property
    def base_url(self) -> str:
        """연결 중인 Supabase 프로젝트 URL."""
        return self._base_url

    def fetch(self) -> list[dict[str, Any]]:
        """서버 기준정보를 정렬 순서대로 읽는다."""
        select = ",".join(GAME_MODES_FIELDS)
        response = self._request(
            "GET",
            f"{self._base_url}/rest/v1/game_modes?select={select}&order=sort_order.asc",
            None,
        )
        body = self._json(response)
        if not isinstance(body, list):
            raise AdminModesError("모드 목록 응답 형식이 올바르지 않습니다.")
        return [dict(row) for row in body if isinstance(row, Mapping)]

    def upsert(self, mode: Mapping[str, Any]) -> dict[str, Any]:
        """모드를 생성하거나 같은 id의 모드를 갱신한다."""
        payload = {
            "operation": "upsert",
            "mode_id": mode["id"],
            "standing_kind": mode["standing_kind"],
            "display_name": mode["display_name"],
            "play_context_id": mode["play_context_id"],
            "sort_order": mode["sort_order"],
            "is_active": mode["is_active"],
            "season_label": mode["season_label"],
        }
        response = self._request(
            "POST", f"{self._base_url}/rest/v1/rpc/manage_game_modes", payload
        )
        body = self._json(response)
        if not isinstance(body, dict):
            raise AdminModesError("모드 저장 응답 형식이 올바르지 않습니다.")
        return body

    def delete(self, mode_id: str) -> dict[str, Any]:
        """모드를 서버 기준정보에서 삭제한다."""
        response = self._request(
            "POST",
            f"{self._base_url}/rest/v1/rpc/manage_game_modes",
            {"operation": "delete", "mode_id": mode_id},
        )
        body = self._json(response)
        if not isinstance(body, dict):
            raise AdminModesError("모드 삭제 응답 형식이 올바르지 않습니다.")
        return body

    def _request(self, method: str, url: str, payload: object | None) -> HttpResponse:
        try:
            response = self._client.request_json(method, url, payload, self._headers())
        except NetworkError as error:
            raise AdminModesError(
                "서버에 연결할 수 없습니다. 연결 상태를 확인하고 다시 시도하세요."
            ) from error
        if response.status not in (200, 201, 204):
            raise AdminModesError(
                f"서버가 요청을 거부했습니다. (HTTP {response.status})"
            )
        return response

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._service_role_key,
            "Authorization": f"Bearer {self._service_role_key}",
        }

    @staticmethod
    def _json(response: HttpResponse) -> Any:
        try:
            return response.json()
        except ResponseFormatError as error:
            raise AdminModesError("서버 응답을 해석할 수 없습니다.") from error


def admin_client_from_environment(
    *, client: JsonHttpClient | None = None
) -> AdminModesClient:
    """관리자 전용 환경 변수에서 client를 생성한다."""
    base_url = os.environ.get(_ADMIN_URL_ENV, "").strip()
    service_role_key = os.environ.get(_SERVICE_ROLE_KEY_ENV, "").strip()
    missing = [
        name
        for name, value in (
            (_ADMIN_URL_ENV, base_url),
            (_SERVICE_ROLE_KEY_ENV, service_role_key),
        )
        if not value
    ]
    if missing:
        names = ", ".join(missing)
        raise AdminConfigurationError(
            f"관리자 앱에 필요한 환경 변수가 없습니다: {names}"
        )
    return AdminModesClient(base_url, service_role_key, client=client)
