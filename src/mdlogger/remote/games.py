"""등록 계정 private games의 versioned push/pull adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .. import __version__
from .client import HttpResponse, JsonHttpClient
from .config import RemoteConfig
from .errors import NetworkError, RemoteError, ResponseFormatError

SYNC_SCHEMA_VERSION = 1
PAYLOAD_VERSION = 1

PRIVATE_GAME_FIELDS = (
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
    "timezone_offset_minutes",
    "environment_version_id",
)
REMOTE_GAME_FIELDS = (
    "id",
    *PRIVATE_GAME_FIELDS,
    "created_at",
    "updated_at",
    "deleted_at",
    "change_version",
    "payload_version",
    "source_kind",
    "client_version",
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
class MutationResult:
    game_id: str
    status: str
    change_version: int | None
    remote: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RegisteredPushResult:
    results: tuple[MutationResult, ...]

    @property
    def remote_versions(self) -> dict[str, int]:
        return {
            result.game_id: result.change_version
            for result in self.results
            if result.status == "applied" and result.change_version is not None
        }


@dataclass(frozen=True, slots=True)
class RegisteredPullResult:
    games: tuple[dict[str, Any], ...]


def private_game_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """로컬 metadata를 제외한 private games payload를 만든다."""
    return {
        field_name: payload[field_name]
        for field_name in PRIVATE_GAME_FIELDS
        if field_name in payload
    }


def build_game_change(
    payload: Mapping[str, Any],
    *,
    sync_id: str,
    operation: str,
    remote_version: int | None,
) -> dict[str, Any]:
    """로컬 outbox를 서버 CAS mutation envelope로 변환한다."""
    if remote_version is None:
        remote_operation = "create"
    elif operation == "delete":
        remote_operation = "delete"
    elif operation == "restore":
        remote_operation = "restore"
    else:
        remote_operation = "update"

    change: dict[str, Any] = {"op": remote_operation, "id": sync_id}
    if remote_operation != "create":
        change["expected_change_version"] = remote_version
    # 게스트를 포함한 단일 출처 버전을 등록 게임에도 기록한다(하드닝 H4/N-1).
    change["client_version"] = __version__
    change["payload"] = (
        {} if remote_operation == "delete" else private_game_payload(payload)
    )
    return change


def build_registered_game(
    payload: Mapping[str, Any],
    *,
    sync_id: str,
    user_id: str,
    operation: str,
    payload_version: int,
) -> dict[str, Any]:
    """단계 7 호출자 호환용 private game 표현을 구성한다."""
    row = {
        "id": sync_id,
        "user_id": user_id,
        "payload_version": payload_version,
        "source_kind": "native",
        **private_game_payload(payload),
    }
    if operation == "delete":
        row["deleted_at"] = payload.get("deleted_at")
        if not row["deleted_at"]:
            raise ValueError("delete outbox payload에는 deleted_at이 필요합니다.")
    return row


class RegisteredGamesClient:
    """JWT+RLS/RPC로 등록 계정의 게임과 장치 cursor를 동기화한다."""

    def __init__(
        self, config: RemoteConfig, *, client: JsonHttpClient | None = None
    ) -> None:
        self._config = config
        self._client = client or JsonHttpClient()

    def apply_changes(
        self,
        changes: Iterable[Mapping[str, Any]],
        *,
        access_token: str,
    ) -> RegisteredPushResult:
        batch = [dict(change) for change in changes]
        if not batch:
            raise ValueError("등록 games batch는 비어 있을 수 없습니다.")
        response = self._request(
            "POST",
            f"{self._config.rest_url}/rpc/apply_game_changes",
            {
                "sync_schema_version": SYNC_SCHEMA_VERSION,
                "payload_version": PAYLOAD_VERSION,
                "changes": batch,
            },
            access_token,
            action="업로드",
        )
        body = self._json(response)
        rows = body.get("results") if isinstance(body, dict) else None
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.SERVER,
                "등록 games mutation 응답 형식이 올바르지 않습니다.",
            )
        results: list[MutationResult] = []
        try:
            for row in rows:
                if not isinstance(row, dict):
                    raise TypeError
                status = str(row["status"])
                if status not in ("applied", "conflict"):
                    raise ValueError
                version_value = (
                    row.get("change_version")
                    if status == "applied"
                    else row.get("current_change_version")
                )
                version = int(version_value) if version_value is not None else None
                if status == "applied" and (version is None or version < 1):
                    raise ValueError
                remote = row.get("remote")
                results.append(
                    MutationResult(
                        game_id=str(row["id"]),
                        status=status,
                        change_version=version,
                        remote=dict(remote) if isinstance(remote, dict) else None,
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.SERVER,
                "등록 games mutation 응답 값이 올바르지 않습니다.",
            ) from error
        return RegisteredPushResult(tuple(results))

    def upsert_batch(
        self,
        games: Iterable[Mapping[str, Any]],
        *,
        access_token: str,
    ) -> RegisteredPushResult:
        """기존 테스트/호출자용으로 신규 create batch를 RPC에 위임한다."""
        changes = [
            build_game_change(
                game,
                sync_id=str(game["id"]),
                operation="upsert",
                remote_version=None,
            )
            for game in games
        ]
        return self.apply_changes(changes, access_token=access_token)

    def pull_changes(
        self,
        *,
        after_version: int,
        limit: int,
        access_token: str,
    ) -> RegisteredPullResult:
        select = ",".join(REMOTE_GAME_FIELDS)
        url = (
            f"{self._config.rest_url}/games?select={select}"
            f"&change_version=gt.{after_version}"
            "&order=change_version.asc"
            f"&limit={limit}"
        )
        response = self._request("GET", url, None, access_token, action="다운로드")
        body = self._json(response)
        if not isinstance(body, list):
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.SERVER,
                "등록 games pull 응답 형식이 올바르지 않습니다.",
            )
        games: list[dict[str, Any]] = []
        try:
            for row in body:
                if not isinstance(row, dict):
                    raise TypeError
                int(row["change_version"])
                games.append(dict(row))
        except (KeyError, TypeError, ValueError) as error:
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.SERVER,
                "등록 games pull 응답에 서버 버전이 없습니다.",
            ) from error
        return RegisteredPullResult(tuple(games))

    def register_device(
        self,
        *,
        installation_id: str,
        display_name: str,
        client_version: str,
        access_token: str,
    ) -> None:
        self._request(
            "POST",
            f"{self._config.rest_url}/rpc/register_or_touch_device",
            {
                "sync_schema_version": SYNC_SCHEMA_VERSION,
                "payload_version": PAYLOAD_VERSION,
                "installation_id": installation_id,
                "display_name": display_name,
                "client_version": client_version,
            },
            access_token,
            action="장치 등록",
        )

    def acknowledge_device_version(
        self,
        *,
        installation_id: str,
        acknowledged_version: int,
        access_token: str,
    ) -> None:
        self._request(
            "POST",
            f"{self._config.rest_url}/rpc/acknowledge_device_version",
            {
                "sync_schema_version": SYNC_SCHEMA_VERSION,
                "payload_version": PAYLOAD_VERSION,
                "installation_id": installation_id,
                "acknowledged_version": acknowledged_version,
            },
            access_token,
            action="장치 cursor 확인",
        )

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
            response = self._client.request_json(method, url, payload, headers)
        except NetworkError as error:
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.NETWORK,
                f"네트워크 오류로 계정 기록 {action}을 완료하지 못했습니다.",
            ) from error
        if response.status in (200, 201, 204):
            return response
        body = self._json(response, required=False)
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
            f"등록 games {action}이 거부되었습니다. (HTTP {response.status})",
            code=str(code) if code else None,
        )

    @staticmethod
    def _json(response: HttpResponse, *, required: bool = True) -> Any:
        try:
            body = response.json()
        except ResponseFormatError as error:
            if not required:
                return None
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.SERVER,
                "등록 games 서버 응답을 해석할 수 없습니다.",
            ) from error
        if required and body is None:
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.SERVER,
                "등록 games 서버 응답이 비어 있습니다.",
            )
        return body
