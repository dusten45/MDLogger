# MDLogger 세션 핸드오프 — 다음 세션에서 계속할 작업 (2026-08-10)

이 문서는 어느 세션에서 그 다음 세션으로 작업 맥락을 넘기기 위해 만든 핸드오프다.
`docs/pre-release-hardening-roadmap.md` §10의 단계 12 진입 조건이 어디까지 왔고,
Windows를 제외했을 때 남은 일을 **네 가지 분류**로 정리한다. `docs/open-items.md`의
"아직 열려 있는 항목"을 실행 단위로 쪼갠 것으로 보면 된다.

> **다음 세션(AI 에이전트) 지침**: 이 문서의 ①~④는 우선순위가 아니라 실행 주체별 묶음이다.
> 항목을 하나씩 진행할 때마다 여기에 상태를 갱신하고, `docs/open-items.md`와
> `docs/pre-release-hardening-roadmap.md` §10을 함께 맞춘다. Python 코드를 바꾸면
> `AGENTS.md`의 필수 검증(Ruff, format, ty, 관련/전체 pytest)을 실제로 돌린다.

---

## 현재 출발점 (기준선)

- 하드닝 H1~H6, 서버 검증(migration `0001~0016` + pgTAP 173 tests), hosted Edge Function 검증 완료.
- 클라이언트 자동 검증: ruff / format / ty / **pytest 261 passed, 4 skipped** 통과.
- 단계 12 진입 조건 `§10`: **8/11 충족**. 문서 정합성·미루기 항목 체크박스는 이 세션에서 `[x]`로 갱신함.
- **유일한 하드 게이트 = Windows 빌드 실동작 + exe 시크릿 스캔** (사용자 지시로 지금은 최대한 미룸).

---

## ① 검토·확정 — 소유자 판단 게이트 (실행 코드 없음)

| #   | 항목                                                                                                                  | 상태     | 근거 위치                                 |
| --- | --------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------- |
| 1   | 단계 12 진입 조건 최종 서명 (§10 문서 정합성·미루기 항목 승인)                                                        | **대기** | `pre-release-hardening-roadmap.md` §10    |
| 2   | RH1~~RH6 검토 게이트(H1~~H6 각 단계) 통과 판단                                                                        | **대기** | `pre-release-hardening-roadmap.md` §7·§10 |
| 3   | rollback/forward-fix 기준 + 최소 지원 앱 버전 확정                                                                    | **대기** | 원본 로드맵 §13(단계 12) 완료 조건        |
| 4   | 개인정보·자동 업로드 고지 최종 검토                                                                                   | **대기** | 단계 12 게이트 RF(privacy)                |
| 5   | 운영 값 확정: 백업 보존(이미 `BACKUP_RETENTION=1`), guest rate limit 운영값, Turnstile 도입 판단 기준(남용 지표 관측) | **대기** | `open-items` #4, runbook §11              |

소유자가 판단·서명만 하면 되는 항목들이다. 에이전트가 임의로 확정하지 않는다.

---

## ② 환경 실행 검증 — Windows 무관 (Linux/macOS)

| #   | 항목                                                                            | 실행할 곳               | 비고                                                 |
| --- | ------------------------------------------------------------------------------- | ----------------------- | ---------------------------------------------------- |
| 1   | 구버전 앱 → 0.1.5 업그레이드 rehearsal                                          | 소유자 Linux            | migration 경로 실증                                  |
| 2   | 장시간 offline/online 전환 + 대량(1,000건) 동기화 스트레스                      | 소유자 Linux            | `test_sync_engine` 1,000건 매트릭스 재현             |
| 3   | RLS·서버 함수 최종 공격 테스트 (`supabase db reset` + `test db`, 173 tests)     | **소유자 환경(podman)** | 이 에이전트 sandbox는 Docker 기반 Supabase 실행 불가 |
| 4   | macOS/Linux secure storage(keyring/Secret Service)·데이터 경로·worker 종료 검증 | 소유자 Linux            | 단계 12 작업 분                                      |
| 5   | 문서 최종 정합 재확인                                                           | 임의                    | `final_bugs`·`open-items`·`hardening`·`runbook`      |

서버 검증(3)은 이 세션에서 실제 실행했던 `supabase db reset`/`test db`가 소유자 환경
(podman, migration `0001~0016`, 173 tests 통과)에서 이미 완료되어 있으나, 단계 12
진입 직전 소유자가 다시 실행해 재확인한다.

---

## ③ 에이전트가 지금 바로 진행 가능 (개발·테스트 보강)

| #   | 항목                                            | 상태                           | 근거                                                                                                                     |
| --- | ----------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| 1   | Qt 자동 UI 클릭 테스트 보강 (통계 창·편집 흐름) | **진행(2026-08-10 정리 세션)** | `open-items` #1 잔여분 → 통계 창·편집/삭제 + 구버전 시작 마이그레이션 통합 + 계정·동기화 다이얼로그 클릭 테스트 9개 추가 |
| 2   | 하드닝 전체 커밋·정리 (아래 ※ 참조)             | **완료(2026-08-10 정리 세션)** | H1~H6 + 문서 정합 7개 커밋으로 분리                                                                                      |

그 외 `open-items`의 미루기 확정 항목(Turnstile #4, 휴대용 아카이브 #8, 세션 폐기 #9,
tombstone #7, DTO #2)은 이번 릴리스 범위에서 제외/연기이므로 **진행하지 않는다.**

---

## ④ Windows 연기 확정 (사용자 지시로 최대한 미룸)

| #   | 항목                                                      | 필요 성과                                    | 비고                                                                |
| --- | --------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------- |
| 1   | Windows PyInstaller 빌드 실동작 (로그인·guest ingest)     | 단계 12 진입의 하드 게이트                   | 소유자 Windows 실기 검증                                            |
| 2   | 빌드 산출물 시크릿 스캔 (`secret_scan dist/MDLogger.exe`) | 진입 조건 §10 "빌드 산출물 시크릿 스캔 통과" | exe 산출물 필요. 스캔 로직 자체는 `test_build_config` 17개로 검증됨 |
| 3   | Windows 시각적 폴리시 최종 점검                           | `open-items` #6                              | 소유자                                                              |
| 4   | Credential Manager(Windows) 검증                          | 단계 12                                      | 소유자                                                              |

> 시크릿 스캔 **파이프라인**은 이 세션에서 `uv run pytest tests/test_build_config.py tests/test_checksum.py` → **18 passed**로 정상 동작을 확인했음.
> 남은 것은 실제 exe 산출물에 대한 실행뿐.

---

## ※ uncommitted 상태 정리 (가장 먼저 권장)

현재 `git status` 기준, 하드닝·서버·문서 작업 **전체가 커밋 전 상태**로 쌓여 있다.
Windows를 미루는 동안 이대로 방치하면 상태를 알 수 없게 되므로, **다음 세션 첫 작업으로
커밋·정리를 권장한다.**

- **정리 완료(2026-08-10 정리 세션)**: 하드닝·서버·문서 작업 전체를 `docs/pre-release-hardening-roadmap.md` §9·§12 기준(H1~H6 + 문서 정합)으로 7개 커밋까지 분리 커밋했다. 커밋 순서: H1 빌드 구성 주입 → H2 서버 권한 forward-fix → H3 release policy·버전 → H4 환경 버전 → H5 운영·남용 방어 → H6 UX·번들·테스트 → 문서 정합. 커밋 직후 ruff / format / ty / pytest(252 passed, 4 skipped) 전부 재확인 통과.
- 현재 기준 `main`은 `origin/main`보다 22커밋 앞섬.
- **수정됨(추적 중)**: `.gitignore`, `README.md`, `pyproject.toml`, `uv.lock`,
  `docs/online-account-and-duel-data-roadmap.md`, `docs/open-items.md`,
  `docs/operations/runbook.md`, `supabase/*`(migration 제외), `src/mdlogger/*`,
  `tests/*` 등.
- **추적 안 함(신규)**: `docs/final_bugs.md`, `docs/pre-release-hardening-roadmap.md`,
  `docs/session-handoff.md`, `scripts/generate_build_config.py`, `src/mdlogger/_version.py`,
  `src/mdlogger/data/`, `src/mdlogger/environment.py`, `src/mdlogger/release_policy.py`,
  `src/mdlogger/secret_scan.py`, `supabase/migrations/0011~0016`, pgTAP `08~11`,
  `tests/test_build_config.py` 등 신규 테스트.
- **커밋하면 안 되는 것**: `src/mdlogger/remote/_bundled_config.py`(번들 생성 모듈,
  `.gitignore` 대상), 시크릿/키 값 포함 산출물. 커밋 전 `secret_scan`으로 재확인.
- **추천**: 기능 단위(하드닝 H1~H6, 문선 정합)로 나눠 커밋하고, 필요하면 브랜치 전략 결정.
  이후 `v0.1.5` 태그 상태를 현재 구현과 일치시키는 작업까지.

---

## 참고 링크

- 진입 조건·남은 게이트: `docs/pre-release-hardening-roadmap.md` §10
- 실행 단위 잔여: `docs/open-items.md`
- 최근 버그 해소 기록: `docs/final_bugs.md`
- 운영 절차(빌드·시크릿 스캔·백업·유출 대응): `docs/operations/runbook.md`
- 원본 로드맵 단계 12 계획: `docs/online-account-and-duel-data-roadmap.md` §13
- 프로젝트 규칙·필수 검증: `AGENTS.md`
