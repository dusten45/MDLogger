import "./UnofficialNotice.css";

export const KOREAN_UNOFFICIAL_NOTICE =
    "MDLogger는 Yu-Gi-Oh! MASTER DUEL을 위한 비공식 전적 기록 및 통계 도구이며, KONAMI 또는 관련 권리자와 제휴·후원·승인 관계가 없습니다. Yu-Gi-Oh! MASTER DUEL 및 관련 명칭, 표장, 게임 자산에 관한 권리는 각 권리자에게 있습니다.";

export const ENGLISH_UNOFFICIAL_NOTICE =
    "MDLogger is an unofficial match logging and analytics tool for Yu-Gi-Oh! MASTER DUEL. It is not affiliated with, endorsed by, sponsored by, or approved by KONAMI or the relevant rights holders. Rights in Yu-Gi-Oh! MASTER DUEL and related names, marks, and game assets belong to their respective rights holders.";

export function UnofficialNotice() {
    return (
        <div
            className="unofficial-notice"
            role="note"
            aria-label="비공식 도구 및 권리 관계 안내"
        >
            <p lang="ko">{KOREAN_UNOFFICIAL_NOTICE}</p>
            <p lang="en">{ENGLISH_UNOFFICIAL_NOTICE}</p>
        </div>
    );
}
