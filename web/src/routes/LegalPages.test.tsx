/// <reference types="node" />

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PrivacyPolicyPage } from "./PrivacyPolicyPage";
import { TermsPage } from "./TermsPage";

const privacyMarkdown = readFileSync(
    resolve(import.meta.dirname, "../../../docs/privacy-policy.md"),
    "utf8",
);
const termsMarkdown = readFileSync(
    resolve(import.meta.dirname, "../../../docs/terms-of-service.md"),
    "utf8",
);

function expectMarkdownParity(container: HTMLElement, markdown: string) {
    const displayed = Array.from(
        container.querySelectorAll(".legal-meta, .legal-section"),
        (element) => element.textContent,
    ).join("");
    const plainMarkdown = markdown
        .replace(/^# .+\n/, "")
        .replace(/^---$/gm, "")
        .replace(/^(?:#{2,3} |- |\d+\. )/gm, "")
        .replace(/\*\*|`/g, "");
    expect(displayed.replace(/\s+/g, "")).toBe(plainMarkdown.replace(/\s+/g, ""));
    expect(displayed).not.toMatch(/guest_game_observations|소급.*수정.*삭제되지/);
}

describe("LegalPages", () => {
    describe("PrivacyPolicyPage", () => {
        it("개인정보 처리방침의 조항과 데이터 경계를 공개 문서와 동일하게 표시한다", () => {
            const { container } = render(
                <MemoryRouter>
                    <PrivacyPolicyPage />
                </MemoryRouter>,
            );

            expect(
                screen.getByRole("heading", { name: "개인정보 처리방침", level: 1 }),
            ).toBeInTheDocument();
            expect(screen.getByText(/제1조 \(개인정보의 처리 목적\)/)).toBeInTheDocument();
            expect(screen.getByText(/제2조 \(개인정보의 처리 및 보유 기간\)/)).toBeInTheDocument();
            expect(screen.getByText(/제3조 \(처리하는 개인정보의 항목\)/)).toBeInTheDocument();
            expect(screen.getByText(/제4조 \(개인정보의 제3자 제공\)/)).toBeInTheDocument();
            expect(screen.getByText(/제5조 \(개인정보 처리의 위탁\)/)).toBeInTheDocument();
            expect(screen.getByText(/제6조 \(개인정보의 국외 이전\)/)).toBeInTheDocument();
            expect(screen.getByText(/제7조 \(개인정보의 파기 절차 및 방법\)/)).toBeInTheDocument();
            expect(screen.getByText(/제8조 \(정보주체와 법정대리인의 권리·의무 및 행사방법\)/)).toBeInTheDocument();
            expect(screen.getByText(/제9조 \(개인정보의 안전성 확보 조치\)/)).toBeInTheDocument();
            expect(screen.getByText(/제10조 \(개인정보 자동 수집 장치의 설치·운영 및 거부에 관한 사항\)/)).toBeInTheDocument();
            expect(screen.getByText(/제11조 \(개인정보 보호책임자 및 고충처리 연락처\)/)).toBeInTheDocument();
            expect(screen.getByText(/제12조 \(정보주체의 권익침해에 대한 구제방법\)/)).toBeInTheDocument();
            expect(screen.getByText(/제13조 \(개인정보 처리방침의 변경\)/)).toBeInTheDocument();

            // 만 14세 미만 조항 및 권익침해 구제기관 확인
            expect(screen.getByText(/만 14세 미만은 회원가입을 할 수 없습니다/)).toBeInTheDocument();
            expect(screen.getByText(/1833-6972/)).toBeInTheDocument();
            expect(screen.getByText(/privacy\.kisa\.or\.kr/)).toBeInTheDocument();
            expect(screen.getByText(/듀얼 환경 분석 데이터 \(게스트 및 회원 공통\)/)).toBeInTheDocument();
            expect(screen.getByText(/timezone_offset_minutes/)).toBeInTheDocument();
            const content = screen.getByRole("main");
            for (const fact of [
                "analytics.duel_observations",
                "경기 수정이 서버에 반영되면 분석 관측도 갱신됩니다.",
                "철회 표시(withdrawn_at)를 남기며 관측 행 자체는 보존합니다.",
                "계정 삭제만으로 분석 관측이 삭제되거나 철회되지는 않습니다.",
                "앱 초기화는 이 기기의 로컬 데이터 정리이며 서버 기록 삭제나 분석 관측 철회가 아닙니다.",
                "game_create_receipts",
                "완전한 익명 데이터라는 뜻은 아닙니다.",
                "게스트 메모는 분석 서버로 전송하지 않습니다.",
                "계정 JSON 내보내기는 프로필·개인 경기 기록·등록 장치만 포함합니다.",
                "전체 계정 백업이나 복원 파일이 아닙니다.",
                "분석 전송만 끄는 전역 설정은 없습니다.",
                "서버에 동의 버전·시각을 별도로 저장하지 않습니다.",
                "Windows 설치판은 시작 후 공개 GitHub Releases를 자동 확인합니다.",
                "MDLogger-Updater",
                "%LOCALAPPDATA%\\MDLogger\\updates",
                "MDLOGGER_DATA_DIR과 별개",
                "실패하면 복구 자료를 보존하여 다음 실행에서 복구",
                "경기 데이터를 IndexedDB에 영구 저장하거나 오프라인 전송 대기열에 보관하지 않습니다.",
                "API·Database 로그 보유기간은 1일, Auth Audit Logs는 1시간입니다.",
                "서비스 DB의 경기·분석·진단 테이블에 적용되는 삭제 기한이 아닙니다.",
                "자동 정리 Cron은 설정되어 있지 않습니다.",
                "운영자의 별도 DB 백업도 없습니다.",
                "사용자 정의 Worker 코드, Logpush, Tail Workers 및 Cron 작업은 사용하지 않습니다.",
                "운영자의 개인 Gmail 계정을 이용한 인증 메일 SMTP 발송",
                "경기 기록과 메모는 인증 메일에 포함하지 않습니다.",
                "MDLogger 계정 삭제로 자동 삭제되지 않습니다.",
                "문구 정비일은 새 시행일이나 사전 공지·배포 완료를 뜻하지 않습니다.",
            ]) {
                expect(content).toHaveTextContent(fact);
            }
            expectMarkdownParity(container, privacyMarkdown);

            // 외부 위탁 및 국외 이전 수탁자 명시 확인
            expect(screen.getAllByText(/Supabase, Inc\./).length).toBeGreaterThan(0);
            expect(screen.getAllByText(/Cloudflare, Inc\./).length).toBeGreaterThan(0);
            expect(screen.getAllByText(/GitHub, Inc\./).length).toBeGreaterThan(0);
            expect(screen.getAllByText(/Google LLC \(Gmail\)/).length).toBeGreaterThan(0);

            // 약관 링크 확인
            expect(
                screen.getByRole("link", { name: "서비스 이용약관 보기" }),
            ).toHaveAttribute("href", "/terms");
        });
    });

    describe("TermsPage", () => {
        it("이용약관의 오픈소스 권리와 삭제 범위를 공개 문서와 동일하게 표시한다", () => {
            const { container } = render(
                <MemoryRouter>
                    <TermsPage />
                </MemoryRouter>,
            );

            expect(
                screen.getByRole("heading", { name: "서비스 이용약관", level: 1 }),
            ).toBeInTheDocument();
            expect(screen.getByText(/제1조 \(목적\)/)).toBeInTheDocument();
            expect(screen.getByText(/제2조 \(용어의 정의\)/)).toBeInTheDocument();
            expect(screen.getByText(/제3조 \(약관의 효력 및 변경\)/)).toBeInTheDocument();
            expect(screen.getByText(/제4조 \(이용계약의 체결 및 계정 관리\)/)).toBeInTheDocument();
            expect(screen.getByText(/제5조 \(서비스의 제공 및 변경\)/)).toBeInTheDocument();
            expect(screen.getByText(/제6조 \(이용자의 의무 및 오픈소스 권리 보장\)/)).toBeInTheDocument();
            expect(screen.getByText(/제7조 \(계약 해지 및 회원 탈퇴\)/)).toBeInTheDocument();
            expect(screen.getByText(/제8조 \(면책 조항\)/)).toBeInTheDocument();
            expect(screen.getByText(/제9조 \(준거법 및 재판관할\)/)).toBeInTheDocument();
            expect(screen.getByText(/부칙/)).toBeInTheDocument();

            // 가입 제한, 오픈소스 권리 및 개인 기록과 분석 관측의 처리 경계 확인
            expect(screen.getByText(/본 서비스는 만 14세 이상의 이용자를 대상으로 제공되며/)).toBeInTheDocument();
            expect(screen.getByText(/허용된 경기 정보를 분석 서버로 전송하는 사람/)).toBeInTheDocument();
            expect(screen.getByText(/GPL-3\.0-or-later/)).toBeInTheDocument();
            const content = screen.getByRole("main");
            for (const fact of [
                "경기 수정이 서버에 반영되면 분석 관측도 갱신됩니다.",
                "철회 표시(withdrawn_at)를 남기며 관측 행 자체는 보존합니다.",
                "계정 삭제만으로 분석 관측이 삭제되거나 철회되지는 않습니다.",
                "앱 초기화는 이 기기의 로컬 데이터 정리이며 서버 기록 삭제나 분석 관측 철회가 아닙니다.",
                "계정 JSON 내보내기는 프로필·개인 경기 기록·등록 장치만 포함합니다.",
                "전체 계정 백업이나 복원 파일이 아닙니다.",
                "웹/PWA의 경기 기능은 온라인 전용입니다.",
            ]) {
                expect(content).toHaveTextContent(fact);
            }
            expectMarkdownParity(container, termsMarkdown);

            // 개인정보 처리방침 링크 확인
            expect(
                screen.getByRole("link", { name: "개인정보 처리방침 보기" }),
            ).toHaveAttribute("href", "/privacy");
        });
    });
});
