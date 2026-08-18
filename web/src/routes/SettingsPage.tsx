import { useState } from "react";
import { useAuth } from "../auth/useAuth";
import {
    deleteAccount,
    downloadAccountExport,
    exportAccountData,
    revokeAllSessions,
} from "../auth/account";

// 설정 화면 (spec §5.2). 계정 운영은 3-B에서, 테마·강조색·글자 크기 등은 3-E에서 구현한다.
export function SettingsPage() {
    const { user, signOut } = useAuth();
    const [busy, setBusy] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);

    async function handleExport() {
        setBusy("export");
        setMessage(null);
        try {
            const data = await exportAccountData();
            downloadAccountExport(data);
            setMessage("계정 데이터를 내보냈습니다.");
        } catch {
            setMessage("계정 데이터 내보내기에 실패했습니다.");
        } finally {
            setBusy(null);
        }
    }

    async function handleRevokeAll() {
        setBusy("revoke");
        setMessage(null);
        try {
            await revokeAllSessions();
            // 모든 기기 로그아웃은 현재 기기도 즉시 로그아웃한다(제품 결정).
            // signOut이 로컬 세션을 제거하고 RequireAuth가 /login으로 이동시킨다.
            await signOut();
        } catch {
            setMessage("모든 기기 로그아웃에 실패했습니다.");
            setBusy(null);
        }
    }

    async function handleDelete() {
        if (
            !window.confirm(
                "계정을 삭제하면 모든 기록이 사라지며 되돌릴 수 없습니다. 계속할까요?",
            )
        ) {
            return;
        }
        setBusy("delete");
        setMessage(null);
        try {
            await deleteAccount();
            await signOut();
        } catch {
            setMessage("계정 삭제에 실패했습니다.");
            setBusy(null);
        }
    }

    return (
        <section aria-labelledby="settings-title">
            <h1 id="settings-title" className="page-title">
                설정
            </h1>
            <p className="page-description">
                테마·강조색·글자 크기·계정·동기화.
            </p>

            <section
                aria-labelledby="account-title"
                className="settings-section"
            >
                <h2 id="account-title" className="section-title">
                    계정 및 데이터
                </h2>
                {user?.email ? (
                    <p className="account-email">{user.email}</p>
                ) : null}
                {message ? (
                    <p className="settings-message" role="status">
                        {message}
                    </p>
                ) : null}
                <div className="settings-actions">
                    <button
                        type="button"
                        onClick={handleExport}
                        disabled={busy !== null}
                    >
                        {busy === "export"
                            ? "내보내는 중..."
                            : "계정 데이터 내보내기"}
                    </button>
                    <button
                        type="button"
                        onClick={handleRevokeAll}
                        disabled={busy !== null}
                    >
                        {busy === "revoke"
                            ? "처리 중..."
                            : "모든 기기 로그아웃"}
                    </button>
                    <button type="button" onClick={() => signOut()}>
                        로그아웃
                    </button>
                    <button
                        type="button"
                        className="danger"
                        onClick={handleDelete}
                        disabled={busy !== null}
                    >
                        {busy === "delete" ? "삭제 중..." : "계정 삭제"}
                    </button>
                </div>
            </section>
        </section>
    );
}
