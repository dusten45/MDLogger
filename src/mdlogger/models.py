"""경기 모드·랭크 도메인 모델 (1단계).

문자열·임의 dict 사용을 줄이고 명시적 모델로 다룬다(로드맵 6.2, spec §2).
검증 규칙은 spec §2.5를 따른다. 티어 순서·단계 범위는 `enums.py`가 단일 출처다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .enums import (
    RANK_DIVISION_MAX,
    RANK_DIVISION_MIN,
    RANK_TIER_INDEX,
    RANK_TIER_LABELS,
    RANK_TIERS,
)


class StandingKind(StrEnum):
    """경기 모드의 종류. 서버 CHECK('rank','rating','event_points')와 일치한다."""

    RANK = "rank"
    RATING = "rating"
    EVENT_POINTS = "event_points"


class RankTierError(ValueError):
    """티어·단계 값이 유효하지 않을 때 발생한다."""


def _upper_tier(tier: str) -> str:
    index = RANK_TIER_INDEX[tier]
    return RANK_TIERS[index + 1][0]


def _lower_tier(tier: str) -> str:
    index = RANK_TIER_INDEX[tier]
    return RANK_TIERS[index - 1][0]


@dataclass(frozen=True, slots=True)
class RankStanding:
    """티어 + 단계(1~5) 조합. 전후 스냅샷과 빠른 변동 계산에 쓴다 (spec §2.2)."""

    tier: str
    division: int

    def __post_init__(self) -> None:
        if self.tier not in RANK_TIER_INDEX:
            raise RankTierError(f"알 수 없는 티어: {self.tier!r}")
        if not RANK_DIVISION_MIN <= self.division <= RANK_DIVISION_MAX:
            raise RankTierError(
                f"단계는 {RANK_DIVISION_MIN}~{RANK_DIVISION_MAX}이어야 합니다: {self.division}"
            )

    @property
    def label(self) -> str:
        return f"{RANK_TIER_LABELS.get(self.tier, self.tier)} {self.division}"

    def promoted(self) -> RankStanding:
        """한 단계 승급(+1). 최고(마스터 1)면 그대로 유지 (spec §2.2)."""
        if self.tier == RANK_TIERS[-1][0] and self.division == RANK_DIVISION_MIN:
            return self
        if self.division == RANK_DIVISION_MIN:
            return RankStanding(_upper_tier(self.tier), RANK_DIVISION_MAX)
        return RankStanding(self.tier, self.division - 1)

    def demoted(self) -> RankStanding:
        """한 단계 강등(-1). 최저(루키 5)면 그대로 유지 (spec §2.2)."""
        if self.tier == RANK_TIERS[0][0] and self.division == RANK_DIVISION_MAX:
            return self
        if self.division == RANK_DIVISION_MAX:
            return RankStanding(_lower_tier(self.tier), RANK_DIVISION_MIN)
        return RankStanding(self.tier, self.division + 1)


@dataclass(frozen=True, slots=True)
class GameMode:
    """선택 가능한 모드 설치본 (로컬 `play_modes` 캐시 행, spec §2.3).

    원본은 서버 `game_modes`이며, 로컬은 그 클라이언트 캐시다(B2).
    """

    id: str
    standing_kind: StandingKind
    display_name: str
    play_context_id: str | None
    sort_order: int = 0
    is_active: bool = True
    season_label: str | None = None
