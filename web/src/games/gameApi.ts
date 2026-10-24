// 경기 읽기/쓰기 클라이언트 (spec §3.1, §3.2).
// 쓰기는 `apply_game_changes` 단일 change + 낙관적 동시성(expected_change_version).

import { CLIENT_VERSION } from "../lib/build";
import { getSupabaseClient } from "../lib/supabase";
import type { Game, GamePayload } from "./types";
import type { DeckMatchup, Summary } from "./stats";

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

export interface CreateAttempt {
  readonly id: string;
  readonly request_id: string;
  readonly payload: Readonly<GamePayload>;
}

export interface RecordState {
  snapshot_version: number;
  today: { wins: number; losses: number };
  last_game: Game | null;
  last_my_deck: string | null;
  latest_by_mode: Game[];
}

export interface GameStatistics {
  snapshot_version: number;
  summary: Summary;
  matchups: DeckMatchup[];
  series: {
    played_at: string;
    standing_kind: string;
    value: number | null;
    tier: string | null;
    division: number | null;
  }[];
}

export interface HistoryCursor { played_at: string; id: string }
export interface HistoryPageResult {
  games: Game[];
  snapshot_version: number;
  has_more: boolean;
  next_cursor: HistoryCursor | null;
  stale: boolean;
}

export class GameMutationRejectedError extends Error { }

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
    if (/^(22|23|28|42501)/.test(error.code ?? "")) {
      throw new GameMutationRejectedError(error.message);
    }
    throw error;
  }
  const result = (data as ApplyResponse | null)?.results?.[0];
  if (!result || !["applied", "conflict"].includes(result.status)
    || result.id !== (changes[0] as { id: string }).id) {
    throw new Error("저장 결과를 확인할 수 없습니다. 같은 요청으로 다시 확인하세요.");
  }
  return result;
}

export function prepareCreate(payload: GamePayload): CreateAttempt {
  return Object.freeze({
    id: generateId(), request_id: generateId(), payload: Object.freeze({ ...payload }),
  });
}

function receipt(result: ChangeResult): CreateResult {
  if (!Number.isSafeInteger(result.change_version) || (result.change_version ?? 0) <= 0) {
    throw new Error("저장 버전을 확인할 수 없습니다. 같은 요청으로 다시 확인하세요.");
  }
  return { id: result.id, change_version: result.change_version! };
}

export async function createGame(attempt: CreateAttempt): Promise<CreateResult> {
  const result = await applyChanges([
    { op: "create", ...attempt, client_version: CLIENT_VERSION },
  ]);
  if (result.status === "conflict") {
    throw new GameConflictError(result);
  }
  return receipt(result);
}

export async function updateGame(
  id: string,
  expectedChangeVersion: number,
  payload: Partial<GamePayload>,
): Promise<CreateResult> {
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
  return receipt(result);
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
    .order("id", { ascending: false })
    .range(offset, offset + limit - 1);
  if (error) {
    throw error;
  }
  return (data ?? []) as Game[];
}

export async function getRecordState(localDate: string): Promise<RecordState> {
  const { data, error } = await getSupabaseClient().rpc("get_record_state", { p_local_date: localDate });
  if (error) throw error;
  if (!data || !Array.isArray(data.latest_by_mode) || !data.today) throw new Error("기록 상태를 확인할 수 없습니다.");
  return data as RecordState;
}

export async function getGameStatistics(context: string | null): Promise<GameStatistics> {
  const { data, error } = await getSupabaseClient().rpc("get_game_statistics", { p_context: context });
  if (error) throw error;
  if (!data?.summary || !Array.isArray(data.matchups) || !Array.isArray(data.series)) throw new Error("통계를 확인할 수 없습니다.");
  const stats = data as GameStatistics;
  stats.matchups.sort((a, b) => b.games - a.games || a.deck.localeCompare(b.deck, "ko"));
  return stats;
}

export async function getHistoryPage(context: string | null, cursor: HistoryCursor | null = null,
  snapshotVersion: number | null = null): Promise<HistoryPageResult> {
  const { data, error } = await getSupabaseClient().rpc("list_game_history", {
    p_context: context, p_before_played_at: cursor?.played_at ?? null,
    p_before_id: cursor?.id ?? null, p_limit: 100, p_snapshot_version: snapshotVersion,
  });
  if (error) throw error;
  if (!data || !Array.isArray(data.games) || typeof data.stale !== "boolean") throw new Error("기록 목록을 확인할 수 없습니다.");
  return data as HistoryPageResult;
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
