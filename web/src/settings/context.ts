// 설정 컨텍스트 정의 (컴포넌트 없음, spec §4).
// 프로바이더는 `SettingsProvider.tsx`, 훅은 `useSettings.ts`에 분리한다.

import { createContext } from "react";
import type { WebSettings } from "./webSettings";

export interface SettingsContextValue {
  settings: WebSettings;
  updateSettings(patch: Partial<WebSettings>): void;
  resetSettings(): void;
}

export const SettingsContext = createContext<SettingsContextValue | undefined>(
  undefined,
);
