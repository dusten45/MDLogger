// 설정 프로바이더 (spec §4). 저장소에서 설정을 불러오고, 변경 시 테마·강조색·
// 글자 크기를 즉시 적용하며 localStorage에 저장한다.

import {
    useCallback,
    useEffect,
    useMemo,
    useState,
    type ReactNode,
} from "react";
import { applyTheme } from "../theme/applyTheme";
import { SettingsContext, type SettingsContextValue } from "./context";
import {
    DEFAULT_SETTINGS,
    LocalStorageSettingsStore,
    type SettingsStore,
    type WebSettings,
} from "./webSettings";

export function SettingsProvider({
    children,
    store,
}: {
    children: ReactNode;
    store?: SettingsStore;
}) {
    const [settings, setSettings] = useState<WebSettings>(() =>
        (store ?? new LocalStorageSettingsStore()).load(),
    );

    useEffect(() => {
        applyTheme({
            themeMode: settings.theme_mode,
            accentColor: settings.accent_color,
            fontScale: settings.font_scale,
        });
    }, [settings.theme_mode, settings.accent_color, settings.font_scale]);

    // 시스템 테마(OS 다크 모드) 전환을 즉시 반영한다 (로드맵 20장 "시스템 전환").
    useEffect(() => {
        if (settings.theme_mode !== "system" || typeof window === "undefined") {
            return;
        }
        const media = window.matchMedia("(prefers-color-scheme: dark)");
        const onChange = () => {
            applyTheme({
                themeMode: settings.theme_mode,
                accentColor: settings.accent_color,
                fontScale: settings.font_scale,
            });
        };
        media.addEventListener("change", onChange);
        return () => media.removeEventListener("change", onChange);
    }, [settings.theme_mode, settings.accent_color, settings.font_scale]);

    const updateSettings = useCallback(
        (patch: Partial<WebSettings>) => {
            setSettings((current) => {
                const next = { ...current, ...patch };
                (store ?? new LocalStorageSettingsStore()).save(next);
                return next;
            });
        },
        [store],
    );

    const resetSettings = useCallback(() => {
        setSettings({ ...DEFAULT_SETTINGS });
        (store ?? new LocalStorageSettingsStore()).save({
            ...DEFAULT_SETTINGS,
        });
    }, [store]);

    const value = useMemo<SettingsContextValue>(
        () => ({ settings, updateSettings, resetSettings }),
        [settings, updateSettings, resetSettings],
    );

    return (
        <SettingsContext.Provider value={value}>
            {children}
        </SettingsContext.Provider>
    );
}
