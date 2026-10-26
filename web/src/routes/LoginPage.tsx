import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { AuthUnavailable } from "../components/AuthUnavailable";
import { GitHubLink } from "../components/GitHubLink";
import { UnofficialNotice } from "../components/UnofficialNotice";

type Mode = "login" | "signup" | "reset";

// 로그인 화면 (spec §6). 이메일/비밀번호 로그인·회원가입·비밀번호 재설정.
// 비밀번호 재설정 링크로 진입하면(PASSWORD_RECOVERY) 새 비밀번호 폼을 보여준다.
export function LoginPage() {
    const {
        session,
        loading,
        recovery,
        signIn,
        signUp,
        resetPassword,
        updatePassword,
        clearRecovery,
        authError,
        retrySession,
    } = useAuth();
    const navigate = useNavigate();

    const [mode, setMode] = useState<Mode>("login");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [ageConsent, setAgeConsent] = useState(false);
    const [termsConsent, setTermsConsent] = useState(false);
    const [privacyConsent, setPrivacyConsent] = useState(false);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    if (loading) {
        return (
            <p className="auth-loading" role="status">
                인증 확인 중...
            </p>
        );
    }
    if (session && !recovery) {
        return <Navigate to="/" replace />;
    }
    if (authError) {
        return <AuthUnavailable onRetry={retrySession} />;
    }

    async function handleSubmit(event: FormEvent) {
        event.preventDefault();
        setBusy(true);
        setError(null);
        setMessage(null);

        if (recovery) {
            const { error: updateError } = await updatePassword(password);
            if (updateError) {
                setError(updateError.message);
            } else {
                clearRecovery();
                navigate("/", { replace: true });
            }
            setBusy(false);
            return;
        }

        if (mode === "reset") {
            const { error: resetError } = await resetPassword(email);
            if (resetError) {
                setError(resetError.message);
            } else {
                setMessage(
                    "비밀번호 재설정 링크를 보냈습니다. 이메일을 확인해 주세요.",
                );
            }
            setBusy(false);
            return;
        }

        if (mode === "signup") {
            if (!ageConsent || !termsConsent || !privacyConsent) {
                setError(
                    "필수 약관 및 만 14세 이상 확인에 모두 동의해 주세요.",
                );
                setBusy(false);
                return;
            }
            const { error: signupError, needsConfirmation } = await signUp(
                email,
                password,
            );
            if (signupError) {
                setError(signupError.message);
            } else if (needsConfirmation) {
                setMessage(
                    "이메일 인증 링크를 보냈습니다. 이메일을 확인해 주세요.",
                );
            }
            setBusy(false);
            return;
        }

        const { error: signInError } = await signIn(email, password);
        if (signInError) {
            setError(signInError.message);
        }
        setBusy(false);
    }

    return (
        <div className="auth-page">
            <h1 className="page-title">MDLogger</h1>

            {recovery ? (
                <form className="auth-form" onSubmit={handleSubmit}>
                    <h2 className="section-title">새 비밀번호 설정</h2>
                    <label className="auth-field">
                        새 비밀번호
                        <input
                            type="password"
                            value={password}
                            onChange={(event) =>
                                setPassword(event.target.value)
                            }
                            required
                            minLength={6}
                            autoComplete="new-password"
                        />
                    </label>
                    <button type="submit" disabled={busy}>
                        {busy ? "처리 중..." : "비밀번호 변경"}
                    </button>
                </form>
            ) : (
                <form className="auth-form" onSubmit={handleSubmit}>
                    <div
                        className="auth-tabs"
                        role="group"
                        aria-label="인증 방식"
                    >
                        <button
                            type="button"
                            className={
                                mode === "login"
                                    ? "auth-tab auth-tab--active"
                                    : "auth-tab"
                            }
                            aria-pressed={mode === "login"}
                            onClick={() => {
                                setMode("login");
                                setError(null);
                                setMessage(null);
                            }}
                        >
                            로그인
                        </button>
                        <button
                            type="button"
                            className={
                                mode === "signup"
                                    ? "auth-tab auth-tab--active"
                                    : "auth-tab"
                            }
                            aria-pressed={mode === "signup"}
                            onClick={() => {
                                setMode("signup");
                                setAgeConsent(false);
                                setTermsConsent(false);
                                setPrivacyConsent(false);
                                setError(null);
                                setMessage(null);
                            }}
                        >
                            회원가입
                        </button>
                    </div>

                    {mode === "reset" ? (
                        <>
                            <h2 className="section-title">비밀번호 재설정</h2>
                            <label className="auth-field">
                                이메일
                                <input
                                    type="email"
                                    value={email}
                                    onChange={(event) =>
                                        setEmail(event.target.value)
                                    }
                                    required
                                    autoComplete="email"
                                />
                            </label>
                            <button type="submit" disabled={busy}>
                                {busy ? "보내는 중..." : "재설정 링크 보내기"}
                            </button>
                            <button
                                type="button"
                                className="auth-link"
                                onClick={() => {
                                    setMode("login");
                                    setError(null);
                                    setMessage(null);
                                }}
                            >
                                로그인으로 돌아가기
                            </button>
                        </>
                    ) : (
                        <>
                            <label className="auth-field">
                                이메일
                                <input
                                    type="email"
                                    value={email}
                                    onChange={(event) =>
                                        setEmail(event.target.value)
                                    }
                                    required
                                    autoComplete="email"
                                />
                            </label>
                            <label className="auth-field">
                                비밀번호
                                <input
                                    type="password"
                                    value={password}
                                    onChange={(event) =>
                                        setPassword(event.target.value)
                                    }
                                    required
                                    minLength={6}
                                    autoComplete={
                                        mode === "signup"
                                            ? "new-password"
                                            : "current-password"
                                    }
                                />
                            </label>
                            {mode === "signup" ? (
                                <div
                                    className="auth-consents"
                                    role="group"
                                    aria-label="회원가입 필수 동의"
                                >
                                    <label className="auth-consent-item">
                                        <input
                                            type="checkbox"
                                            checked={ageConsent}
                                            onChange={(event) =>
                                                setAgeConsent(
                                                    event.target.checked,
                                                )
                                            }
                                        />
                                        <span>[필수] 만 14세 이상입니다</span>
                                    </label>
                                    <label className="auth-consent-item">
                                        <input
                                            type="checkbox"
                                            checked={termsConsent}
                                            onChange={(event) =>
                                                setTermsConsent(
                                                    event.target.checked,
                                                )
                                            }
                                        />
                                        <span>
                                            [필수]{" "}
                                            <Link to="/terms">이용약관</Link>에
                                            동의합니다
                                        </span>
                                    </label>
                                    <label className="auth-consent-item">
                                        <input
                                            type="checkbox"
                                            checked={privacyConsent}
                                            onChange={(event) =>
                                                setPrivacyConsent(
                                                    event.target.checked,
                                                )
                                            }
                                        />
                                        <span>
                                            [필수]{" "}
                                            <Link to="/privacy">
                                                개인정보 처리방침
                                            </Link>{" "}
                                            (개인정보 수집·이용 및 국외 이전)에
                                            동의합니다
                                        </span>
                                    </label>
                                </div>
                            ) : null}
                            <button type="submit" disabled={busy}>
                                {busy
                                    ? "처리 중..."
                                    : mode === "signup"
                                      ? "회원가입"
                                      : "로그인"}
                            </button>
                            {mode === "signup" ? (
                                <p className="auth-legal-notice">
                                    본 서비스는 만 14세 이상만 이용 가능하며,
                                    회원가입 시 서비스 이용약관 및 개인정보
                                    처리방침에 동의해야 합니다.
                                </p>
                            ) : null}
                            {mode === "login" ? (
                                <button
                                    type="button"
                                    className="auth-link"
                                    onClick={() => {
                                        setMode("reset");
                                        setError(null);
                                        setMessage(null);
                                    }}
                                >
                                    비밀번호를 잊으셨나요?
                                </button>
                            ) : null}
                        </>
                    )}
                </form>
            )}

            {error ? (
                <p className="auth-error" role="alert">
                    {error}
                </p>
            ) : null}
            {message ? (
                <p className="auth-message" role="status">
                    {message}
                </p>
            ) : null}

            <UnofficialNotice />

            <footer className="auth-footer">
                <div className="auth-footer-links">
                    <Link to="/privacy">개인정보 처리방침</Link>
                    <span aria-hidden="true">·</span>
                    <Link to="/terms">이용약관</Link>
                    <span aria-hidden="true">·</span>
                    <a href="/third-party-notices.txt">오픈소스 라이선스</a>
                </div>
                <GitHubLink />
            </footer>
        </div>
    );
}
