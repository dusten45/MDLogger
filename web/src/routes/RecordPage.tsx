// 기록 화면 (기본 화면, spec §5.2, §7). 핵심 기록 흐름:
// 모드 선택 → 승/패 → 상세 입력 → 저장(낙관적 동시성) → 마지막 기록 취소.

import { useEffect, useMemo, useRef, useState } from "react";
import { GameDetailForm } from "../components/record/GameDetailForm";
import "../components/record/record.css";
import { fetchDecks } from "../decks/deckCatalog";
import {
    createGame, deleteGame, getRecordState, prepareCreate, GameConflictError,
    GameMutationRejectedError, type CreateAttempt, type CreateResult, type RecordState
} from "../games/gameApi";
import { buildGamePayload, type GameFormState } from "../games/formModel";
import {
    getLastUsedModeId,
    resolveInitialModeId,
    setLastUsedModeId,
} from "../games/modeSelection";
import { listGameModes } from "../games/modes";
import { RANK_DIVISION_MIN, RANK_TIERS } from "../games/rank";
import type { GameMode } from "../games/types";
import { useSettings } from "../settings/useSettings";

interface Message {
    kind: "error" | "success";
    text: string;
}

export function RecordPage() {
    const { settings } = useSettings();
    const [modes, setModes] = useState<GameMode[]>([]);
    const [decks, setDecks] = useState<string[]>([]);
    const [record, setRecord] = useState<RecordState | null>(null);
    const [lastGame, setLastGame] = useState<CreateResult | null>(null);
    const [ready, setReady] = useState(false);
    const [attempt, setAttempt] = useState<CreateAttempt | null>(null);
    const pending = useRef<CreateAttempt | null>(null);
    const active = useRef(true);
    const reading = useRef(0);
    const submitting = useRef(false);
    const settingsRef = useRef(settings);
    settingsRef.current = settings;
    const [form, setForm] = useState<GameFormState>(() => emptyForm());
    const [baseline, setBaseline] = useState<GameFormState>(() => emptyForm());
    // 비동기 저장/취소 후에도 최신 폼을 참조하기 위한 ref (dirty 기준 동기화).
    const formRef = useRef(form);
    formRef.current = form;
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<Message | null>(null);
    const [loading, setLoading] = useState(true);
    const [initialReload, setInitialReload] = useState(0);

    async function refreshRecord(reset: boolean, replaceUndo = false) {
        const generation = ++reading.current;
        let state: RecordState;
        try {
            state = await getRecordState(localDateString(new Date()));
        } catch (error) {
            if (!active.current || generation !== reading.current) return false;
            throw error;
        }
        if (!active.current || generation !== reading.current) return false;
        setRecord(state);
        setReady(true);
        if (replaceUndo) setLastGame(state.last_game);
        const next = applyMode(formRef.current, formRef.current.mode, state, settingsRef.current, reset);
        setForm(next);
        setBaseline(next);
        return true;
    }

    useEffect(() => {
        let cancelled = false;
        active.current = true;
        Promise.all([
            listGameModes(),
            fetchDecks().catch(() => ["기타"]),
            getRecordState(localDateString(new Date())),
        ])
            .then(([modeRows, deckRows, state]) => {
                if (cancelled) {
                    return;
                }
                setModes(modeRows);
                setDecks(deckRows);
                setMessage(null);
                setRecord(state);
                setLastGame(state.last_game);
                setReady(true);
                const initialId = resolveInitialModeId(
                    modeRows,
                    settingsRef.current.default_mode,
                    getLastUsedModeId(),
                );
                const initialMode =
                    modeRows.find((mode) => mode.id === initialId) ?? null;
                const next = applyMode(
                    formRef.current,
                    initialMode,
                    state,
                    settingsRef.current,
                    false,
                );
                setForm(next);
                setBaseline(next);
            })
            .catch(() => {
                if (!cancelled) {
                    setMessage({
                        kind: "error",
                        text: "기록 화면을 불러오지 못했습니다.",
                    });
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false);
                }
            });
        return () => {
            cancelled = true;
            active.current = false;
            reading.current += 1;
        };
    }, [initialReload]);

    function selectMode(modeId: string) {
        if (!record || pending.current || submitting.current || !ready) return;
        if (modeId === form.mode?.id) {
            return;
        }
        // 모드별 입력(점수/레이팅 변동폭·직접값)이 있으면 확인 후 전환한다
        // (로드맵 §5.1: 상세 입력 중에는 확인 없이 모드가 바뀌지 않게 한다).
        if (hasTypedStanding(form)) {
            if (
                !window.confirm(
                    "모드를 바꾸면 입력한 점수/레이팅 값이 초기화됩니다. 계속할까요?",
                )
            ) {
                return;
            }
        }
        const mode = modes.find((candidate) => candidate.id === modeId) ?? null;
        const next = applyMode(form, mode, record, settings, false);
        setForm(next);
        setBaseline(next);
    }

    function selectResult(result: "win" | "lose") {
        setForm((current) => ({ ...current, result }));
    }

    async function handleSave() {
        if (submitting.current || (!ready && !pending.current)) return;
        if (!pending.current) {
            const result = buildGamePayload({
                ...form,
                playedAt: localNaiveIso(new Date()),
                timezoneOffsetMinutes: -new Date().getTimezoneOffset(),
            });
            if (result.error || !result.payload) {
                setMessage({
                    kind: "error",
                    text: result.error ?? "입력을 확인하세요.",
                });
                return;
            }
            pending.current = prepareCreate(result.payload);
            setAttempt(pending.current);
        }
        submitting.current = true;
        reading.current += 1;
        setSaving(true);
        setMessage(null);
        try {
            const saved = await createGame(pending.current);
            if (!active.current) return;
            pending.current = null;
            setAttempt(null);
            setLastGame(saved);
            setReady(false);
            if (form.mode) {
                setLastUsedModeId(form.mode.id);
            }
            setMessage({ kind: "success", text: "기록을 저장했습니다." });
            // 성공한 입력은 즉시 비운다. 후속 읽기는 생성 재시도의 원인이 될 수 없다.
            const next = { ...emptyForm(), mode: formRef.current.mode };
            setForm(next);
            setBaseline(next);
            try {
                await refreshRecord(true);
            } catch {
                if (active.current) setMessage({ kind: "success", text: "기록은 저장했습니다. 최신 상태 조회에 실패했습니다. 새로고침 후 다음 기록을 입력하세요." });
            }
        } catch (error) {
            if (!active.current) return;
            if (error instanceof GameConflictError || error instanceof GameMutationRejectedError) {
                pending.current = null;
                setAttempt(null);
            }
            setMessage({
                kind: "error",
                text: pending.current
                    ? "저장 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인하세요. 확인 전 페이지를 닫지 마세요."
                    : error instanceof Error
                        ? error.message
                        : "기록 저장에 실패했습니다.",
            });
        } finally {
            submitting.current = false;
            if (active.current) setSaving(false);
        }
    }

    async function handleUndo() {
        if (submitting.current || pending.current) return;
        if (!lastGame) {
            setMessage({ kind: "error", text: "취소할 기록이 없습니다." });
            return;
        }
        submitting.current = true;
        reading.current += 1;
        setSaving(true);
        setMessage(null);
        try {
            await deleteGame(lastGame.id, lastGame.change_version);
            if (!active.current) return;
            setLastGame(null);
            setReady(false);
            setMessage({
                kind: "success",
                text: "마지막 기록을 취소했습니다.",
            });
            try {
                await refreshRecord(true, true);
            } catch {
                if (active.current) setMessage({ kind: "success", text: "기록은 취소했습니다. 최신 상태를 새로고침하세요." });
            }
        } catch (error) {
            if (!active.current) return;
            setReady(false);
            setLastGame(null);
            setMessage({
                kind: "error",
                text:
                    error instanceof Error
                        ? error.message
                        : "마지막 기록 취소에 실패했습니다.",
            });
        } finally {
            submitting.current = false;
            if (active.current) setSaving(false);
        }
    }

    const dirty = useMemo(() => !sameInput(form, baseline), [form, baseline]);

    useEffect(() => {
        if (!dirty && !attempt) {
            return;
        }
        const handler = (event: BeforeUnloadEvent) => {
            event.preventDefault();
        };
        window.addEventListener("beforeunload", handler);
        return () => window.removeEventListener("beforeunload", handler);
    }, [dirty, attempt]);

    if (loading) {
        return <p className="auth-loading">기록 화면을 불러오는 중...</p>;
    }

    return (
        <section aria-labelledby="record-title" className="record-page">
            <h1 id="record-title" className="page-title">
                기록
            </h1>
            <p className="record-today">
                {record ? `오늘 전적 ${record.today.wins}승 ${record.today.losses}패` : "오늘 전적을 확인하지 못했습니다."}
            </p>

            <div className="mode-chips" role="group" aria-label="경기 모드">
                {modes.map((mode) => (
                    <button
                        key={mode.id}
                        type="button"
                        className={
                            form.mode?.id === mode.id
                                ? "mode-chip mode-chip--active"
                                : "mode-chip"
                        }
                        aria-pressed={form.mode?.id === mode.id}
                        disabled={saving || !!attempt || !ready}
                        onClick={() => selectMode(mode.id)}
                    >
                        {mode.display_name}
                    </button>
                ))}
            </div>

            <p className="result-prompt">이번 듀얼의 결과를 기록하세요</p>
            <div className="result-buttons" role="group" aria-label="승/패">
                <button
                    type="button"
                    className={resultButtonClass("win", form.result)}
                    aria-pressed={form.result === "win"}
                    disabled={saving || !!attempt || !ready}
                    onClick={() => selectResult("win")}
                >
                    승
                </button>
                <button
                    type="button"
                    className={resultButtonClass("lose", form.result)}
                    aria-pressed={form.result === "lose"}
                    disabled={saving || !!attempt || !ready}
                    onClick={() => selectResult("lose")}
                >
                    패
                </button>
            </div>

            {message ? (
                <p
                    className={
                        message.kind === "error"
                            ? "form-message form-message--error"
                            : "form-message form-message--success"
                    }
                    role="status"
                >
                    {message.text}
                </p>
            ) : null}

            <fieldset disabled={saving || !!attempt || !ready} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
                <GameDetailForm
                    state={form}
                    decks={decks}
                    onChange={(patch) =>
                        setForm((current) => ({ ...current, ...patch }))
                    }
                />
            </fieldset>

            <div className="record-actions">
                <button
                    type="button"
                    className="primary-button"
                    onClick={handleSave}
                    disabled={saving || (!ready && !attempt)}
                >
                    {saving ? "저장 중..." : attempt ? "같은 요청 다시 확인" : "저장"}
                </button>
                <button
                    type="button"
                    className="undo-button"
                    onClick={handleUndo}
                    disabled={saving || !!attempt || !lastGame}
                >
                    마지막 기록 취소
                </button>
                <button type="button" disabled={saving || !!attempt} onClick={async () => {
                    if (dirty && !window.confirm("최신 기준값을 불러오면 상태 입력이 초기화됩니다. 계속할까요?")) return;
                    if (modes.length === 0) {
                        setLoading(true);
                        setInitialReload((value) => value + 1);
                        return;
                    }
                    setReady(false);
                    try {
                        if (await refreshRecord(false, lastGame === null)) setMessage(null);
                    } catch {
                        if (active.current) setMessage({ kind: "error", text: "최신 상태를 불러오지 못했습니다. 다시 시도하세요." });
                    }
                }}>새로고침</button>
            </div>
        </section>
    );
}

function resultButtonClass(
    value: "win" | "lose",
    selected: "win" | "lose" | null,
): string {
    if (selected === null) {
        return value === "win"
            ? "result-button result-button--win"
            : "result-button result-button--lose";
    }
    if (selected === "win") {
        return value === "win"
            ? "result-button result-button--selected-win"
            : "result-button result-button--lose";
    }
    return value === "lose"
        ? "result-button result-button--selected-lose"
        : "result-button result-button--win";
}

function emptyForm(): GameFormState {
    return {
        mode: null,
        result: null,
        turnOrder: "first",
        myDeck: "",
        oppDeck: "",
        turns: 1,
        endReason: "regular",
        note: "",
        memoEnabled: true,
        scoreInputMode: "delta",
        editing: false,
        scoreBase: 0,
        scoreBeforeInput: "",
        scoreDelta: "",
        scoreAfter: "",
        ratingBase: null,
        ratingBeforeInput: "",
        ratingDelta: "",
        ratingAfter: "",
        rankBefore: null,
        rankAfter: null,
        playedAt: "",
        timezoneOffsetMinutes: null,
    };
}

function applyMode(
    current: GameFormState,
    mode: GameMode | null,
    record: RecordState,
    settings: {
        memo_enabled: boolean;
        score_input_mode: GameFormState["scoreInputMode"];
    },
    fullReset: boolean,
): GameFormState {
    const games = record.latest_by_mode;
    const lastMyDeck = record.last_my_deck ?? "";
    const base: GameFormState = {
        ...current,
        mode,
        memoEnabled: settings.memo_enabled,
        scoreInputMode: settings.score_input_mode,
        myDeck: fullReset ? lastMyDeck : current.myDeck || lastMyDeck,
        result: fullReset ? null : current.result,
        turnOrder: fullReset ? "first" : current.turnOrder,
        oppDeck: fullReset ? "" : current.oppDeck,
        turns: fullReset ? 1 : current.turns,
        endReason: fullReset ? "regular" : current.endReason,
        note: fullReset ? "" : current.note,
        editing: false,
        scoreBase: 0,
        scoreBeforeInput: "",
        scoreDelta: "",
        scoreAfter: "",
        ratingBase: null,
        ratingBeforeInput: "",
        ratingDelta: "",
        ratingAfter: "",
        rankBefore: null,
        rankAfter: null,
    };
    if (mode === null) {
        return base;
    }
    const context = mode.play_context_id;
    if (mode.standing_kind === "event_points") {
        const last = games.find(
            (game) =>
                game.play_context_id === context &&
                game.standing_kind === "event_points" &&
                game.event_points_after !== null,
        );
        base.scoreBase = last?.event_points_after ?? 0;
    } else if (mode.standing_kind === "rating") {
        const last = games.find(
            (game) =>
                game.play_context_id === context &&
                game.standing_kind === "rating" &&
                game.rating_after !== null,
        );
        base.ratingBase = last?.rating_after ?? null;
    } else {
        const last = games.find(
            (game) =>
                game.play_context_id === context &&
                game.standing_kind === "rank" &&
                game.rank_tier_after !== null &&
                game.rank_division_after !== null,
        );
        if (last) {
            const before = {
                tier: last.rank_tier_after as string,
                division: last.rank_division_after as number,
            };
            base.rankBefore = before;
            base.rankAfter = before;
        } else {
            const fallback = {
                tier: RANK_TIERS[0].value,
                division: RANK_DIVISION_MIN,
            };
            base.rankBefore = fallback;
            base.rankAfter = fallback;
        }
    }
    return base;
}

function localNaiveIso(date: Date): string {
    const pad = (value: number) => String(value).padStart(2, "0");
    return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
        `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    );
}

function localDateString(date: Date): string {
    const pad = (value: number) => String(value).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 사용자 입력 필드가 기준(마지막 저장/리셋 상태)과 같은지 비교한다. */
function sameInput(a: GameFormState, b: GameFormState): boolean {
    return (
        a.mode?.id === b.mode?.id &&
        a.result === b.result &&
        a.turnOrder === b.turnOrder &&
        a.myDeck === b.myDeck &&
        a.oppDeck === b.oppDeck &&
        a.turns === b.turns &&
        a.endReason === b.endReason &&
        a.note === b.note &&
        a.scoreBeforeInput === b.scoreBeforeInput &&
        a.scoreDelta === b.scoreDelta &&
        a.scoreAfter === b.scoreAfter &&
        a.ratingBeforeInput === b.ratingBeforeInput &&
        a.ratingDelta === b.ratingDelta &&
        a.ratingAfter === b.ratingAfter &&
        a.rankBefore?.tier === b.rankBefore?.tier &&
        a.rankBefore?.division === b.rankBefore?.division &&
        a.rankAfter?.tier === b.rankAfter?.tier &&
        a.rankAfter?.division === b.rankAfter?.division
    );
}

/** 모드 전환 시 사라지는 타이핑 입력(점수/레이팅)이 있는지 확인한다. */
function hasTypedStanding(form: GameFormState): boolean {
    return (
        form.scoreDelta !== "" ||
        form.scoreAfter !== "" ||
        form.ratingDelta !== "" ||
        form.ratingAfter !== "" ||
        form.ratingBeforeInput !== ""
    );
}
