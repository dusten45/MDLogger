// 기록 목록 화면 (spec §8.1). 전체/모드 필터, 수정·삭제(낙관적 동시성).

import { useCallback, useEffect, useMemo, useState } from "react";
import { GameDetailForm } from "../components/record/GameDetailForm";
import { fetchDecks } from "../decks/deckCatalog";
import {
    deleteGame,
    GameConflictError,
    listGames,
    updateGame,
} from "../games/gameApi";
import {
    buildGamePayload,
    findModeForGame,
    gameToFormState,
    syntheticModeForGame,
    type GameFormState,
} from "../games/formModel";
import {
    formatStandingChange,
    label,
    RESULT_LABELS,
    TURN_ORDER_LABELS,
} from "../games/labels";
import { listGameModes } from "../games/modes";
import type { Game, GameMode } from "../games/types";
import { useSettings } from "../settings/useSettings";
import "./history.css";

interface Message {
    kind: "error" | "success";
    text: string;
}

export function HistoryPage() {
    const { settings } = useSettings();
    const [modes, setModes] = useState<GameMode[]>([]);
    const [decks, setDecks] = useState<string[]>([]);
    const [games, setGames] = useState<Game[]>([]);
    const [filter, setFilter] = useState<string>("all");
    const [editingGame, setEditingGame] = useState<Game | null>(null);
    const [editForm, setEditForm] = useState<GameFormState | null>(null);
    const [message, setMessage] = useState<Message | null>(null);
    const [busy, setBusy] = useState(false);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
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
            })
            .catch(() => {
                if (!cancelled) {
                    setMessage({
                        kind: "error",
                        text: "기록 목록을 불러오지 못했습니다.",
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
    }, []);

    const filteredGames = useMemo(() => {
        if (filter === "all") {
            return games;
        }
        const mode = modes.find((candidate) => candidate.id === filter);
        if (!mode) {
            return games;
        }
        return games.filter(
            (game) => game.play_context_id === mode.play_context_id,
        );
    }, [games, modes, filter]);

    function startEdit(game: Game) {
        const mode = findModeForGame(modes, game) ?? syntheticModeForGame(game);
        setEditingGame(game);
        setEditForm(gameToFormState(game, mode, settings));
        setMessage(null);
    }

    function cancelEdit() {
        setEditingGame(null);
        setEditForm(null);
        setMessage(null);
    }

    async function saveEdit() {
        if (!editingGame || !editForm) {
            return;
        }
        const result = buildGamePayload({
            ...editForm,
            playedAt: editingGame.played_at,
            timezoneOffsetMinutes: editingGame.timezone_offset_minutes,
        });
        if (result.error || !result.payload) {
            setMessage({
                kind: "error",
                text: result.error ?? "입력을 확인하세요.",
            });
            return;
        }
        setBusy(true);
        setMessage(null);
        try {
            await updateGame(
                editingGame.id,
                editingGame.change_version,
                result.payload,
            );
            setMessage({ kind: "success", text: "기록을 수정했습니다." });
            setEditingGame(null);
            setEditForm(null);
            await refresh();
        } catch (error) {
            setMessage({
                kind: "error",
                text:
                    error instanceof GameConflictError
                        ? "다른 기기에서 수정된 기록입니다. 최신 내용을 다시 불러왔습니다."
                        : error instanceof Error
                          ? error.message
                          : "기록 수정에 실패했습니다.",
            });
            if (error instanceof GameConflictError) {
                await refresh();
                setEditingGame(null);
                setEditForm(null);
            }
        } finally {
            setBusy(false);
        }
    }

    async function handleDelete(game: Game) {
        if (!window.confirm("이 기록을 삭제할까요?")) {
            return;
        }
        setBusy(true);
        setMessage(null);
        try {
            await deleteGame(game.id, game.change_version);
            setMessage({ kind: "success", text: "기록을 삭제했습니다." });
            await refresh();
        } catch (error) {
            setMessage({
                kind: "error",
                text:
                    error instanceof GameConflictError
                        ? "다른 기기에서 수정된 기록입니다. 최신 내용을 다시 불러왔습니다."
                        : error instanceof Error
                          ? error.message
                          : "기록 삭제에 실패했습니다.",
            });
            if (error instanceof GameConflictError) {
                await refresh();
            }
        } finally {
            setBusy(false);
        }
    }

    if (loading) {
        return <p className="auth-loading">기록 목록을 불러오는 중...</p>;
    }

    return (
        <section aria-labelledby="history-title" className="history-page">
            <h1 id="history-title" className="page-title">
                기록 목록
            </h1>

            <div
                className="segmented history-filter"
                role="group"
                aria-label="모드 필터"
            >
                <button
                    type="button"
                    className={
                        filter === "all"
                            ? "segmented__button segmented__button--active"
                            : "segmented__button"
                    }
                    aria-pressed={filter === "all"}
                    onClick={() => setFilter("all")}
                >
                    전체
                </button>
                {modes.map((mode) => (
                    <button
                        key={mode.id}
                        type="button"
                        className={
                            filter === mode.id
                                ? "segmented__button segmented__button--active"
                                : "segmented__button"
                        }
                        aria-pressed={filter === mode.id}
                        onClick={() => setFilter(mode.id)}
                    >
                        {mode.display_name}
                    </button>
                ))}
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

            {editingGame && editForm ? (
                <section
                    className="section-surface"
                    aria-labelledby="edit-title"
                >
                    <h2 id="edit-title" className="section-surface__title">
                        기록 수정
                    </h2>
                    <p className="history-item__meta">
                        모드:{" "}
                        {editingGame
                            ? (modes.find(
                                  (mode) =>
                                      mode.play_context_id ===
                                      editingGame.play_context_id,
                              )?.display_name ?? "기록")
                            : ""}
                    </p>
                    <div className="field">
                        <span className="field__label">결과</span>
                        <div
                            className="segmented"
                            role="group"
                            aria-label="결과"
                        >
                            {(["win", "lose"] as const).map((value) => (
                                <button
                                    key={value}
                                    type="button"
                                    className={
                                        editForm.result === value
                                            ? "segmented__button segmented__button--active"
                                            : "segmented__button"
                                    }
                                    aria-pressed={editForm.result === value}
                                    onClick={() =>
                                        setEditForm((current) =>
                                            current
                                                ? { ...current, result: value }
                                                : current,
                                        )
                                    }
                                >
                                    {RESULT_LABELS[value]}
                                </button>
                            ))}
                        </div>
                    </div>
                    <GameDetailForm
                        state={editForm}
                        decks={decks}
                        onChange={(patch) =>
                            setEditForm((current) =>
                                current ? { ...current, ...patch } : current,
                            )
                        }
                    />
                    <div className="record-actions">
                        <button
                            type="button"
                            className="primary-button"
                            onClick={saveEdit}
                            disabled={busy}
                        >
                            {busy ? "저장 중..." : "수정 저장"}
                        </button>
                        <button
                            type="button"
                            onClick={cancelEdit}
                            disabled={busy}
                        >
                            취소
                        </button>
                    </div>
                </section>
            ) : null}

            {filteredGames.length === 0 ? (
                <p className="page-description">기록이 없습니다.</p>
            ) : (
                <>
                    <ul className="history-list">
                        {filteredGames.map((game) => (
                            <li key={game.id} className="history-item">
                                <GameRow
                                    game={game}
                                    modes={modes}
                                    onEdit={() => startEdit(game)}
                                    onDelete={() => handleDelete(game)}
                                    busy={busy}
                                />
                            </li>
                        ))}
                    </ul>
                    <table className="history-table">
                        <thead>
                            <tr>
                                <th scope="col">시각</th>
                                <th scope="col">결과</th>
                                <th scope="col">모드</th>
                                <th scope="col">덱</th>
                                <th scope="col">진행</th>
                                <th scope="col">상태 변화</th>
                                <th scope="col">작업</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filteredGames.map((game) => (
                                <GameTableRow
                                    key={game.id}
                                    game={game}
                                    modes={modes}
                                    onEdit={() => startEdit(game)}
                                    onDelete={() => handleDelete(game)}
                                    busy={busy}
                                />
                            ))}
                        </tbody>
                    </table>
                </>
            )}
        </section>
    );
}

function GameRow({
    game,
    modes,
    onEdit,
    onDelete,
    busy,
}: {
    game: Game;
    modes: GameMode[];
    onEdit(): void;
    onDelete(): void;
    busy: boolean;
}) {
    const modeLabel = modeDisplayName(game, modes);
    return (
        <div className="history-item__body">
            <div className="history-item__head">
                <span
                    className={
                        game.result === "win"
                            ? "result-badge result-badge--win"
                            : "result-badge result-badge--lose"
                    }
                >
                    {label(RESULT_LABELS, game.result)}
                </span>
                <span className="mode-badge">{modeLabel}</span>
                <span className="history-item__time">
                    {game.played_at.replace("T", " ")}
                </span>
            </div>
            <p className="history-item__decks">
                {game.my_deck || "—"} vs {game.opp_deck || "—"}
            </p>
            <p className="history-item__meta">
                {label(TURN_ORDER_LABELS, game.turn_order)}
                {game.turns !== null ? ` · ${game.turns}턴` : ""} ·{" "}
                {formatStandingChange(game)}
            </p>
            <div className="history-item__actions">
                <button type="button" onClick={onEdit} disabled={busy}>
                    수정
                </button>
                <button
                    type="button"
                    className="danger"
                    onClick={onDelete}
                    disabled={busy}
                >
                    삭제
                </button>
            </div>
        </div>
    );
}

function GameTableRow({
    game,
    modes,
    onEdit,
    onDelete,
    busy,
}: {
    game: Game;
    modes: GameMode[];
    onEdit(): void;
    onDelete(): void;
    busy: boolean;
}) {
    return (
        <tr>
            <td className="history-table__time">
                {game.played_at.replace("T", " ")}
            </td>
            <td>
                <span
                    className={
                        game.result === "win"
                            ? "result-badge result-badge--win"
                            : "result-badge result-badge--lose"
                    }
                >
                    {label(RESULT_LABELS, game.result)}
                </span>
            </td>
            <td>{modeDisplayName(game, modes)}</td>
            <td>
                {game.my_deck || "—"} vs {game.opp_deck || "—"}
            </td>
            <td>
                {label(TURN_ORDER_LABELS, game.turn_order)}
                {game.turns !== null ? ` · ${game.turns}턴` : ""}
            </td>
            <td>{formatStandingChange(game)}</td>
            <td className="history-table__actions">
                <button type="button" onClick={onEdit} disabled={busy}>
                    수정
                </button>
                <button
                    type="button"
                    className="danger"
                    onClick={onDelete}
                    disabled={busy}
                >
                    삭제
                </button>
            </td>
        </tr>
    );
}

function modeDisplayName(game: Game, modes: GameMode[]): string {
    return (
        modes.find((mode) => mode.play_context_id === game.play_context_id)
            ?.display_name ?? "기록"
    );
}
