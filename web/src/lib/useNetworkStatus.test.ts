import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNetworkStatus } from "./useNetworkStatus";

describe("useNetworkStatus", () => {
    let originalOnLine: boolean;

    beforeEach(() => {
        originalOnLine = navigator.onLine;
    });

    afterEach(() => {
        vi.restoreAllMocks();
        Object.defineProperty(navigator, "onLine", {
            value: originalOnLine,
            configurable: true,
        });
    });

    it("초기 온라인 상태를 정확히 반영한다", () => {
        Object.defineProperty(navigator, "onLine", {
            value: true,
            configurable: true,
        });
        const { result } = renderHook(() => useNetworkStatus());
        expect(result.current).toBe(true);
    });

    it("offline 및 online 이벤트를 수신하여 상태를 동적으로 변경한다", () => {
        Object.defineProperty(navigator, "onLine", {
            value: true,
            configurable: true,
        });
        const { result } = renderHook(() => useNetworkStatus());
        expect(result.current).toBe(true);

        act(() => {
            window.dispatchEvent(new Event("offline"));
        });
        expect(result.current).toBe(false);

        act(() => {
            window.dispatchEvent(new Event("online"));
        });
        expect(result.current).toBe(true);
    });
});
