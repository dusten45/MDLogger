"""서버 `game_modes` 기준정보 fetch + 로컬 `play_modes` 캐시 동기화 (spec §4.8).

모드의 원본은 서버 `game_modes`(B2)이며, 로컬 `play_modes`는 그 클라이언트
캐시다. 앱 시작 시 + 동기화 시 이 목록을 받아 로컬 캐시를 맞춘다. 실패(오프라인)면
기존 캐시로 동작한다(비차단 폴백, §10-2).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ..remote.client import JsonHttpClient
from ..remote.config import RemoteConfig
from ..remote.errors import NetworkError, RemoteError, ResponseFormatError

GAME_MODES_FIELDS = (
    "id",
    "standing_kind",
    "display_name",
    "play_context_id",
    "sort_order",
    "is_active",
    "season_label",
)


class GameModesError(RemoteError):
    """서버 game_modes 조회 실패."""


class GameModesClient:
    """공개 기준정보인 서버 game_modes를 조회한다 (anon key만 필요)."""

    def __init__(
        self, config: RemoteConfig, *, client: JsonHttpClient | None = None
    ) -> None:
        self._config = config
        self._client = client or JsonHttpClient()

    def fetch(self) -> list[dict[str, Any]]:
        select = ",".join(GAME_MODES_FIELDS)
        url = f"{self._config.rest_url}/game_modes?select={select}&order=sort_order.asc"
        headers = {"apikey": self._config.anon_key}
        try:
            response = self._client.request_json("GET", url, None, headers)
        except NetworkError as error:
            raise GameModesError(
                "네트워크 오류로 모드 기준정보를 가져오지 못했습니다."
            ) from error
        if response.status not in (200, 201, 204):
            raise GameModesError(
                f"모드 기준정보 조회가 거부되었습니다. (HTTP {response.status})"
            )
        try:
            body = response.json()
        except ResponseFormatError as error:
            raise GameModesError("모드 기준정보 응답을 해석할 수 없습니다.") from error
        if not isinstance(body, list):
            raise GameModesError("모드 기준정보 응답 형식이 올바르지 않습니다.")
        return [dict(row) for row in body]


def sync_play_modes(
    conn: sqlite3.Connection, remote_modes: Sequence[Mapping[str, Any]]
) -> int:
    """서버 game_modes 목록으로 로컬 play_modes 캐시를 맞춘다.

    서버가 원본이므로 로컬 캐시를 서버 목록과 동일하게 재구성한다. 반환값은
    갱신된 행 수다. ``created_at``은 로컬 시각으로 유지한다.
    ``created_at``은 로컬 시각으로 유지한다.
    """
    now = datetime.now().isoformat(timespec="seconds")
    count = 0
    with conn:
        conn.execute("DELETE FROM play_modes")
        for mode in remote_modes:
            conn.execute(
                """
                INSERT INTO play_modes
                    (id, standing_kind, display_name, play_context_id, sort_order,
                     is_active, season_label, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(mode["id"]),
                    str(mode["standing_kind"]),
                    str(mode["display_name"]),
                    mode.get("play_context_id"),
                    int(mode.get("sort_order") or 0),
                    1 if mode.get("is_active", True) else 0,
                    mode.get("season_label"),
                    now,
                ),
            )
            count += 1
    return count
