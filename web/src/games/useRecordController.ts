import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/useAuth";
import { fetchDecks } from "../decks/deckCatalog";
import { useSettings } from "../settings/useSettings";
import {
    createGame, deleteGame, getRecordState, prepareCreate, GameConflictError,
    GameMutationRejectedError, type CreateAttempt, type CreateResult, type RecordState,
} from "./gameApi";
import { buildGamePayload, type GameFormState } from "./formModel";
import { getLastUsedModeId, resolveInitialModeId, setLastUsedModeId } from "./modeSelection";
import { listGameModes } from "./modes";
import { RANK_DIVISION_MIN, RANK_TIERS } from "./rank";
import type { GameMode } from "./types";

interface Message {
    kind: "error" | "success";
    text: string;
}

export function useRecordController() {
    const { isSessionCurrent } = useAuth();
    const { settings } = useSettings();
    const [modes, setModes] = useState<GameMode[]>([]);
    const [decks, setDecks] = useState<string[]>([]);
    const [record, setRecord] = useState<RecordState | null>(null);
    const [lastGame, setLastGame] = useState<CreateResult | null>(null);
    const [ready, setReady] = useState(false);
    const [attempt, setAttempt] = useState<CreateAttempt | null>(null);
    const pending = useRef<CreateAttempt | null>(null);
    const active = useRef(true);
    const isActive = useCallback(() => active.current && isSessionCurrent(), [isSessionCurrent]);
    const reading = useRef(0);
    const submitting = useRef(false);
    const loaded = useRef(false);
    const settingsRef = useRef(settings);
    settingsRef.current = settings;
    const [form, setForm] = useState<GameFormState>(emptyForm);
    const [baseline, setBaseline] = useState<GameFormState>(emptyForm);
    const formRef = useRef(form);
    formRef.current = form;
    const baselineRef = useRef(baseline);
    baselineRef.current = baseline;
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<Message | null>(null);
    const confirmation = useRef<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [visits, setVisits] = useState(0);
    const open = useCallback(() => setVisits((value) => value + 1), []);

    useEffect(() => {
        active.current = true;
        return () => { active.current = false; reading.current += 1; };
    }, []);

    async function refreshRecord(reset: boolean, replaceUndo = false) {
        const generation = ++reading.current;
        let state: RecordState;
        try {
            state = await getRecordState(localDateString(new Date()));
        } catch (error) {
            if (!isActive() || generation !== reading.current) return false;
            throw error;
        }
        if (!isActive() || generation !== reading.current) return false;
        setRecord(state);
        setReady(true);
        if (replaceUndo) setLastGame(state.last_game);
        const next = applyMode(formRef.current, formRef.current.mode, state, settingsRef.current, reset);
        setForm(next);
        setBaseline(next);
        return true;
    }

    useEffect(() => {
        // 첫 방문 때만 시작한다. 재방문은 미확인 요청이나 새 초안의 입력을 덮어쓰지 않는다.
        if (!isActive() || visits === 0 || pending.current || submitting.current
            || (loaded.current && !sameInput(formRef.current, baselineRef.current))) return;
        let cancelled = false;
        const generation = ++reading.current;
        setLoading(true);
        setReady(false);
        Promise.all([
            listGameModes(),
            fetchDecks().catch(() => ["기타"]),
            getRecordState(localDateString(new Date())),
        ])
            .then(([modeRows, deckRows, state]) => {
                if (!isActive() || cancelled || generation !== reading.current) return;
                setModes(modeRows);
                setDecks(deckRows);
                setMessage(confirmation.current ? { kind: "success", text: confirmation.current } : null);
                loaded.current = true;
                setRecord(state);
                // 확인한 영수증의 버전은 이후 다른 기기의 수정이나 삭제로 교체하지 않는다.
                setLastGame((previous) => previous ?? state.last_game);
                setReady(true);
                const initialId = resolveInitialModeId(modeRows, settingsRef.current.default_mode, getLastUsedModeId());
                const mode = modeRows.find((row) => row.id === initialId) ?? null;
                const next = applyMode(formRef.current, mode, state, settingsRef.current, false);
                setForm(next);
                setBaseline(next);
            })
            .catch(() => {
                if (isActive() && !cancelled && generation === reading.current) {
                    setMessage(confirmation.current
                        ? { kind: "success", text: `${confirmation.current} 최신 상태 조회에 실패했습니다. 새로고침 후 다음 기록을 입력하세요.` }
                        : { kind: "error", text: "기록 화면을 불러오지 못했습니다." });
                }
            })
            .finally(() => {
                if (isActive() && !cancelled && generation === reading.current) setLoading(false);
            });
        return () => { cancelled = true; };
    }, [visits, isActive]);

    function selectMode(modeId: string) {
        if (!record || pending.current || submitting.current || !ready || modeId === form.mode?.id) return;
        if (hasTypedStanding(form) && !window.confirm("모드를 바꾸면 입력한 점수/레이팅 값이 초기화됩니다. 계속할까요?")) return;
        const mode = modes.find((candidate) => candidate.id === modeId) ?? null;
        const next = applyMode(form, mode, record, settings, false);
        setForm(next);
        setBaseline(next);
    }

    async function handleSave() {
        if (!isActive() || submitting.current || (!ready && !pending.current)) return;
        confirmation.current = null;
        if (!pending.current) {
            const result = buildGamePayload({
                ...form,
                playedAt: localNaiveIso(new Date()),
                timezoneOffsetMinutes: -new Date().getTimezoneOffset(),
            });
            if (result.error || !result.payload) {
                setMessage({ kind: "error", text: result.error ?? "입력을 확인하세요." });
                return;
            }
            pending.current = prepareCreate(result.payload);
            setAttempt(pending.current);
        }
        const submitted = pending.current;
        submitting.current = true;
        reading.current += 1;
        setSaving(true);
        setMessage(null);
        try {
            let saved: CreateResult;
            try {
                saved = await createGame(submitted);
            } catch (error) {
                if (!isActive() || pending.current !== submitted) return;
                if (error instanceof GameConflictError || error instanceof GameMutationRejectedError) {
                    pending.current = null;
                    setAttempt(null);
                }
                setMessage({
                    kind: "error",
                    text: pending.current
                        ? "저장 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인하세요. 확인 전 페이지를 닫지 마세요."
                        : error instanceof Error ? error.message : "기록 저장에 실패했습니다.",
                });
                return;
            }
            if (!isActive() || pending.current !== submitted) return;
            pending.current = null;
            setAttempt(null);
            setLastGame(saved);
            setReady(false);
            confirmation.current = "기록을 저장했습니다.";
            setMessage({ kind: "success", text: confirmation.current });
            // 영수증 이후에는 생성 실패로 돌아가지 않는다. 제출 중에는 입력을 잠근다.
            const next = { ...emptyForm(), mode: formRef.current.mode };
            setForm(next);
            setBaseline(next);
            if (form.mode) setLastUsedModeId(form.mode.id);
            try {
                await refreshRecord(true);
            } catch {
                if (isActive()) setMessage({ kind: "success", text: "기록은 저장했습니다. 최신 상태 조회에 실패했습니다. 새로고침 후 다음 기록을 입력하세요." });
            }
        } finally {
            submitting.current = false;
            if (isActive()) setSaving(false);
        }
    }

    async function handleUndo() {
        if (!isActive() || submitting.current || pending.current) return;
        if (!lastGame) {
            setMessage({ kind: "error", text: "취소할 기록이 없습니다." });
            return;
        }
        confirmation.current = null;
        submitting.current = true;
        reading.current += 1;
        setSaving(true);
        setMessage(null);
        try {
            await deleteGame(lastGame.id, lastGame.change_version);
            if (!isActive()) return;
            setLastGame(null);
            setReady(false);
            confirmation.current = "마지막 기록을 취소했습니다.";
            setMessage({ kind: "success", text: confirmation.current });
            try {
                await refreshRecord(true, true);
            } catch {
                if (isActive()) setMessage({ kind: "success", text: "기록은 취소했습니다. 최신 상태를 새로고침하세요." });
            }
        } catch (error) {
            if (!isActive()) return;
            setReady(false);
            setLastGame(null);
            setMessage({ kind: "error", text: error instanceof Error ? error.message : "마지막 기록 취소에 실패했습니다." });
        } finally {
            submitting.current = false;
            if (isActive()) setSaving(false);
        }
    }

    const dirty = !sameInput(form, baseline);
    useEffect(() => {
        if (!dirty && !attempt) return;
        const handler = (event: BeforeUnloadEvent) => { event.preventDefault(); };
        window.addEventListener("beforeunload", handler);
        return () => window.removeEventListener("beforeunload", handler);
    }, [dirty, attempt]);

    async function handleRefresh() {
        if (!isActive() || submitting.current || pending.current) return;
        if (dirty && !window.confirm("최신 기준값을 불러오면 상태 입력이 초기화됩니다. 계속할까요?")) return;
        if (modes.length === 0) { open(); return; }
        setReady(false);
        try {
            if (await refreshRecord(false, lastGame === null)) {
                confirmation.current = null;
                setMessage(null);
            }
        } catch {
            if (isActive()) setMessage({ kind: "error", text: "최신 상태를 불러오지 못했습니다. 다시 시도하세요." });
        }
    }

    return {
        modes, decks, record, lastGame, ready, attempt, form, setForm,
        saving, message, loading, open, selectMode, handleSave, handleUndo, handleRefresh,
    };
}

function emptyForm(): GameFormState {
    return {
        mode: null, result: null, turnOrder: "first", myDeck: "", oppDeck: "", turns: 1,
        endReason: "regular", note: "", memoEnabled: true, scoreInputMode: "delta", editing: false,
        scoreBase: 0, scoreBeforeInput: "", scoreDelta: "", scoreAfter: "",
        ratingBase: null, ratingBeforeInput: "", ratingDelta: "", ratingAfter: "",
        rankBefore: null, rankAfter: null, playedAt: "", timezoneOffsetMinutes: null,
    };
}

function applyMode(
    current: GameFormState,
    mode: GameMode | null,
    record: RecordState,
    settings: { memo_enabled: boolean; score_input_mode: GameFormState["scoreInputMode"] },
    fullReset: boolean,
): GameFormState {
    const games = record.latest_by_mode;
    const lastMyDeck = record.last_my_deck ?? "";
    const base: GameFormState = {
        ...current, mode, memoEnabled: settings.memo_enabled, scoreInputMode: settings.score_input_mode,
        myDeck: fullReset ? lastMyDeck : current.myDeck || lastMyDeck,
        result: fullReset ? null : current.result,
        turnOrder: fullReset ? "first" : current.turnOrder,
        oppDeck: fullReset ? "" : current.oppDeck,
        turns: fullReset ? 1 : current.turns,
        endReason: fullReset ? "regular" : current.endReason,
        note: fullReset ? "" : current.note,
        editing: false, scoreBase: 0, scoreBeforeInput: "", scoreDelta: "", scoreAfter: "",
        ratingBase: null, ratingBeforeInput: "", ratingDelta: "", ratingAfter: "", rankBefore: null, rankAfter: null,
    };
    if (mode === null) return base;
    const context = mode.play_context_id;
    if (mode.standing_kind === "event_points") {
        const last = games.find((game) => game.play_context_id === context
            && game.standing_kind === "event_points" && game.event_points_after !== null);
        base.scoreBase = last?.event_points_after ?? 0;
    } else if (mode.standing_kind === "rating") {
        const last = games.find((game) => game.play_context_id === context
            && game.standing_kind === "rating" && game.rating_after !== null);
        base.ratingBase = last?.rating_after ?? null;
    } else {
        const last = games.find((game) => game.play_context_id === context && game.standing_kind === "rank"
            && game.rank_tier_after !== null && game.rank_division_after !== null);
        const before = last
            ? { tier: last.rank_tier_after as string, division: last.rank_division_after as number }
            : { tier: RANK_TIERS[0].value, division: RANK_DIVISION_MIN };
        base.rankBefore = before;
        base.rankAfter = before;
    }
    return base;
}

function localNaiveIso(date: Date): string {
    const pad = (value: number) => String(value).padStart(2, "0");
    return `${localDateString(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function localDateString(date: Date): string {
    const pad = (value: number) => String(value).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 사용자 입력 필드가 기준(마지막 저장/리셋 상태)과 같은지 비교한다. */
function sameInput(a: GameFormState, b: GameFormState): boolean {
    return a.mode?.id === b.mode?.id && a.result === b.result && a.turnOrder === b.turnOrder
        && a.myDeck === b.myDeck && a.oppDeck === b.oppDeck && a.turns === b.turns
        && a.endReason === b.endReason && a.note === b.note
        && a.scoreBeforeInput === b.scoreBeforeInput && a.scoreDelta === b.scoreDelta && a.scoreAfter === b.scoreAfter
        && a.ratingBeforeInput === b.ratingBeforeInput && a.ratingDelta === b.ratingDelta && a.ratingAfter === b.ratingAfter
        && a.rankBefore?.tier === b.rankBefore?.tier && a.rankBefore?.division === b.rankBefore?.division
        && a.rankAfter?.tier === b.rankAfter?.tier && a.rankAfter?.division === b.rankAfter?.division;
}

/** 모드 전환 시 사라지는 타이핑 입력(점수/레이팅)이 있는지 확인한다. */
function hasTypedStanding(form: GameFormState): boolean {
    return form.scoreDelta !== "" || form.scoreAfter !== "" || form.ratingDelta !== ""
        || form.ratingAfter !== "" || form.ratingBeforeInput !== "";
}
