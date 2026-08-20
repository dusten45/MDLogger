// 경량 SVG 시계열 차트 (외부 차트 라이브러리 없음, spec §8.2).
// 색상만으로 의미를 전달하지 않고 첫/마지막 라벨과 접근성 요약을 함께 표시한다.

export interface SeriesPoint {
    label: string;
    value: number;
}

export interface SeriesChartProps {
    points: SeriesPoint[];
    step?: boolean;
}

const WIDTH = 320;
const HEIGHT = 160;
const PADDING = 24;

export function SeriesChart({ points, step = false }: SeriesChartProps) {
    if (points.length < 2) {
        return <p className="chart-empty">표시할 데이터가 부족합니다.</p>;
    }

    const values = points.map((point) => point.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;

    const x = (index: number) =>
        PADDING + (index / (points.length - 1)) * (WIDTH - PADDING * 2);
    const y = (value: number) =>
        HEIGHT - PADDING - ((value - min) / range) * (HEIGHT - PADDING * 2);

    const path = points
        .map((point, index) => {
            if (index === 0) {
                return `M ${x(index).toFixed(1)} ${y(point.value).toFixed(1)}`;
            }
            if (step) {
                return `H ${x(index).toFixed(1)} V ${y(point.value).toFixed(1)}`;
            }
            return `L ${x(index).toFixed(1)} ${y(point.value).toFixed(1)}`;
        })
        .join(" ");

    const summary = `${points[0].label} → ${points[points.length - 1].label}`;

    return (
        <figure className="series-chart">
            <svg
                viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                role="img"
                aria-label={`시계열 차트: ${summary}`}
                preserveAspectRatio="none"
            >
                <line
                    x1={PADDING}
                    y1={HEIGHT - PADDING}
                    x2={WIDTH - PADDING}
                    y2={HEIGHT - PADDING}
                    className="series-chart__axis"
                />
                <path d={path} className="series-chart__line" fill="none" />
                {points.map((point, index) => (
                    <circle
                        key={`${point.label}-${index}`}
                        cx={x(index)}
                        cy={y(point.value)}
                        r={3}
                        className="series-chart__dot"
                    />
                ))}
            </svg>
            <figcaption className="series-chart__caption">
                <span>{points[0].label}</span>
                <span>{points[points.length - 1].label}</span>
            </figcaption>
        </figure>
    );
}
