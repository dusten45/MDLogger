// 기록 목록 화면 (spec §5.2). 목록·필터·수정/삭제는 3-E에서 구현한다.

export function HistoryPage() {
  return (
    <section aria-labelledby="history-title">
      <h1 id="history-title" className="page-title">
        기록 목록
      </h1>
      <p className="page-description">전체/점수전/랭크전 필터와 수정·삭제.</p>
    </section>
  );
}
