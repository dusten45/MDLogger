// 경기 상세 입력 폼 (데스크톱 `detail_form.py`와 동일, spec §7).
// 공통 필드(선후공·덱·턴·종료·메모) + 모드별 상태 입력(점수/랭크/레이팅).

import type { EndReason, TurnOrder } from "../../games/types";
import { END_REASON_LABELS, TURN_ORDER_LABELS } from "../../games/labels";
import type { GameFormState, RankValue } from "../../games/formModel";
import { RankPanel } from "./RankPanel";

export interface GameDetailFormProps {
    state: GameFormState;
    decks: string[];
    onChange(patch: Partial<GameFormState>): void;
}

const TURN_ORDERS: TurnOrder[] = ["first", "second"];
const END_REASONS: EndReason[] = [
    "regular",
    "surrender",
    "timeout",
    "disconnect",
];

export function GameDetailForm({
    state,
    decks,
    onChange,
}: GameDetailFormProps) {
    const kind = state.mode?.standing_kind ?? null;

    return (
        <div className="stack">
            <section
                className="section-surface"
                aria-labelledby="progress-title"
            >
                <h2 id="progress-title" className="section-surface__title">
                    진행 정보
                </h2>
                <div className="field-row">
                    <span className="field__label">선/후공</span>
                    <div
                        className="segmented"
                        role="group"
                        aria-label="선/후공"
                    >
                        {TURN_ORDERS.map((value) => (
                            <button
                                key={value}
                                type="button"
                                className={
                                    state.turnOrder === value
                                        ? "segmented__button segmented__button--active"
                                        : "segmented__button"
                                }
                                aria-pressed={state.turnOrder === value}
                                onClick={() => onChange({ turnOrder: value })}
                            >
                                {TURN_ORDER_LABELS[value]}
                            </button>
                        ))}
                    </div>
                </div>
                <div className="field">
                    <label className="field__label" htmlFor="turns-input">
                        소요 턴
                    </label>
                    <input
                        id="turns-input"
                        type="number"
                        min={1}
                        max={99}
                        inputMode="numeric"
                        value={state.turns}
                        onChange={(event) =>
                            onChange({ turns: Number(event.target.value) || 1 })
                        }
                    />
                </div>
            </section>

            <section className="section-surface" aria-labelledby="decks-title">
                <h2 id="decks-title" className="section-surface__title">
                    덱
                </h2>
                <DeckField
                    id="my-deck"
                    label="내 덱"
                    value={state.myDeck}
                    decks={decks}
                    onChange={(value) => onChange({ myDeck: value })}
                />
                <DeckField
                    id="opp-deck"
                    label="상대 덱"
                    value={state.oppDeck}
                    decks={decks}
                    onChange={(value) => onChange({ oppDeck: value })}
                />
            </section>

            <section className="section-surface" aria-labelledby="reason-title">
                <h2 id="reason-title" className="section-surface__title">
                    종료 방식
                </h2>
                <div className="segmented" role="group" aria-label="종료 방식">
                    {END_REASONS.map((value) => (
                        <button
                            key={value}
                            type="button"
                            className={
                                state.endReason === value
                                    ? "segmented__button segmented__button--active"
                                    : "segmented__button"
                            }
                            aria-pressed={state.endReason === value}
                            onClick={() => onChange({ endReason: value })}
                        >
                            {END_REASON_LABELS[value]}
                        </button>
                    ))}
                </div>
            </section>

            <section
                className="section-surface"
                aria-labelledby="standing-title"
            >
                <h2 id="standing-title" className="section-surface__title">
                    모드 상태
                </h2>
                {kind === "rank" ? (
                    <RankPanel
                        before={state.rankBefore}
                        after={state.rankAfter}
                        onBeforeChange={(value: RankValue) =>
                            onChange({ rankBefore: value })
                        }
                        onAfterChange={(value: RankValue) =>
                            onChange({ rankAfter: value })
                        }
                    />
                ) : kind === "rating" ? (
                    <RatingPanel state={state} onChange={onChange} />
                ) : (
                    <ScorePanel state={state} onChange={onChange} />
                )}
            </section>

            {state.memoEnabled ? (
                <section
                    className="section-surface"
                    aria-labelledby="note-title"
                >
                    <h2 id="note-title" className="section-surface__title">
                        메모
                    </h2>
                    <textarea
                        aria-label="메모 (선택)"
                        placeholder="메모 (선택)"
                        rows={2}
                        value={state.note}
                        onChange={(event) =>
                            onChange({ note: event.target.value })
                        }
                    />
                </section>
            ) : null}
        </div>
    );
}

function DeckField({
    id,
    label: fieldLabel,
    value,
    decks,
    onChange,
}: {
    id: string;
    label: string;
    value: string;
    decks: string[];
    onChange(value: string): void;
}) {
    // 덱 목록에 없는 기존 값(예: Gist에서 삭제된 덱)도 빈 선택으로 보이지 않게
    // 현재 값을 옵션에 추가한다.
    const options = value && !decks.includes(value) ? [value, ...decks] : decks;
    return (
        <div className="field">
            <label className="field__label" htmlFor={id}>
                {fieldLabel}
            </label>
            <select
                id={id}
                value={value}
                onChange={(event) => onChange(event.target.value)}
            >
                <option value="">선택하세요</option>
                {options.map((deck) => (
                    <option key={deck} value={deck}>
                        {deck}
                    </option>
                ))}
            </select>
        </div>
    );
}

function ScorePanel({
    state,
    onChange,
}: {
    state: GameFormState;
    onChange(patch: Partial<GameFormState>): void;
}) {
    if (state.editing) {
        return (
            <div className="stack">
                <div className="field">
                    <label className="field__label" htmlFor="score-before">
                        경기 전 점수
                    </label>
                    <input
                        id="score-before"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.scoreBeforeInput}
                        onChange={(event) =>
                            onChange({ scoreBeforeInput: event.target.value })
                        }
                    />
                </div>
                <div className="field">
                    <label className="field__label" htmlFor="score-after">
                        경기 후 점수
                    </label>
                    <input
                        id="score-after"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.scoreAfter}
                        onChange={(event) =>
                            onChange({ scoreAfter: event.target.value })
                        }
                    />
                </div>
            </div>
        );
    }
    const delta = state.scoreInputMode === "delta";
    return (
        <div className="stack">
            <div className="field-row">
                <span className="field__label">경기 전 점수</span>
                <span className="readonly-value">
                    {state.scoreBase.toLocaleString()}
                </span>
            </div>
            {delta ? (
                <div className="field">
                    <label className="field__label" htmlFor="score-delta">
                        점수 변동폭
                    </label>
                    <input
                        id="score-delta"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.scoreDelta}
                        onChange={(event) =>
                            onChange({ scoreDelta: event.target.value })
                        }
                    />
                    <DeltaPreview
                        before={state.scoreBase}
                        delta={state.scoreDelta}
                        result={state.result}
                    />
                </div>
            ) : (
                <div className="field">
                    <label className="field__label" htmlFor="score-after">
                        경기 후 점수
                    </label>
                    <input
                        id="score-after"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.scoreAfter}
                        onChange={(event) =>
                            onChange({ scoreAfter: event.target.value })
                        }
                    />
                </div>
            )}
        </div>
    );
}

function RatingPanel({
    state,
    onChange,
}: {
    state: GameFormState;
    onChange(patch: Partial<GameFormState>): void;
}) {
    if (state.editing) {
        return (
            <div className="stack">
                <div className="field">
                    <label className="field__label" htmlFor="rating-before">
                        경기 전 레이팅
                    </label>
                    <input
                        id="rating-before"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.ratingBeforeInput}
                        onChange={(event) =>
                            onChange({ ratingBeforeInput: event.target.value })
                        }
                    />
                </div>
                <div className="field">
                    <label className="field__label" htmlFor="rating-after">
                        경기 후 레이팅
                    </label>
                    <input
                        id="rating-after"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.ratingAfter}
                        onChange={(event) =>
                            onChange({ ratingAfter: event.target.value })
                        }
                    />
                </div>
            </div>
        );
    }
    const delta = state.scoreInputMode === "delta";
    const beforeEditable = state.ratingBase === null;
    const before = state.ratingBase ?? parseNumber(state.ratingBeforeInput);
    return (
        <div className="stack">
            {beforeEditable ? (
                <div className="field">
                    <label className="field__label" htmlFor="rating-before">
                        경기 전 레이팅
                    </label>
                    <input
                        id="rating-before"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.ratingBeforeInput}
                        onChange={(event) =>
                            onChange({ ratingBeforeInput: event.target.value })
                        }
                    />
                </div>
            ) : (
                <div className="field-row">
                    <span className="field__label">경기 전 레이팅</span>
                    <span className="readonly-value">
                        {state.ratingBase?.toLocaleString() ?? "—"}
                    </span>
                </div>
            )}
            {delta ? (
                <div className="field">
                    <label className="field__label" htmlFor="rating-delta">
                        레이팅 변동폭
                    </label>
                    <input
                        id="rating-delta"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.ratingDelta}
                        onChange={(event) =>
                            onChange({ ratingDelta: event.target.value })
                        }
                    />
                    <DeltaPreview
                        before={before}
                        delta={state.ratingDelta}
                        result={state.result}
                    />
                </div>
            ) : (
                <div className="field">
                    <label className="field__label" htmlFor="rating-after">
                        경기 후 레이팅
                    </label>
                    <input
                        id="rating-after"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={state.ratingAfter}
                        onChange={(event) =>
                            onChange({ ratingAfter: event.target.value })
                        }
                    />
                </div>
            )}
        </div>
    );
}

function DeltaPreview({
    before,
    delta,
    result,
}: {
    before: number | null;
    delta: string;
    result: "win" | "lose" | null;
}) {
    const parsed = parseNumber(delta);
    if (parsed === null || result === null || before === null) {
        return null;
    }
    const after = result === "win" ? before + parsed : before - parsed;
    return (
        <p className="field-hint" aria-live="polite">
            경기 후: {after.toLocaleString()}
        </p>
    );
}

function parseNumber(text: string): number | null {
    const trimmed = text.trim();
    if (!trimmed) {
        return null;
    }
    const value = Number(trimmed);
    return Number.isFinite(value) ? value : null;
}
