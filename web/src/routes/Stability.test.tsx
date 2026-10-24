import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { RequireAuth } from "../components/RequireAuth";
import type { Game } from "../games/types";
import type { GameStatistics, HistoryPageResult, RecordState } from "../games/gameApi";
import { summarizeGames } from "../games/stats";
import { RecordPage } from "./RecordPage";
import { HistoryPage } from "./HistoryPage";
import { StatsPage } from "./StatsPage";

const mocks = vi.hoisted(() => ({ rpc: vi.fn(), user: "user-a" }));
vi.mock("../lib/supabase", () => ({ getSupabaseClient: () => ({ rpc: mocks.rpc }) }));
vi.mock("../auth/useAuth", () => ({
    useAuth: () => ({ session: { user: { id: mocks.user } }, loading: false }),
}));
vi.mock("../decks/deckCatalog", () => ({ fetchDecks: async () => ["A", "B"] }));
vi.mock("../settings/useSettings", () => ({
    useSettings: () => ({ settings: { memo_enabled: true, score_input_mode: "delta", default_mode: "last_used" } }),
}));
vi.mock("../games/modes", () => ({
    listGameModes: async () => [
        { id: "dc", display_name: "DC", standing_kind: "event_points", play_context_id: "dc_cup_2026_08", is_active: true },
        { id: "rank", display_name: "랭크", standing_kind: "rank", play_context_id: "rank_2026_08", is_active: true },
    ],
}));

function game(id: string, overrides: Partial<Game> = {}): Game {
    return {
        id, played_at: "2026-08-07T10:00:00", result: "win", turn_order: "first",
        my_deck: "A", opp_deck: "B", turns: 2, end_reason: "regular", note: null,
        play_context_id: "dc_cup_2026_08", standing_kind: "event_points",
        rank_tier_before: null, rank_tier_after: null, rank_division_before: null, rank_division_after: null,
        rating_before: null, rating_after: null, event_points_before: 9900, event_points_after: 10000,
        timezone_offset_minutes: 540, environment_version_id: null, created_at: "", updated_at: "",
        deleted_at: null, change_version: 1, payload_version: 2, source_kind: "web", client_version: null,
        ...overrides,
    };
}

function recordState(): RecordState {
    return {
        snapshot_version: 1001, today: { wins: 1001, losses: 0 },
        last_game: game("latest-rank", { play_context_id: "rank_2026_08", standing_kind: "rank" }),
        last_my_deck: "A", latest_by_mode: [game("older-dc")],
    };
}

function page(games: Game[], overrides: Partial<HistoryPageResult> = {}): HistoryPageResult {
    return { games, snapshot_version: 1001, next_cursor: null, has_more: false, stale: false, ...overrides };
}

function statistics(total: number): GameStatistics {
    return { snapshot_version: total, summary: { ...summarizeGames([]), total, wins: total, winrate: 100 }, matchups: [], series: [] };
}

async function fillRecord() {
    await screen.findByRole("button", { name: "DC" });
    fireEvent.click(screen.getByRole("button", { name: "승" }));
    fireEvent.change(screen.getByLabelText("상대 덱"), { target: { value: "B" } });
    fireEvent.change(screen.getByLabelText("점수 변동폭"), { target: { value: "100" } });
}

beforeEach(() => {
    mocks.rpc.mockReset();
    mocks.user = "user-a";
    localStorage.clear();
    vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("저장 영수증과 재시도", () => {
    it("최신 1000건 밖의 모드 기준과 전체 오늘 전적을 사용한다", async () => {
        mocks.rpc.mockImplementation(async (name, args) => {
            if (name === "get_record_state") return { data: recordState(), error: null };
            return { data: { results: [{ id: args.changes[0].id, status: "applied", change_version: 1002 }] }, error: null };
        });
        render(<RecordPage />);
        await fillRecord();
        expect(screen.getByText("오늘 전적 1001승 0패")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText("기록을 저장했습니다.");
        const request = mocks.rpc.mock.calls.find(([name]) => name === "apply_game_changes")![1];
        expect(request.changes[0].payload.event_points_before).toBe(10000);
        expect(request.changes[0].payload.event_points_after).toBe(10100);
    });

    it("저장 후 조회 실패는 재생성하지 않고 확인된 ID만 취소한다", async () => {
        let reads = 0;
        let savedId = "";
        mocks.rpc.mockImplementation(async (name, args) => {
            if (name === "get_record_state") {
                return ++reads === 1 ? { data: recordState(), error: null } : { data: null, error: new Error("조회 실패") };
            }
            const change = args.changes[0];
            if (change.op === "create") savedId = change.id;
            return { data: { results: [{ id: change.id, status: "applied", change_version: 1002 }] }, error: null };
        });
        render(<RecordPage />);
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(/기록은 저장했습니다/);
        expect(screen.getByRole("button", { name: "저장" })).toBeDisabled();
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(null);
        fireEvent.click(screen.getByRole("button", { name: "마지막 기록 취소" }));
        await screen.findByText(/기록은 취소했습니다/);
        const mutations = mocks.rpc.mock.calls.filter(([name]) => name === "apply_game_changes");
        expect(mutations).toHaveLength(2);
        expect(mutations[1][1].changes[0]).toMatchObject({ op: "delete", id: savedId, expected_change_version: 1002 });
        expect(savedId).not.toBe("latest-rank");
        expect(screen.getByRole("button", { name: "마지막 기록 취소" })).toBeDisabled();
    });

    it("응답 유실 후 UUID, 요청 ID, 시각과 payload를 그대로 재전송한다", async () => {
        let calls = 0;
        const receipts = new Map<string, string>();
        mocks.rpc.mockImplementation(async (name, args) => {
            if (name === "get_record_state") return { data: recordState(), error: null };
            const change = args.changes[0];
            const body = JSON.stringify(change.payload);
            if (receipts.has(change.request_id)) expect(receipts.get(change.request_id)).toBe(body);
            receipts.set(change.request_id, body);
            if (++calls === 1) return { data: null, error: new Error("응답 유실") };
            return { data: { results: [{ id: change.id, status: "applied", change_version: 1002, replayed: true }] }, error: null };
        });
        render(<RecordPage />);
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(/저장 결과를 확인하지 못했습니다/);
        expect(screen.getByLabelText("점수 변동폭")).toBeDisabled();
        fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 확인" }));
        await screen.findByText("기록을 저장했습니다.");
        const sent = mocks.rpc.mock.calls.filter(([name]) => name === "apply_game_changes");
        expect(sent[0][1]).toEqual(sent[1][1]);
        expect(receipts.size).toBe(1);
        expect(localStorage.getItem("pending_game")).toBeNull();
    });

    it("초기 조회 실패를 0점으로 사용하지 않고 새로고침으로 복구한다", async () => {
        mocks.rpc.mockResolvedValueOnce({ data: null, error: new Error("오프라인") })
            .mockResolvedValue({ data: recordState(), error: null });
        render(<RecordPage />);
        await screen.findByText("기록 화면을 불러오지 못했습니다.");
        expect(screen.getByRole("button", { name: "저장" })).toBeDisabled();
        fireEvent.click(screen.getByRole("button", { name: "새로고침" }));
        await screen.findByRole("button", { name: "DC" });
        expect(screen.getByRole("button", { name: "저장" })).toBeEnabled();
    });
});

describe("기록 목록 계약", () => {
    it("실제 SQL 수정 영수증 뒤 조회 실패도 수정 완료로 표시한다", async () => {
        let reads = 0;
        mocks.rpc.mockImplementation(async (name, args) => {
            if (name === "list_game_history") return ++reads === 1
                ? { data: page([game("edit-me")]), error: null }
                : { data: null, error: new Error("읽기 실패") };
            return { data: { results: [{ id: args.changes[0].id, status: "applied", change_version: 2 }] }, error: null };
        });
        render(<HistoryPage />);
        const edits = await screen.findAllByRole("button", { name: "수정" });
        fireEvent.click(edits[0]);
        fireEvent.click(screen.getByRole("button", { name: "수정 저장" }));
        await screen.findByText("기록을 수정했습니다. 목록 갱신에 실패했습니다. 새로고침하세요.");
        expect(screen.queryByRole("button", { name: "수정 저장" })).not.toBeInTheDocument();
        expect(screen.getAllByRole("button", { name: "수정" })[0]).toBeDisabled();
        expect(mocks.rpc.mock.calls.filter(([name]) => name === "apply_game_changes")).toHaveLength(1);
    });

    it("동률 커서와 snapshot을 보내며 변경된 페이지는 이어 붙이지 않는다", async () => {
        const first = game("tie-2");
        let reads = 0;
        mocks.rpc.mockImplementation(async () => {
            reads += 1;
            if (reads === 1) return { data: page([first], { has_more: true, next_cursor: { played_at: first.played_at, id: first.id } }), error: null };
            if (reads === 2) return { data: page([], { stale: true, snapshot_version: 1002 }), error: null };
            return { data: page([game("new", { opp_deck: "최신 덱" })], { snapshot_version: 1002 }), error: null };
        });
        render(<HistoryPage />);
        fireEvent.click(await screen.findByRole("button", { name: "더 보기" }));
        await screen.findByText("다른 기기의 변경이 있어 첫 페이지부터 다시 불러왔습니다.");
        expect(mocks.rpc.mock.calls[1][1]).toMatchObject({ p_before_id: "tie-2", p_before_played_at: first.played_at, p_snapshot_version: 1001 });
        expect(screen.getAllByText(/최신 덱/).length).toBeGreaterThan(0);
        expect(screen.queryByRole("button", { name: "더 보기" })).not.toBeInTheDocument();
    });

    it("모드 필터를 서버에 전달하고 이전 필터의 늦은 응답을 버린다", async () => {
        let resolveOld!: (value: unknown) => void;
        mocks.rpc.mockImplementation(async (_name, args) => {
            if (args.p_context === "dc_cup_2026_08") return new Promise((resolve) => { resolveOld = resolve; });
            return { data: page([game("current", { opp_deck: args.p_context === "rank_2026_08" ? "랭크 덱" : "전체 덱" })]), error: null };
        });
        render(<HistoryPage />);
        fireEvent.click(await screen.findByRole("button", { name: "DC" }));
        await waitFor(() => expect(resolveOld).toBeTypeOf("function"));
        fireEvent.click(screen.getByRole("button", { name: "랭크" }));
        await screen.findAllByText(/랭크 덱/);
        await act(async () => { resolveOld({ data: page([game("late", { opp_deck: "늦은 덱" })]), error: null }); });
        expect(screen.queryByText(/늦은 덱/)).not.toBeInTheDocument();
        expect(mocks.rpc.mock.calls[mocks.rpc.mock.calls.length - 1][1].p_context).toBe("rank_2026_08");
    });
});

describe("전체 집계와 계정 격리", () => {
    it("전체 집계 1001건을 그대로 표시한다", async () => {
        mocks.rpc.mockResolvedValue({ data: statistics(1001), error: null });
        const view = render(<StatsPage />);
        await screen.findByRole("heading", { name: "통계" });
        expect(view.container.querySelector(".stat-card")?.textContent).toBe("전체1001");
        expect(mocks.rpc).toHaveBeenCalledWith("get_game_statistics", { p_context: null });
    });

    it("조회 오류를 빈 통계로 표시하지 않는다", async () => {
        mocks.rpc.mockResolvedValue({ data: null, error: new Error("오프라인") });
        const view = render(<StatsPage />);
        await screen.findByText("통계를 불러오지 못했습니다.");
        expect(view.container.querySelector(".stat-card")).toBeNull();
    });

    it("계정이 바뀌면 기록 상태를 폐기하고 이전 계정의 늦은 응답을 무시한다", async () => {
        let resolveA!: (value: unknown) => void;
        mocks.rpc.mockImplementation(async () => mocks.user === "user-a"
            ? new Promise((resolve) => { resolveA = resolve; })
            : { data: statistics(2), error: null });
        const app = () => <MemoryRouter><RequireAuth><StatsPage /></RequireAuth></MemoryRouter>;
        const view = render(app());
        await waitFor(() => expect(resolveA).toBeTypeOf("function"));
        mocks.user = "user-b";
        view.rerender(app());
        await screen.findByRole("heading", { name: "통계" });
        await act(async () => { resolveA({ data: statistics(999), error: null }); });
        expect(view.container.querySelector(".stat-card")?.textContent).toBe("전체2");
        expect(screen.queryByText("999")).not.toBeInTheDocument();
    });
});
