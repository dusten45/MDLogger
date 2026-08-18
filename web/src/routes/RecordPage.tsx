// 기록 화면 (기본 화면, spec §5.2). 핵심 기록 흐름은 3-D에서 구현한다.

export function RecordPage() {
  return (
    <section aria-labelledby="record-title">
      <h1 id="record-title" className="page-title">
        기록
      </h1>
      <p className="page-description">모드 선택 → 승/패 → 상세 입력 → 저장.</p>
    </section>
  );
}
