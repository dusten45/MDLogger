import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

// 이메일 인증·비밀번호 재설정 콜백 (spec §6).
// detectSessionInUrl이 URL의 인증 토큰을 처리하므로, 세션 확정 후 이동만 한다.
export function AuthCallbackPage() {
  const { session, loading } = useAuth();

  if (loading) {
    return <p className="auth-loading">인증 처리 중...</p>;
  }
  return <Navigate to={session ? "/" : "/login"} replace />;
}
