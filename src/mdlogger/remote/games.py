"""등록 계정 private games PostgREST push adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .client import JsonHttpClient
from .config import RemoteConfig
from .errors import NetworkError, RemoteError, ResponseFormatError

_PRIVATE_GAME_FIELDS = (
    "played_at",
    "result",
    "turn_order",
    "my_deck",
    "opp_deck",
    "turns",
    "end_reason",
    "score_after",
    "note",
    "play_context_id",
    "standing_kind",
    "rank_tier_before",
    "rank_tier_after",
    "rank_division_before",
    "rank_division_after",
    "rating_before",
    "rating_after",
    "event_points_before",
    "event_points_after",
    "deleted_at",
    "timezone_offset_minutes",
)


class RegisteredGamesErrorKind(StrEnum):
    NETWORK = "network"
    AUTH_REQUIRED = "auth_required"
    REJECTED = "rejected"
    SERVER = "server"


class RegisteredGamesError(RemoteError):
    def __init__(
        self,
        kind: RegisteredGamesErrorKind,
        message: str,
        *,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code


@dataclass(frozen=True, slots=True)
class RegisteredPushResult:
    remote_versions: dict[str, int]


def build_registered_game(
    payload: Mapping[str, Any],
    *,
    sync_id: str,
    user_id: str,
    operation: str,
    payload_version: int,
) -> dict[str, Any]:
    """로컬 metadata를 제외하고 private games 계약만 구성한다."""
    row: dict[str, Any] = {
        "id": sync_id,
        "user_id": user_id,
        "payload_version": payload_version,
        "source_kind": "native",
    }
    for field_name in _PRIVATE_GAME_FIELDS:
        if field_name in payload:
            row[field_name] = payload[field_name]
    if operation == "delete" and not row.get("deleted_at"):
        raise ValueError("delete outbox payload에는 deleted_at이 필요합니다.")
    return row


class RegisteredGamesClient:
    """JWT+RLS로 등록 계정의 private games를 batch upsert한다."""

    def __init__(
        self, config: RemoteConfig, *, client: JsonHttpClient | None = None
    ) -> None:
        self._config = config
        self._client = client or JsonHttpClient()

    def upsert_batch(
        self,
        games: Iterable[Mapping[str, Any]],
        *,
        access_token: str,
    ) -> RegisteredPushResult:
        batch = [dict(game) for game in games]
        if not batch:
            raise ValueError("등록 games batch는 비어 있을 수 없습니다.")
        headers = {
            "apikey": self._config.anon_key,
            "Authorization": f"Bearer {access_token}",
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        try:
            response = self._client.post_json(
                f"{self._config.rest_url}/games?on_conflict=id", batch, headers
            )
        except NetworkError as error:
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.NETWORK,
                "네트워크 오류로 계정 기록을 업로드하지 못했습니다.",
            ) from error

        try:
            body = response.json()
        except ResponseFormatError:
            body = None
        if response.status in (200, 201):
            if not isinstance(body, list):
                raise RegisteredGamesError(
                    RegisteredGamesErrorKind.SERVER,
                    "등록 games 응답 형식이 올바르지 않습니다.",
                )
            try:
                versions = {
                    str(row["id"]): int(row["change_version"])
                    for row in body
                    if isinstance(row, dict)
                }
            except (KeyError, TypeError, ValueError) as error:
                raise RegisteredGamesError(
                    RegisteredGamesErrorKind.SERVER,
                    "등록 games 응답에 서버 버전이 없습니다.",
                ) from error
            if len(versions) != len(batch):
                raise RegisteredGamesError(
                    RegisteredGamesErrorKind.SERVER,
                    "등록 games 응답 수가 요청과 일치하지 않습니다.",
                )
            return RegisteredPushResult(remote_versions=versions)

        code = body.get("code") if isinstance(body, dict) else None
        if response.status in (401, 403):
            kind = (
                RegisteredGamesErrorKind.AUTH_REQUIRED
                if response.status == 401
                else RegisteredGamesErrorKind.REJECTED
            )
        elif 400 <= response.status < 500:
            kind = RegisteredGamesErrorKind.REJECTED
        else:
            kind = RegisteredGamesErrorKind.SERVER
        raise RegisteredGamesError(
            kind,
            f"등록 games 업로드가 거부되었습니다. (HTTP {response.status})",
            code=str(code) if code else None,
        )
