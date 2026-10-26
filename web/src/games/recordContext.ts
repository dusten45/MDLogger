import { createContext, useContext } from "react";
import type { useRecordController } from "./useRecordController";

export const RecordContext = createContext<ReturnType<typeof useRecordController> | null>(null);

export function useRecord() {
    const value = useContext(RecordContext);
    if (!value) throw new Error("기록 상태는 로그인된 앱 안에서만 사용할 수 있습니다.");
    return value;
}
