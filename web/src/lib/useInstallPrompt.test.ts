import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
    checkIsIOS,
    checkIsStandalone,
    useInstallPrompt,
} from "./useInstallPrompt";

describe("useInstallPrompt", () => {
    let originalMatchMedia: typeof window.matchMedia;

    beforeEach(() => {
        originalMatchMedia = window.matchMedia;
    });

    afterEach(() => {
        window.matchMedia = originalMatchMedia;
        vi.restoreAllMocks();
    });

    it("초기에는 설치 불가 상태(canInstall=false)로 시작한다", () => {
        window.matchMedia = vi.fn().mockReturnValue({ matches: false });
        const { result } = renderHook(() => useInstallPrompt());
        expect(result.current.canInstall).toBe(false);
        expect(result.current.isStandalone).toBe(false);
    });

    it("beforeinstallprompt 이벤트를 캡처하여 canInstall을 true로 변경한다", () => {
        window.matchMedia = vi.fn().mockReturnValue({ matches: false });
        const { result } = renderHook(() => useInstallPrompt());

        const mockEvent = new Event("beforeinstallprompt") as Event & {
            platforms: string[];
            userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
            prompt: ReturnType<typeof vi.fn>;
        };
        mockEvent.platforms = ["web"];
        mockEvent.prompt = vi.fn().mockResolvedValue(undefined);
        mockEvent.userChoice = Promise.resolve({ outcome: "accepted", platform: "web" });

        act(() => {
            window.dispatchEvent(mockEvent);
        });

        expect(result.current.canInstall).toBe(true);
    });

    it("promptInstall을 호출하여 사용자 승인 결과를 반환한다", async () => {
        window.matchMedia = vi.fn().mockReturnValue({ matches: false });
        const { result } = renderHook(() => useInstallPrompt());

        const mockPrompt = vi.fn().mockResolvedValue(undefined);
        const mockEvent = new Event("beforeinstallprompt") as Event & {
            platforms: string[];
            userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
            prompt: typeof mockPrompt;
        };
        mockEvent.platforms = ["web"];
        mockEvent.prompt = mockPrompt;
        mockEvent.userChoice = Promise.resolve({ outcome: "accepted", platform: "web" });

        act(() => {
            window.dispatchEvent(mockEvent);
        });

        let outcome = false;
        await act(async () => {
            outcome = await result.current.promptInstall();
        });

        expect(mockPrompt).toHaveBeenCalledOnce();
        expect(outcome).toBe(true);
        expect(result.current.canInstall).toBe(false);
    });

    it("appinstalled 이벤트 수신 시 isStandalone을 true로 갱신한다", () => {
        window.matchMedia = vi.fn().mockReturnValue({ matches: false });
        const { result } = renderHook(() => useInstallPrompt());

        act(() => {
            window.dispatchEvent(new Event("appinstalled"));
        });

        expect(result.current.isStandalone).toBe(true);
        expect(result.current.canInstall).toBe(false);
    });

    it("checkIsStandalone은 standalone 미디어 쿼리를 감지한다", () => {
        window.matchMedia = vi.fn().mockImplementation((query: string) => ({
            matches: query === "(display-mode: standalone)",
        }));
        expect(checkIsStandalone()).toBe(true);
    });

    it("checkIsIOS는 iOS User-Agent를 판별한다", () => {
        const originalUserAgent = navigator.userAgent;
        Object.defineProperty(navigator, "userAgent", {
            value: "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
            configurable: true,
        });

        expect(checkIsIOS()).toBe(true);

        Object.defineProperty(navigator, "userAgent", {
            value: originalUserAgent,
            configurable: true,
        });
    });
});
