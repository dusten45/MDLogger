import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OfflineBanner } from "./OfflineBanner";
import * as networkHook from "../lib/useNetworkStatus";

describe("OfflineBanner", () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("온라인 상태일 때는 렌더링되지 않는다", () => {
        vi.spyOn(networkHook, "useNetworkStatus").mockReturnValue(true);
        const { container } = render(<OfflineBanner />);
        expect(container).toBeEmptyDOMElement();
    });

    it("오프라인 상태일 때 경고 배너 및 안내 문구를 표시한다", () => {
        vi.spyOn(networkHook, "useNetworkStatus").mockReturnValue(false);
        render(<OfflineBanner />);

        expect(screen.getByRole("alert")).toBeInTheDocument();
        expect(screen.getByText("오프라인 상태입니다")).toBeInTheDocument();
        expect(
            screen.getByText(/네트워크 연결이 끊어졌습니다/),
        ).toBeInTheDocument();
    });

    it("다시 시도 버튼 클릭 시 onRetry 콜백을 호출한다", () => {
        vi.spyOn(networkHook, "useNetworkStatus").mockReturnValue(false);
        const onRetry = vi.fn();
        render(<OfflineBanner onRetry={onRetry} />);

        const retryButton = screen.getByRole("button", { name: "다시 시도" });
        fireEvent.click(retryButton);

        expect(onRetry).toHaveBeenCalledOnce();
    });
});
