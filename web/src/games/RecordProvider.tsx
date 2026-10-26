import type { ReactNode } from "react";
import { useAuth } from "../auth/useAuth";
import { RecordContext } from "./recordContext";
import { useRecordController } from "./useRecordController";

// 화면 이동과 무관하게 요청을 유지하되, 인증 범위를 벗어나면 함께 폐기한다.
export function RecordProvider({ children }: { children: ReactNode }) {
    const { session, sessionGeneration } = useAuth();
    return <RecordScope key={`${session?.user.id}:${sessionGeneration}`}>{children}</RecordScope>;
}

function RecordScope({ children }: { children: ReactNode }) {
    const record = useRecordController();
    return <RecordContext.Provider value={record}>{children}</RecordContext.Provider>;
}
