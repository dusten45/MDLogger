// 인증 서비스에 연결할 수 없을 때 로그인·보호 화면에서 공통으로 보여 준다.

export function AuthUnavailable({ onRetry }: { onRetry(): void }) {
    return (
        <section
            className="auth-unavailable"
            aria-labelledby="auth-unavailable-title"
        >
            <h1 id="auth-unavailable-title" className="page-title">
                인증 서비스를 확인할 수 없습니다
            </h1>
            <p className="page-description" role="alert">
                네트워크 연결을 확인한 뒤 다시 시도해 주세요.
            </p>
            <button type="button" onClick={onRetry}>
                다시 시도
            </button>
        </section>
    );
}
