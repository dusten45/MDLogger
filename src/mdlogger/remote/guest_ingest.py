"""게스트용 제한된 Guest Ingest 요청 흐름(로드맵 8.3, 단계 5).

- 게스트는 auth 사용자 없이 installation pseudonym과 publishable key만으로
  분석 허용 필드를 batch 업로드한다.
- payload는 명시적 allowlist로만 구성한다. ``note``, 이메일, 표시 이름,
  파일 경로 등은 필드 자체가 존재하지 않는다.
- batch ID와 game ``sync_id``로 idempotency를 보장하므로 응답 유실 후
  같은 batch를 재전송해도 중복이 생기지 않는다.
- rate limit·Turnstile 확장 경계: 서버가 429/428을 돌려주면 전용 오류로
  분류하고, 이후 도입될 일회성 challenge token을 전달할 수 있다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .. import __version__
from .client import HttpResponse, JsonHttpClient
from .config import RemoteConfig
from .errors import NetworkError, RemoteError, ResponseFormatError

GUEST_INGEST_PAYLOAD_VERSION = 1
MAX_BATCH_SIZE = 200

# 로컬 games 행에서 그대로 옮기는 분석 허용 필드(로드맵 7.4).
# note, id, score_after(레거시 개인 점수)는 의도적으로 제외한다.
_DIRECT_FIELDS = (
    "result",
    "turn_order",
    "my_deck",
    "opp_deck",
    "turns",
    "end_reason",
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
    "environment_version_id",
)


class GuestIngestErrorKind(StrEnum):
    """게스트 ingest 실패 분류."""

    NETWORK = "network"
    REJECTED = "rejected"
    RATE_LIMITED = "rate_limited"
    CHALLENGE_REQUIRED = "challenge_required"
    SERVER = "server"


class GuestIngestError(RemoteError):
    """게스트 ingest 요청 실패."""

    def __init__(
        self,
        kind: GuestIngestErrorKind,
        message: str,
        *,
        code: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class GuestIngestResult:
    """서버가 반영한 batch 처리 요약."""

    batch_id: str
    accepted: int
    skipped: int
    rejected: int
    replayed: bool


def current_timezone_offset_minutes() -> int:
    """기록 시점 장치의 UTC offset(분). 신규 기록의 자동 수집용."""
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds() // 60)


def build_observation(
    game: Mapping[str, Any],
    *,
    timezone_offset_minutes: int | None = None,
) -> dict[str, Any]:
    """로컬 games 행에서 분석 허용 필드만 골라 observation payload를 만든다.

    ``sync_id``와 ``played_at``은 필수이며, 알 수 없는 값은 추측하지 않고
    필드를 생략한다(로드맵 7.6).
    """
    data = dict(game)
    sync_id = data.get("sync_id")
    played_at = data.get("played_at")
    if not sync_id or not played_at:
        raise ValueError("observation에는 sync_id와 played_at이 필요합니다.")

    observation: dict[str, Any] = {
        "sync_id": str(uuid.UUID(str(sync_id))),
        "played_at_local": str(played_at),
    }
    if timezone_offset_minutes is not None:
        observation["timezone_offset_minutes"] = int(timezone_offset_minutes)
    for field_name in _DIRECT_FIELDS:
        value = data.get(field_name)
        if value is None or value == "":
            continue
        observation[field_name] = value
    return observation


def build_withdrawal(sync_id: str) -> dict[str, Any]:
    """이미 업로드된 게스트 기록 한 건의 철회 observation(로드맵 9.3)."""
    return {"op": "withdraw", "sync_id": str(uuid.UUID(str(sync_id)))}


class GuestIngestClient:
    """Guest Ingest Edge Function으로 observation batch를 업로드한다."""

    def __init__(
        self,
        config: RemoteConfig,
        installation_id: str,
        *,
        client: JsonHttpClient | None = None,
        client_version: str = __version__,
    ) -> None:
        self._config = config
        self._installation_id = str(uuid.UUID(installation_id))
        self._client = client or JsonHttpClient()
        self._client_version = client_version

    def upload_batch(
        self,
        observations: Iterable[Mapping[str, Any]],
        *,
        batch_id: str | None = None,
        challenge_token: str | None = None,
    ) -> GuestIngestResult:
        """observation batch를 업로드하고 서버 처리 요약을 돌려준다.

        ``batch_id``를 유지한 재호출은 서버에서 idempotent하게 처리되므로
        응답을 받지 못한 batch는 같은 ID로 재전송해야 한다.
        """
        batch = [dict(observation) for observation in observations]
        if not 1 <= len(batch) <= MAX_BATCH_SIZE:
            raise ValueError(f"batch 크기는 1~{MAX_BATCH_SIZE}이어야 합니다.")

        payload: dict[str, Any] = {
            "batch_id": batch_id or str(uuid.uuid4()),
            "installation_id": self._installation_id,
            "client_version": self._client_version,
            "payload_version": GUEST_INGEST_PAYLOAD_VERSION,
            "observations": batch,
        }
        if challenge_token is not None:
            payload["challenge_token"] = challenge_token

        headers = {
            "apikey": self._config.anon_key,
            "Authorization": f"Bearer {self._config.anon_key}",
        }
        try:
            response = self._client.post_json(
                f"{self._config.functions_url}/guest-ingest", payload, headers
            )
        except NetworkError as error:
            raise GuestIngestError(
                GuestIngestErrorKind.NETWORK,
                "네트워크 오류로 게스트 기록을 업로드하지 못했습니다.",
            ) from error

        return self._interpret(response)

    @staticmethod
    def _interpret(response: HttpResponse) -> GuestIngestResult:
        try:
            body = response.json()
        except ResponseFormatError:
            body = None
        body = body if isinstance(body, dict) else {}
        code = body.get("code")

        if response.status == 200:
            try:
                return GuestIngestResult(
                    batch_id=str(body["batch_id"]),
                    accepted=int(body["accepted"]),
                    skipped=int(body["skipped"]),
                    rejected=int(body["rejected"]),
                    replayed=bool(body.get("replayed", False)),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise GuestIngestError(
                    GuestIngestErrorKind.SERVER,
                    "게스트 ingest 응답 형식이 올바르지 않습니다.",
                ) from error
        if response.status == 428:
            raise GuestIngestError(
                GuestIngestErrorKind.CHALLENGE_REQUIRED,
                "서버가 일회성 확인(challenge)을 요구했습니다.",
                code=code,
            )
        if response.status == 429:
            retry_after = body.get("retry_after_seconds")
            raise GuestIngestError(
                GuestIngestErrorKind.RATE_LIMITED,
                "요청이 많아 게스트 업로드가 잠시 제한됐습니다.",
                code=code,
                retry_after_seconds=int(retry_after)
                if isinstance(retry_after, int)
                else None,
            )
        if 400 <= response.status < 500:
            raise GuestIngestError(
                GuestIngestErrorKind.REJECTED,
                "서버가 게스트 업로드 요청을 거부했습니다.",
                code=code,
            )
        raise GuestIngestError(
            GuestIngestErrorKind.SERVER,
            f"게스트 ingest 서버 오류입니다. (HTTP {response.status})",
            code=code,
        )
