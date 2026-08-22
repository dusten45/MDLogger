import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PrivacyPolicyPage } from "./PrivacyPolicyPage";
import { TermsPage } from "./TermsPage";

describe("LegalPages", () => {
    describe("PrivacyPolicyPage", () => {
        it("개인정보 처리방침 제목과 주요 법정 조항을 모두 렌더링한다", () => {
            render(
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
            expect(screen.getByText(/제12조 \(개인정보 처리방침의 변경\)/)).toBeInTheDocument();

            // 만 14세 미만 조항 확인
            expect(screen.getByText(/만 14세 미만 아동의 개인정보를 수집하지 않으며/)).toBeInTheDocument();

            // 외부 위탁 및 국외 이전 수탁자 명시 확인
            expect(screen.getAllByText(/Supabase, Inc\./).length).toBeGreaterThan(0);
            expect(screen.getAllByText(/Cloudflare, Inc\./).length).toBeGreaterThan(0);
            expect(screen.getAllByText(/GitHub, Inc\./).length).toBeGreaterThan(0);

            // 약관 링크 확인
            expect(
                screen.getByRole("link", { name: "서비스 이용약관 보기" }),
            ).toHaveAttribute("href", "/terms");
        });
    });

    describe("TermsPage", () => {
        it("서비스 이용약관 제목과 주요 조항을 모두 렌더링한다", () => {
            render(
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
            expect(screen.getByText(/제6조 \(이용자의 의무 및 금지행위\)/)).toBeInTheDocument();
            expect(screen.getByText(/제7조 \(계약 해지 및 회원 탈퇴\)/)).toBeInTheDocument();
            expect(screen.getByText(/제8조 \(면책 조항\)/)).toBeInTheDocument();
            expect(screen.getByText(/제9조 \(준거법 및 재판관할\)/)).toBeInTheDocument();
            expect(screen.getByText(/부칙/)).toBeInTheDocument();

            // 만 14세 미만 가입 제한 조항 확인
            expect(screen.getByText(/본 서비스는 만 14세 이상의 이용자를 대상으로 제공되며/)).toBeInTheDocument();

            // 개인정보 처리방침 링크 확인
            expect(
                screen.getByRole("link", { name: "개인정보 처리방침 보기" }),
            ).toHaveAttribute("href", "/privacy");
        });
    });
});
