// 테마 적용 (데스크톱 `ui/theme.py`의 `resolve_theme_mode`/`_with_accent`/
// `apply_font_scale`과 동일한 의미, spec §5.3).

import { ACCENT_PRESETS, type AccentId } from "./accentPresets";
import { mix, shade } from "./color";

export type ThemeMode = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export interface AccentTokens {
    accent: string;
    accentHover: string;
    accentPressed: string;
    textOnAccent: string;
    focusRing: string;
    selection: string;
    chartPrimary: string;
}

const DARK_BACKGROUND = "#11151B";

export function resolveThemeMode(mode: ThemeMode): ResolvedTheme {
    if (mode === "light") {
        return "light";
    }
    if (mode === "dark") {
        return "dark";
    }
    if (
        typeof window !== "undefined" &&
        window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ) {
        return "dark";
    }
    return "light";
}

export function resolveAccentTokens(
    accent: AccentId,
    dark: boolean,
): AccentTokens {
    const preset = ACCENT_PRESETS[accent];
    const accentHex = dark ? preset.dark : preset.light;
    const textOnAccent = dark
        ? preset.darkTextOnAccent
        : preset.lightTextOnAccent;
    const hover = shade(accentHex, dark ? 1.15 : 0.88);
    const pressed = shade(accentHex, dark ? 0.88 : 0.72);
    const selection = mix(
        accentHex,
        dark ? DARK_BACKGROUND : "#FFFFFF",
        dark ? 0.28 : 0.18,
    );
    return {
        accent: accentHex,
        accentHover: hover,
        accentPressed: pressed,
        textOnAccent,
        focusRing: accentHex,
        selection,
        chartPrimary: accentHex,
    };
}

export interface ThemeInput {
    themeMode: ThemeMode;
    accentColor: AccentId;
    fontScale: number;
}

/** 문서 루트에 테마·강조색·글자 크기를 적용한다. */
export function applyTheme(input: ThemeInput): void {
    const root = document.documentElement;
    const resolved = resolveThemeMode(input.themeMode);
    root.dataset.theme = resolved;
    root.dataset.accent = input.accentColor;

    const tokens = resolveAccentTokens(input.accentColor, resolved === "dark");
    root.style.setProperty("--accent", tokens.accent);
    root.style.setProperty("--accent-hover", tokens.accentHover);
    root.style.setProperty("--accent-pressed", tokens.accentPressed);
    root.style.setProperty("--text-on-accent", tokens.textOnAccent);
    root.style.setProperty("--focus-ring", tokens.focusRing);
    root.style.setProperty("--selection", tokens.selection);
    root.style.setProperty("--chart-primary", tokens.chartPrimary);

    root.style.setProperty("--font-scale", String(input.fontScale));

    // 브라우저 주소창/상태 표시줄 색을 테마에 맞춘다 (모바일 안전 영역과 시각 일관성).
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) {
        themeColor.setAttribute(
            "content",
            resolved === "dark" ? "#11151B" : "#F5F7FA",
        );
    }
}
