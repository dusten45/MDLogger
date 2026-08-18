// 강조색 프리셋 (데스크톱 `ui/theme.py`의 `ACCENT_PRESETS`와 동일한 값, spec §5.3).
// 각 프리셋은 라이트/다크 accent hex와 WCAG 대비를 통과하는 text_on_accent를 담는다.

export type AccentId = "blue" | "indigo" | "teal" | "magenta" | "amber";

export interface AccentPreset {
  light: string;
  dark: string;
  lightTextOnAccent: string;
  darkTextOnAccent: string;
}

export const ACCENT_PRESETS: Record<AccentId, AccentPreset> = {
  blue: {
    light: "#356AE6",
    dark: "#7EA2FF",
    lightTextOnAccent: "#FFFFFF",
    darkTextOnAccent: "#11151B",
  },
  indigo: {
    light: "#4F46E5",
    dark: "#A5B4FC",
    lightTextOnAccent: "#FFFFFF",
    darkTextOnAccent: "#11151B",
  },
  teal: {
    light: "#0F766E",
    dark: "#5EEAD4",
    lightTextOnAccent: "#FFFFFF",
    darkTextOnAccent: "#11151B",
  },
  magenta: {
    light: "#A21CAF",
    dark: "#F0ABFC",
    lightTextOnAccent: "#FFFFFF",
    darkTextOnAccent: "#11151B",
  },
  amber: {
    light: "#B45309",
    dark: "#FCD34D",
    lightTextOnAccent: "#FFFFFF",
    darkTextOnAccent: "#11151B",
  },
};

export const ACCENT_IDS: readonly AccentId[] = [
  "blue",
  "indigo",
  "teal",
  "magenta",
  "amber",
];

export function isAccentId(value: unknown): value is AccentId {
  return (
    typeof value === "string" &&
    (ACCENT_IDS as readonly string[]).includes(value)
  );
}
