// 인증 프로바이더 (spec §6, P12). Supabase 브라우저 SDK + PKCE + 로그인 상태 유지.
// 이메일/비밀번호 로그인·회원가입·이메일 인증·비밀번호 재설정·세션 복구를 담는다.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { getSupabaseClient } from "../lib/supabase";
import { AuthContext, type AuthContextValue } from "./context";

export function AuthProvider({ children }: { children: ReactNode }) {
    const [session, setSession] = useState<AuthContextValue["session"]>(null);
    const [loading, setLoading] = useState(true);
    const [recovery, setRecovery] = useState(false);
    const [authError, setAuthError] = useState(false);
    const [sessionAttempt, setSessionAttempt] = useState(0);

    useEffect(() => {
        let active = true;
        let unsubscribe: (() => void) | undefined;

        async function restoreSession() {
            setLoading(true);
            setAuthError(false);
            try {
                const supabase = getSupabaseClient();
                const { data, error } = await supabase.auth.getSession();
                if (!active) {
                    return;
                }
                setSession(data.session);
                setAuthError(error !== null);
                const { data: listener } = supabase.auth.onAuthStateChange(
                    (event, newSession) => {
                        if (!active) {
                            return;
                        }
                        setSession(newSession);
                        setAuthError(false);
                        // 비밀번호 재설정 링크를 통해 진입하면 PASSWORD_RECOVERY가 발생한다.
                        // PKCE 흐름에서는 URL에 type=recovery가 없을 수 있으므로 이 이벤트로 감지한다.
                        if (event === "PASSWORD_RECOVERY") {
                            setRecovery(true);
                        }
                    },
                );
                unsubscribe = () => listener.subscription.unsubscribe();
            } catch {
                if (active) {
                    setSession(null);
                    setAuthError(true);
                }
            } finally {
                if (active) {
                    setLoading(false);
                }
            }
        }

        void restoreSession();
        return () => {
            active = false;
            unsubscribe?.();
        };
    }, [sessionAttempt]);

    const value = useMemo<AuthContextValue>(
        () => ({
            session,
            user: session?.user ?? null,
            loading,
            recovery,
            authError,
            retrySession() {
                setSessionAttempt((attempt) => attempt + 1);
            },
            async signIn(email, password) {
                const { error } =
                    await getSupabaseClient().auth.signInWithPassword({
                        email,
                        password,
                    });
                return { error };
            },
            async signUp(email, password) {
                const { data, error } = await getSupabaseClient().auth.signUp({
                    email,
                    password,
                    options: {
                        // 이메일 인증 완료 후 이 콜백으로 돌아온다(spec §6).
                        emailRedirectTo: `${window.location.origin}/auth/callback`,
                    },
                });
                // 이메일 인증이 켜져 있으면 세션이 null로 반환된다.
                return { error, needsConfirmation: data.session === null };
            },
            async signOut() {
                await getSupabaseClient().auth.signOut();
            },
            async resetPassword(email) {
                const { error } =
                    await getSupabaseClient().auth.resetPasswordForEmail(
                        email,
                        {
                            // 재설정 링크는 로그인 화면으로 돌아와 새 비밀번호 폼을 보여준다.
                            redirectTo: `${window.location.origin}/login`,
                        },
                    );
                return { error };
            },
            async updatePassword(password) {
                const { error } = await getSupabaseClient().auth.updateUser({
                    password,
                });
                return { error };
            },
            clearRecovery() {
                setRecovery(false);
            },
        }),
        [session, loading, recovery, authError],
    );

    return (
        <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
    );
}
