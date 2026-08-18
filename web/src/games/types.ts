// 경기·모드 도메인 타입 (데스크톱 `enums.py`/`models.py`/`games` 스키마와 동일 의미).

export type Result = "win" | "lose";
export type TurnOrder = "first" | "second";
export type EndReason = "regular" | "surrender" | "timeout" | "disconnect";
export type StandingKind = "rank" | "rating" | "event_points";

export interface GameMode {
  id: string;
  standing_kind: StandingKind;
  display_name: string;
  play_context_id: string | null;
  sort_order: number;
  is_active: boolean;
  season_label: string | null;
}

export interface Game {
  id: string;
  played_at: string;
  result: Result;
  turn_order: TurnOrder;
  my_deck: string | null;
  opp_deck: string | null;
  turns: number | null;
  end_reason: EndReason | null;
  note: string | null;
  play_context_id: string | null;
  standing_kind: StandingKind | null;
  rank_tier_before: string | null;
  rank_tier_after: string | null;
  rank_division_before: number | null;
  rank_division_after: number | null;
  rating_before: number | null;
  rating_after: number | null;
  event_points_before: number | null;
  event_points_after: number | null;
  timezone_offset_minutes: number | null;
  environment_version_id: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  change_version: number;
  payload_version: number;
  source_kind: string;
  client_version: string | null;
}

// apply_game_changes payload (create/update). 서버 allowed_payload_keys와 일치한다.
export interface GamePayload {
  played_at: string;
  result: Result;
  turn_order: TurnOrder;
  my_deck?: string | null;
  opp_deck?: string | null;
  turns?: number | null;
  end_reason?: EndReason | null;
  note?: string | null;
  play_context_id: string;
  standing_kind: StandingKind;
  rank_tier_before?: string | null;
  rank_tier_after?: string | null;
  rank_division_before?: number | null;
  rank_division_after?: number | null;
  rating_before?: number | null;
  rating_after?: number | null;
  event_points_before?: number | null;
  event_points_after?: number | null;
  timezone_offset_minutes?: number | null;
}
