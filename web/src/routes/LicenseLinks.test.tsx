import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../auth/useAuth";
import { useInstallPrompt } from "../lib/useInstallPrompt";
import { useSettings } from "../settings/useSettings";
import { DEFAULT_SETTINGS } from "../settings/webSettings";
import { LoginPage } from "./LoginPage";
import { SettingsPage } from "./SettingsPage";

vi.mock("../auth/useAuth", () => ({ useAuth: vi.fn() }));
vi.mock("../games/modes", () => ({ listGameModes: vi.fn(() => Promise.resolve([])) }));
vi.mock("../lib/useInstallPrompt", () => ({ useInstallPrompt: vi.fn() }));
vi.mock("../settings/useSettings", () => ({ useSettings: vi.fn() }));

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseInstallPrompt = vi.mocked(useInstallPrompt);
const mockedUseSettings = vi.mocked(useSettings);

beforeEach(() => {
    mockedUseAuth.mockReturnValue({
        session: null,
        user: null,
        loading: false,
        recovery: false,
        authError: false,
        retrySession: vi.fn(),
        signIn: vi.fn(),
        signUp: vi.fn(),
        signOut: vi.fn(),
        resetPassword: vi.fn(),
        updatePassword: vi.fn(),
        clearRecovery: vi.fn(),
    } as ReturnType<typeof useAuth>);
    mockedUseSettings.mockReturnValue({
        settings: DEFAULT_SETTINGS,
        updateSettings: vi.fn(),
        resetSettings: vi.fn(),
    });
    mockedUseInstallPrompt.mockReturnValue({
        canInstall: false,
        isStandalone: false,
        isIOS: false,
        promptInstall: vi.fn(),
    });
});

describe("오픈소스 라이선스 링크", () => {
    it("로그인 footer에서 정적 고지 파일로 이동한다", () => {
        render(
            <MemoryRouter>
                <LoginPage />
            </MemoryRouter>,
        );

        expect(
            screen.getByRole("link", { name: "오픈소스 라이선스" }),
        ).toHaveAttribute("href", "/third-party-notices.txt");
    });

    it("설정의 법률 정책 영역에서 정적 고지 파일로 이동한다", () => {
        render(
            <MemoryRouter>
                <SettingsPage />
            </MemoryRouter>,
        );

        expect(
            screen.getByRole("link", { name: "오픈소스 라이선스" }),
        ).toHaveAttribute("href", "/third-party-notices.txt");
    });
});
