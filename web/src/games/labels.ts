// enum 값 ↔ 한글 라벨 (데스크톱 `enums.py`와 동일).

import type { Game } from "./types";
import { RANK_TIER_LABELS } from "./rank";

export const RESULT_LABELS: Readonly<Record<string, string>> = {
    win: "승",
    lose: "패",
};

export const TURN_ORDER_LABELS: Readonly<Record<string, string>> = {
    first: "선공",
    second: "후공",
};

export const END_REASON_LABELS: Readonly<Record<string, string>> = {
    regular: "정규 결착",
    surrender: "서렌",
    timeout: "시간 제한",
    disconnect: "연결 두절",
};

export const STANDING_KIND_LABELS: Readonly<Record<string, string>> = {
    rank: "랭크",
    rating: "레이팅",
    event_points: "점수전",
};

export function label(
    mapping: Readonly<Record<string, string>>,
    value: string | null | undefined,
    fallback = "—",
): string {
    if (value === null || value === undefined) {
        return fallback;
    }
    return mapping[value] ?? value;
}

/** 모드별 전후 상태 변화를 사람이 읽는 문자열로 표시한다 (spec §5.3). */
export function formatStandingChange(game: Game): string {
    const kind = game.standing_kind;
    if (kind === "event_points") {
        const before = game.event_points_before;
        const after = game.event_points_after;
        if (before === null || after === null) {
            return "—";
        }
        return `${before.toLocaleString()} → ${after.toLocaleString()}`;
    }
    if (kind === "rating") {
        const before = game.rating_before;
        const after = game.rating_after;
        if (before === null || after === null) {
            return "—";
        }
        return `${before.toLocaleString()} → ${after.toLocaleString()}`;
    }
    if (kind === "rank") {
        const beforeTier = game.rank_tier_before;
        const beforeDivision = game.rank_division_before;
        const afterTier = game.rank_tier_after;
        const afterDivision = game.rank_division_after;
        if (
            beforeTier === null ||
            afterTier === null ||
            beforeDivision === null ||
            afterDivision === null
        ) {
            return "—";
        }
        const before = `${RANK_TIER_LABELS[beforeTier] ?? beforeTier} ${beforeDivision}`;
        const after = `${RANK_TIER_LABELS[afterTier] ?? afterTier} ${afterDivision}`;
        return before === after ? `${before} 유지` : `${before} → ${after}`;
    }
    return "—";
}
