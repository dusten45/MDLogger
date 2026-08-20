import { describe, expect, it } from "vitest";
import type { Game, GameMode, StandingKind } from "./types";
import {
    applyRankQuick,
    buildGamePayload,
    gameToFormState,
    type GameFormState,
} from "./formModel";

function mode(kind: StandingKind): GameMode {
    return {
        id: "m1",
        standing_kind: kind,
        display_name: "테스트",
        play_context_id: "ctx_1",
        sort_order: 0,
        is_active: true,
        season_label: null,
    };
}

function state(overrides: Partial<GameFormState> = {}): GameFormState {
    return {
        mode: mode("event_points"),
        result: "win",
        turnOrder: "first",
        myDeck: "내덱",
        oppDeck: "상대덱",
        turns: 1,
        endReason: "regular",
        note: "",
        memoEnabled: true,
        scoreInputMode: "delta",
        editing: false,
        scoreBase: 100,
        scoreBeforeInput: "",
        scoreDelta: "20",
        scoreAfter: "",
        ratingBase: null,
        ratingBeforeInput: "",
        ratingDelta: "",
        ratingAfter: "",
        rankBefore: null,
        rankAfter: null,
        playedAt: "2026-08-18T12:00:00",
        timezoneOffsetMinutes: 540,
        ...overrides,
    };
}

describe("buildGamePayload — 점수전", () => {
    it("DELTA 승리: 경기 전 + 변동폭", () => {
        const result = buildGamePayload(
            state({ result: "win", scoreDelta: "20" }),
        );
        expect(result.error).toBeUndefined();
        expect(result.payload?.event_points_before).toBe(100);
        expect(result.payload?.event_points_after).toBe(120);
    });

    it("DELTA 패배: 경기 전 - 변동폭", () => {
        const result = buildGamePayload(
            state({ result: "lose", scoreDelta: "20" }),
        );
        expect(result.payload?.event_points_after).toBe(80);
    });

    it("DIRECT: 경기 후 점수를 직접 입력", () => {
        const result = buildGamePayload(
            state({ scoreInputMode: "direct", scoreAfter: "150" }),
        );
        expect(result.payload?.event_points_before).toBe(100);
        expect(result.payload?.event_points_after).toBe(150);
    });

    it("변동폭이 비어 있으면 오류", () => {
        const result = buildGamePayload(state({ scoreDelta: "" }));
        expect(result.error).toBe("점수 변동폭을 입력하세요");
    });

    it("패배로 경기 후 점수가 음수가 되면 오류", () => {
        const result = buildGamePayload(
            state({ result: "lose", scoreBase: 10, scoreDelta: "20" }),
        );
        expect(result.error).toBe("경기 후 점수는 0 이상이어야 합니다.");
    });

    it("편집 모드: 전/후 점수를 직접 입력", () => {
        const result = buildGamePayload(
            state({ editing: true, scoreBeforeInput: "90", scoreAfter: "110" }),
        );
        expect(result.payload?.event_points_before).toBe(90);
        expect(result.payload?.event_points_after).toBe(110);
    });
});

describe("buildGamePayload — 레이팅전", () => {
    it("DELTA: 직전 레이팅 + 변동폭", () => {
        const result = buildGamePayload(
            state({
                mode: mode("rating"),
                ratingBase: 1500,
                ratingDelta: "30",
                result: "win",
            }),
        );
        expect(result.payload?.rating_before).toBe(1500);
        expect(result.payload?.rating_after).toBe(1530);
    });

    it("첫 경기: 경기 전 레이팅을 직접 입력", () => {
        const result = buildGamePayload(
            state({
                mode: mode("rating"),
                ratingBase: null,
                ratingBeforeInput: "1500",
                ratingDelta: "30",
                result: "win",
            }),
        );
        expect(result.payload?.rating_before).toBe(1500);
        expect(result.payload?.rating_after).toBe(1530);
    });

    it("첫 경기에 경기 전 레이팅이 없으면 오류", () => {
        const result = buildGamePayload(
            state({
                mode: mode("rating"),
                ratingBase: null,
                ratingDelta: "30",
            }),
        );
        expect(result.error).toBe("경기 전 레이팅을 입력하세요");
    });
});

describe("buildGamePayload — 랭크전", () => {
    it("전후 스냅샷을 저장한다", () => {
        const result = buildGamePayload(
            state({
                mode: mode("rank"),
                rankBefore: { tier: "gold", division: 3 },
                rankAfter: { tier: "gold", division: 2 },
            }),
        );
        expect(result.payload?.rank_tier_before).toBe("gold");
        expect(result.payload?.rank_division_before).toBe(3);
        expect(result.payload?.rank_tier_after).toBe("gold");
        expect(result.payload?.rank_division_after).toBe(2);
    });

    it("랭크가 없으면 오류", () => {
        const result = buildGamePayload(state({ mode: mode("rank") }));
        expect(result.error).toBe("랭크를 선택하세요");
    });
});

describe("buildGamePayload — 공통 검증", () => {
    it("덱이 비어 있으면 오류", () => {
        const result = buildGamePayload(state({ myDeck: "" }));
        expect(result.error).toBe(
            "내 덱 / 상대 덱을 후보에서 정확히 선택하세요",
        );
    });

    it("승/패가 없으면 오류", () => {
        const result = buildGamePayload(state({ result: null }));
        expect(result.error).toBe("승/패를 선택하세요");
    });

    it("메모 비활성화 시 빈 메모를 저장한다", () => {
        const result = buildGamePayload(
            state({ memoEnabled: false, note: "비밀 메모" }),
        );
        expect(result.payload?.note).toBe("");
    });
});

describe("applyRankQuick", () => {
    it("변동 없음은 전 상태를 유지한다", () => {
        expect(applyRankQuick({ tier: "gold", division: 3 }, "same")).toEqual({
            tier: "gold",
            division: 3,
        });
    });

    it("한 단계 승급/강등을 계산한다", () => {
        expect(applyRankQuick({ tier: "gold", division: 3 }, "up")).toEqual({
            tier: "gold",
            division: 2,
        });
        expect(applyRankQuick({ tier: "gold", division: 3 }, "down")).toEqual({
            tier: "gold",
            division: 4,
        });
    });
});

describe("gameToFormState", () => {
    it("편집 모드는 메모 설정과 무관하게 메모를 보존한다", () => {
        const game: Game = {
            id: "g1",
            played_at: "2026-08-18T12:00:00",
            result: "win",
            turn_order: "first",
            my_deck: "내덱",
            opp_deck: "상대덱",
            turns: 10,
            end_reason: "regular",
            note: "기존 메모",
            play_context_id: "ctx_1",
            standing_kind: "event_points",
            rank_tier_before: null,
            rank_tier_after: null,
            rank_division_before: null,
            rank_division_after: null,
            rating_before: null,
            rating_after: null,
            event_points_before: 100,
            event_points_after: 120,
            timezone_offset_minutes: 540,
            environment_version_id: null,
            created_at: "2026-08-18T12:00:00",
            updated_at: "2026-08-18T12:00:00",
            deleted_at: null,
            change_version: 1,
            payload_version: 2,
            source_kind: "native",
            client_version: "web-dev",
        };
        const form = gameToFormState(game, mode("event_points"), {
            memo_enabled: false,
            score_input_mode: "delta",
        });
        expect(form.memoEnabled).toBe(true);
        expect(form.note).toBe("기존 메모");
        expect(form.editing).toBe(true);
    });
});
