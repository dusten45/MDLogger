import { useRegisterSW } from "virtual:pwa-register/react";
import "./ReloadPrompt.css";

export function ReloadPrompt() {
    const {
        needRefresh: [needRefresh, setNeedRefresh],
        updateServiceWorker,
    } = useRegisterSW({
        onRegisterError(error) {
            console.error("Service Worker registration error", error);
        },
    });

    function handleClose() {
        setNeedRefresh(false);
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
                    onClick={() => updateServiceWorker(true)}
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
