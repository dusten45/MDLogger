import { useNetworkStatus } from "../lib/useNetworkStatus";
import "./OfflineBanner.css";

interface OfflineBannerProps {
    onRetry?: () => void;
}

export function OfflineBanner({ onRetry }: OfflineBannerProps) {
    const isOnline = useNetworkStatus();

    if (isOnline) {
        return null;
    }

    function handleRetry() {
        if (onRetry) {
            onRetry();
        } else {
            window.location.reload();
        }
    }

    return (
        <aside
            className="offline-banner"
            role="alert"
            aria-live="assertive"
            aria-label="오프라인 상태 알림"
        >
            <div className="offline-banner__content">
                <div className="offline-banner__header">
                    <span className="offline-banner__icon" aria-hidden="true">
                        ⚠️
                    </span>
                    <strong>오프라인 상태입니다</strong>
                </div>
                <p className="offline-banner__text">
                    네트워크 연결이 끊어졌습니다. 기록 및 통계 조회를 이용하려면
                    인터넷 연결을 확인해 주세요.
                </p>
            </div>
            <button
                type="button"
                className="offline-banner__retry-btn"
                onClick={handleRetry}
            >
                다시 시도
            </button>
        </aside>
    );
}
