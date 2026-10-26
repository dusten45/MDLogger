import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { AuthChangeEvent, Session } from "@supabase/supabase-js";
import { AuthProvider } from "../auth/AuthProvider";
import { AppShell } from "../components/AppShell";
import { RequireAuth } from "../components/RequireAuth";
import { SettingsProvider } from "../settings/SettingsProvider";
import { DEFAULT_SETTINGS, MemorySettingsStore } from "../settings/webSettings";
import type { Game } from "../games/types";
import type { HistoryPageResult, RecordState } from "../games/gameApi";
import { summarizeGames } from "../games/stats";
import { RecordProvider } from "../games/RecordProvider";
import { RecordPage } from "./RecordPage";
import { HistoryPage } from "./HistoryPage";
import { StatsPage } from "./StatsPage";
import { SettingsPage } from "./SettingsPage";
import { TermsPage } from "./TermsPage";
import { PrivacyPolicyPage } from "./PrivacyPolicyPage";
import App from "../App";

const sdk = vi.hoisted(() => ({
    rpc: vi.fn(), getSession: vi.fn(), onAuthStateChange: vi.fn(),
}));
vi.mock("../lib/supabase", () => ({
    getSupabaseClient: () => ({
        rpc: sdk.rpc,
        auth: { getSession: sdk.getSession, onAuthStateChange: sdk.onAuthStateChange },
        from: () => ({ select: () => ({ eq: () => ({ order: async () => ({
            data: [
                { id: "dc", display_name: "DC", standing_kind: "event_points", play_context_id: "dc_cup_2026_08", is_active: true },
                { id: "rank", display_name: "랭크", standing_kind: "rank", play_context_id: "rank_2026_08", is_active: true },
            ], error: null,
        }) }) }) }),
        functions: { invoke: async () => ({ data: { decks: ["테스트 덱", "상대 덱"] }, error: null }) },
    }),
}));
vi.mock("virtual:pwa-register/react", () => ({
    useRegisterSW: () => ({ needRefresh: [false, vi.fn()], updateServiceWorker: vi.fn() }),
}));

function session(id = "account-a", scope = "session-a", nonce = "initial"): Session {
    const payload = btoa(JSON.stringify({ session_id: scope, nonce }));
    return { user: { id, email: `${id}@example.invalid` }, access_token: `header.${payload}.signature` } as Session;
}

let authChanged: (event: AuthChangeEvent, session: Session | null) => void;

function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason: unknown) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}

function game(id: string, overrides: Partial<Game> = {}): Game {
    return {
        id, played_at: "2026-10-25T10:00:00", result: "win", turn_order: "first",
        my_deck: "테스트 덱", opp_deck: "상대 덱", turns: 1, end_reason: "regular", note: null,
        play_context_id: "dc_cup_2026_08", standing_kind: "event_points",
        rank_tier_before: null, rank_tier_after: null, rank_division_before: null, rank_division_after: null,
        rating_before: null, rating_after: null, event_points_before: 9900, event_points_after: 10000,
        timezone_offset_minutes: 540, environment_version_id: null, created_at: "", updated_at: "",
        deleted_at: null, change_version: 1, payload_version: 2, source_kind: "web", client_version: null,
        ...overrides,
    };
}

function recordState(last = game("previous")): RecordState {
    return { snapshot_version: last.change_version, today: { wins: 1, losses: 0 }, last_game: last,
        last_my_deck: "테스트 덱", latest_by_mode: [last] };
}

function page(games: Game[] = [], overrides: Partial<HistoryPageResult> = {}): HistoryPageResult {
    return { games, snapshot_version: 1, next_cursor: null, has_more: false, stale: false, ...overrides };
}

const ok = (data: unknown): { data: unknown; error: Error | null } => ({ data, error: null });
const failed = () => ({ data: null, error: new Error("테스트 통신 실패") });
const receipt = (id: string) => ok({ results: [{ id, status: "applied", change_version: 2 }] });
const writes = () => sdk.rpc.mock.calls.filter(([name]) => name === "apply_game_changes");

function mount(path = "/") {
    const router = createMemoryRouter([
        { element: <RequireAuth><AppShell /></RequireAuth>, children: [
            { index: true, element: <RecordPage /> },
            { path: "history", element: <HistoryPage /> },
            { path: "stats", element: <StatsPage /> },
            { path: "settings", element: <SettingsPage /> },
        ] },
        { path: "login", element: <p>로그인 화면</p> },
        { path: "terms", element: <TermsPage /> },
        { path: "privacy", element: <PrivacyPolicyPage /> },
    ], { initialEntries: [path] });
    const view = render(
        <SettingsProvider store={new MemorySettingsStore({ ...DEFAULT_SETTINGS, theme_mode: "light" })}>
            <AuthProvider><RecordProvider><RouterProvider router={router} /></RecordProvider></AuthProvider>
        </SettingsProvider>,
    );
    return { router, ...view };
}

async function fillRecord(delta = "100") {
    await waitFor(() => expect(screen.getByRole("button", { name: "승" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "승" }));
    fireEvent.change(screen.getByLabelText("상대 덱"), { target: { value: "상대 덱" } });
    fireEvent.change(screen.getByLabelText("점수 변동폭"), { target: { value: delta } });
}

beforeEach(() => {
    sdk.rpc.mockReset();
    sdk.getSession.mockResolvedValue({ data: { session: session() }, error: null });
    sdk.onAuthStateChange.mockImplementation((callback) => {
        authChanged = callback;
        return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    localStorage.clear();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    vi.stubGlobal("fetch", vi.fn(() => { throw new Error("실제 네트워크 사용 금지"); }));
    sdk.rpc.mockImplementation(async (name, args) => {
        if (name === "get_record_state") return ok(recordState());
        if (name === "list_game_history") return ok(page([game("previous")]));
        if (name === "get_game_statistics") return ok({ snapshot_version: 1, summary: summarizeGames([]), matchups: [], series: [] });
        return receipt(args.changes[0].id);
    });
});

afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

describe("MDL-210-06 실제 라우터와 로그인 수명", () => {
    it.each(["/terms", "/privacy"])("로그인 상태에서 공개 문서 %s를 거쳐도 미확인 요청을 유지한다", async (path) => {
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation(async (name, args) => name === "apply_game_changes" ? failed() : fallback(name, args));
        const { router } = mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(/저장 결과를 확인하지 못했습니다/);
        await act(() => router.navigate(path));
        expect(screen.queryByRole("button", { name: "같은 요청 다시 확인" })).not.toBeInTheDocument();
        await act(() => router.navigate("/"));
        expect(await screen.findByRole("button", { name: "같은 요청 다시 확인" })).toBeEnabled();
    });

    it("실제 BrowserRouter의 브라우저 뒤로·앞으로 이동에도 미확인 요청을 유지한다", async () => {
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation(async (name, args) => name === "apply_game_changes" ? failed() : fallback(name, args));
        window.history.replaceState(null, "", "/");
        render(<App />);
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(/저장 결과를 확인하지 못했습니다/);
        fireEvent.click(screen.getByRole("link", { name: "기록 목록" }));
        await screen.findByRole("heading", { name: "기록 목록" });
        act(() => window.history.back());
        await screen.findByRole("button", { name: "같은 요청 다시 확인" });
        act(() => window.history.forward());
        await screen.findByRole("heading", { name: "기록 목록" });
        act(() => window.history.back());
        fireEvent.click(await screen.findByRole("button", { name: "같은 요청 다시 확인" }));
        await waitFor(() => expect(writes()).toHaveLength(2));
        expect(writes()[1][1]).toEqual(writes()[0][1]);
    });

    it.each(["기록 목록", "통계", "설정"])("응답 유실 뒤 %s 링크를 왕복해도 최초 요청으로 확인한다", async (destination) => {
        let latest = game("previous");
        const receipts = new Map<string, string>();
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation(async (name, args) => {
            if (name === "get_record_state") return ok(recordState(latest));
            if (name !== "apply_game_changes") return fallback(name, args);
            const change = args.changes[0];
            const prior = receipts.get(change.request_id);
            if (prior) {
                expect(JSON.stringify(change)).toBe(prior);
                return receipt(change.id);
            }
            receipts.set(change.request_id, JSON.stringify(change));
            latest = game(change.id, { ...change.payload, change_version: 2 });
            return failed();
        });
        mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(/저장 결과를 확인하지 못했습니다/);
        fireEvent.click(screen.getByRole("link", { name: destination }));
        await screen.findByRole("heading", { name: destination });
        const unload = new Event("beforeunload", { cancelable: true });
        window.dispatchEvent(unload);
        expect(unload.defaultPrevented).toBe(true);
        fireEvent.click(screen.getByRole("link", { name: "기록" }));
        fireEvent.click(await screen.findByRole("button", { name: "같은 요청 다시 확인" }));
        await screen.findByText("기록을 저장했습니다.");
        expect(writes()).toHaveLength(2);
        expect(writes()[1][1]).toEqual(writes()[0][1]);
        expect(receipts.size).toBe(1);
        expect(latest.event_points_after).toBe(10100);
        expect(localStorage.length).toBe(1);
        expect(localStorage.key(0)).toBe("mdlogger.last_used_mode");
    });

    it("프로그램 이동과 뒤로·앞으로 이동에서도 재시도 입력을 재계산하지 않는다", async () => {
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation(async (name, args) => name === "apply_game_changes" ? failed() : fallback(name, args));
        const { router } = mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(/저장 결과를 확인하지 못했습니다/);
        await act(() => router.navigate("/history"));
        await act(() => router.navigate(-1));
        expect(await screen.findByRole("button", { name: "같은 요청 다시 확인" })).toBeEnabled();
        await act(() => router.navigate(1));
        await act(() => router.navigate("/"));
        fireEvent.click(await screen.findByRole("button", { name: "같은 요청 다시 확인" }));
        await waitFor(() => expect(writes()).toHaveLength(2));
        expect(writes()[1][1]).toEqual(writes()[0][1]);
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(100);
    });

    it.each([
        [true, true], [true, false], [false, true], [false, false],
    ])("전송 중 이동: 성공=%s, 완료 전에 복귀=%s", async (success, returnEarly) => {
        const pending = deferred<ReturnType<typeof ok>>();
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation((name, args) => name === "apply_game_changes" ? pending.promise : fallback(name, args));
        const { router } = mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        const id = writes()[0][1].changes[0].id;
        await act(() => router.navigate("/history"));
        if (returnEarly) {
            await act(() => router.navigate("/"));
            expect(await screen.findByRole("button", { name: "저장 중..." })).toBeDisabled();
            expect(screen.getByLabelText("점수 변동폭")).toBeDisabled();
        }
        await act(async () => { pending.resolve(success ? receipt(id) : failed()); });
        if (!returnEarly) await act(() => router.navigate("/"));
        if (success) {
            await screen.findByText("기록을 저장했습니다.");
            expect(screen.getByLabelText("점수 변동폭")).toHaveValue(null);
            expect(screen.getByRole("button", { name: "마지막 기록 취소" })).toBeEnabled();
        } else {
            expect(await screen.findByRole("button", { name: "같은 요청 다시 확인" })).toBeEnabled();
            expect(screen.getByLabelText("점수 변동폭")).toHaveValue(100);
        }
        expect(writes()).toHaveLength(1);
    });

    it.each(["account-b", "account-a"])("이전 세션 응답이 %s의 새 초안과 취소 대상에 적용되지 않는다", async (account) => {
        const pending = deferred<ReturnType<typeof ok>>();
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation((name, args) => name === "apply_game_changes" ? pending.promise : fallback(name, args));
        mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        const id = writes()[0][1].changes[0].id;
        act(() => {
            authChanged("SIGNED_OUT", null);
            authChanged("SIGNED_IN", session(account, "new-session"));
        });
        await fillRecord("250");
        await act(async () => { pending.resolve(receipt(id)); });
        expect(screen.queryByText("기록을 저장했습니다.")).not.toBeInTheDocument();
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(250);
        sdk.rpc.mockImplementation(fallback);
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText("기록을 저장했습니다.");
        expect(writes()[1][1].changes[0].id).not.toBe(id);
        expect(writes()[1][1].changes[0].payload.event_points_after).toBe(10250);
    });

    it("토큰 갱신은 미확인 요청을 폐기하지 않고 명시적 로그아웃은 폐기한다", async () => {
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation(async (name, args) => name === "apply_game_changes" ? failed() : fallback(name, args));
        const { router } = mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(/저장 결과를 확인하지 못했습니다/);
        act(() => authChanged("TOKEN_REFRESHED", session("account-a", "session-a", "rotated")));
        act(() => authChanged("SIGNED_IN", session("account-a", "session-a", "rotated")));
        expect(screen.getByRole("button", { name: "같은 요청 다시 확인" })).toBeEnabled();
        act(() => authChanged("SIGNED_OUT", null));
        await screen.findByText("로그인 화면");
        act(() => authChanged("SIGNED_IN", session("account-a", "new-session")));
        await act(() => router.navigate("/"));
        await screen.findByRole("button", { name: "저장" });
        expect(screen.queryByRole("button", { name: "같은 요청 다시 확인" })).not.toBeInTheDocument();
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(null);
    });

    it.each([true, false])("같은 계정의 새 세션에도 이전 응답 성공=%s와 초안을 적용하지 않는다", async (success) => {
        const pending = deferred<ReturnType<typeof ok>>();
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation((name, args) => name === "apply_game_changes" ? pending.promise : fallback(name, args));
        mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        const id = writes()[0][1].changes[0].id;
        act(() => authChanged("SIGNED_IN", session("account-a", "another-session")));
        await fillRecord("250");
        await act(async () => { pending.resolve(success ? receipt(id) : failed()); });
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(250);
        expect(screen.queryByText(/저장 결과를 확인하지 못했습니다|기록을 저장했습니다/)).not.toBeInTheDocument();
        expect(writes()).toHaveLength(1);
    });

    it.each([true, false])("화면 밖에서 확인한 저장은 후속 조회 실패=%s와 재진입 조회 실패에도 성공으로 남는다", async (postReadFails) => {
        let reads = 0;
        const pending = deferred<ReturnType<typeof ok>>();
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation((name, args) => {
            if (name === "get_record_state" && ++reads > 1 && (postReadFails || reads > 2)) return failed();
            return name === "apply_game_changes" ? pending.promise : fallback(name, args);
        });
        const { router } = mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        const id = writes()[0][1].changes[0].id;
        await act(() => router.navigate("/history"));
        await act(async () => { pending.resolve(receipt(id)); });
        await act(() => router.navigate("/"));
        await screen.findByText(/기록.*저장했습니다.*조회에 실패/);
        expect(screen.getByRole("button", { name: "저장" })).toBeDisabled();
        expect(screen.getByRole("button", { name: "마지막 기록 취소" })).toBeEnabled();
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(null);
        expect(writes()).toHaveLength(1);
    });

    it("인증 변경과 영수증이 같은 작업에서 도착해도 이전 요청의 후속 조회를 시작하지 않는다", async () => {
        const pending = deferred<ReturnType<typeof ok>>();
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation((name, args) => name === "apply_game_changes" ? pending.promise : fallback(name, args));
        const { router } = mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        const id = writes()[0][1].changes[0].id;
        await act(() => router.navigate("/settings"));
        await act(async () => {
            authChanged("SIGNED_IN", session("account-b", "another-session"));
            pending.resolve(receipt(id));
        });
        expect(sdk.rpc.mock.calls.filter(([name]) => name === "get_record_state")).toHaveLength(1);
        expect(localStorage.getItem("mdlogger.last_used_mode")).toBeNull();
    });

    it.each([true, false])("재확인 뒤 원격 삭제=%s 기록을 원래 payload로 되돌리거나 새 버전으로 취소하지 않는다", async (deleted) => {
        let saved: Game | null = null;
        let creates = 0;
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation((name, args) => {
            if (name === "get_record_state") return ok(recordState(saved && !deleted ? saved : game("previous")));
            if (name !== "apply_game_changes") return fallback(name, args);
            const change = args.changes[0];
            if (change.op === "delete") return ok({ results: [{ id: change.id, status: "conflict", current_change_version: 3 }] });
            if (++creates === 1) {
                saved = game(change.id, { ...change.payload, note: "다른 기기의 수정", change_version: 3, deleted_at: deleted ? "2026-10-25T11:00:00" : null });
                return failed();
            }
            return receipt(change.id);
        });
        const { router } = mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(/저장 결과를 확인하지 못했습니다/);
        await act(() => router.navigate("/history"));
        await act(() => router.navigate("/"));
        fireEvent.click(await screen.findByRole("button", { name: "같은 요청 다시 확인" }));
        await screen.findByText("기록을 저장했습니다.");
        await act(() => router.navigate("/stats"));
        await act(() => router.navigate("/"));
        fireEvent.click(await screen.findByRole("button", { name: "마지막 기록 취소" }));
        await screen.findByText("다른 기기에서 수정된 기록입니다.");
        expect(writes()[1][1]).toEqual(writes()[0][1]);
        expect(writes()[2][1].changes[0]).toMatchObject({ op: "delete", id: writes()[0][1].changes[0].id, expected_change_version: 2 });
        expect(saved).toMatchObject({ note: "다른 기기의 수정", change_version: 3 });
    });

    it("내용이 같은 정상 경기는 별도 ID로 저장하며 새 초안은 이전 완료로 지우지 않는다", async () => {
        const { router } = mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText("기록을 저장했습니다.");
        await fillRecord();
        await act(() => router.navigate("/stats"));
        await act(() => router.navigate("/"));
        expect(await screen.findByLabelText("점수 변동폭")).toHaveValue(100);
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await waitFor(() => expect(writes()).toHaveLength(2));
        expect(writes()[1][1].changes[0].id).not.toBe(writes()[0][1].changes[0].id);
        expect(writes()[1][1].changes[0].request_id).not.toBe(writes()[0][1].changes[0].request_id);
    });
});

describe("MDL-210-07 성공 영수증 이후 선택적 취향 저장", () => {
    it("저장·취소 성공 뒤 제출 상세 필드를 초기화하고 확인된 버전으로만 취소한다", async () => {
        mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "후공" }));
        fireEvent.change(screen.getByLabelText("소요 턴"), { target: { value: "5" } });
        fireEvent.change(screen.getByLabelText("메모 (선택)"), { target: { value: "제출할 메모" } });
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText("기록을 저장했습니다.");
        expect(screen.getByRole("button", { name: "선공" })).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByLabelText("소요 턴")).toHaveValue(1);
        expect(screen.getByLabelText("메모 (선택)")).toHaveValue("");
        expect(screen.getByLabelText("상대 덱")).toHaveValue("");
        await fillRecord("300");
        fireEvent.click(screen.getByRole("button", { name: "마지막 기록 취소" }));
        await screen.findByText("마지막 기록을 취소했습니다.");
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(null);
        expect(screen.getByRole("button", { name: "승" })).toHaveAttribute("aria-pressed", "false");
        expect(writes()[1][1].changes[0]).toMatchObject({ id: writes()[0][1].changes[0].id, op: "delete", expected_change_version: 2 });
    });

    it.each(["QuotaExceededError", "SecurityError", "Error"].flatMap((name) => [
        { name, readFails: false }, { name, readFails: true },
    ]))("$name, 후속 조회 실패=$readFails", async ({ name, readFails }) => {
        let reads = 0;
        const fallback = sdk.rpc.getMockImplementation()!;
        sdk.rpc.mockImplementation((method, args) => {
            if (method === "get_record_state" && ++reads > 1 && readFails) return failed();
            return fallback(method, args);
        });
        mount();
        await fillRecord();
        const setItem = Storage.prototype.setItem;
        vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
            if (key === "mdlogger.last_used_mode") throw name === "Error" ? new Error("쓰기 실패") : new DOMException("쓰기 실패", name);
            setItem.call(this, key, value);
        });
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText(readFails ? /기록은 저장했습니다.*조회에 실패/ : "기록을 저장했습니다.");
        expect(reads).toBe(2);
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(null);
        expect(writes()).toHaveLength(1);
        expect(screen.queryByRole("button", { name: "같은 요청 다시 확인" })).not.toBeInTheDocument();
        const id = writes()[0][1].changes[0].id;
        sdk.rpc.mockImplementation((method, args) => method === "apply_game_changes"
            ? ok({ results: [{ id: args.changes[0].id, status: "conflict", current_change_version: 3 }] })
            : fallback(method, args));
        fireEvent.click(screen.getByRole("button", { name: "마지막 기록 취소" }));
        await screen.findByText("다른 기기에서 수정된 기록입니다.");
        expect(writes()[1][1].changes[0]).toMatchObject({ op: "delete", id, expected_change_version: 2 });
        expect(screen.getByRole("button", { name: "마지막 기록 취소" })).toBeDisabled();
    });

    it("취향 읽기 실패는 정상 기록 조회와 생성을 막지 않는다", async () => {
        const getItem = Storage.prototype.getItem;
        vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, key) {
            if (key === "mdlogger.last_used_mode") throw new DOMException("읽기 실패", "SecurityError");
            return getItem.call(this, key);
        });
        mount();
        await fillRecord();
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText("기록을 저장했습니다.");
        expect(writes()).toHaveLength(1);
    });

    it("검증 오류와 서버 거절은 성공으로 숨기지 않고 재입력을 허용한다", async () => {
        mount();
        fireEvent.click(await screen.findByRole("button", { name: "저장" }));
        expect(writes()).toHaveLength(0);
        await fillRecord();
        sdk.rpc.mockResolvedValue({ data: null, error: { code: "22023", message: "서버 입력 거절" } });
        fireEvent.click(screen.getByRole("button", { name: "저장" }));
        await screen.findByText("서버 입력 거절");
        expect(screen.getByLabelText("점수 변동폭")).toHaveValue(100);
        expect(screen.getByRole("button", { name: "저장" })).toBeEnabled();
        expect(screen.queryByText("기록을 저장했습니다.")).not.toBeInTheDocument();
    });
});

describe("MDL-210-08 목록 세대와 메시지 소유권", () => {
    it.each([true, false])("수정 검증 오류를 이전 읽기 성공=%s로 덮어쓰지 않는다", async (success) => {
        const old = deferred<ReturnType<typeof ok>>();
        sdk.rpc.mockResolvedValueOnce(ok(page([game("row")])))
            .mockImplementationOnce(() => old.promise);
        mount("/history");
        fireEvent.click(await screen.findByRole("button", { name: "새로고침" }));
        fireEvent.click(screen.getAllByRole("button", { name: "수정" })[0]);
        fireEvent.change(screen.getByLabelText("상대 덱"), { target: { value: "" } });
        fireEvent.click(screen.getByRole("button", { name: "수정 저장" }));
        const validation = screen.getByRole("status").textContent;
        expect(validation).toBeTruthy();
        await act(async () => { old.resolve(success ? ok(page()) : failed()); });
        expect(screen.getByRole("status")).toHaveTextContent(validation!);
        expect(screen.getByRole("button", { name: "수정 저장" })).toBeEnabled();
        expect(writes()).toHaveLength(0);
    });

    it.each([true, false])("스냅숏 재조회 성공=%s의 늦은 응답은 새 필터의 오류와 로딩을 바꾸지 않는다", async (success) => {
        const old = deferred<ReturnType<typeof ok>>();
        const first = game("row");
        sdk.rpc.mockResolvedValueOnce(ok(page([first], { has_more: true, next_cursor: { id: first.id, played_at: first.played_at } })))
            .mockResolvedValueOnce(ok(page([], { stale: true })))
            .mockImplementationOnce(() => old.promise)
            .mockResolvedValueOnce(failed());
        mount("/history");
        fireEvent.click(await screen.findByRole("button", { name: "더 보기" }));
        await waitFor(() => expect(sdk.rpc).toHaveBeenCalledTimes(3));
        fireEvent.click(screen.getByRole("button", { name: "DC" }));
        await screen.findByText("기록 목록을 불러오지 못했습니다.");
        await act(async () => { old.resolve(success ? ok(page()) : failed()); });
        expect(screen.getByText("기록 목록을 불러오지 못했습니다.")).toBeInTheDocument();
        expect(screen.queryByText(/다른 기기의 변경이 있어|기록이 변경되었습니다/)).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "새로고침" })).toBeEnabled();
    });

    it.each([true, false])("이전 수동 조회 성공=%s 이후에도 최신 필터의 결과를 보존한다", async (oldSuccess) => {
        const old = deferred<ReturnType<typeof ok>>();
        sdk.rpc.mockResolvedValueOnce(ok(page([game("initial")])))
            .mockImplementationOnce(() => old.promise)
            .mockResolvedValueOnce(oldSuccess ? failed() : ok(page([game("latest", { opp_deck: "최신 필터 덱" })])));
        mount("/history");
        fireEvent.click(await screen.findByRole("button", { name: "새로고침" }));
        fireEvent.click(screen.getByRole("button", { name: "DC" }));
        if (oldSuccess) await screen.findByText("기록 목록을 불러오지 못했습니다.");
        else await screen.findAllByText(/최신 필터 덱/);
        await act(async () => { old.resolve(oldSuccess ? ok(page([game("old", { opp_deck: "이전 필터 덱" })])) : failed()); });
        if (oldSuccess) expect(screen.getByText("기록 목록을 불러오지 못했습니다.")).toBeInTheDocument();
        else {
            expect(screen.queryByText("기록 목록을 불러오지 못했습니다.")).not.toBeInTheDocument();
            expect(screen.getAllByText(/최신 필터 덱/)).toHaveLength(2);
        }
        expect(screen.queryByText(/이전 필터 덱/)).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "DC" })).toHaveAttribute("aria-pressed", "true");
    });

    it.each([true, false])("같은 필터로 돌아온 최신 조회가 진행 중이면 이전 finally 성공=%s를 무시한다", async (oldSuccess) => {
        const old = deferred<ReturnType<typeof ok>>();
        const latest = deferred<ReturnType<typeof ok>>();
        sdk.rpc.mockResolvedValueOnce(ok(page()))
            .mockImplementationOnce(() => old.promise)
            .mockResolvedValueOnce(ok(page()))
            .mockImplementationOnce(() => latest.promise);
        mount("/history");
        fireEvent.click(await screen.findByRole("button", { name: "새로고침" }));
        fireEvent.click(screen.getByRole("button", { name: "DC" }));
        await waitFor(() => expect(sdk.rpc).toHaveBeenCalledTimes(3));
        fireEvent.click(screen.getByRole("button", { name: "전체" }));
        await act(async () => { old.resolve(oldSuccess ? ok(page()) : failed()); });
        expect(screen.getByText("기록 목록을 불러오는 중...")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "새로고침" })).toBeDisabled();
        await act(async () => { latest.resolve(ok(page())); });
        expect(screen.getByText("기록이 없습니다.")).toBeInTheDocument();
        expect(screen.queryByText("기록 목록을 불러오는 중...")).not.toBeInTheDocument();
    });

    it.each([true, false])("이전 읽기 완료가 삭제 성공=%s 메시지를 지우지 않는다", async (success) => {
        const old = deferred<ReturnType<typeof ok>>();
        let reads = 0;
        sdk.rpc.mockImplementation((name, args) => {
            if (name === "list_game_history") return ++reads === 2 ? old.promise : ok(page([game("row")]));
            return success ? receipt(args.changes[0].id) : failed();
        });
        mount("/history");
        fireEvent.click(await screen.findByRole("button", { name: "새로고침" }));
        fireEvent.click(screen.getAllByRole("button", { name: "삭제" })[0]);
        const message = success ? "기록을 삭제했습니다." : "테스트 통신 실패";
        await screen.findByText(message);
        await act(async () => { old.resolve(ok(page([game("outdated", { opp_deck: "삭제 전 덱" })]))); });
        expect(screen.getByText(message)).toBeInTheDocument();
        expect(screen.queryByText(/삭제 전 덱/)).not.toBeInTheDocument();
        expect(screen.queryByText("기록 목록을 불러오는 중...")).not.toBeInTheDocument();
    });

    it.each(["navigation", "account"])("%s 이후 늦은 목록 오류와 finally가 새 화면에 반영되지 않는다", async (boundary) => {
        const old = deferred<ReturnType<typeof ok>>();
        sdk.rpc.mockResolvedValueOnce(ok(page()))
            .mockImplementationOnce(() => old.promise)
            .mockResolvedValue(ok(page([game("fresh", { opp_deck: "새 화면 덱" })])));
        const { router } = mount("/history");
        fireEvent.click(await screen.findByRole("button", { name: "새로고침" }));
        if (boundary === "account") act(() => authChanged("SIGNED_IN", session("account-b")));
        else {
            await act(() => router.navigate("/settings"));
            await act(() => router.navigate("/history"));
        }
        await screen.findAllByText(/새 화면 덱/);
        await act(async () => { old.reject(new Error("이전 목록 오류")); });
        expect(screen.getAllByText(/새 화면 덱/)).toHaveLength(2);
        expect(screen.queryByText(/기록 목록을 불러오지 못했습니다/)).not.toBeInTheDocument();
    });
});
