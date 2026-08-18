// 경기 모드 기준정보 조회 (서버 `game_modes` 원본, spec §3.1, B2).

import { getSupabaseClient } from "../lib/supabase";
import type { GameMode } from "./types";

export async function listGameModes(): Promise<GameMode[]> {
  const { data, error } = await getSupabaseClient()
    .from("game_modes")
    .select("*")
    .eq("is_active", true)
    .order("sort_order", { ascending: true });
  if (error) {
    throw error;
  }
  return (data ?? []) as GameMode[];
}
