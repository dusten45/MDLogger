# MDLogger 미결 항목 (Open Items)

이 문서는 `docs/online-account-and-duel-data-roadmap.md` 와
`docs/pre-release-hardening-roadmap.md` 의 단계별 구현 기록에서
**아직 진짜로 열려 있는 항목만** 모은 것이다.

분류 기준:

- **포함**: 이번 릴리스(하드닝 H1~~H6)와 원본 단계 0~~11에서 아직 해소·검증되지 않은 항목,
  또는 명시적으로 "후속 결정/후속 통합/추후/범위 제외"로 미뤄져 남은 항목.
- **제외**: 이미 구현·해소된 항목은 본문 "이번 릴리스에서 해소된 항목" 표로 옮겨 참고로 남긴다.

---

## 이번 릴리스에서 해소된 항목 (하드닝 H1~H6)

| ID  | 항목                                        | 해소                                                                    |
| --- | ------------------------------------------- | ----------------------------------------------------------------------- |
| B1  | 빌드 설정 주입 전무                         | H1: `_bundled_config` 생성 스크립트·시크릿 검사·runbook 절차            |
| B2  | `next_game_change_version` 권한 회수 불완전 | H2: `0011` 함수 EXECUTE `from public, anon, authenticated`              |
| B3  | release policy 전면 부재                    | H3: `0012` `release_policies` + 클라이언트 정책 해석·차단·캐시          |
| M1  | 휴대용 아카이브 UI 도달 불가                | **미루기 확정(H-3)**: runbook에 "사용 불가 + CSV/XLSX 대체" 명시        |
| M2  | 플레이 문맥·standing NULL                   | H4(부분): `environment_versions` 최소 도입(결정 H-2)                    |
| M3  | 등록 projection이 게스트 철회 마커 되살림   | H2: projection upsert가 `withdrawn_at`을 지우지 않음                    |
| H-1 | RLS 미활성 5개 테이블                       | H2: `0011` RLS 활성화(기본 거부)                                        |
| H-2 | `profiles` 서버 필드 위조                   | H2: BEFORE INSERT OR UPDATE 트리거                                      |
| H-3 | `revoke_all_devices` 세션 미폐기            | **미루기 확정(D-6)**: 한계를 UI·runbook에 명시. 실제 폐기는 다음 릴리스 |
| H-4 | 계정 삭제 비원자성                          | H5: `account-delete` auth 먼저 삭제 → FK cascade                        |
| H-5 | guest ingest rate limit 미구현              | H5: `0014` + Edge `guest_rate_check`                                    |
| H-6 | Edge 필드 allowlist 없음                    | H5: guest-ingest Edge 계층 allowlist·이상 값 검사                       |
| H-7 | 마이그레이션 부분 적용 위험                 | H5: README 재개·1회성 insert 가이드                                     |
| H-8 | `contributor_salt` 백업·재생성 미문서화     | H5: runbook §8.1                                                        |
| H-9 | `account-delete` `verify_jwt` 미명시        | H5: `config.toml` 명시                                                  |
| N-1 | 버전 드리프트 `0.1.0` vs `v0.1.5`           | H3: `_version.py` 단일 출처(hatchling dynamic) + 0.1.5                  |
| N-2 | `sessions is None` 무반응 버튼              | H6: 안내 메시지 표시                                                    |
| N-3 | supabase README 표 0007~0009 누락           | H2/H6: 0007~0014 전체 표기                                              |
| N-4 | `decks.json` 미번들                         | H6: 패키지 리소스 번들 + 첫 실행 시드                                   |
| N-5 | `.spec` 재사용 안내                         | H6: README 문구 정리                                                    |
| N-6 | 의존성 상한·pyinstaller 미고정              | H6: 런타임 상한 + `pyinstaller==6.21.0`                                 |
| N-7 | `score_after` 라벨 불일치                   | H6: "누적 점수"로 통일                                                  |
| N-8 | 1,000건 동기화 매트릭스 미달                | H6: `test_sync_engine` 대량 동기화 테스트                               |
| N-9 | 문서 상태가 실제보다 낙관적                 | H6: open-items·로드맵·runbook 재정렬                                    |

---

## 요약 표 (현재 남은 항목)

| #   | 항목                                                  | 최초 지적 | 현재 상태                                                                                                                                             | 해소 예상 위치          |
| --- | ----------------------------------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| 1   | Qt 자동 UI 클릭 테스트                                | 단계 1, 6 | 클릭 테스트 추가(2026-08-10): 저장·취소·유효성, 통계 창·편집/삭제 다이얼로그, 구버전 시작 마이그레이션 통합, 계정·동기화 다이얼로그(게스트/등록) 12개 | 지속 회귀 관리          |
| 2   | 도메인 DTO 도입 결정                                  | 단계 1    | 범위 제외(결정)                                                                                                                                       | 제품 결정               |
| 3   | 백업 보존 정책/개수                                   | 단계 2    | **확정(2026-08-10)**: 로컬 migration 사전 백업 최근 1개 보관·내부 전용. `BACKUP_RETENTION=1` + `_retain_backups` 구현·테스트                          | 완료                    |
| 4   | Turnstile/CAPTCHA 게스트 남용 방어                    | 단계 4, 5 | 확장 경계만, 미구현                                                                                                                                   | 남용 관찰 후            |
| 5   | hosted production + Windows 패키징 검증               | 단계 5~8  | hosted 적용·Edge 검증 완료(2026-08-10). Windows 빌드는 사용자 지시로 제외                                                                             | 단계 12                 |
| 6   | 최종 Windows 시각적 폴리시                            | 단계 6    | 사용자 최종 점검 예정                                                                                                                                 | 단계 12                 |
| 7   | tombstone 물리 정리·비활성 장치 제거                  | 단계 8    | 범위 제외(결정)                                                                                                                                       | 데이터 규모 문제 후     |
| 8   | 휴대용 아카이브 UI 배선                               | 단계 10   | 미루기 확정(H-3)                                                                                                                                      | 다음 릴리스             |
| 9   | 실제 세션 폐기(Auth Admin 로그아웃)                   | H-3       | 한계 명시만(D-6)                                                                                                                                      | 다음 릴리스             |
| 10  | supabase db reset / test db(0001~~0016, pgTAP 01~~11) | H2~H5     | **해소(2026-08-10)**: 소유자 환경(podman) 173 tests 전체 통과                                                                                         | 완료                    |
| 11  | Edge Function(guest-ingest·account-delete) 로컬 검증  | H5        | **해소(2026-08-10)**: guest-ingest(200/422/429) + account-delete(200, auth·개인 데이터 삭제/분석 보존) 로컬 검증 완료                                 | 완료                    |
| 12  | `contributor_salt` 백업 재생성 확인                   | H-8       | **해소(2026-08-10)**: 로컬 백업/복원 rehearsal 통과. salt·contributor_key·pseudonym_for 동일, RLS 유지. `extensions` 스키마 포함 복원 강조            | 완료                    |
| 13  | release policy 초기 값(최신/최소/update_url)          | D-7       | **확정: 최소=최신=0.1.5, update_url 비움**                                                                                                            | 업데이트 발생 시 재결정 |
| 14  | 빌드 산출물 시크릿 스캔·패키징 실동작                 | H1        | 자동화 + 테스트 ok, Windows 빌드 미실행                                                                                                               | 소유자 환경             |

---

## 항목별 상세

### 1. Qt 자동 UI 클릭 테스트

- **최초 지적**: 단계 1 "남은 위험", 단계 6 완료 조건.
- **내용**: 실제 Qt 클릭·다이얼로그를 구동하는 자동 UI 테스트가 아직 없다.
- **현재 상태**: `tests/test_ui_flow_clicks.py` + `tests/test_account_ui_clicks.py` 추가(2026-08-10). offscreen에서 `QTest.mouseClick`으로 실제 위젯을 클릭해 ① 화면1→화면2 저장/취소/유효성, ② 통계 창 열기·요약/기록 렌더링, ③ 기록 편집(저장·결과 토글·취소), ④ 삭제 확인, ⑤ 구버전(v4) DB 시작 경로 마이그레이션 통합, ⑥ 계정·동기화 다이얼로그(메인 '계정' 버튼 시그널, 게스트/등록 렌더링·시그널·닫기, 충돌 배지)를 구동한다(총 12개). 모달(`exec()`)은 `QTimer.singleShot`으로 이벤트 루프 안 상호작용을 예약한다. 기존 검증(offscreen smoke·mock 단위 테스트)은 계속 유지한다.
- **해소 예상 위치**: 핵심 기록·통계·편집/삭제·구버전 시작 마이그레이션·계정 다이얼로그 렌더링/시그널 흐름은 추가됨. 로그인 제출·서버 동기화 등 네트워크/세션 의존 흐름은 mock 단위 테스트가 담당하고, 실제 서버 연동은 단계 12 통합 시 담당. 마이그레이션/백업은 확인 다이얼로그가 없어 시작 경로 통합으로 대신한다.

### 2. 도메인 DTO 도입 결정

- **최초 지적**: 단계 1 "남은 위험".
- **내용**: 반환 행 타입이 여전히 `sqlite3.Row`. 하드닝 §5에서 **이번 릴리스 범위 제외**로 확정.
- **현재 상태**: 결정 보류(범위 제외).
- **해소 예상 위치**: 제품 결정 시점.

### 3. 백업 보존 정책/개수

- **최초 지적**: 단계 2 "남은 위험".
- **내용**: migration 백업 보존 개수와 사용자 노출/정리 정책 미확정.
- **현재 상태**: **확정(2026-08-10)**. 로컬 DB 마이그레이션 사전 백업(`<db>.pre-migration-v<version>.bak`)은 **최근 1개만 보관**하고, 새 백업 생성 시 이전 백업을 정리한다(`migrations.BACKUP_RETENTION=1`, `_retain_backups`). 백업은 **내부 전용**이며 사용자에게 노출하지 않고, migration 실패 시 복구 안내로만 사용한다.
- **해소 예상 위치**: 완료. `tests/test_migrations.py::test_retain_backups_keeps_only_latest`로 검증.

### 4. Turnstile/CAPTCHA 게스트 남용 방어

- **최초 지적**: 단계 4, 5; 하드닝 §5 비목표.
- **내용**: 실제 Turnstile 검증은 확정 결정 12에 따라 남용이 관찰된 뒤 도입. rate limit(방어 1)은
  H5에서 구현됨.
- **현재 상태**: 미구현(연기). `challenge_token`/428 계약만 존재.
- **해소 예상 위치**: 남용 관찰 후.

### 5. hosted production + Windows 패키징 검증

- **최초 지적**: 단계 5~8; 하드닝 남은 위험.
- **내용**: 실제 hosted 적용, Windows Credential Manager/Secret Service, Windows PyInstaller
  빌드·인증·시크릿 스캔, 다중 물리 PC 동기화.
- **현재 상태**: **hosted production 적용·Edge 검증 완료(2026-08-10)**. 소유자가 hosted 프로젝트(`tqdlqzssfnbkhxcvekxj`)를 생성하고 `supabase link` → `supabase db push`(migration `0001`~`0016` 적용 성공) → `supabase functions deploy guest-ingest account-delete`를 진행했다. 배포된 `guest-ingest`를 publishable key로 실제 호출해 정상 `200`/허용되지 않은 필드 `422`를 확인했고(검증용 관측치는 `withdraw`로 사후 정리), `account-delete`는 무인증 요청 `401` 반환을 확인했다. **Windows PyInstaller 빌드·Credential Manager는 여전히 미검증**(사용자 지시로 이번 작업에서 제외).
- **해소 예상 위치**: hosted 적용·Edge 검증은 완료. Windows 빌드는 단계 12에서 사용자가 직접 수행.

### 6. 최종 Windows 시각적 폴리시

- **최초 지적**: 단계 6.
- **현재 상태**: 사용자 주도 전체 UI 최종 점검 예정.
- **해소 예상 위치**: 단계 12.

### 7. tombstone 물리 정리·비활성 장치 제거

- **최초 지적**: 단계 8; 하드닝 §5 비목표.
- **현재 상태**: 범위 제외(데이터 규모 문제 발생 후).
- **해소 예상 위치**: 이후 릴리스.

### 8. 휴대용 아카이브 UI 배선

- **최초 지적**: 단계 10; 하드닝 M1/H-3.
- **내용**: writer/reader/검증/중복 방지/provenance/outbox는 구현·테스트 완료, UI만 미배선.
- **현재 상태**: **미루기 확정(H-3)**. runbook은 CSV/XLSX 대체 안내.
- **해소 예상 위치**: 다음 릴리스(저위험 추가).

### 9. 실제 세션 폐기(Auth Admin 로그아웃)

- **최초 지적**: 하드닝 H-3.
- **내용**: `revoke_all_devices`는 장치 행만 삭제. 활성 세션/refresh token 폐기는 Auth Admin API 필요.
- **현재 상태**: 한계를 UI·runbook에 명시(D-6 연기).
- **해소 예상 위치**: 다음 릴리스.
