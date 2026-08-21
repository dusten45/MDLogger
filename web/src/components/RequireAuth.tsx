import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { AuthUnavailable } from "./AuthUnavailable";

// 미로그인 사용자는 경기·통계·설정 URL 접근 시 로그인 화면으로 이동한다 (spec §5.2).
export function RequireAuth({ children }: { children: ReactNode }) {
    const { session, loading, authError, retrySession } = useAuth();
    const location = useLocation();

    if (loading) {
        return (
            <p className="auth-loading" role="status">
                인증 확인 중...
            </p>
        );
    }
    if (authError) {
        return <AuthUnavailable onRetry={retrySession} />;
    }
    if (!session) {
        return <Navigate to="/login" state={{ from: location }} replace />;
    }
    return <>{children}</>;
}
