import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/supabase", () => ({
  getSupabaseClient: vi.fn(),
}));

import { getSupabaseClient } from "../lib/supabase";
import {
  GameConflictError,
  createGame,
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
    mockRpc.mockResolvedValue({
      data: {
        results: [{ id: "x", status: "applied", change_version: 1 }],
      },
      error: null,
    });

    const result = await createGame({
      played_at: "2026-08-18T12:00:00",
      result: "win",
      turn_order: "first",
      play_context_id: "rank_2026_08",
      standing_kind: "rank",
    });

    expect(mockRpc).toHaveBeenCalledWith(
      "apply_game_changes",
      expect.objectContaining({
        sync_schema_version: 1,
        payload_version: 2,
        changes: [
          expect.objectContaining({
            op: "create",
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
            remote: { id: "x", change_version: 2 },
          },
        ],
      },
      error: null,
    });

    await updateGame("x", 1, { result: "lose" });

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
});
