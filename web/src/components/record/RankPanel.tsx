// 랭크 모드 상태 입력 (데스크톱 `_RankPanel`과 동일, spec §5.2).
// 경기 전 프리필 + 빠른 변동(변동 없음/승급/강등) + 직접 선택.

import {
  RANK_DIVISION_MAX,
  RANK_DIVISION_MIN,
  RANK_TIERS,
} from "../../games/rank";
import { applyRankQuick, type RankValue } from "../../games/formModel";

export interface RankPanelProps {
  before: RankValue | null;
  after: RankValue | null;
  onBeforeChange(value: RankValue): void;
  onAfterChange(value: RankValue): void;
}

const DEFAULT_TIER = RANK_TIERS[0].value;
const DEFAULT_DIVISION = RANK_DIVISION_MIN;

export function RankPanel({
  before,
  after,
  onBeforeChange,
  onAfterChange,
}: RankPanelProps) {
  function applyQuick(action: "same" | "up" | "down") {
    const next = applyRankQuick(before, action);
    if (next !== null) {
      onAfterChange(next);
    }
  }

  return (
    <div className="stack">
      <div className="field-row">
        <span className="field__label">경기 전</span>
        <select
          aria-label="경기 전 티어"
          value={before?.tier ?? DEFAULT_TIER}
          onChange={(event) =>
            onBeforeChange({
              tier: event.target.value,
              division: before?.division ?? DEFAULT_DIVISION,
            })
          }
        >
          {RANK_TIERS.map((tier) => (
            <option key={tier.value} value={tier.value}>
              {tier.label}
            </option>
          ))}
        </select>
        <select
          aria-label="경기 전 단계"
          value={before?.division ?? DEFAULT_DIVISION}
          onChange={(event) =>
            onBeforeChange({
              tier: before?.tier ?? DEFAULT_TIER,
              division: Number(event.target.value),
            })
          }
        >
          {divisionOptions()}
        </select>
      </div>

      <div className="segmented" role="group" aria-label="빠른 변동">
        <button
          type="button"
          className="segmented__button"
          onClick={() => applyQuick("same")}
        >
          변동 없음
        </button>
        <button
          type="button"
          className="segmented__button"
          onClick={() => applyQuick("up")}
        >
          한 단계 승급
        </button>
        <button
          type="button"
          className="segmented__button"
          onClick={() => applyQuick("down")}
        >
          한 단계 강등
        </button>
      </div>

      <div className="field-row">
        <span className="field__label">경기 후</span>
        <select
          aria-label="경기 후 티어"
          value={after?.tier ?? DEFAULT_TIER}
          onChange={(event) =>
            onAfterChange({
              tier: event.target.value,
              division: after?.division ?? DEFAULT_DIVISION,
            })
          }
        >
          {RANK_TIERS.map((tier) => (
            <option key={tier.value} value={tier.value}>
              {tier.label}
            </option>
          ))}
        </select>
        <select
          aria-label="경기 후 단계"
          value={after?.division ?? DEFAULT_DIVISION}
          onChange={(event) =>
            onAfterChange({
              tier: after?.tier ?? DEFAULT_TIER,
              division: Number(event.target.value),
            })
          }
        >
          {divisionOptions()}
        </select>
      </div>
    </div>
  );
}

function divisionOptions() {
  const options = [];
  for (
    let division = RANK_DIVISION_MIN;
    division <= RANK_DIVISION_MAX;
    division += 1
  ) {
    options.push(
      <option key={division} value={division}>
        {division}
      </option>,
    );
  }
  return options;
}
