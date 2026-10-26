import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
        sessionGeneration: 0,
        isSessionCurrent: () => true,
        user: null,
        loading: false,
        recovery: false,
        authError: false,
        retrySession: vi.fn(),
        signIn: vi.fn(),
        signUp: vi.fn().mockResolvedValue({ error: null, needsConfirmation: true }),
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

describe("GitHub 저장소 아이콘 링크", () => {
    it.each([
        ["로그인", LoginPage],
        ["설정", SettingsPage],
    ])("%s 화면에서 공식 로고로 저장소를 새 탭에 연결한다", async (_, Page) => {
        const user = userEvent.setup();
        render(
            <MemoryRouter>
                <Page />
            </MemoryRouter>,
        );

        const link = await screen.findByRole("link", {
            name: "MDLogger GitHub 저장소 (새 탭에서 열림)",
        });
        expect(link).toHaveAttribute("href", "https://github.com/dusten45/MDLogger");
        expect(link).toHaveAttribute("target", "_blank");
        expect(link.getAttribute("rel")?.split(/\s+/)).toEqual(
            expect.arrayContaining(["noopener", "noreferrer"]),
        );
        expect(link).toHaveAttribute("title", "MDLogger GitHub 저장소 (새 탭에서 열림)");

        const icons = Array.from(link.querySelectorAll("img"));
        expect(icons.map((icon) => icon.getAttribute("src"))).toEqual([
            "/github-invertocat-black.svg",
            "/github-invertocat-white.svg",
        ]);
        for (const icon of icons) {
            expect(icon).toHaveAttribute("alt", "");
            expect(icon).toHaveAttribute("width", "32");
            expect(icon).toHaveAttribute("height", "32");
        }

        await user.tab({ shift: true });
        expect(link).toHaveFocus();
    });
});

describe("오픈소스 및 GPL-3.0 라이선스 링크와 회원가입 동의", () => {
    it("로그인 footer에서 정적 오픈소스 라이선스 고지 파일로 이동한다", () => {
        render(
            <MemoryRouter>
                <LoginPage />
            </MemoryRouter>,
        );

        expect(
            screen.queryByRole("link", { name: "프로그램 라이선스 (GPL-3.0)" }),
        ).not.toBeInTheDocument();
        expect(
            screen.getByRole("link", { name: "오픈소스 라이선스" }),
        ).toHaveAttribute("href", "/third-party-notices.txt");
    });

    it("설정의 법률 정책 영역에서 GPL-3.0 고지와 라이선스 링크를 표시한다", () => {
        render(
            <MemoryRouter>
                <SettingsPage />
            </MemoryRouter>,
        );

        expect(screen.getByTestId("settings-gpl-notice")).toHaveTextContent(
            "MDLogger는 GPL-3.0-or-later 라이선스로 배포되는 오픈소스 소프트웨어입니다.",
        );
        expect(
            screen.queryByRole("link", { name: "프로그램 라이선스 (GPL-3.0)" }),
        ).not.toBeInTheDocument();
        expect(
            screen.getByRole("link", { name: "오픈소스 라이선스" }),
        ).toHaveAttribute("href", "/third-party-notices.txt");
    });

    it("회원가입 시 필수 동의 체크박스 3개를 모두 체크해야 가입 요청을 보낸다", async () => {
        const user = userEvent.setup();
        render(
            <MemoryRouter>
                <LoginPage />
            </MemoryRouter>,
        );

        await user.click(screen.getByRole("button", { name: "회원가입" }));
        await user.type(screen.getByLabelText("이메일"), "duelist@example.com");
        await user.type(screen.getByLabelText("비밀번호"), "password123");

        const submitButtons = screen.getAllByRole("button", { name: "회원가입" });
        const submitButton = submitButtons[submitButtons.length - 1];
        await user.click(submitButton);

        expect(
            screen.getByRole("alert"),
        ).toHaveTextContent("필수 약관 및 만 14세 이상 확인에 모두 동의해 주세요.");
        expect(mockedUseAuth().signUp).not.toHaveBeenCalled();

        const checkboxes = screen.getAllByRole("checkbox");
        expect(checkboxes).toHaveLength(3);
        for (const checkbox of checkboxes) {
            await user.click(checkbox);
        }
        await user.click(submitButton);

        expect(mockedUseAuth().signUp).toHaveBeenCalledWith(
            "duelist@example.com",
            "password123",
        );
    });
});
