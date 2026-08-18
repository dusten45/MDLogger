import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/supabase", () => ({
  getSupabaseClient: vi.fn(),
}));

import { getSupabaseClient } from "../lib/supabase";
import { fetchDecks } from "./deckCatalog";

const mockInvoke = vi.fn();

beforeEach(() => {
  mockInvoke.mockReset();
  vi.mocked(getSupabaseClient).mockReturnValue({
    functions: { invoke: mockInvoke },
  } as never);
});

describe("deckCatalog", () => {
  it("deck-catalog 함수를 호출해 덱 목록을 반환한다", async () => {
    mockInvoke.mockResolvedValue({
      data: {
        decks: ["기타", "티아라멘츠"],
        stale: false,
        source: "gist",
        updated_at: "2026-08-18T00:00:00Z",
      },
      error: null,
    });

    const decks = await fetchDecks();

    expect(mockInvoke).toHaveBeenCalledWith("deck-catalog");
    expect(decks).toEqual(["기타", "티아라멘츠"]);
  });

  it("decks가 배열이 아니면 오류를 던진다", async () => {
    mockInvoke.mockResolvedValue({
      data: { decks: "not-an-array" },
      error: null,
    });

    await expect(fetchDecks()).rejects.toThrow("덱 목록 응답을 해석할 수 없습니다.");
  });
});
