// 기록 화면 (기본 화면, spec §5.2, §7). 핵심 기록 흐름:
// 모드 선택 → 승/패 → 상세 입력 → 저장(낙관적 동시성) → 마지막 기록 취소.

import { useCallback, useEffect, useMemo, useState } from "react";
import { GameDetailForm } from "../components/record/GameDetailForm";
import "../components/record/record.css";
import { fetchDecks } from "../decks/deckCatalog";
import { createGame, deleteGame, listGames } from "../games/gameApi";
import { buildGamePayload, type GameFormState } from "../games/formModel";
import {
    getLastUsedModeId,
    resolveInitialModeId,
    setLastUsedModeId,
} from "../games/modeSelection";
import { listGameModes } from "../games/modes";
import { RANK_DIVISION_MIN, RANK_TIERS } from "../games/rank";
import type { Game, GameMode } from "../games/types";
import { useSettings } from "../settings/useSettings";

interface Message {
    kind: "error" | "success";
    text: string;
}

export function RecordPage() {
    const { settings } = useSettings();
    const [modes, setModes] = useState<GameMode[]>([]);
    const [decks, setDecks] = useState<string[]>([]);
    const [games, setGames] = useState<Game[]>([]);
    const [form, setForm] = useState<GameFormState>(() => emptyForm());
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<Message | null>(null);
    const [loading, setLoading] = useState(true);

    const refreshGames = useCallback(async () => {
        const rows = await listGames({ limit: 1000 });
        setGames(rows);
        return rows;
    }, []);

    useEffect(() => {
        let cancelled = false;
        Promise.all([listGameModes(), fetchDecks(), listGames({ limit: 1000 })])
            .then(([modeRows, deckRows, gameRows]) => {
                if (cancelled) {
                    return;
                }
                setModes(modeRows);
                setDecks(deckRows);
                setGames(gameRows);
                const initialId = resolveInitialModeId(
                    modeRows,
                    settings.default_mode,
                    getLastUsedModeId(),
                );
                const initialMode =
                    modeRows.find((mode) => mode.id === initialId) ?? null;
                setForm((current) =>
                    applyMode(current, initialMode, gameRows, settings, false),
                );
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
        };
    }, [settings]);

    const todayRecord = useMemo(() => {
        const today = localDateString(new Date());
        const wins = games.filter(
            (game) => game.result === "win" && game.played_at.startsWith(today),
        ).length;
        const losses = games.filter(
            (game) =>
                game.result === "lose" && game.played_at.startsWith(today),
        ).length;
        return { wins, losses };
    }, [games]);

    const lastGame = useMemo(() => games[0] ?? null, [games]);

    function selectMode(modeId: string) {
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
        setForm((current) => applyMode(current, mode, games, settings, false));
    }

    function selectResult(result: "win" | "lose") {
        setForm((current) => ({ ...current, result }));
    }

    async function handleSave() {
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
        setSaving(true);
        setMessage(null);
        try {
            await createGame(result.payload);
            if (form.mode) {
                setLastUsedModeId(form.mode.id);
            }
            setMessage({ kind: "success", text: "기록을 저장했습니다." });
            const rows = await refreshGames();
            setForm((current) =>
                applyMode(current, current.mode, rows, settings, true),
            );
        } catch (error) {
            setMessage({
                kind: "error",
                text:
                    error instanceof Error
                        ? error.message
                        : "기록 저장에 실패했습니다.",
            });
        } finally {
            setSaving(false);
        }
    }

    async function handleUndo() {
        if (!lastGame) {
            setMessage({ kind: "error", text: "취소할 기록이 없습니다." });
            return;
        }
        setSaving(true);
        setMessage(null);
        try {
            await deleteGame(lastGame.id, lastGame.change_version);
            setMessage({
                kind: "success",
                text: "마지막 기록을 취소했습니다.",
            });
            const rows = await refreshGames();
            setForm((current) =>
                applyMode(current, current.mode, rows, settings, true),
            );
        } catch (error) {
            setMessage({
                kind: "error",
                text:
                    error instanceof Error
                        ? error.message
                        : "마지막 기록 취소에 실패했습니다.",
            });
        } finally {
            setSaving(false);
        }
    }

    const dirty = useMemo(
        () =>
            form.result !== null ||
            form.myDeck !== "" ||
            form.oppDeck !== "" ||
            form.scoreDelta !== "" ||
            form.scoreAfter !== "" ||
            form.ratingDelta !== "" ||
            form.ratingAfter !== "" ||
            form.ratingBeforeInput !== "" ||
            form.note !== "",
        [form],
    );

    useEffect(() => {
        if (!dirty) {
            return;
        }
        const handler = (event: BeforeUnloadEvent) => {
            event.preventDefault();
        };
        window.addEventListener("beforeunload", handler);
        return () => window.removeEventListener("beforeunload", handler);
    }, [dirty]);

    if (loading) {
        return <p className="auth-loading">기록 화면을 불러오는 중...</p>;
    }

    return (
        <section aria-labelledby="record-title" className="record-page">
            <h1 id="record-title" className="page-title">
                기록
            </h1>
            <p className="record-today">
                오늘 전적 {todayRecord.wins}승 {todayRecord.losses}패
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
                    onClick={() => selectResult("win")}
                >
                    승
                </button>
                <button
                    type="button"
                    className={resultButtonClass("lose", form.result)}
                    aria-pressed={form.result === "lose"}
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

            <GameDetailForm
                state={form}
                decks={decks}
                onChange={(patch) =>
                    setForm((current) => ({ ...current, ...patch }))
                }
            />

            <div className="record-actions">
                <button
                    type="button"
                    className="primary-button"
                    onClick={handleSave}
                    disabled={saving}
                >
                    {saving ? "저장 중..." : "저장"}
                </button>
                <button
                    type="button"
                    className="undo-button"
                    onClick={handleUndo}
                    disabled={saving || !lastGame}
                >
                    마지막 기록 취소
                </button>
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
    games: Game[],
    settings: {
        memo_enabled: boolean;
        score_input_mode: GameFormState["scoreInputMode"];
    },
    fullReset: boolean,
): GameFormState {
    const lastMyDeck = games.find((game) => game.my_deck)?.my_deck ?? "";
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
