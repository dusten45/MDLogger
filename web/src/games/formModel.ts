// 경기 입력 → 서버 payload 변환·검증 (데스크톱 `detail_form.py`의 `values()`와
// 동일한 규칙, spec §7). React 폼과 분리해 단위 테스트 가능하게 한다.

import type { ScoreInputMode } from "../settings/webSettings";
import { STANDING_KIND_LABELS } from "./labels";
import { RankStanding } from "./rank";
import type {
    EndReason,
    Game,
    GameMode,
    GamePayload,
    Result,
    StandingKind,
    TurnOrder,
} from "./types";

export interface RankValue {
    tier: string;
    division: number;
}

export interface GameFormState {
    mode: GameMode | null;
    result: Result | null;
    turnOrder: TurnOrder;
    myDeck: string;
    oppDeck: string;
    turns: number;
    endReason: EndReason;
    note: string;
    memoEnabled: boolean;
    scoreInputMode: ScoreInputMode;
    // 편집 모드: 전/후 값을 직접 입력한다 (데스크톱 `_editing`).
    editing: boolean;
    // 점수 모드
    scoreBase: number;
    scoreBeforeInput: string;
    scoreDelta: string;
    scoreAfter: string;
    // 레이팅 모드
    ratingBase: number | null;
    ratingBeforeInput: string;
    ratingDelta: string;
    ratingAfter: string;
    // 랭크 모드
    rankBefore: RankValue | null;
    rankAfter: RankValue | null;
    playedAt: string;
    timezoneOffsetMinutes: number | null;
}

export interface GameFormResult {
    payload?: GamePayload;
    error?: string;
}

function parseIntOrNull(text: string): number | null {
    const trimmed = text.trim();
    if (!trimmed) {
        return null;
    }
    const value = Number(trimmed);
    // 데스크톱 `_int_line`의 QIntValidator(0, 9999999)와 동일 범위.
    if (!Number.isInteger(value) || value < 0 || value > 9_999_999) {
        return null;
    }
    return value;
}

export function buildGamePayload(state: GameFormState): GameFormResult {
    const myDeck = state.myDeck.trim();
    const oppDeck = state.oppDeck.trim();
    if (!myDeck || !oppDeck) {
        return { error: "내 덱 / 상대 덱을 후보에서 정확히 선택하세요" };
    }
    if (state.mode === null) {
        return { error: "모드를 선택하세요" };
    }
    if (state.result === null) {
        return { error: "승/패를 선택하세요" };
    }
    if (!state.mode.play_context_id) {
        return { error: "선택한 모드의 경기 문맥이 없습니다." };
    }

    const payload: GamePayload = {
        played_at: state.playedAt,
        result: state.result,
        turn_order: state.turnOrder,
        my_deck: myDeck,
        opp_deck: oppDeck,
        turns: state.turns,
        end_reason: state.endReason,
        note: state.memoEnabled ? state.note.trim() : "",
        play_context_id: state.mode.play_context_id,
        standing_kind: state.mode.standing_kind,
        timezone_offset_minutes: state.timezoneOffsetMinutes,
    };

    const kind: StandingKind = state.mode.standing_kind;
    if (kind === "event_points") {
        const result = buildEventPoints(payload, state);
        if (result.error) {
            return result;
        }
    } else if (kind === "rank") {
        const result = buildRank(payload, state);
        if (result.error) {
            return result;
        }
    } else {
        const result = buildRating(payload, state);
        if (result.error) {
            return result;
        }
    }
    return { payload };
}

function buildEventPoints(
    payload: GamePayload,
    state: GameFormState,
): GameFormResult {
    if (state.editing) {
        const before = parseIntOrNull(state.scoreBeforeInput);
        const after = parseIntOrNull(state.scoreAfter);
        if (before === null || after === null) {
            return { error: "경기 전/후 점수를 입력하세요" };
        }
        payload.event_points_before = before;
        payload.event_points_after = after;
        return {};
    }
    if (state.scoreInputMode === "delta") {
        const delta = parseIntOrNull(state.scoreDelta);
        if (delta === null) {
            return { error: "점수 변동폭을 입력하세요" };
        }
        const before = state.scoreBase;
        const after = state.result === "win" ? before + delta : before - delta;
        // 서버 CHECK(event_points_after >= 0)를 미리 차단한다.
        if (after < 0) {
            return { error: "경기 후 점수는 0 이상이어야 합니다." };
        }
        payload.event_points_before = before;
        payload.event_points_after = after;
    } else {
        const after = parseIntOrNull(state.scoreAfter);
        if (after === null) {
            return { error: "경기 후 점수를 입력하세요" };
        }
        payload.event_points_before = state.scoreBase;
        payload.event_points_after = after;
    }
    return {};
}

function buildRating(
    payload: GamePayload,
    state: GameFormState,
): GameFormResult {
    if (state.editing) {
        const before = parseIntOrNull(state.ratingBeforeInput);
        const after = parseIntOrNull(state.ratingAfter);
        if (before === null || after === null) {
            return { error: "경기 전/후 레이팅을 입력하세요" };
        }
        payload.rating_before = before;
        payload.rating_after = after;
        return {};
    }
    const before = state.ratingBase ?? parseIntOrNull(state.ratingBeforeInput);
    if (before === null) {
        return { error: "경기 전 레이팅을 입력하세요" };
    }
    if (state.scoreInputMode === "delta") {
        const delta = parseIntOrNull(state.ratingDelta);
        if (delta === null) {
            return { error: "레이팅 변동폭을 입력하세요" };
        }
        const after = state.result === "win" ? before + delta : before - delta;
        payload.rating_before = before;
        payload.rating_after = after;
    } else {
        const after = parseIntOrNull(state.ratingAfter);
        if (after === null) {
            return { error: "경기 후 레이팅을 입력하세요" };
        }
        payload.rating_before = before;
        payload.rating_after = after;
    }
    return {};
}

function buildRank(payload: GamePayload, state: GameFormState): GameFormResult {
    if (state.rankBefore === null || state.rankAfter === null) {
        return { error: "랭크를 선택하세요" };
    }
    payload.rank_tier_before = state.rankBefore.tier;
    payload.rank_division_before = state.rankBefore.division;
    payload.rank_tier_after = state.rankAfter.tier;
    payload.rank_division_after = state.rankAfter.division;
    return {};
}

/** 랭크 빠른 변동(변동 없음/승급/강등) 계산 (데스크톱 `_RankPanel._apply_quick`). */
export function applyRankQuick(
    before: RankValue | null,
    action: "same" | "up" | "down",
): RankValue | null {
    if (before === null) {
        return null;
    }
    const standing = new RankStanding(before.tier, before.division);
    if (action === "up") {
        const after = standing.promoted();
        return { tier: after.tier, division: after.division };
    }
    if (action === "down") {
        const after = standing.demoted();
        return { tier: after.tier, division: after.division };
    }
    return before;
}

/** 게임의 play_context_id와 일치하는 활성 모드를 찾는다. 없으면 null. */
export function findModeForGame(
    modes: GameMode[],
    game: Game,
): GameMode | null {
    return (
        modes.find((mode) => mode.play_context_id === game.play_context_id) ??
        null
    );
}

/** 비활성/삭제된 모드의 게임도 편집할 수 있게 합성 모드를 만든다. */
export function syntheticModeForGame(game: Game): GameMode {
    const kind: StandingKind = game.standing_kind ?? "event_points";
    return {
        id: game.play_context_id ?? "legacy",
        standing_kind: kind,
        display_name: STANDING_KIND_LABELS[kind] ?? "기록",
        play_context_id: game.play_context_id,
        sort_order: 0,
        is_active: false,
        season_label: null,
    };
}

/** 기존 게임을 편집용 폼 상태로 변환한다 (데스크톱 `set_values`와 동일). */
export function gameToFormState(
    game: Game,
    mode: GameMode | null,
    settings: { memo_enabled: boolean; score_input_mode: ScoreInputMode },
): GameFormState {
    const rankBefore =
        game.rank_tier_before !== null && game.rank_division_before !== null
            ? {
                  tier: game.rank_tier_before,
                  division: game.rank_division_before,
              }
            : null;
    const rankAfter =
        game.rank_tier_after !== null && game.rank_division_after !== null
            ? { tier: game.rank_tier_after, division: game.rank_division_after }
            : null;
    return {
        mode,
        result: game.result,
        turnOrder: game.turn_order,
        myDeck: game.my_deck ?? "",
        oppDeck: game.opp_deck ?? "",
        turns: game.turns ?? 1,
        endReason: game.end_reason ?? "regular",
        note: game.note ?? "",
        // 편집 다이얼로그는 메모 설정과 무관하게 항상 메모를 보여주고 보존한다
        // (데스크톱 EditDialog는 set_memo_enabled를 호출하지 않음).
        memoEnabled: true,
        scoreInputMode: settings.score_input_mode,
        editing: true,
        scoreBase: game.event_points_before ?? 0,
        scoreBeforeInput:
            game.event_points_before !== null
                ? String(game.event_points_before)
                : "",
        scoreDelta: "",
        scoreAfter:
            game.event_points_after !== null
                ? String(game.event_points_after)
                : "",
        ratingBase: game.rating_before ?? null,
        ratingBeforeInput:
            game.rating_before !== null ? String(game.rating_before) : "",
        ratingDelta: "",
        ratingAfter:
            game.rating_after !== null ? String(game.rating_after) : "",
        rankBefore,
        rankAfter,
        playedAt: game.played_at,
        timezoneOffsetMinutes: game.timezone_offset_minutes,
    };
}
