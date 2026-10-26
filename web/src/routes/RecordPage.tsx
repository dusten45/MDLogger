// 기록 화면 (기본 화면, spec §5.2, §7). 핵심 기록 흐름:
// 모드 선택 → 승/패 → 상세 입력 → 저장(낙관적 동시성) → 마지막 기록 취소.

import { useEffect } from "react";
import { GameDetailForm } from "../components/record/GameDetailForm";
import "../components/record/record.css";
import { useRecord } from "../games/recordContext";

export function RecordPage() {
    const {
        modes, decks, record, lastGame, ready, attempt, form, setForm,
        saving, message, loading, open, selectMode, handleSave, handleUndo, handleRefresh,
    } = useRecord();

    useEffect(() => { open(); }, [open]);

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
                        className={form.mode?.id === mode.id ? "mode-chip mode-chip--active" : "mode-chip"}
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
                    onClick={() => setForm((current) => ({ ...current, result: "win" }))}
                >
                    승
                </button>
                <button
                    type="button"
                    className={resultButtonClass("lose", form.result)}
                    aria-pressed={form.result === "lose"}
                    disabled={saving || !!attempt || !ready}
                    onClick={() => setForm((current) => ({ ...current, result: "lose" }))}
                >
                    패
                </button>
            </div>

            {message ? (
                <p
                    className={message.kind === "error" ? "form-message form-message--error" : "form-message form-message--success"}
                    role="status"
                >
                    {message.text}
                </p>
            ) : null}

            <fieldset disabled={saving || !!attempt || !ready} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
                <GameDetailForm
                    state={form}
                    decks={decks}
                    onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
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
                <button type="button" disabled={saving || !!attempt} onClick={handleRefresh}>새로고침</button>
            </div>
        </section>
    );
}

function resultButtonClass(value: "win" | "lose", selected: "win" | "lose" | null): string {
    if (selected === null) {
        return value === "win" ? "result-button result-button--win" : "result-button result-button--lose";
    }
    if (selected === "win") {
        return value === "win" ? "result-button result-button--selected-win" : "result-button result-button--lose";
    }
    return value === "lose" ? "result-button result-button--selected-lose" : "result-button result-button--win";
}
