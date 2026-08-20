import { describe, expect, it } from "vitest";
import type { Game } from "./types";
import {
  deckMatchups,
  rankSeries,
  ratingSeries,
  scoreSeries,
  summarizeGames,
} from "./stats";

function game(overrides: Partial<Game> = {}): Game {
  return {
    id: "id",
    played_at: "2026-08-18T12:00:00",
    result: "win",
    turn_order: "first",
    my_deck: "티아라멘츠",
    opp_deck: "상대덱",
    turns: 10,
    end_reason: "regular",
    note: null,
    play_context_id: "dc_cup_2026_08",
    standing_kind: "event_points",
    rank_tier_before: null,
    rank_tier_after: null,
    rank_division_before: null,
    rank_division_after: null,
    rating_before: null,
    rating_after: null,
    event_points_before: null,
    event_points_after: null,
    timezone_offset_minutes: 540,
    environment_version_id: null,
    created_at: "2026-08-18T12:00:00",
    updated_at: "2026-08-18T12:00:00",
    deleted_at: null,
    change_version: 1,
    payload_version: 2,
    source_kind: "native",
    client_version: "web-dev",
    ...overrides,
  };
}

describe("summarizeGames", () => {
  it("승/패/승률/선후공 승률을 집계한다", () => {
    const games = [
      game({ id: "1", result: "win", turn_order: "first", turns: 10 }),
      game({ id: "2", result: "lose", turn_order: "second", turns: 20 }),
      game({ id: "3", result: "win", turn_order: "first", turns: 30 }),
    ];
    const summary = summarizeGames(games);
    expect(summary.total).toBe(3);
    expect(summary.wins).toBe(2);
    expect(summary.losses).toBe(1);
    expect(summary.winrate).toBeCloseTo(66.67, 1);
    expect(summary.first_games).toBe(2);
    expect(summary.first_wins).toBe(2);
    expect(summary.second_games).toBe(1);
    expect(summary.second_wins).toBe(0);
    expect(summary.avg_turns).toBeCloseTo(20, 1);
  });

  it("play_context_id로 필터링한다", () => {
    const games = [
      game({ id: "1", play_context_id: "dc_cup_2026_08" }),
      game({ id: "2", play_context_id: "wcq_2026" }),
    ];
    expect(summarizeGames(games, "dc_cup_2026_08").total).toBe(1);
    expect(summarizeGames(games, null).total).toBe(2);
  });
});

describe("deckMatchups", () => {
  it("상대 덱별 승패를 집계하고 경기 수 내림차순으로 정렬한다", () => {
    const games = [
      game({ id: "1", opp_deck: "A", result: "win" }),
      game({ id: "2", opp_deck: "A", result: "lose" }),
      game({ id: "3", opp_deck: "B", result: "win" }),
    ];
    const rows = deckMatchups(games);
    expect(rows[0].deck).toBe("A");
    expect(rows[0].games).toBe(2);
    expect(rows[0].wins).toBe(1);
    expect(rows[0].losses).toBe(1);
    expect(rows[0].winrate).toBeCloseTo(50, 1);
    expect(rows[1].deck).toBe("B");
  });
});

describe("시계열", () => {
  it("scoreSeries는 전체에서는 빈 배열을 반환한다", () => {
    const games = [
      game({ id: "1", event_points_after: 100 }),
    ];
    expect(scoreSeries(games, null)).toEqual([]);
  });

  it("scoreSeries는 문맥과 standing_kind로 필터링한다", () => {
    const games = [
      game({
        id: "1",
        play_context_id: "dc_cup_2026_08",
        event_points_after: 100,
      }),
      game({
        id: "2",
        play_context_id: "dc_cup_2026_08",
        standing_kind: "rank",
        event_points_after: 200,
      }),
      game({
        id: "3",
        play_context_id: "wcq_2026",
        event_points_after: 300,
      }),
    ];
    const series = scoreSeries(games, "dc_cup_2026_08");
    expect(series).toHaveLength(1);
    expect(series[0].value).toBe(100);
  });

  it("rankSeries는 rank_tier_after가 있는 랭크전만 반환한다", () => {
    const games = [
      game({
        id: "1",
        standing_kind: "rank",
        rank_tier_after: "gold",
        rank_division_after: 3,
      }),
      game({ id: "2", standing_kind: "rank", rank_tier_after: null }),
    ];
    const series = rankSeries(games, "dc_cup_2026_08");
    expect(series).toHaveLength(1);
    expect(series[0].tier).toBe("gold");
    expect(series[0].division).toBe(3);
  });

  it("ratingSeries는 rating_after가 있는 레이팅전만 반환한다", () => {
    const games = [
      game({ id: "1", standing_kind: "rating", rating_after: 1500 }),
      game({ id: "2", standing_kind: "rating", rating_after: null }),
    ];
    const series = ratingSeries(games, "dc_cup_2026_08");
    expect(series).toHaveLength(1);
    expect(series[0].value).toBe(1500);
  });
});
