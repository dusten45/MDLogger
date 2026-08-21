import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRegisterSW } from "virtual:pwa-register/react";
import { ReloadPrompt } from "./ReloadPrompt";

vi.mock("virtual:pwa-register/react", () => ({
    useRegisterSW: vi.fn(),
}));

const mockedUseRegisterSW = vi.mocked(useRegisterSW);

describe("ReloadPrompt", () => {
    const updateServiceWorker = vi.fn();
    const setNeedRefresh = vi.fn();
    const setOfflineReady = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("새로고침이 필요 없을 때는 렌더링되지 않는다", () => {
        mockedUseRegisterSW.mockReturnValue({
            offlineReady: [false, setOfflineReady],
            needRefresh: [false, setNeedRefresh],
            updateServiceWorker,
        });

        const { container } = render(<ReloadPrompt />);
        expect(container).toBeEmptyDOMElement();
    });

    it("새 버전 배포 시 안내 메시지와 액션 버튼을 렌더링한다", () => {
        mockedUseRegisterSW.mockReturnValue({
            offlineReady: [false, setOfflineReady],
            needRefresh: [true, setNeedRefresh],
            updateServiceWorker,
        });

        render(<ReloadPrompt />);

        expect(screen.getByRole("alert")).toBeInTheDocument();
        expect(
            screen.getByText("새 버전이 배포되었습니다"),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("button", { name: "새로고침" }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("button", { name: "닫기" }),
        ).toBeInTheDocument();
    });

    it("새로고침 버튼 클릭 시 updateServiceWorker(true)를 호출한다", () => {
        mockedUseRegisterSW.mockReturnValue({
            offlineReady: [false, setOfflineReady],
            needRefresh: [true, setNeedRefresh],
            updateServiceWorker,
        });

        render(<ReloadPrompt />);

        const refreshButton = screen.getByRole("button", { name: "새로고침" });
        fireEvent.click(refreshButton);

        expect(updateServiceWorker).toHaveBeenCalledWith(true);
    });

    it("닫기 버튼 클릭 시 setNeedRefresh(false)를 호출한다", () => {
        mockedUseRegisterSW.mockReturnValue({
            offlineReady: [false, setOfflineReady],
            needRefresh: [true, setNeedRefresh],
            updateServiceWorker,
        });

        render(<ReloadPrompt />);

        const closeButton = screen.getByRole("button", { name: "닫기" });
        fireEvent.click(closeButton);

        expect(setNeedRefresh).toHaveBeenCalledWith(false);
    });
});
