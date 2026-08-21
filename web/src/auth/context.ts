// 인증 컨텍스트 정의 (컴포넌트 없음, spec §6).
// 프로바이더는 `AuthProvider.tsx`, 훅은 `useAuth.ts`에 분리한다.

import { createContext } from "react";
import type { AuthError, Session, User } from "@supabase/supabase-js";

export interface AuthContextValue {
    session: Session | null;
    user: User | null;
    loading: boolean;
    recovery: boolean;
    authError: boolean;
    retrySession(): void;
    signIn(
        email: string,
        password: string,
    ): Promise<{ error: AuthError | null }>;
    signUp(
        email: string,
        password: string,
    ): Promise<{ error: AuthError | null; needsConfirmation: boolean }>;
    signOut(): Promise<void>;
    resetPassword(email: string): Promise<{ error: AuthError | null }>;
    updatePassword(password: string): Promise<{ error: AuthError | null }>;
    clearRecovery(): void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(
    undefined,
);
