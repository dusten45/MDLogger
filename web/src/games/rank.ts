// 랭크 티어·단계 도메인 (데스크톱 `enums.py`/`models.py`와 동일 의미, spec §2.2).
//
// 티어 순서는 화면 배치·정렬 순서의 단일 출처다. 단계는 모든 티어가 5 → 1로
// 감소한다(P7).

export interface RankTier {
  value: string;
  label: string;
}

export const RANK_TIERS: readonly RankTier[] = [
  { value: "rookie", label: "루키" },
  { value: "bronze", label: "브론즈" },
  { value: "silver", label: "실버" },
  { value: "gold", label: "골드" },
  { value: "platinum", label: "플래티넘" },
  { value: "diamond", label: "다이아몬드" },
  { value: "master", label: "마스터" },
];

export const RANK_TIER_LABELS: Readonly<Record<string, string>> =
  Object.fromEntries(RANK_TIERS.map((tier) => [tier.value, tier.label]));

export const RANK_TIER_INDEX: Readonly<Record<string, number>> =
  Object.fromEntries(RANK_TIERS.map((tier, index) => [tier.value, index]));

export const RANK_DIVISION_MIN = 1;
export const RANK_DIVISION_MAX = 5;

export class RankTierError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RankTierError";
  }
}

/** 티어 + 단계(1~5) 조합. 전후 스냅샷과 빠른 변동 계산에 쓴다 (spec §2.2). */
export class RankStanding {
  readonly tier: string;
  readonly division: number;

  constructor(tier: string, division: number) {
    if (!(tier in RANK_TIER_INDEX)) {
      throw new RankTierError(`알 수 없는 티어: ${tier}`);
    }
    if (division < RANK_DIVISION_MIN || division > RANK_DIVISION_MAX) {
      throw new RankTierError(
        `단계는 ${RANK_DIVISION_MIN}~${RANK_DIVISION_MAX}이어야 합니다: ${division}`,
      );
    }
    this.tier = tier;
    this.division = division;
  }

  get label(): string {
    return `${RANK_TIER_LABELS[this.tier] ?? this.tier} ${this.division}`;
  }

  /** 한 단계 승급(+1). 최고(마스터 1)면 그대로 유지 (spec §2.2). */
  promoted(): RankStanding {
    const top = RANK_TIERS[RANK_TIERS.length - 1];
    if (this.tier === top.value && this.division === RANK_DIVISION_MIN) {
      return this;
    }
    if (this.division === RANK_DIVISION_MIN) {
      const index = RANK_TIER_INDEX[this.tier];
      return new RankStanding(RANK_TIERS[index + 1].value, RANK_DIVISION_MAX);
    }
    return new RankStanding(this.tier, this.division - 1);
  }

  /** 한 단계 강등(-1). 최저(루키 5)면 그대로 유지 (spec §2.2). */
  demoted(): RankStanding {
    const bottom = RANK_TIERS[0];
    if (this.tier === bottom.value && this.division === RANK_DIVISION_MAX) {
      return this;
    }
    if (this.division === RANK_DIVISION_MAX) {
      const index = RANK_TIER_INDEX[this.tier];
      return new RankStanding(RANK_TIERS[index - 1].value, RANK_DIVISION_MIN);
    }
    return new RankStanding(this.tier, this.division + 1);
  }
}
