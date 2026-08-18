// 통계 화면 (spec §5.2). 통계 집계·차트는 3-E에서 구현한다.

export function StatsPage() {
  return (
    <section aria-labelledby="stats-title">
      <h1 id="stats-title" className="page-title">
        통계
      </h1>
      <p className="page-description">모드별 요약·덱 매치업·시리즈 차트.</p>
    </section>
  );
}
