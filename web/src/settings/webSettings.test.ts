import { describe, expect, it } from "vitest";
import { resolveAccentTokens, resolveThemeMode } from "../theme/applyTheme";
import {
  DEFAULT_SETTINGS,
  DEVICE_KEYS,
  PREFERENCE_KEYS,
  effectiveReduceMotion,
  parseSettings,
  serializeSettings,
} from "./webSettings";

describe("WebSettings", () => {
  it("기본값을 반환한다", () => {
    expect(parseSettings(undefined)).toEqual(DEFAULT_SETTINGS);
    expect(parseSettings({})).toEqual(DEFAULT_SETTINGS);
  });

  it("손상된 단일 필드를 기본값으로 대체한다", () => {
    expect(parseSettings({ theme_mode: "bogus" }).theme_mode).toBe("system");
    expect(parseSettings({ accent_color: "bogus" }).accent_color).toBe("blue");
    expect(parseSettings({ font_scale: 9 }).font_scale).toBe(1.0);
    expect(parseSettings({ font_scale: true }).font_scale).toBe(1.0);
    expect(parseSettings({ memo_enabled: "yes" }).memo_enabled).toBe(true);
    expect(parseSettings({ score_input_mode: "bogus" }).score_input_mode).toBe(
      "delta",
    );
  });

  it("font_scale은 0.8~1.5 범위를 검증한다", () => {
    expect(parseSettings({ font_scale: 0.8 }).font_scale).toBe(0.8);
    expect(parseSettings({ font_scale: 1.5 }).font_scale).toBe(1.5);
    expect(parseSettings({ font_scale: 0.7 }).font_scale).toBe(1.0);
    expect(parseSettings({ font_scale: 1.6 }).font_scale).toBe(1.0);
  });

  it("직렬화/역직렬화 왕복이 일치한다", () => {
    const settings = {
      ...DEFAULT_SETTINGS,
      theme_mode: "dark" as const,
      accent_color: "teal" as const,
    };
    const roundTripped = parseSettings(JSON.parse(serializeSettings(settings)));
    expect(roundTripped).toEqual(settings);
  });

  it("PREFERENCE_KEYS/DEVICE_KEYS가 데스크톱과 동일하다", () => {
    expect(PREFERENCE_KEYS).toEqual([
      "theme_mode",
      "accent_color",
      "memo_enabled",
      "default_mode",
      "score_input_mode",
    ]);
    expect(DEVICE_KEYS).toEqual([
      "font_scale",
      "low_spec_mode",
      "reduce_motion",
    ]);
  });

  it("저사양 모드 on이면 애니메이션을 강제로 끈다", () => {
    expect(
      effectiveReduceMotion({ ...DEFAULT_SETTINGS, low_spec_mode: true }),
    ).toBe(true);
    expect(
      effectiveReduceMotion({ ...DEFAULT_SETTINGS, reduce_motion: "on" }),
    ).toBe(true);
    expect(effectiveReduceMotion({ ...DEFAULT_SETTINGS })).toBe(false);
  });
});

describe("테마 토큰", () => {
  it("resolveThemeMode가 명시 모드를 반환한다", () => {
    expect(resolveThemeMode("light")).toBe("light");
    expect(resolveThemeMode("dark")).toBe("dark");
  });

  it("강조색 프리셋이 라이트/다크 accent를 반환한다", () => {
    const indigoLight = resolveAccentTokens("indigo", false);
    expect(indigoLight.accent).toBe("#4F46E5");
    expect(indigoLight.textOnAccent).toBe("#FFFFFF");

    const indigoDark = resolveAccentTokens("indigo", true);
    expect(indigoDark.accent).toBe("#A5B4FC");
    expect(indigoDark.textOnAccent).toBe("#11151B");
  });
});
