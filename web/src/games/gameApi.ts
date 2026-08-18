// 경기 읽기/쓰기 클라이언트 (spec §3.1, §3.2).
// 쓰기는 `apply_game_changes` 단일 change + 낙관적 동시성(expected_change_version).

import { CLIENT_VERSION } from "../lib/build";
import { getSupabaseClient } from "../lib/supabase";
import type { Game, GamePayload } from "./types";

const SYNC_SCHEMA_VERSION = 1;
const PAYLOAD_VERSION = 2;

export interface ChangeResult {
  id: string;
  status: "applied" | "conflict";
  change_version?: number;
  expected_change_version?: number | null;
  current_change_version?: number | null;
  remote?: Game | null;
}

interface ApplyResponse {
  results: ChangeResult[];
}

export interface CreateResult {
  id: string;
  change_version: number;
}

export class GameConflictError extends Error {
  constructor(public readonly result: ChangeResult) {
    super("다른 기기에서 수정된 기록입니다.");
    this.name = "GameConflictError";
  }
}

async function applyChanges(changes: unknown[]): Promise<ChangeResult> {
  const { data, error } = await getSupabaseClient().rpc("apply_game_changes", {
    sync_schema_version: SYNC_SCHEMA_VERSION,
    payload_version: PAYLOAD_VERSION,
    changes,
  });
  if (error) {
    throw error;
  }
  const result = (data as ApplyResponse).results?.[0];
  if (!result) {
    throw new Error("서버 응답에 결과가 없습니다.");
  }
  return result;
}

export async function createGame(payload: GamePayload): Promise<CreateResult> {
  const id = generateId();
  const result = await applyChanges([
    { op: "create", id, client_version: CLIENT_VERSION, payload },
  ]);
  if (result.status === "conflict") {
    throw new GameConflictError(result);
  }
  return { id, change_version: result.change_version ?? 0 };
}

export async function updateGame(
  id: string,
  expectedChangeVersion: number,
  payload: Partial<GamePayload>,
): Promise<Game> {
  const result = await applyChanges([
    {
      op: "update",
      id,
      expected_change_version: expectedChangeVersion,
      client_version: CLIENT_VERSION,
      payload,
    },
  ]);
  if (result.status === "conflict") {
    throw new GameConflictError(result);
  }
  if (!result.remote) {
    throw new Error("서버가 갱신된 기록을 반환하지 않았습니다.");
  }
  return result.remote;
}

export async function deleteGame(
  id: string,
  expectedChangeVersion?: number,
): Promise<void> {
  const change: Record<string, unknown> = { op: "delete", id };
  if (expectedChangeVersion !== undefined) {
    change.expected_change_version = expectedChangeVersion;
  }
  const result = await applyChanges([change]);
  if (result.status === "conflict") {
    throw new GameConflictError(result);
  }
}

export async function listGames(options: {
  limit?: number;
  offset?: number;
} = {}): Promise<Game[]> {
  const limit = options.limit ?? 100;
  const offset = options.offset ?? 0;
  const { data, error } = await getSupabaseClient()
    .from("games")
    .select("*")
    .is("deleted_at", null)
    .order("played_at", { ascending: false })
    .range(offset, offset + limit - 1);
  if (error) {
    throw error;
  }
  return (data ?? []) as Game[];
}

function generateId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // 구형/테스트 환경 폴백.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0;
    const value = char === "x" ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}
