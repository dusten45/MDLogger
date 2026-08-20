import { useContext } from "react";
import { SettingsContext, type SettingsContextValue } from "./context";

export function useSettings(): SettingsContextValue {
  const context = useContext(SettingsContext);
  if (context === undefined) {
    throw new Error("useSettings는 SettingsProvider 안에서 사용해야 합니다.");
  }
  return context;
}
