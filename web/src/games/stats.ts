// 클라이언트 집계 통계 (spec §8.2). 서버에서 본인 게임을 조회해 집계한다.
// 데스크톱 `db.py`의 get_summary/get_deck_matchups/get_*_series와 동일한 의미.

import type { Game, Result } from "./types";

export interface Summary {
  total: number;
  wins: number;
  losses: number;
  winrate: number;
  first_games: number;
  first_wins: number;
  first_winrate: number;
  second_games: number;
  second_wins: number;
  second_winrate: number;
  avg_turns: number;
}

export interface DeckMatchup {
  deck: string;
  games: number;
  wins: number;
  losses: number;
  winrate: number;
}

export interface ScorePoint {
  played_at: string;
  value: number;
  result: Result;
}

export interface RankPoint {
  played_at: string;
  tier: string;
  division: number;
  result: Result;
}

export interface RatingPoint {
  played_at: string;
  value: number;
  result: Result;
}

function rate(wins: number, games: number): number {
  return games ? (wins / games) * 100 : 0;
}

function filterByContext(
  games: Game[],
  playContextId: string | null,
): Game[] {
  if (playContextId === null) {
    return games;
  }
  return games.filter((game) => game.play_context_id === playContextId);
}

export function summarizeGames(
  games: Game[],
  playContextId: string | null = null,
): Summary {
  const rows = filterByContext(games, playContextId);
  const total = rows.length;
  const wins = rows.filter((game) => game.result === "win").length;
  const first = rows.filter((game) => game.turn_order === "first");
  const second = rows.filter((game) => game.turn_order === "second");
  const firstWins = first.filter((game) => game.result === "win").length;
  const secondWins = second.filter((game) => game.result === "win").length;
  const turnValues = rows
    .filter((game) => game.turns !== null)
    .map((game) => game.turns as number);
  const avgTurns = turnValues.length
    ? turnValues.reduce((sum, value) => sum + value, 0) / turnValues.length
    : 0;
  return {
    total,
    wins,
    losses: total - wins,
    winrate: rate(wins, total),
    first_games: first.length,
    first_wins: firstWins,
    first_winrate: rate(firstWins, first.length),
    second_games: second.length,
    second_wins: secondWins,
    second_winrate: rate(secondWins, second.length),
    avg_turns: avgTurns,
  };
}

export function deckMatchups(
  games: Game[],
  playContextId: string | null = null,
  turnFilter: "first" | "second" | null = null,
): DeckMatchup[] {
  let rows = filterByContext(games, playContextId);
  if (turnFilter !== null) {
    rows = rows.filter((game) => game.turn_order === turnFilter);
  }
  const byDeck = new Map<
    string,
    { games: number; wins: number; losses: number }
  >();
  for (const game of rows) {
    const deck = game.opp_deck ?? "";
    const entry = byDeck.get(deck) ?? { games: 0, wins: 0, losses: 0 };
    entry.games += 1;
    if (game.result === "win") {
      entry.wins += 1;
    } else {
      entry.losses += 1;
    }
    byDeck.set(deck, entry);
  }
  return [...byDeck.entries()]
    .map(([deck, entry]) => ({
      deck,
      games: entry.games,
      wins: entry.wins,
      losses: entry.losses,
      winrate: rate(entry.wins, entry.games),
    }))
    .sort(
      (a, b) => b.games - a.games || a.deck.localeCompare(b.deck, "ko"),
    );
}

function byPlayedAt(a: Game, b: Game): number {
  return a.played_at.localeCompare(b.played_at) || a.id.localeCompare(b.id);
}

/** 점수 모드 하나의 시계열 (A1: 전체에서는 그리지 않음, spec §5.4). */
export function scoreSeries(
  games: Game[],
  playContextId: string | null = null,
): ScorePoint[] {
  if (playContextId === null) {
    return [];
  }
  return filterByContext(games, playContextId)
    .filter(
      (game) =>
        game.standing_kind === "event_points" &&
        game.event_points_after !== null,
    )
    .sort(byPlayedAt)
    .map((game) => ({
      played_at: game.played_at,
      value: game.event_points_after as number,
      result: game.result,
    }));
}

/** 랭크전만: (played_at, rank_tier_after, rank_division_after) (spec §5.5). */
export function rankSeries(
  games: Game[],
  playContextId: string | null = null,
): RankPoint[] {
  if (playContextId === null) {
    return [];
  }
  return filterByContext(games, playContextId)
    .filter(
      (game) =>
        game.standing_kind === "rank" && game.rank_tier_after !== null,
    )
    .sort(byPlayedAt)
    .map((game) => ({
      played_at: game.played_at,
      tier: game.rank_tier_after as string,
      division: game.rank_division_after as number,
      result: game.result,
    }));
}

/** 레이팅전만: (played_at, rating_after) (spec §5.6). */
export function ratingSeries(
  games: Game[],
  playContextId: string | null = null,
): RatingPoint[] {
  if (playContextId === null) {
    return [];
  }
  return filterByContext(games, playContextId)
    .filter(
      (game) =>
        game.standing_kind === "rating" && game.rating_after !== null,
    )
    .sort(byPlayedAt)
    .map((game) => ({
      played_at: game.played_at,
      value: game.rating_after as number,
      result: game.result,
    }));
}
