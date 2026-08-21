import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../auth/useAuth";
import { RequireAuth } from "./RequireAuth";

vi.mock("../auth/useAuth", () => ({ useAuth: vi.fn() }));

const mockedUseAuth = vi.mocked(useAuth);
const retrySession = vi.fn();

function setAuthState(overrides: Record<string, unknown> = {}) {
  mockedUseAuth.mockReturnValue({
    session: null,
    user: null,
    loading: false,
    recovery: false,
    authError: false,
    retrySession,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    resetPassword: vi.fn(),
    updatePassword: vi.fn(),
    clearRecovery: vi.fn(),
    ...overrides,
  } as ReturnType<typeof useAuth>);
}

function renderRequireAuth() {
  return render(
    <MemoryRouter>
      <RequireAuth>
        <p>보호된 화면</p>
      </RequireAuth>
    </MemoryRouter>,
  );
}

describe("RequireAuth", () => {
  beforeEach(() => {
    retrySession.mockReset();
  });

  it("인증 확인 중에는 진행 상태를 표시한다", () => {
    setAuthState({ loading: true });

    renderRequireAuth();

    expect(screen.getByText("인증 확인 중...")).toBeInTheDocument();
  });

  it("인증 서버 장애에서는 재시도 가능한 안내를 표시한다", () => {
    setAuthState({ authError: true });

    renderRequireAuth();

    expect(
      screen.getByRole("heading", { name: "인증 서비스를 확인할 수 없습니다" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(retrySession).toHaveBeenCalledOnce();
  });

  it("유효한 세션에서 보호된 화면을 표시한다", () => {
    setAuthState({ session: { user: {} } });

    renderRequireAuth();

    expect(screen.getByText("보호된 화면")).toBeInTheDocument();
  });
});
