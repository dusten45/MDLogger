// 덱 목록 조회 (deck-catalog Edge Function proxy, spec §3.6).
// 브라우저는 Gist를 직접 요청하지 않는다.

import { getSupabaseClient } from "../lib/supabase";

export interface DeckCatalogResponse {
  decks: string[];
  stale: boolean;
  source: string;
  updated_at: string;
}

export async function fetchDecks(): Promise<string[]> {
  const { data, error } = await getSupabaseClient().functions.invoke(
    "deck-catalog",
    { method: "GET" },
  );
  if (error) {
    throw error;
  }
  const response = data as DeckCatalogResponse;
  if (!Array.isArray(response?.decks)) {
    throw new Error("덱 목록 응답을 해석할 수 없습니다.");
  }
  return response.decks;
}
