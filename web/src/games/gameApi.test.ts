import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/supabase", () => ({
  getSupabaseClient: vi.fn(),
}));

import { getSupabaseClient } from "../lib/supabase";
import {
  GameConflictError,
  createGame,
  prepareCreate,
  deleteGame,
  updateGame,
} from "./gameApi";

const mockRpc = vi.fn();

beforeEach(() => {
  mockRpc.mockReset();
  vi.mocked(getSupabaseClient).mockReturnValue({
    rpc: mockRpc,
    from: vi.fn(),
  } as never);
});

describe("gameApi", () => {
  it("createGame은 apply_game_changes 단일 change로 호출한다", async () => {
    const attempt = prepareCreate({
      played_at: "2026-08-18T12:00:00", result: "win", turn_order: "first",
      play_context_id: "rank_2026_08", standing_kind: "rank",
    });
    mockRpc.mockResolvedValue({
      data: {
        results: [{ id: attempt.id, status: "applied", change_version: 1 }],
      },
      error: null,
    });

    const result = await createGame(attempt);

    expect(mockRpc).toHaveBeenCalledWith(
      "apply_game_changes",
      expect.objectContaining({
        sync_schema_version: 1,
        payload_version: 2,
        changes: [
          expect.objectContaining({
            op: "create",
            id: attempt.id,
            request_id: attempt.request_id,
            payload: expect.objectContaining({ result: "win" }),
          }),
        ],
      }),
    );
    expect(result.change_version).toBe(1);
  });

  it("updateGame은 expected_change_version을 전달한다", async () => {
    mockRpc.mockResolvedValue({
      data: {
        results: [
          {
            id: "x",
            status: "applied",
            change_version: 2,
          },
        ],
      },
      error: null,
    });

    await expect(updateGame("x", 1, { result: "lose" })).resolves.toEqual({ id: "x", change_version: 2 });

    expect(mockRpc).toHaveBeenCalledWith(
      "apply_game_changes",
      expect.objectContaining({
        changes: [
          expect.objectContaining({
            op: "update",
            expected_change_version: 1,
          }),
        ],
      }),
    );
  });

  it("deleteGame은 expected_change_version 없이 delete를 호출한다", async () => {
    mockRpc.mockResolvedValue({
      data: { results: [{ id: "x", status: "applied" }] },
      error: null,
    });

    await deleteGame("x");

    expect(mockRpc).toHaveBeenCalledWith(
      "apply_game_changes",
      expect.objectContaining({
        changes: [expect.objectContaining({ op: "delete", id: "x" })],
      }),
    );
  });

  it("conflict 응답은 GameConflictError를 던진다", async () => {
    mockRpc.mockResolvedValue({
      data: { results: [{ id: "x", status: "conflict" }] },
      error: null,
    });

    await expect(updateGame("x", 1, { result: "lose" })).rejects.toBeInstanceOf(
      GameConflictError,
    );
  });

  it("논리 요청은 입력을 복사해 고정하고 다음 경기에는 별도 ID를 부여한다", () => {
    const payload = {
      played_at: "2026-08-18T12:00:00", result: "win" as const,
      turn_order: "first" as const, play_context_id: "dc_cup_2026_08",
      standing_kind: "event_points" as const, note: "최초 입력",
    };
    const first = prepareCreate(payload);
    const second = prepareCreate(payload);
    payload.note = "나중 입력";
    expect(first.payload.note).toBe("최초 입력");
    expect(Object.isFrozen(first)).toBe(true);
    expect(Object.isFrozen(first.payload)).toBe(true);
    expect(first.id).not.toBe(second.id);
    expect(first.request_id).not.toBe(second.request_id);
  });

  it("수정 성공의 버전이 없으면 0으로 꾸며내지 않는다", async () => {
    mockRpc.mockResolvedValue({ data: { results: [{ id: "x", status: "applied" }] }, error: null });
    await expect(updateGame("x", 1, { result: "lose" })).rejects.toThrow("저장 버전을 확인할 수 없습니다.");
  });

  it("다른 기록의 응답을 요청 성공으로 인정하지 않는다", async () => {
    mockRpc.mockResolvedValue({ data: { results: [{ id: "y", status: "applied", change_version: 2 }] }, error: null });
    await expect(updateGame("x", 1, { result: "lose" })).rejects.toThrow("저장 결과를 확인할 수 없습니다.");
  });
});
