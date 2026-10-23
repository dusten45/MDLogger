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

    it("새로고침 버튼 클릭 시 updateServiceWorker(true)를 호출한다", async () => {
        mockedUseRegisterSW.mockReturnValue({
            offlineReady: [false, setOfflineReady],
            needRefresh: [true, setNeedRefresh],
            updateServiceWorker,
        });

        render(<ReloadPrompt />);

        const refreshButton = screen.getByRole("button", { name: "새로고침" });
        fireEvent.click(refreshButton);

        await vi.waitFor(() => {
            expect(updateServiceWorker).toHaveBeenCalledWith(true);
        });
    });

    it("대기 중인 서비스 워커가 활성화되면 페이지를 새로고침한다", async () => {
        const reloadPage = vi.fn();
        let stateChangeHandler: (() => void) | undefined;
        const waitingWorker = {
            state: "installed" as ServiceWorkerState,
            postMessage: vi.fn(),
            addEventListener: vi.fn((event: string, cb: () => void) => {
                if (event === "statechange") {
                    stateChangeHandler = cb;
                }
            }),
        };
        const registration = {
            waiting: waitingWorker,
        } as unknown as ServiceWorkerRegistration;

        mockedUseRegisterSW.mockImplementation((options) => {
            options?.onRegisteredSW?.("/sw.js", registration);
            return {
                offlineReady: [false, setOfflineReady],
                needRefresh: [true, setNeedRefresh],
                updateServiceWorker,
            };
        });

        render(<ReloadPrompt reloadPage={reloadPage} />);

        fireEvent.click(screen.getByRole("button", { name: "새로고침" }));

        await vi.waitFor(() => {
            expect(waitingWorker.postMessage).toHaveBeenCalledWith({
                type: "SKIP_WAITING",
            });
            expect(updateServiceWorker).toHaveBeenCalledWith(true);
        });
        expect(reloadPage).not.toHaveBeenCalled();

        waitingWorker.state = "activated";
        stateChangeHandler?.();

        expect(reloadPage).toHaveBeenCalledTimes(1);
    });

    it("대기 중인 서비스 워커 이벤트가 없어도 폴백 타이머로 새로고침한다", async () => {
        vi.useFakeTimers();
        try {
            const reloadPage = vi.fn();
            const waitingWorker = {
                state: "installed" as ServiceWorkerState,
                postMessage: vi.fn(),
                addEventListener: vi.fn(),
            };
            const registration = {
                waiting: waitingWorker,
            } as unknown as ServiceWorkerRegistration;

            mockedUseRegisterSW.mockImplementation((options) => {
                options?.onRegisteredSW?.("/sw.js", registration);
                return {
                    offlineReady: [false, setOfflineReady],
                    needRefresh: [true, setNeedRefresh],
                    updateServiceWorker,
                };
            });

            render(<ReloadPrompt reloadPage={reloadPage} />);

            fireEvent.click(screen.getByRole("button", { name: "새로고침" }));
            await vi.advanceTimersByTimeAsync(1000);

            expect(reloadPage).toHaveBeenCalledTimes(1);
        } finally {
            vi.useRealTimers();
        }
    });

    it("이미 활성화된 서비스 워커(waiting이 null) 상태에서는 즉시 새로고침한다", async () => {
        const reloadPage = vi.fn();
        const registration = {
            waiting: null,
        } as unknown as ServiceWorkerRegistration;

        mockedUseRegisterSW.mockImplementation((options) => {
            options?.onRegisteredSW?.("/sw.js", registration);
            return {
                offlineReady: [false, setOfflineReady],
                needRefresh: [true, setNeedRefresh],
                updateServiceWorker,
            };
        });

        render(<ReloadPrompt reloadPage={reloadPage} />);

        fireEvent.click(screen.getByRole("button", { name: "새로고침" }));

        await vi.waitFor(() => {
            expect(updateServiceWorker).toHaveBeenCalledWith(true);
            expect(reloadPage).toHaveBeenCalledTimes(1);
        });
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
