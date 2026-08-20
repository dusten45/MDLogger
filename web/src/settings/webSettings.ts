// 웹 설정 모델·검증·저장소 (데스크톱 `app_settings.py`와 동일한 키·기본값·검증, spec §4).
//
// 데스크톱과 달리 프로필 DB가 없으므로 `default_mode`도 `localStorage`에 둔다
// (spec §1.1). 동기화 대상은 `PREFERENCE_KEYS`(취향 설정)뿐이고 `DEVICE_KEYS`
// (기기 특성)는 어떤 경로로도 직렬화·전송하지 않는다.

import { isAccentId, type AccentId } from "../theme/accentPresets";
import type { ThemeMode } from "../theme/applyTheme";

export const SCHEMA_VERSION = 1;
export const DEFAULT_MODE_LAST_USED = "last_used";

export type ScoreInputMode = "delta" | "direct";

// 동기화(취향 설정) allowlist. 데스크톱 `PREFERENCE_KEYS`와 동일하다.
export const PREFERENCE_KEYS = [
    "theme_mode",
    "accent_color",
    "memo_enabled",
    "default_mode",
    "score_input_mode",
] as const;

// 기기 특성 설정. 어떤 경로로도 직렬화·전송하지 않는다.
export const DEVICE_KEYS = ["font_scale"] as const;

export interface WebSettings {
    theme_mode: ThemeMode;
    accent_color: AccentId;
    font_scale: number; // 0.8 ~ 1.5
    memo_enabled: boolean;
    default_mode: string;
    score_input_mode: ScoreInputMode;
}

export const DEFAULT_SETTINGS: WebSettings = {
    theme_mode: "system",
    accent_color: "blue",
    font_scale: 1.0,
    memo_enabled: true,
    default_mode: DEFAULT_MODE_LAST_USED,
    score_input_mode: "delta",
};

export function parseSettings(data: unknown): WebSettings {
    const source =
        typeof data === "object" && data !== null && !Array.isArray(data)
            ? (data as Record<string, unknown>)
            : {};
    return {
        theme_mode: parseThemeMode(source.theme_mode),
        accent_color: parseAccent(source.accent_color),
        font_scale: parseFontScale(source.font_scale),
        memo_enabled: parseBool(source.memo_enabled, true),
        default_mode: parseDefaultMode(source.default_mode),
        score_input_mode: parseScoreInputMode(source.score_input_mode),
    };
}

export function serializeSettings(settings: WebSettings): string {
    return JSON.stringify({
        schema_version: SCHEMA_VERSION,
        theme_mode: settings.theme_mode,
        accent_color: settings.accent_color,
        font_scale: settings.font_scale,
        memo_enabled: settings.memo_enabled,
        default_mode: settings.default_mode,
        score_input_mode: settings.score_input_mode,
    });
}

export interface SettingsStore {
    load(): WebSettings;
    save(settings: WebSettings): void;
}

const STORAGE_KEY = "mdlogger.settings";

/** `localStorage` 기반 저장소. 손상·스키마 불일치는 기본값으로 대체한다. */
export class LocalStorageSettingsStore implements SettingsStore {
    load(): WebSettings {
        if (typeof window === "undefined") {
            return { ...DEFAULT_SETTINGS };
        }
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (raw === null) {
            return { ...DEFAULT_SETTINGS };
        }
        try {
            const data: unknown = JSON.parse(raw);
            if (
                typeof data === "object" &&
                data !== null &&
                !Array.isArray(data) &&
                (data as Record<string, unknown>).schema_version !==
                    SCHEMA_VERSION
            ) {
                return { ...DEFAULT_SETTINGS };
            }
            return parseSettings(data);
        } catch {
            return { ...DEFAULT_SETTINGS };
        }
    }

    save(settings: WebSettings): void {
        if (typeof window === "undefined") {
            return;
        }
        window.localStorage.setItem(STORAGE_KEY, serializeSettings(settings));
    }
}

/** 테스트용 인메모리 저장소. */
export class MemorySettingsStore implements SettingsStore {
    private settings: WebSettings;

    constructor(initial: WebSettings = { ...DEFAULT_SETTINGS }) {
        this.settings = initial;
    }

    load(): WebSettings {
        return this.settings;
    }

    save(settings: WebSettings): void {
        this.settings = settings;
    }
}

function parseThemeMode(value: unknown): ThemeMode {
    if (value === "light" || value === "dark" || value === "system") {
        return value;
    }
    return "system";
}

function parseAccent(value: unknown): AccentId {
    return isAccentId(value) ? value : "blue";
}

function parseFontScale(value: unknown): number {
    if (typeof value === "boolean") {
        return 1.0;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
        if (value >= 0.8 && value <= 1.5) {
            return value;
        }
    }
    return 1.0;
}

function parseScoreInputMode(value: unknown): ScoreInputMode {
    if (value === "delta" || value === "direct") {
        return value;
    }
    return "delta";
}

function parseDefaultMode(value: unknown): string {
    return typeof value === "string" ? value : DEFAULT_MODE_LAST_USED;
}

function parseBool(value: unknown, fallback: boolean): boolean {
    return typeof value === "boolean" ? value : fallback;
}
