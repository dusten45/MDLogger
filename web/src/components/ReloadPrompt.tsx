import { useRef } from "react";
import { useRegisterSW } from "virtual:pwa-register/react";
import "./ReloadPrompt.css";

const RELOAD_FALLBACK_TIMEOUT_MS = 1000;

function defaultReloadPage() {
    window.location.reload();
}

export interface ReloadPromptProps {
    reloadPage?: () => void;
}

export function ReloadPrompt({
    reloadPage = defaultReloadPage,
}: ReloadPromptProps = {}) {
    const registrationRef = useRef<ServiceWorkerRegistration | undefined>(
        undefined,
    );
    const reloadedRef = useRef(false);
    const {
        needRefresh: [needRefresh, setNeedRefresh],
        updateServiceWorker,
    } = useRegisterSW({
        onRegisteredSW(_swUrl, registration) {
            registrationRef.current = registration;
        },
        onRegisterError(error) {
            console.error("Service Worker registration error", error);
        },
    });

    function handleClose() {
        setNeedRefresh(false);
    }

    async function handleRefresh() {
        const triggerReload = () => {
            if (reloadedRef.current) {
                return;
            }
            reloadedRef.current = true;
            reloadPage();
        };

        const registration =
            registrationRef.current ??
            (await navigator.serviceWorker?.getRegistration?.());
        const waitingWorker = registration?.waiting;

        if (waitingWorker) {
            waitingWorker.addEventListener("statechange", () => {
                if (
                    waitingWorker.state === "activated" ||
                    waitingWorker.state === "redundant"
                ) {
                    triggerReload();
                }
            });
            navigator.serviceWorker?.addEventListener(
                "controllerchange",
                triggerReload,
                { once: true },
            );
            window.setTimeout(triggerReload, RELOAD_FALLBACK_TIMEOUT_MS);
            waitingWorker.postMessage({ type: "SKIP_WAITING" });
            await updateServiceWorker(true);
            return;
        }

        await updateServiceWorker(true);
        if (
            registration !== undefined ||
            "serviceWorker" in navigator ||
            reloadPage !== defaultReloadPage
        ) {
            triggerReload();
        }
    }

    if (!needRefresh) {
        return null;
    }

    return (
        <aside
            className="reload-prompt"
            role="alert"
            aria-live="polite"
            aria-label="앱 업데이트 알림"
        >
            <div className="reload-prompt__message">
                <strong>새 버전이 배포되었습니다</strong>
                <p>최신 기능과 변경 사항을 적용하려면 새로고침하세요.</p>
            </div>
            <div className="reload-prompt__actions">
                <button
                    type="button"
                    className="reload-prompt__btn reload-prompt__btn--primary"
                    onClick={() => void handleRefresh()}
                >
                    새로고침
                </button>
                <button
                    type="button"
                    className="reload-prompt__btn reload-prompt__btn--secondary"
                    onClick={handleClose}
                >
                    닫기
                </button>
            </div>
        </aside>
    );
}
