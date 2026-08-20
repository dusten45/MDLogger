// 설정 화면 (spec §8.3). 테마·강조색·글자 크기·성능·기록 설정 + 계정·동기화.

import { useEffect, useState } from "react";
import { useAuth } from "../auth/useAuth";
import {
    deleteAccount,
    downloadAccountExport,
    exportAccountData,
    revokeAllSessions,
} from "../auth/account";
import { listGameModes } from "../games/modes";
import type { GameMode } from "../games/types";
import { ACCENT_IDS, ACCENT_PRESETS } from "../theme/accentPresets";
import { resolveThemeMode } from "../theme/applyTheme";
import { useSettings } from "../settings/useSettings";
import {
    downloadPreferences,
    uploadPreferences,
} from "../settings/settingsSync";
import { DEFAULT_MODE_LAST_USED, parseSettings } from "../settings/webSettings";
import "./settings.css";

const THEME_OPTIONS = [
    { value: "system", label: "시스템" },
    { value: "light", label: "밝음" },
    { value: "dark", label: "어두움" },
] as const;

const ACCENT_LABELS: Readonly<Record<string, string>> = {
    blue: "파랑",
    indigo: "인디고",
    teal: "청록",
    magenta: "마젠타",
    amber: "호박",
};

const REDUCE_MOTION_OPTIONS = [
    { value: "system", label: "시스템" },
    { value: "off", label: "끔" },
    { value: "on", label: "켬" },
] as const;

const FONT_SCALE_OPTIONS = [0.8, 0.9, 1.0, 1.1, 1.25, 1.5];

const SCORE_INPUT_OPTIONS = [
    { value: "delta", label: "변동폭 입력" },
    { value: "direct", label: "직접 입력" },
] as const;

interface Message {
    kind: "error" | "success";
    text: string;
}

export function SettingsPage() {
    const { user, signOut } = useAuth();
    const { settings, updateSettings, resetSettings } = useSettings();
    const [modes, setModes] = useState<GameMode[]>([]);
    const [busy, setBusy] = useState<string | null>(null);
    const [message, setMessage] = useState<Message | null>(null);

    useEffect(() => {
        let cancelled = false;
        listGameModes()
            .then((rows) => {
                if (!cancelled) {
                    setModes(rows);
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setMessage({
                        kind: "error",
                        text: "모드 목록을 불러오지 못했습니다.",
                    });
                }
            });
        return () => {
            cancelled = true;
        };
    }, []);

    async function handleExport() {
        setBusy("export");
        setMessage(null);
        try {
            const data = await exportAccountData();
            downloadAccountExport(data);
            setMessage({
                kind: "success",
                text: "계정 데이터를 내보냈습니다.",
            });
        } catch {
            setMessage({
                kind: "error",
                text: "계정 데이터 내보내기에 실패했습니다.",
            });
        } finally {
            setBusy(null);
        }
    }

    async function handleRevokeAll() {
        setBusy("revoke");
        setMessage(null);
        try {
            await revokeAllSessions();
            await signOut();
        } catch {
            setMessage({
                kind: "error",
                text: "모든 기기 로그아웃에 실패했습니다.",
            });
            setBusy(null);
        }
    }

    async function handleDelete() {
        if (
            !window.confirm(
                "계정을 삭제하면 모든 기록이 사라지며 되돌릴 수 없습니다. 계속할까요?",
            )
        ) {
            return;
        }
        setBusy("delete");
        setMessage(null);
        try {
            await deleteAccount();
            await signOut();
        } catch {
            setMessage({ kind: "error", text: "계정 삭제에 실패했습니다." });
            setBusy(null);
        }
    }

    async function handleUpload() {
        setBusy("upload");
        setMessage(null);
        try {
            await uploadPreferences(settings);
            setMessage({
                kind: "success",
                text: "설정을 서버에 업로드했습니다.",
            });
        } catch {
            setMessage({ kind: "error", text: "설정 업로드에 실패했습니다." });
        } finally {
            setBusy(null);
        }
    }

    async function handleDownload() {
        setBusy("download");
        setMessage(null);
        try {
            const patch = await downloadPreferences();
            if (patch === null) {
                setMessage({
                    kind: "success",
                    text: "서버에 저장된 설정이 없습니다.",
                });
            } else {
                // 서버 값이 손상되었을 수 있으므로 병합 후 검증해 적용한다.
                updateSettings(parseSettings({ ...settings, ...patch }));
                setMessage({
                    kind: "success",
                    text: "서버 설정을 불러왔습니다.",
                });
            }
        } catch {
            setMessage({
                kind: "error",
                text: "설정 다운로드에 실패했습니다.",
            });
        } finally {
            setBusy(null);
        }
    }

    function handleReset() {
        if (
            !window.confirm(
                "앱 설정을 기본값으로 되돌릴까요? 기록과 계정은 유지됩니다.",
            )
        ) {
            return;
        }
        resetSettings();
        setMessage({ kind: "success", text: "설정을 초기화했습니다." });
    }

    return (
        <section aria-labelledby="settings-title" className="settings-page">
            <h1 id="settings-title" className="page-title">
                설정
            </h1>

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

            <section
                className="section-surface"
                aria-labelledby="appearance-title"
            >
                <h2 id="appearance-title" className="section-surface__title">
                    화면 및 접근성
                </h2>

                <div className="field">
                    <span className="field__label">테마</span>
                    <div className="segmented" role="group" aria-label="테마">
                        {THEME_OPTIONS.map((option) => (
                            <button
                                key={option.value}
                                type="button"
                                className={
                                    settings.theme_mode === option.value
                                        ? "segmented__button segmented__button--active"
                                        : "segmented__button"
                                }
                                aria-pressed={
                                    settings.theme_mode === option.value
                                }
                                onClick={() =>
                                    updateSettings({ theme_mode: option.value })
                                }
                            >
                                {option.label}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="field">
                    <span className="field__label">강조색</span>
                    <div
                        className="accent-options"
                        role="group"
                        aria-label="강조색"
                    >
                        {ACCENT_IDS.map((id) => {
                            const dark =
                                resolveThemeMode(settings.theme_mode) ===
                                "dark";
                            const swatch = dark
                                ? ACCENT_PRESETS[id].dark
                                : ACCENT_PRESETS[id].light;
                            return (
                                <button
                                    key={id}
                                    type="button"
                                    className={
                                        settings.accent_color === id
                                            ? "accent-swatch accent-swatch--active"
                                            : "accent-swatch"
                                    }
                                    aria-pressed={settings.accent_color === id}
                                    aria-label={ACCENT_LABELS[id] ?? id}
                                    onClick={() =>
                                        updateSettings({ accent_color: id })
                                    }
                                >
                                    <span
                                        className="accent-swatch__dot"
                                        style={{ background: swatch }}
                                    />
                                    {ACCENT_LABELS[id] ?? id}
                                </button>
                            );
                        })}
                    </div>
                </div>

                <div className="field">
                    <label className="field__label" htmlFor="font-scale">
                        글자 크기
                    </label>
                    <select
                        id="font-scale"
                        value={settings.font_scale}
                        onChange={(event) =>
                            updateSettings({
                                font_scale: Number(event.target.value),
                            })
                        }
                    >
                        {FONT_SCALE_OPTIONS.map((scale) => (
                            <option key={scale} value={scale}>
                                {Math.round(scale * 100)}%
                            </option>
                        ))}
                    </select>
                </div>

                <div className="field">
                    <span className="field__label">애니메이션 감소</span>
                    <div
                        className="segmented"
                        role="group"
                        aria-label="애니메이션 감소"
                    >
                        {REDUCE_MOTION_OPTIONS.map((option) => (
                            <button
                                key={option.value}
                                type="button"
                                className={
                                    settings.reduce_motion === option.value
                                        ? "segmented__button segmented__button--active"
                                        : "segmented__button"
                                }
                                aria-pressed={
                                    settings.reduce_motion === option.value
                                }
                                onClick={() =>
                                    updateSettings({
                                        reduce_motion: option.value,
                                    })
                                }
                            >
                                {option.label}
                            </button>
                        ))}
                    </div>
                </div>
            </section>

            <section
                className="section-surface"
                aria-labelledby="performance-title"
            >
                <h2 id="performance-title" className="section-surface__title">
                    성능
                </h2>
                <ToggleRow
                    label="저사양 모드"
                    description="애니메이션과 일부 시각 효과를 줄여 CPU·GPU 사용량을 낮춥니다."
                    checked={settings.low_spec_mode}
                    onChange={(value) =>
                        updateSettings({ low_spec_mode: value })
                    }
                />
            </section>

            <section
                className="section-surface"
                aria-labelledby="recording-title"
            >
                <h2 id="recording-title" className="section-surface__title">
                    기록
                </h2>
                <ToggleRow
                    label="메모 사용"
                    description="끄면 입력과 기록 열에서 메모를 숨깁니다. 기존 메모는 삭제하지 않습니다."
                    checked={settings.memo_enabled}
                    onChange={(value) =>
                        updateSettings({ memo_enabled: value })
                    }
                />

                <div className="field">
                    <label className="field__label" htmlFor="default-mode">
                        기본 모드
                    </label>
                    <select
                        id="default-mode"
                        value={settings.default_mode}
                        onChange={(event) =>
                            updateSettings({ default_mode: event.target.value })
                        }
                    >
                        <option value={DEFAULT_MODE_LAST_USED}>
                            이전 모드 기억
                        </option>
                        {modes.map((mode) => (
                            <option key={mode.id} value={mode.id}>
                                {mode.display_name}
                            </option>
                        ))}
                        {settings.default_mode !== DEFAULT_MODE_LAST_USED &&
                        !modes.some(
                            (mode) => mode.id === settings.default_mode,
                        ) ? (
                            <option value={settings.default_mode}>
                                {settings.default_mode}
                            </option>
                        ) : null}
                    </select>
                </div>

                <div className="field">
                    <span className="field__label">점수/레이팅 입력 방식</span>
                    <div
                        className="segmented"
                        role="group"
                        aria-label="점수/레이팅 입력 방식"
                    >
                        {SCORE_INPUT_OPTIONS.map((option) => (
                            <button
                                key={option.value}
                                type="button"
                                className={
                                    settings.score_input_mode === option.value
                                        ? "segmented__button segmented__button--active"
                                        : "segmented__button"
                                }
                                aria-pressed={
                                    settings.score_input_mode === option.value
                                }
                                onClick={() =>
                                    updateSettings({
                                        score_input_mode: option.value,
                                    })
                                }
                            >
                                {option.label}
                            </button>
                        ))}
                    </div>
                </div>
            </section>

            <section className="section-surface" aria-labelledby="sync-title">
                <h2 id="sync-title" className="section-surface__title">
                    설정 동기화
                </h2>
                <p className="page-description">
                    취향 설정(테마·강조색·메모·기본 모드·입력 방식)만 수동으로
                    업로드/다운로드합니다. 글자 크기·저사양 모드·애니메이션
                    감소는 기기별 설정이라 동기화하지 않습니다.
                </p>
                <div className="settings-actions">
                    <button
                        type="button"
                        onClick={handleUpload}
                        disabled={busy !== null}
                    >
                        {busy === "upload" ? "업로드 중..." : "서버에 업로드"}
                    </button>
                    <button
                        type="button"
                        onClick={handleDownload}
                        disabled={busy !== null}
                    >
                        {busy === "download"
                            ? "다운로드 중..."
                            : "서버에서 다운로드"}
                    </button>
                </div>
            </section>

            <section
                className="section-surface"
                aria-labelledby="account-title"
            >
                <h2 id="account-title" className="section-surface__title">
                    계정 및 데이터
                </h2>
                {user?.email ? (
                    <p className="account-email">{user.email}</p>
                ) : null}
                <div className="settings-actions">
                    <button
                        type="button"
                        onClick={handleExport}
                        disabled={busy !== null}
                    >
                        {busy === "export"
                            ? "내보내는 중..."
                            : "계정 데이터 내보내기"}
                    </button>
                    <button
                        type="button"
                        onClick={handleRevokeAll}
                        disabled={busy !== null}
                    >
                        {busy === "revoke"
                            ? "처리 중..."
                            : "모든 기기 로그아웃"}
                    </button>
                    <button type="button" onClick={() => signOut()}>
                        로그아웃
                    </button>
                    <button
                        type="button"
                        className="danger"
                        onClick={handleDelete}
                        disabled={busy !== null}
                    >
                        {busy === "delete" ? "삭제 중..." : "계정 삭제"}
                    </button>
                </div>
            </section>

            <section className="section-surface" aria-labelledby="reset-title">
                <h2 id="reset-title" className="section-surface__title">
                    설정 초기화
                </h2>
                <p className="page-description">
                    앱 설정만 기본값으로 되돌립니다. 경기 기록과 계정은 변경되지
                    않습니다.
                </p>
                <button
                    type="button"
                    onClick={handleReset}
                    disabled={busy !== null}
                >
                    설정 초기화
                </button>
            </section>
        </section>
    );
}

function ToggleRow({
    label: rowLabel,
    description,
    checked,
    onChange,
}: {
    label: string;
    description: string;
    checked: boolean;
    onChange(value: boolean): void;
}) {
    return (
        <div className="toggle-row">
            <div className="toggle-row__text">
                <span className="field__label">{rowLabel}</span>
                <span className="toggle-row__description">{description}</span>
            </div>
            <input
                type="checkbox"
                role="switch"
                aria-label={rowLabel}
                checked={checked}
                onChange={(event) => onChange(event.target.checked)}
            />
        </div>
    );
}
