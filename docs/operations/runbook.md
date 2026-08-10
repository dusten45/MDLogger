# MDLogger 운영 Runbook(단계 11)

이 문서는 로드맵 13장 단계 11의 완료 조건 중 "운영 runbook과 장애 대응 절차
작성", "key/token 유출 대응 절차 작성" 을 충족한다. 게스트 ingest 진단 정리,
계정 삭제, 장치 해제, 백업/복구, key rotation, 유출 대응을 다룬다.

## 1. 환경 구성: local / production

| 항목                  | local 개발                     | production                          |
| --------------------- | ------------------------------ | ----------------------------------- |
| Supabase CLI          | 2.109.1 고정                   | 소유자 장비만 사용                  |
| 데이터베이스          | `supabase start` (Docker)      | hosted project (지역은 결정 17.3 G) |
| publishable(anon) key | `.env`/환경 변수               | hosted 프로젝트의 anon key          |
| service-role key      | Edge Function 서버 환경 변수만 | hosted 프로젝트의 service-role key  |
| 테스트                | `supabase test db`             | staging에서 동일 절차               |

클라이언트 앱은 `MDLOGGER_SUPABASE_URL`과 `MDLOGGER_SUPABASE_ANON_KEY` 두
환경 변수를 읽는다(우선순위: 환경변수 > 번들 빌드 설정 > 없음, `remote/config.py`).
배포 빌드는 §1.1의 절차로 anon key를 번들에 주입한다. service-role/secret key는
`remote/config.py` 어디에도 들어가지 않는다.

### 1.1 배포 빌드 절차 (publishable 설정 주입)

배포용 exe가 로그인·게스트 ingest를 활성화하려면 빌드 시점에 publishable
(anon) 값을 주입해야 한다(하드닝 H1). 우선순위는 **환경변수 > 번들 빌드 설정

> 없음(오프라인)** 이며, 개발·테스트에서 환경변수가 번들 값을 덮어쓴다.

```bash
# 1) 값 주입 — 빈 값이면 스크립트가 실패한다. service-role/secret key를 넣으면
#    `assert_not_secret`/재스캔에서 중단된다.
MDLOGGER_SUPABASE_URL=<hosted project url> \
MDLOGGER_SUPABASE_ANON_KEY=<hosted anon key> \
    uv run python scripts/generate_build_config.py
#    → src/mdlogger/remote/_bundled_config.py 생성 (gitignore 대상, 커밋 금지)

# 2) 빌드 — 생성 모듈이 패키지 내부에 존재하므로 PyInstaller가 자동 번들한다.
uv run pyinstaller --noconfirm --clean --onefile --windowed --name MDLogger run.py

# 3) 산출물 시크릿 스캔 — service-role key·secret JWT·URL 자격 증명 0건이어야 한다.
uv run python -m mdlogger.secret_scan dist/MDLogger.exe

# 4) 체크섬
uv run python -m mdlogger.checksum dist/MDLogger.exe
```

- `_bundled_config.py`에는 오직 URL과 anon key만 담는다. 생성 후 재스캔으로
  service-role key(`sb_secret_`/role=`service_role` JWT)와 임베드된 자격 증명이
  없음을 보장한다.
- anon key는 로드맵 8.1에 따라 산출물 포함이 허용된다. service-role/secret key를
  클라이언트 산출물에 넣는 경로는 `scripts/generate_build_config.py`와
  `src/mdlogger/secret_scan.py`가 모두 차단한다.
- `README.md`는 사용자 관점이므로 이 절차를 넣지 않는다(소유자 runbook 전용).

### 1.2 릴리스 정책 운영 (하드닝 H3)

서버 `public.release_policies`가 릴리스 킬 스위치와 최소 지원 버전을 강제한다.
클라이언트 버전은 단일 출처(`src/mdlogger/_version.py`, hatchling dynamic
version)에서 오며 게스트 ingest·장치 등록·아카이브 manifest로 전송된다.
릴리스는 이 값을 실제 tag로 올린 뒤 배포한다.

- 초기 정책(결정 D-7 확정): `latest_version = minimum_supported_version = 0.1.6`
  (0.1.6가 유일한 버전이라 최소=최신), `update_url`은 비워 둔다(당장 마이그레이션할
  업데이트 없음). 이후 업데이트가 생기면 이 행의 latest/minimum/update_url을
  갱신하고 배포한다. 0.1.6 미만 클라이언트는 온라인에서 차단된다.
- 정책은 RLS로 읽기 전용이며 anon/authenticated가 조회할 수 있다. 클라이언트는
  최소 지원 미만이면 온라인(로그인·업로드·pull)을 차단하되 로컬 기록·내보내기는
  항상 허용한다(로드맵 17.3.J).
- 정책 값 갱신 절차:
  `supabase link --project-ref <ref>` → `supabase db push`(전체) 또는 제어판에서
  해당 행 UPDATE. 기존 릴리스의 pending 기록은 삭제되지 않고, 업데이트 후
  전송된다.

## 2. 확인 절차 (로컬 검증)

```bash
supabase start
supabase db reset          # migrations/ 전체 적용
supabase test db           # tests/database/ pgTAP 공격 테스트
supabase functions serve guest-ingest account-delete
```

모든 migration/함수 변경은 hosted 적용 전에 이 절차를 통과해야 한다. 이
sandbox는 Docker 기반 Supabase를 실행할 수 없으므로 소유자 환경에서 수행한다.

### 2.1 장시간 offline/online 전환 + 대량(1,000건) 동기화 스트레스

핸드오프 ②-2. `test_sync_engine.py::test_large_1000_game_sync_completes`
매트릭스를 hosted Supabase에 대해 재현한다. **게스트 경로를 기본**으로
한다(등록 경로는 아래 선택 항목).

중요한 동작 특성:

- **offline/online 전환 = 앱 재시작.** `MDLOGGER_SUPABASE_URL`/
  `MDLOGGER_SUPABASE_ANON_KEY`는 시작 시 `remote/config.py`가 읽고 실행 중엔
  바뀌지 않으므로, offline→online 전환은 환경변수 유무를 바꾼 뒤 재시작한다.
- **게스트 1,000건 = 10배치**(엔진 `BATCH_SIZE=100`)이고, 초과 직전 통과가
  rate limit(1분/10회)의 경계다. 반복 실행이나 다른 게스트와 같은 IP면
  IP 카운터도 공유되므로, 429 출력 후 재실행할 땐 1분 이상 기다린다.
- 실제 사용자 데이터를 건드리지 않도록 **반드시 스크래치 `MDLOGGER_DATA_DIR`**
  로 앱·스크립트를 함께 띄운다.

```bash
# 0) 사전 준비: hosted 값 준비 + 스크래치 디렉터리
#    MDLOGGER_SUPABASE_URL / MDLOGGER_SUPABASE_ANON_KEY는 hosted 프로젝트 값.
export MDLOGGER_DATA_DIR=/tmp/mdlogger-stress
unset MDLOGGER_SUPABASE_URL MDLOGGER_SUPABASE_ANON_KEY
rm -rf "$MDLOGGER_DATA_DIR"
```

```bash
# 1) OFFLINE 앱 기동 → 게스트로 자동 시작
uv run python run.py
```

```bash
# 2) 앱을 끈 뒤(또는 별도 터미널에서) 1,000건 pending 기록 생성
#    UI 입력과 같은 경로(GameService -> db.insert_game -> sync_outbox).
uv run python scripts/add_stress_games.py --count 1000 \
    --output /tmp/stress-syncids.txt
# 기대: 생성 완료 — games=1000, pending outbox=1000
```

```bash
# 3) 장시간 offline 유지: 앱을 다시 오프라인으로 띄워 기록이 pending으로
#    남는지 몇 분간 확인. 기록이 `sync_outbox`에 pending으로 쌓인 상태.
uv run python run.py   # (여전히 환경변수 미설정 = 오프라인)
# 통계 화면 games=1000, 동기화 상태는 '오프라인/보류' 유지 확인
```

```bash
# 4) ONLINE 전환: 앱 종료 후 hosted 환경변수를 설정하고 재기동
export MDLOGGER_SUPABASE_URL=<hosted project url>
export MDLOGGER_SUPABASE_ANON_KEY=<hosted anon key>
uv run python run.py
# 게스트 coordinator가 자동으로 10배치를 업로드한다.
# 앱 동기화 상태가 '최신/동기화됨'으로, pending이 줄어 0이 되는지 확인.
```

```bash
# 5) 로컬 측 검증 (앱 종료 후)
uv run python scripts/add_stress_games.py --count 0
# 기대: 생성 완료 — games=1000(+0), pending outbox=0(+0)
# 막 생성이 아니라 로컬 잔여를 재확인하는 용도(--count 0 허용).
# 또는 앱 통계 창에서 게임 수 1000 확인.
```

**서버 측 검증** — Supabase Dashboard SQL Editor(또는 service-role psql)에서
`analytics.duel_observations`를 조회한다(analytics 스키마는 service-role 전용).

```sql
-- 게스트 관측치 수(설치 pseudonym 기준). installation_id는
-- $MDLOGGER_DATA_DIR/global/profiles.json 의 "installation_id" 값.
select count(*) as obs
from analytics.duel_observations
where source_kind = 'guest'
  and contributor_key = analytics.pseudonym_for('<installation_id>');
-- 기대: obs = 1000

-- 보다 엄밀한 교차 검증: 스크립트가 남긴 sync_id 파일과 일치 개수.
-- (정확 비교가 필요할 때만; 1,000개라 매번은 번거로움)

-- 배치 요약: 10배치, accepted 합계 1000, skipped/rejected 0
select count(*) as batches,
       sum(accepted_count) as accepted,
       sum(skipped_count)  as skipped,
       sum(rejected_count) as rejected
from analytics.ingestion_batches
where source_kind = 'guest'
  and installation_key = analytics.pseudonym_for('<installation_id>');
-- 기대: batches=10, accepted=1000, skipped=0, rejected=0
```

**체크리스트**: ☐ 1) 오프라인 게스트 기동 ☐ 2) 1,000건 pending 생성(games=1000,
pending=1000) ☐ 3) 장시간 offline 유지(기록 손실·중복 없음) ☐ 4) online 전환 후
자동 업로드 ☐ 5) 로컬 pending 0·games 1000 유지 ☐ 6) 서버 `duel_observations`
== 1000(또는 sync_id 일치) ☐ 7) `ingestion_batches` 10배치 accepted 1000·거부 0.

**등록 계정 경로(선택)**: 호스티드에 Supabase Auth 계정이 필요하다. (a) online으로
로그인해 등록 프로필을 만든 뒤, (b) 환경변수를 제거한 오프라인 재시작으로 로컬
기록을 쌓고(스크립트는 `--kind registered --user-id <계정 uuid>`), (c) 다시 online
재시작해 양방향(푸시+풀) 동기화를 확인한다. 서버 게임 수는 `public.games`(해당
사용자/장치)로, 관측치는 아래로 확인한다.

```sql
select count(*) as obs
from analytics.duel_observations
where source_kind = 'registered'
  and contributor_key = analytics.pseudonym_for('<user_uuid>');
```

**정리**: 스크래치 디렉터리 삭제, hosted의 테스트 관측치·rate 이벤트는 진단 목적이므로
원하면 `public.guest_rate_events` 과거 행·`guest-ingest` 테스트를 정리한다(§6, §11).

## 3. 계정 데이터 내보내기 (사용자 요청 대응)

사용자가 개인 데이터 사본을 요청하면 클라이언트의 "내 데이터 내보내기"가
`export_account_data` RPC를 호출해 profile·games·devices를 JSON으로 저장한다.

- 분석용 `duel_observations`는 내보내기에 포함되지 않는다(로드맵 12.4).
- 게스트 계정은 auth 프로필이 없으므로 내보내기 대상이 아니다.
- **휴대용 아카이브(단계 10)는 현 릴리스에서 UI가 배선되지 않아 사용할 수
  없다**(결정 H-3, 하드닝 M1). 게스트/로컬 데이터를 옮겨야 하면 통계 창의
  **CSV/XLSX 내보내기**를 사용한다(데이터 탈출 경로 보장, 로드맵 17.3.J).
  휴대용 아카이브는 다음 릴리스에서 저위험으로 추가한다.

## 4. 계정 삭제 절차

클라이언트의 "계정 삭제"는 `account-delete` Edge Function에게 본인 access
token만 보낸다. 함수는 JWT를 검증해 대상 사용자를 확인한 뒤:

1. `public.delete_account_data(target_user)` 호출 → 개인 games·devices·profiles
   삭제.
2. Auth Admin API(`admin.auth.admin.deleteUser`)로 auth 사용자와 모든
   세션/refresh token 폐기.

분석용 `duel_observations`는 보존된다(계정 삭제는 듀얼 철회가 아님, 로드맵
9.3). 클라이언트는 feedback으로 삭제 요약을 받고, 성공 시 저장된 refresh
token을 제거하고 게스트로 전환한다.

### 삭제 실패 시

- `delete_data_failed`: 개인 데이터 삭제 실패. 전체 함수가 500을 반환하므로
  재시도 시 처음부터 다시 실행된다(idempotent).
- `delete_user_failed`: 개인 데이터는 지워졌으나 auth 사용자 삭제 실패.
  재시도는 `deleteUser`를 멱등하게 처리한다. 중단된 사용자는 지원에서
  수동 확인한다.

## 5. 장치 해제

- "모든 기기에서 로그아웃": `revoke_all_devices` RPC. 서버에서 이 계정의
  모든 `devices` 행을 삭제한다.
- "특정 장치 해제": `revoke_device(installation_id)` RPC. 해당 장치만
  해제한다.

### 한계 (하드닝 H-3, 결정 D-6)

- `revoke_all_devices`/`revoke_device`는 **장치 행만 삭제**한다. 이미 발급된
  access token의 세션·refresh token을 Auth Admin API로 폐기하지 않으므로,
  해제된 이전 장치는 JWT 만료까지 계속 동기화할 수 있고 이후 자유롭게
  재로그인해 재등록될 수 있다.
- **현 단계 공지**: 실제 세션 폐기는 다음 릴리스에서 Auth Admin API 경로로
  구현한다. 지금은 클라이언트가 "모든 기기에서 로그아웃" 후 자신의 저장된
  refresh token을 제거하고 재로그인하도록 안내하며(클라이언트 계약),
  서버 측 활성 세션 폐기는 미완이다. 유출 대응(10절)에서 refresh token 유출 시
  이 한계를 고려해 임계 판단한다.

`devices` 행 삭제는 pull cursor acknowledgment 정보를 잃지만, 삭제된 장치가
다시 로그인하면 `register_or_touch_device`로 재등록된다.

## 6. guest ingest 진단 메타데이터 정리

`prune_guest_ingest_diagnostics(older_than_days)`는 `analytics.ingestion_batches`
와 `analytics.rejected_observations`만 정리한다. 기본 보존 기간은 90일
(운영 값, 결정 17.2). `analytics.duel_observations`, 개인 games tombstone,
`withdrawn_at` 마커는 절대 삭제하지 않는다(검토 게이트 R11-3).

운영에서 주기 실행(예: cron / pg_cron) 예시:

```sql
select public.prune_guest_ingest_diagnostics(90);
```

클라이언트(anon/authenticated)는 이 함수를 직접 호출할 수 없다. service_role
전용이다.

`public.guest_rate_events`(guest ingest rate limit 카운터, 하드닝 H5)는
진단·남용 방어용이다. 자유롭게 삭제해도 되며, 운영에서 주기적으로 오래된 행을
정리한다(예: `delete from public.guest_rate_events
where requested_at < now() - interval '1 day';`).

## 7. 보존 정책

- 개인용 `games.deleted_at` **tombstone**: 무기한 보존. 모든 장치가 삭제
  version을 확인할 때까지 보존한다(로드맵 9.3).
- 분석용 `duel_observations.withdrawn_at` **마커**: 무기한 보존. 기본 분석
  dataset에서 제외된 상태를 영구히 기록한다.
- guest ingest **진단** 메타데이터(ingestion_batches, rejected_observations):
  90일 후 정리 대상. 분석 observation과 분리되어 있다.

## 8. 백업과 복구

- Supabase **PITR과 일일 자동 백업은 Pro 이상 유료 플랜 전용**이다(Pro 7일, Team
  14일, Enterprise 30일 보존). 무료 플랜은 자동 백업이 없으므로, **CLI로 정기적으로
  SQL 덤프를 떠서 오프사이트에 보관**한다.

    ```bash
    # 주기 실행(예: cron) — 전체 DB를 SQL 덤프로 보관
    supabase db dump -f backups/mdlogger-$(date +%Y%m%d).sql
    ```

- 로컬 개발 DB도 SQL 덤프로 산출물을 보관한다.

### contributor_salt 백업·재생성(하드닝 H-8)

- `analytics.contributor_salt`는 분석 pseudonym `contributor_key`의 결합 키로,
  서버 전용(service secret 아님)이다. 백업/복원 시 반드시 함께 복원해야 한다
  (`analytics` 스키마 덤프 포함).
- **salt가 재생성되면(예: `db reset`, 다른 프로젝트로 덤프 미포함 복원) 모든
  `contributor_key`가 바뀌어 종단 분석이 단절된다.** 이를 탐지하는 version
  marker는 아직 없으므로, 복구 rehearsal(아래)에서 salt가 보존됐는지
  `select salt from analytics.contributor_salt`로 확인한다.
- salt 회전은 pseudonym 전체 재결합 위험이 있어 기본적으로 금지(9절).
- **복구 rehearsal**: 백업에서 복원한 뒤 다음을 확인한다.
    1. RLS 정책이 복원되는가(`\dp`로 acl 확인, `analytics` 4개 테이블 RLS 활성 확인. 2026-08-10 로컬 rehearsal에서 유지됨).
    2. 서버 함수와 트리거가 유지되는가(`\df`, `\dft`).
    3. `auth.users`/`auth.schema_migrations`가 함께 복원되는가.
    4. `pseudonym_for`가 같은 익명키를 도출하는가: `select analytics.pseudonym_for('<user_id>')` 를 복원 전·후 비교(2026-08-10 rehearsal: 일치 확인).
    5. **`extensions` 스키마(및 pgcrypto)도 함께 복원되는가**: `pseudonym_for`는 `extensions.digest`(pgcrypto sha256)를 호출하므로, `analytics` 스키마만 복원하면 익명키 계산이 깨진다(`schema extensions does not exist`).
    6. 클라이언트 `last_pulled_version`이 복원된 서버보다 앞서면 full
       reconciliation을 강제한다(결정 17.3 C).
- 복원은 데이터 파괴 사고 시에만 사용한다. 일반 결함은 forward-fix
  migration으로 대응한다(README rollback 절 참고).
- **대응 원칙·최소 지원 버전 재확인(2026-08-10, 소유자 ①-3 확정)**: 일반 결함은
  forward-fix migration으로 대응하고, 백업 복원은 데이터 파괴 사고 시에만 쓴다.
  최소 지원 앱 버전 = `0.1.6`(D-7, 유일 버전이라 최소=최신).

## 9. key rotation

- **anon key**: 클라이언트에 포함된 공개 값. 회전 시
  `MDLOGGER_SUPABASE_ANON_KEY`를 새 값으로 갱신하고 앱을 재배포한다. 구 키는
  폐기 전 일정 기간 병행한다.
- **service-role key**: Edge Function 환경 변수로만 존재. 회전 시:
    1. 새 key를 생성.
    2. Edge Function 환경 변수(`SUPABASE_SERVICE_ROLE_KEY`)를 새 값으로 갱신.
    3. 함수를 재배포.
    4. 구 key를 폐기.
- **contributor_salt**: 분석 pseudonym용 서버 전용 salt(0005). 회전하면 기존
  pseudonym이 모두 바뀌어 분석 정합성이 깨지므로 **회전하지 않는다**. 유출 시
  아래 10절을 따른다.

## 10. key/token 유출 대응 절차

1. **확인과 격리**: 유출된 값의 종류(anon/service-role/access/refresh,
   contributor_salt)와 범위를 확인한다.
2. **영향 평가**:
    - `service-role key` 유출: 데이터베이스와 관리 API에 대한 완전 접근. 즉시
      회전(9절)하고 감사 로그를 확인한다.
    - `refresh token` 유출: 해당 세션만 영향. `revoke_all_devices`로 이 계정의
      모든 세션을 폐기하고 사용자에게 재로그인 안내.
    - `anon key` 유출: 공개 값이므로 영향이 제한적. 회전만 수행.
    - `contributor_salt` 유출: 분석 pseudonym 재결합 위험. 소유자가 판단해
      salt 회전과 분석 dataset 재검토.
3. **차단**: service-role 유출 시 프로젝트 접근 키를 회전하고, 필요하면
   데이터베이스 접근을 제한한다.
4. **고지**: 개인정보 유출 가능성에 따라 사용자·소유자에게 통지한다.
5. **문서화**: 유출 사건 기록과 재발 방지 조치를 남긴다.

## 11. 이메일 템플릿 / rate limit

이메일 템플릿(가입 확인, 비밀번호 재설정)은 대시보드 **Authentication → Emails**,
auth rate limit은 **Authentication → Rate Limits**에서 구성한다(로드맵 단계 11).
로컬 개발은 `supabase/config.toml`의 `[auth.email.template.*]`를 쓴다. 기본값으로도
동작하며, 남용이 관찰되면 rate limit을 조정한다. guest ingest rate limit·이상
탐지·Turnstile은 `guest-ingest`의 `checkAbuseGuards` 확장 경계에 추가한다(로드맵 12.3).

- guest ingest rate limit **운영값 확정(2026-08-10)**: installation·IP 각각
  **1분 창 최대 10회**(`RATE_MAX_PER_WINDOW=10`, `RATE_WINDOW_MINUTES=1`, 하드닝
  H5/D-4). 초과 시 `429` + `retry_after` 사용자가 몰아 기록하는 정상 사용을
  방해하지 않는다.
- **Turnstile 도입 판단 기준(2026-08-10 확정)**: guest 업로드 중 rate-limit
  (`429`)에 걸리는 배치가 반복 관측되거나, 알 수 없는 installation이 대량
  거부되는 남용이 이어지면 Turnstile 도입을 검토하기로 정한다. 도입 전까지는
  정상 사용자를 귀찮게 하지 않도록 CAPTCHA 없이 동작한다(결정 12).
