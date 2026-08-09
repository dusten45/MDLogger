"""릴리스 정책 해석·조회·로컬 캐시(하드닝 H3).

서버의 ``public.release_policies``는 읽기 전용으로 anon/authenticated가
조회할 수 있다. 클라이언트는 온라인 시작 시 정책을 조회해 마지막으로 받은
정책을 로컬에 캐시하고, 오프라인에서는 캐시를 사용한다.

판정(로드맵 17.3.J, 2.7):
- 최소 지원 미만 → 온라인 로그인·업로드·pull 차단, 로컬 기록·내보내기는 허용.
- 최소 지원 이상, 최신 미만 → 공지만, 동작은 계속.
- 최신 이상 → 그대로 동작.
정책 조회 실패는 앱 시작을 막지 않는다(마지막 캐시 또는 '알 수 없음').
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import __version__
from .remote.client import JsonHttpClient
from .remote.config import RemoteConfig
from .remote.errors import NetworkError, ResponseFormatError

DEFAULT_PLATFORM = "windows"
POLICY_TIMEOUT_SECONDS = 3.0
_CACHE_SUFFIX = ".tmp"


class PolicyStatus(StrEnum):
    """클라이언트 버전 대비 정책 판정."""

    CURRENT = "current"
    UPDATE_AVAILABLE = "update_available"
    BELOW_MINIMUM = "below_minimum"


def _leading_digits(segment: str) -> str:
    """구간 선두의 숫자를 이어 붙인다. 첫 비숫자부터 suffix로 친다."""
    out: list[str] = []
    for ch in segment:
        if ch.isdigit():
            out.append(ch)
        else:
            break
    return "".join(out)


def parse_version(text: str) -> tuple[int, int, int]:
    """``major.minor.patch`` 버전 문자열을 정렬 가능한 튜플로 변환한다.

    선행 ``v``는 무시하고, 각 구간은 선두 숫자만 취해 suffix(예: ``-rc1``)의
    숫자를 버린다. 구간 누락은 0으로 취급한다. 해석 불가 문자열은
    ``(0, 0, 0)``이다.
    """
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for segment in cleaned.split(".")[:3]:
        digits = _leading_digits(segment)
        parts.append(int(digits) if digits else 0)
    parts += [0] * (3 - len(parts))
    return parts[0], parts[1], parts[2]


def version_less(left: str, right: str) -> bool:
    """``left`` 버전이 ``right``보다 낮은지(배포 의미상) 판정."""
    return parse_version(left) < parse_version(right)


def evaluate_policy(current_version: str, policy: ReleasePolicy | None) -> PolicyStatus:
    if policy is None:
        return PolicyStatus.CURRENT
    if version_less(current_version, policy.minimum_supported_version):
        return PolicyStatus.BELOW_MINIMUM
    if version_less(current_version, policy.latest_version):
        return PolicyStatus.UPDATE_AVAILABLE
    return PolicyStatus.CURRENT


def online_access_allowed(status: PolicyStatus) -> bool:
    """정책이 온라인 동작(로그인·업로드·pull)을 허용하는지."""
    return status is not PolicyStatus.BELOW_MINIMUM


@dataclass(frozen=True, slots=True)
class ReleasePolicy:
    """서버 ``release_policies`` 행의 클라이언트 해석본."""

    platform: str
    latest_version: str
    minimum_supported_version: str
    notice: str | None
    update_url: str
    effective_at: str | None
    payload_version_min: int
    payload_version_max: int
    sync_schema_version_min: int
    sync_schema_version_max: int
    block_online: bool
    block_local_writes: bool
    allow_export: bool

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> ReleasePolicy:
        base = dict(row)
        return cls(
            platform=str(base.get("platform") or DEFAULT_PLATFORM),
            latest_version=str(base.get("latest_version") or ""),
            minimum_supported_version=str(base.get("minimum_supported_version") or ""),
            notice=base.get("notice") if isinstance(base.get("notice"), str) else None,
            update_url=str(base.get("update_url") or ""),
            effective_at=base.get("effective_at")
            if isinstance(base.get("effective_at"), str)
            else None,
            payload_version_min=int(base.get("payload_version_min") or 1),
            payload_version_max=int(base.get("payload_version_max") or 1),
            sync_schema_version_min=int(base.get("sync_schema_version_min") or 1),
            sync_schema_version_max=int(base.get("sync_schema_version_max") or 1),
            block_online=bool(base.get("block_online", True)),
            block_local_writes=bool(base.get("block_local_writes", False)),
            allow_export=bool(base.get("allow_export", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "latest_version": self.latest_version,
            "minimum_supported_version": self.minimum_supported_version,
            "notice": self.notice,
            "update_url": self.update_url,
            "effective_at": self.effective_at,
            "payload_version_min": self.payload_version_min,
            "payload_version_max": self.payload_version_max,
            "sync_schema_version_min": self.sync_schema_version_min,
            "sync_schema_version_max": self.sync_schema_version_max,
            "block_online": self.block_online,
            "block_local_writes": self.block_local_writes,
            "allow_export": self.allow_export,
        }


@dataclass(frozen=True, slots=True)
class PolicyEval:
    """현재 버전에 대한 정책 판정 결과."""

    status: PolicyStatus
    policy: ReleasePolicy | None
    notice: str | None


def evaluate_current(
    policy: ReleasePolicy | None, current_version: str = __version__
) -> PolicyEval:
    """현재 클라이언트 버전에 대한 판정과 안내 문구를 돌려준다."""
    status = evaluate_policy(current_version, policy)
    notice = None
    if policy is not None:
        if status is PolicyStatus.BELOW_MINIMUM:
            notice = (
                f"현재 버전({current_version})은 더 이상 지원되지 않습니다. "
                f"최신 버전(v{policy.latest_version})으로 업데이트해 주세요."
            )
        elif status is PolicyStatus.UPDATE_AVAILABLE and policy.notice:
            notice = policy.notice
    return PolicyEval(status=status, policy=policy, notice=notice)


class ReleasePolicyClient:
    """PostgREST로 ``release_policies`` 행 한 개를 읽는다(읽기 전용)."""

    def __init__(
        self,
        config: RemoteConfig,
        *,
        client: JsonHttpClient | None = None,
        platform: str = DEFAULT_PLATFORM,
        timeout: float = POLICY_TIMEOUT_SECONDS,
    ) -> None:
        self._config = config
        self._client = client or JsonHttpClient(timeout=timeout)
        self._platform = platform

    def fetch(self) -> ReleasePolicy | None:
        """플랫폼 정책을 조회한다. 조회 실패/빈 결과는 None(비차단)."""
        row = self._fetch_row()
        if row is None:
            return None
        try:
            return ReleasePolicy.from_row(row)
        except (TypeError, ValueError):
            return None

    def _fetch_row(self) -> dict[str, Any] | None:
        query = urllib.parse.urlencode(
            {"platform": f"eq.{self._platform}", "select": "*", "limit": "1"}
        )
        url = f"{self._config.rest_url}/release_policies?{query}"
        headers = {
            "apikey": self._config.anon_key,
            "Authorization": f"Bearer {self._config.anon_key}",
        }
        try:
            response = self._client.request_json("GET", url, None, headers)
        except (NetworkError, ResponseFormatError):
            return None
        if response.status != 200:
            return None
        body = response.json()
        if isinstance(body, list) and body:
            item = body[0]
            return item if isinstance(item, dict) else None
        return None


def load_cached_policy(path: Path) -> ReleasePolicy | None:
    """로컬 캐시된 정책을 읽는다. 없거나 손상됐으면 None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return ReleasePolicy.from_row(data)
    except (TypeError, ValueError):
        return None


def save_cached_policy(policy: ReleasePolicy, path: Path) -> None:
    """정책을 원자적으로 로컬 캐시에 기록한다."""
    text = json.dumps(policy.to_dict(), ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + _CACHE_SUFFIX)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _gate_allows(policy: ReleasePolicy) -> bool:
    return online_access_allowed(evaluate_policy(__version__, policy))


def resolve_policy_for_startup(
    remote_config: RemoteConfig | None,
    cache_path: Path,
    *,
    client: JsonHttpClient | None = None,
) -> tuple[ReleasePolicy | None, bool]:
    """온라인 시작 시 정책을 갱신하고 유효 정책과 온라인 허용 여부를 돌려준다.

    - 온라인: 조회 성공 시 캐시 갱신. 실패 시 기존 캐시 사용.
    - 오프라인(``remote_config`` None): 캐시만 사용.
    - 정책/캐시 모두 없으면 최소 차단 없이 최신 동작을 보존한다.
    """
    if remote_config is not None:
        fetched = ReleasePolicyClient(config=remote_config, client=client).fetch()
        if fetched is not None:
            save_cached_policy(fetched, cache_path)
            return fetched, _gate_allows(fetched)

    cached = load_cached_policy(cache_path)
    if cached is not None:
        return cached, _gate_allows(cached)
    return None, True
