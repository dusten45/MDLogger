// 통계 화면 (spec §8.2). 모드별 요약·덱 매치업·시계열 차트(클라이언트 집계).

import { useEffect, useMemo, useState } from "react";
import { SeriesChart, type SeriesPoint } from "../components/stats/SeriesChart";
import { listGames } from "../games/gameApi";
import { listGameModes } from "../games/modes";
import {
    RANK_DIVISION_MAX,
    RANK_TIER_INDEX,
    RANK_TIER_LABELS,
} from "../games/rank";
import {
    deckMatchups,
    rankSeries,
    ratingSeries,
    scoreSeries,
    summarizeGames,
} from "../games/stats";
import type { Game, GameMode } from "../games/types";
import "./stats.css";

interface Message {
    kind: "error";
    text: string;
}

export function StatsPage() {
    const [modes, setModes] = useState<GameMode[]>([]);
    const [games, setGames] = useState<Game[]>([]);
    const [filter, setFilter] = useState<string>("all");
    const [message, setMessage] = useState<Message | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        Promise.all([listGameModes(), listGames({ limit: 1000 })])
            .then(([modeRows, gameRows]) => {
                if (cancelled) {
                    return;
                }
                setModes(modeRows);
                setGames(gameRows);
            })
            .catch(() => {
                if (!cancelled) {
                    setMessage({
                        kind: "error",
                        text: "통계를 불러오지 못했습니다.",
                    });
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false);
                }
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const selectedMode = useMemo(
        () => modes.find((mode) => mode.id === filter) ?? null,
        [modes, filter],
    );

    const contextId = selectedMode?.play_context_id ?? null;
    const summary = useMemo(
        () => summarizeGames(games, contextId),
        [games, contextId],
    );
    const matchups = useMemo(
        () => deckMatchups(games, contextId),
        [games, contextId],
    );

    const series = useMemo(() => {
        if (selectedMode === null) {
            return null;
        }
        if (selectedMode.standing_kind === "event_points") {
            return scoreSeries(games, contextId).map((point): SeriesPoint => ({
                label: `${point.played_at.slice(5, 16).replace("T", " ")} · ${point.value.toLocaleString()}`,
                value: point.value,
            }));
        }
        if (selectedMode.standing_kind === "rating") {
            return ratingSeries(games, contextId).map((point): SeriesPoint => ({
                label: `${point.played_at.slice(5, 16).replace("T", " ")} · ${point.value.toLocaleString()}`,
                value: point.value,
            }));
        }
        return rankSeries(games, contextId).map((point): SeriesPoint => ({
            label: rankLabel(point.tier, point.division),
            value: rankValue(point.tier, point.division),
        }));
    }, [selectedMode, games, contextId]);

    if (loading) {
        return <p className="auth-loading">통계를 불러오는 중...</p>;
    }

    return (
        <section aria-labelledby="stats-title" className="stats-page">
            <h1 id="stats-title" className="page-title">
                통계
            </h1>

            <div
                className="segmented stats-filter"
                role="group"
                aria-label="모드 필터"
            >
                <button
                    type="button"
                    className={
                        filter === "all"
                            ? "segmented__button segmented__button--active"
                            : "segmented__button"
                    }
                    aria-pressed={filter === "all"}
                    onClick={() => setFilter("all")}
                >
                    전체
                </button>
                {modes.map((mode) => (
                    <button
                        key={mode.id}
                        type="button"
                        className={
                            filter === mode.id
                                ? "segmented__button segmented__button--active"
                                : "segmented__button"
                        }
                        aria-pressed={filter === mode.id}
                        onClick={() => setFilter(mode.id)}
                    >
                        {mode.display_name}
                    </button>
                ))}
            </div>

            {message ? (
                <p className="form-message form-message--error" role="status">
                    {message.text}
                </p>
            ) : null}

            <div className="stats-grid">
                <StatCard label="전체" value={String(summary.total)} />
                <StatCard label="승" value={String(summary.wins)} />
                <StatCard label="패" value={String(summary.losses)} />
                <StatCard
                    label="승률"
                    value={`${summary.winrate.toFixed(1)}%`}
                />
                <StatCard
                    label="선공 승률"
                    value={`${summary.first_winrate.toFixed(1)}%`}
                />
                <StatCard
                    label="후공 승률"
                    value={`${summary.second_winrate.toFixed(1)}%`}
                />
                <StatCard
                    label="평균 턴"
                    value={summary.avg_turns.toFixed(1)}
                />
            </div>

            {series !== null ? (
                <section
                    className="section-surface"
                    aria-labelledby="series-title"
                >
                    <h2 id="series-title" className="section-surface__title">
                        시계열
                    </h2>
                    <SeriesChart
                        points={series}
                        step={selectedMode?.standing_kind === "rank"}
                    />
                </section>
            ) : null}

            <section
                className="section-surface"
                aria-labelledby="matchups-title"
            >
                <h2 id="matchups-title" className="section-surface__title">
                    덱 매치업
                </h2>
                {matchups.length === 0 ? (
                    <p className="page-description">기록이 없습니다.</p>
                ) : (
                    <table className="matchup-table">
                        <thead>
                            <tr>
                                <th scope="col">상대 덱</th>
                                <th scope="col">경기</th>
                                <th scope="col">승</th>
                                <th scope="col">패</th>
                                <th scope="col">승률</th>
                            </tr>
                        </thead>
                        <tbody>
                            {matchups.map((row) => (
                                <tr key={row.deck}>
                                    <th scope="row">{row.deck}</th>
                                    <td>{row.games}</td>
                                    <td>{row.wins}</td>
                                    <td>{row.losses}</td>
                                    <td>{row.winrate.toFixed(1)}%</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </section>
    );
}

function StatCard({
    label: cardLabel,
    value,
}: {
    label: string;
    value: string;
}) {
    return (
        <div className="stat-card">
            <span className="stat-card__label">{cardLabel}</span>
            <span className="stat-card__value">{value}</span>
        </div>
    );
}

function rankValue(tier: string, division: number): number {
    const tierIndex = RANK_TIER_INDEX[tier] ?? 0;
    return tierIndex * 5 + (RANK_DIVISION_MAX - division);
}

function rankLabel(tier: string, division: number): string {
    return `${RANK_TIER_LABELS[tier] ?? tier} ${division}`;
}
