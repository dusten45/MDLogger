import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { LocalStorageSettingsStore } from "./settings/webSettings";
import { applyTheme } from "./theme/applyTheme";
import "./theme/tokens.css";
import "./index.css";

// 시작 시 저장된 설정으로 테마·강조색·글자 크기를 적용한다 (spec §5.3).
const settings = new LocalStorageSettingsStore().load();
applyTheme({
  themeMode: settings.theme_mode,
  accentColor: settings.accent_color,
  fontScale: settings.font_scale,
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
