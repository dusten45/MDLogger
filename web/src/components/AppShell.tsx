import { NavLink, Outlet } from "react-router-dom";
import { OfflineBanner } from "./OfflineBanner";
import { ReloadPrompt } from "./ReloadPrompt";
import "./AppShell.css";

// 핵심 내비게이션 최대 네 개 (spec §5.2, 로드맵 18.1).
const NAV_ITEMS = [
  { to: "/", label: "기록", end: true },
  { to: "/stats", label: "통계", end: false },
  { to: "/history", label: "기록 목록", end: false },
  { to: "/settings", label: "설정", end: false },
];

export function AppShell() {
  return (
    <div className="app-shell">
      <OfflineBanner />
      <main className="app-main">
        <Outlet />
      </main>
      <ReloadPrompt />
      <nav className="app-nav" aria-label="주요 내비게이션">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              isActive ? "nav-item nav-item--active" : "nav-item"
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
