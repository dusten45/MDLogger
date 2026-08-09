# MDLogger — `supabase test db` 최초 실기동에서 드러난 버그 기록

- **작성일**: 2026-08-10 (단계 12 진입 조건 점검 중)
- **상태**: 5개 원인 모두 해소 완료 (2026-08-10) — `supabase test db` 전체 통과(173 tests)
- **관련 문서**: `docs/pre-release-hardening-roadmap.md` (§10 단계 12 진입 조건, §7 검증 매트릭스), `docs/open-items.md` 항목 10

---

## 1. 배경 · 왜 이 문서가 생겼나

하드닝 로드맵 §10에 "소유자 환경에서 `supabase db reset` + `supabase test db`가 전체 통과"가
단계 12 진입 조건(3번)으로 걸려 있다. 이 조건은 `docs/open-items.md` 항목 10에
"소유자 환경 검증 필요(Docker)"로 미뤄져 있었는데, 이번에 **실제 로컬 Supabase 스택
(podman)에서 처음 실행**되었다.

결과: `supabase db reset`은 **성공**, `supabase test db`는 **실패**.

실패의 의미를 오해하면 안 된다. 로드맵 §12와 `open-items.md`는 이 pgTAP 서버 테스트를
"작성(written)"까지로 기록하고 있었다. 따라서 이번 실패는 **"회귀"가 아니라 "최초 실기동에서
표면화된 잠재 문제"**다. 즉 테스트 파일과 마이그레이션이 실제 DB에서 실행된 적이 없었고,
이번이 첫 검증이다.

> 짚고 갈 점: 클라이언트 pytest(최초 기록 시점 248, 최신 252 passed)는 통과했지만 이는 서버
> SQL과 무관하다. 서버 사이드는 pgTAP(`tests/database/`)이 별도 검증이며, 그게 지금 처음 돌았다.

---

## 2. 실행 요약

- 스택: `podman`(rootless) 소켓으로 Supabase CLI 2.109.1 로컬 스택 기동
  (`DOCKER_HOST=unix:///run/user/1000/podman/podman.sock`)
- `supabase db reset` → migrations `0001`~`0014` 적용 성공, `pgtap` extension 설치됨
- `supabase test db` → 파일별 결과:

| 파일                        | 계획 | 실제 결과                             |
| --------------------------- | ---- | ------------------------------------- |
| 01~06 (기존 R4 공격 테스트) | —    | **전체 통과**                         |
| 07_account_operations       | 21   | 16 실행, **1 실패** + 19행 parse 오류 |
| 08_hardening                | 24   | **0 실행** (첫 단언에서 parse 오류)   |
| 09_release_policy           | 6    | 4 실행, **1 실패** + UPDATE 권한 오류 |
| 10_environment_version      | 10   | 10 실행, **1 실패**                   |
| 11_guest_abuse              | 8    | **0 실행** (함수 생성·호출 실패)      |

실패는 서로 다른 **4+1개의 독립된 원인**으로 나뉜다. 아래에 각각을 다룬다.

---

## 3. 원인별 상세

---

### 3.1 원인 1 — `0014_guest_abuse.sql`: `guest_rate_ok`에서 파라미터/컬럼 이름 충돌 (실제 버그)

**영향 파일**: `supabase/migrations/0014_guest_abuse.sql`, `supabase/tests/database/11_guest_abuse.test.sql`

#### 뭘 하다가 생겼나

하드닝 H5에서 guest ingest 남용 방어(rate limit)를 구현하며 `public.guest_rate_ok()`
PL/pgSQL 함수를 만들었다. 함수의 **입력 파라미터 이름을 `bucket_key`** 로 정했고,
이 함수는 내부에서 `public.guest_rate_events` 테이블을 쿼리한다. 그런데 **이 테이블에도
동일한 이름의 컬럼 `bucket_key`가 존재**한다.

```sql
create or replace function public.guest_rate_ok(
    bucket_key text,          -- ← 파라미터
    window_minutes integer,
    max_requests integer
)
...
    select count(*) into current_count
    from public.guest_rate_events
    where bucket_key = guest_rate_ok.bucket_key   -- ← 모호함
      and requested_at > now() - make_interval(mins => window_minutes);
```

#### 뭐가 문제인가

- `where bucket_key = ...`의 **비한정 `bucket_key`** 가 PL/pgSQL 변수인지 테이블 컬럼인지
  모호해집니다. PostgreSQL은 이 표현식을 해석하지 못하고 다음 오류를 냅니다:

    ```
    ERROR: column reference "bucket_key" is ambiguous
    DETAIL: It could refer to either a PL/pgSQL variable or a table column.
    ```

- 오른쪽 `guest_rate_ok.bucket_key`는 함수 자신의 파라미터를 한정한 표기이지만,
  FROM 절의 테이블이 같은 이름 컬럼을 가져 충돌합니다.
- **함수가 만들어지지 못하므로 → `guest_rate_ok` 호출이 전부 실패 → 이를 호출하는
  `guest_rate_check`(0014에 정의)도 실패 → H5의 rate limit(1분/10회, D-4)이 실제로
  동작하지 않습니다.** 11번 테스트 8개 전부가 여기 파묻혀 0 실행됐습니다.

#### 왜 지금 드러났나

0014가 `supabase db reset`으로 처음 실제 적용되어 함수가 처음 생성/호출됐기 때문이다.
`create function`은 문법 문제만 검사하고, **본문의 컬럼/변수 한정 문제는 실행 계획을
만들 때** 드러나므로 `supabase test db`(호출 시점)에서 비로소 표면화됐다.

#### 해야 할 것

- **forward-fix가 필요**하다. 로드맵/README 정책상 적용된 migration을 고치지 않으므로
  새 migration(예: `0015_fix_guest_rate_ok.sql`)으로 `create or replace function guest_rate_ok`
  를 다시 정의하되, **파라미터 이름을 `p_bucket_key`처럼 바꿔** 테이블 컬럼과 충돌을 제거한다.
  (`set search_path = ''`라 테이블은 `public.`으로 한정돼 있으므로, 파라미터만 이름을 바꾸면 된다.)
- 이후 `11_guest_abuse.test.sql`이 통과하는지 확인한다.
- 참고: 같은 0014에 정의된 `guest_rate_check`도 파라미터 이름 `ip`(테이블 컬럼 `requested_at`과는
  무관하지만) 쪽은 문제가 없고, `guest_rate_ok` 호출만 고쳐지면 저절로 살아난다.

#### 실물 재현 기록 (2026-08-10, Edge Function 검증 중)

- 하드닝 로드맵 진입 조건 4(Edge Function) 검증 과정에서 `guest-ingest`로 정상 형식의 요청을
  보냈더니 **형식 검증(batch_id/installation_id/payload_version/observations)은 전부 통과**하고,
  rate limit 단계에서 실패했다.

    ```bash
    # 요청: batch_id·installation_id·sync_id 모두 유효 UUID, payload_version=1,
    #       observations=[{sync_id, played_at_local, result=win, turn_order=first,
    #                      environment_version_id=md-2026-08}]
    # 응답:
    HTTP/1.1 500 Internal Server Error
    {"code":"rate_check_failed"}
    ```

- `guest-ingest/index.ts`에서 `rate_check_failed`는 216~227행의
  `supabase.rpc("guest_rate_check", …)`가 에러를 반환했을 때만 내는 응답이다. 정확히 위 버그의
  실행 경로(guest_rate_check → guest_rate_ok 실행 실패)와 일치한다.
- **결론**: 이 버그로 인해 guest ingest가 온라인에서 전혀 성공할 수 없다(정상 요청조차 500).
  진입 조건 3(`supabase test db`)과 4(Edge Function)가 같은 뿌리(0014)에 함께 막혀 있다.
- 확인 팁: `supabase functions serve` 로그의 `console.error("guest rate check failed",
{ code: … })`에서 실제 SQLSTATE로 확증할 수 있다.

---

### 3.2 원인 2 — 정책 이름 불일치: `policies_are(_, ARRAY['SELECT'])` vs 실제 이름 (09, 10)

**영향 파일**: `0012_release_policy.sql` / `09_release_policy.test.sql`, `0013_environment_version.sql` / `10_environment_version.test.sql`

#### 뭘 하다가 생겼나

H3/H4에서 RLS 정책을 만들며 **정책 이름을 설명적인 이름**으로 지었다:

- `0012`: 정책 이름 `release_policies_select_public`
- `0013`: 정책 이름 `environment_versions_select_public`

테스트는 pgTAP의 `policies_are`를 쓰며 **정책 이름이 RLS 기본값인 `'SELECT'`** 라고 단정한다:

```sql
select policies_are('public', 'release_policies', ARRAY['SELECT'],
                    'release_policies에는 SELECT 정책만 존재한다');
```

#### 뭐가 문제인가

- `policies_are`는 `pg_policies.policyname`을 정확히 비교한다. 테스트는 "SELECT"라는
  이름을 기대하는데 실제 정책 이름은 `release_policies_select_public` / `environment_versions_select_public`이어서:
    ```
    # Extra policies: release_policies_select_public
    # Missing policies: "SELECT"
    ```
    **정책은 잘 존재하지만 이름이 달라 실패**한다. 10번은 이것만 실패(9/10 통과), 09는 이어지는
    UPDATE 검증까지 꼬였다.

#### 이어서 꼬인 09의 부가 문제 (테이블 revoke vs RLS 0행)

- `0012`는 `revoke all on table ... from anon, authenticated` 후 `grant select`만 주고
  RLS 정책도 SELECT만 만들었다. 테스트는 "authenticated가 UPDATE를 시도하면 **RLS가 0행 필터**"
  할 것으로 가정하지만, 실제로는 테이블 UPDATE 권한 자체가 없어서:
    ```
    ERROR: permission denied for table release_policies
    ```
    하드 에러(`42501`)가 먼저 난다. RLS의 silent deny가 아니라 **권한 회수로 인한 접근 거부**다.

#### 왜 지금 드러났나

09/10 테스트는 작성만 됐고 실제로 돌아본 적이 없어서, 정책 이름 파라미터와 테이블 권한의
조합이 실제 마이그레이션과 맞는지 검증된 적이 없었다.

#### 해야 할 것

한쪽을 기준으로 맞춘다(둘 다 유효한 선택이므로 **소유자 판단** 필요):

- **옵션 A (마이그레이션에 맞추기)**: 테스트의 `policies_are` 두 번째 인자를 실제 정책 이름
  (`ARRAY['release_policies_select_public']` 등)으로 변경.
- **옵션 B (기본 이름 사용)**: 마이그레이션 정책을 `create policy "SELECT"`와 같은 기본 이름으로
  만들도록 forward-fix. 단, 기존 명명 스타일과 충돌 여부 확인.
- **09의 UPDATE 검증**: 테이블 `revoke`를 유지할 것인지(→ 테스트를 `throws_ok(...,'42501',...)`로) 아니면
  RLS 0행 필터를 원하는지(→ grant UPDATE를 주되 정책 없음) 정한 뒤 테스트/마이그레이션을 일치시킨다.
- 문서화된 정책(RLS 기본 거부 + 클라이언트 수정 금지)의 **의도는 그대로 유지**되도록 해야 한다.

---

### 3.3 원인 3 — pgTAP `is()`에 bigint vs integer 타입 불일치 (07:182)

**영향 파일**: `supabase/tests/database/07_account_operations.test.sql` (182행)

#### 뭘 하다가 생겼나

진단 정리 함수의 반환값을 검증하면서 왼쪽을 `::bigint`로 캐스팅했다:

```sql
select is(
    (public.prune_guest_ingest_diagnostics(90) ->> 'pruned_batches')::bigint,  -- bigint
    1,                                                                          -- integer 리터럴
    '90일보다 오래된 진단 batch만 정리된다'
);
```

#### 뭐가 문제인가

- pgTAP의 `is(got, expected, description)`은 `anyelement, anyelement, text` 서명이고,
  **두 anyelement 인자는 같은 타입이어야** 한다.
- 왼쪽은 `::bigint`, 오른쪽 리터럴 `1`은 `integer` → 타입이 어긋나 PostgreSQL이 후보 함수를
  찾지 못한다:
    ```
    ERROR: function is(bigint, integer, unknown) does not exist
    ```
- 같은 파일의 다른 `is()` 호출들(예: `jsonb_array_length(...)`, 1 → int/int)은 정상 해석돼
  통과했다. **`::bigint` 캐스트만이 원인**이다.

#### 왜 지금 드러났나

07 테스트가 실제 DB에서 처음 실행됐고, bigint 캐스트와 정수 리터럴의 anyelement 해석 불일치는
실행 시점에만 드러난다.

#### 해야 할 것

- 왼쪽을 `::int`로 바꾸거나, 오른쪽을 `1::bigint`로 명시해 타입을 일치시킨다.
- (가능하면) 같은 패턴을 파일 전체에서 점검해 유사한 bigint/int 혼용이 없는지 확인한다.

---

### 3.4 원인 4 — H2 권한 회수 후 오류 코드 변화: `28000` vs `42501` (07 test 7)

**영향 파일**: `supabase/tests/database/07_account_operations.test.sql` (79~84행), 마이그레이션 `0011_permission_forward_fix.sql`

#### 뭘 하다가 생겼나

07 테스트는 "비인증 export는 거부된다"를 다음과 같이 검증한다:

```sql
set local role anon;
select throws_ok(
    $$ select public.export_account_data() $$,
    '28000',                        -- authentication required
    'authentication required',
    '비인증 export는 거부된다'
);
```

#### 뭐가 문제인가

- 테스트는 **함수 본문이 비인증을 감지해 SQLSTATE `28000`을 던질 것**을 전제로 한다.
- 그러나 하드닝 H2(`0011`)가 `export_account_data`의 EXECUTE를 `anon`/`authenticated`에서
  **회수**했다. 그래서 함수 본문에 도달하기 전에 DB 권한 게이트에서 먼저:
    ```
    caught: 42501: permission denied for function export_account_data
    wanted: 28000: authentication required
    ```
    즉 07 테스트는 **H2 이전 동작**을 기대하고 있고, H2 이후 실제 동작과 어긋난다.

#### 왜 지금 드러났나

07 테스트와 0011(H2)이 서로 다른 시점에 만들어졌고, 둘을 **한 번도 실제로 함께 실행해 본 적이
없어서** 오류 코드 기대가 갱신되지 않았다.

#### 해야 할 것

의도에 따라 정한다(소유자 판단):

- **옵션 A**: 클라이언트는 `42501`도 "거부됨"으로 받으므로, 테스트 기대를 `'42501'`로 갱신.
- **옵션 B**: 의미 있는 `28000`(인증 필요)을 클라이언트에 주고 싶다면,
  `export_account_data`를 회수 대상에서 제외하고 함수 내부 검증이 `28000`을 던지도록 유지.
- 어느 쪽이든 **클라이언트(desktop)가 받는 오류 코드 처리와 일치**하는지 함께 확인해야 한다
  (클라이언트 pytest `test_*account*` 등과 대조).

---

### 3.5 원인 5 — `08_hardening`: `is_false(boolean, unknown)` 해석 실패로 파일 전체 미실행

**영향 파일**: `supabase/tests/database/08_hardening.test.sql` (16~19행)

#### 뭘 하다가 생겼나

08(H2 검증)의 첫 assertion이:

```sql
select is_false(
    has_function_privilege('anon', 'public.next_game_change_version(uuid)', 'EXECUTE'),
    'anon은 next_game_change_version을 실행할 수 없다'
);
```

#### 뭐가 문제인가

```
ERROR: function is_false(boolean, unknown) does not exist
```

- 이 파일의 **첫 단언(19행)에서 해석 실패 → 뒤의 24개 assertion 모두 0 실행**됨
  (`Bad plan: planned 24, ran 0`).
- 다른 파일들의 `is` / `ok` / `lives_ok` / `results_eq` / `throws_ok`는 정상 해석된다.
  그런데 `is_false(boolean, unknown)`만 실패한 점이 특이하다(문자열 리터럴은 `unknown`→`text`
  캐스트가 정상 동작해야 한다).
- 두 가지 가능성:
    1. pgtap이 `is_false`를 두 번째 인자 없이(`is_false(boolean)`)만 제공하는 등 **서명 불일치**,
    2. `has_function_privilege`의 반환/`function spec` 해석이 이 인자 조합에서 다른 타입을 만들어
       어떤 함수와도 정확히 일치하지 않음.

#### 왜 지금 드러났나

08 테스트가 실제 DB에서 처음 실행됐고, 특히 **파일의 맨 처음 assertion이 실패하면
해당 파일 전체가 멈춘다**는 특징 때문에 표면화됐다. (다른 파일들은 나중 assertion에서
실패해 부분 실행되었다.)

#### 해야 할 것

- 먼저 **설치된 pgtap 시그니처를 확인**한다. 예:
  `\df extensions.is_false` 또는 `select * from pg_proc where proname='is_false';`
- `is_false`가 어떤 서명인지 확인한 뒤, 테스트를 그 서명에 맞게 고치거나
  (해당이 안 되면) `is(false, has_function_privilege(...), 'desc')`처럼 확실한 형태로 재작성한다.
- 해결 후 08 전체(24 assertion)가 실제로 도는지 확인한다.

---

## 4. 원인 간 상호작용과 영향

- **원인 1(0014)은 서버 동작 버그**로 가장 심각하다. guest ingest rate limit이 실제로
  동작하지 않는 상태라, H5의 "남용 방어" 의도가 무력화된다. → RH5 서버 게이트 미충족.
- **원인 2/3/4/5는 테스트·마이그레이션 정합성 문제**(대부분 “테스트가 실제와 다르게 작성됨”).
  소유자 판단으로 어느 한쪽(일반적으로 테스트)을 실제에 맞추면 해소된다.
- 종합하면 **진입 조건 3(`supabase test db` 전체 통과)은 현재 미충족**이며,
  **RH2(08)·RH3(09)·RH4(10)·RH5(11) 서버 게이트**도 이 실패가 해소되기 전까지 통과할 수 없다.
- 반면 진입 조건으로 `db reset`이 성공했고 01~~06(기존 R4 공격 테스트)은 전부 통과했으므로,
  스키마 기반·기존 보안 경계(01~~06)는 건재하다. 문제는 **하드닝 H2~H5가 추가한 부분**에 국한된다.

---

## 5. 정리 · 권장 순서

| #   | 원인                                            | 유형                 | 위치        | 우선순위                     |
| --- | ----------------------------------------------- | -------------------- | ----------- | ---------------------------- |
| 1   | `guest_rate_ok` 파라미터/컬럼 충돌              | **서버 동작 버그**   | `0014`      | **최우선** (rate limit 무력) |
| 2   | 정책 이름 불일치 + 09 UPDATE 권한               | 테스트↔마이그레이션  | `09`/`10`   | 높음                         |
| 3   | `is()` bigint/int 캐스트                        | 테스트 타입 오류     | `07:182`    | 보통                         |
| 4   | `export_account_data` 오류 코드 `28000`/`42501` | 테스트 기대 갱신     | `07` test 7 | 보통                         |
| 5   | `is_false` 해석 실패로 08 전체 미실행           | pgtap 서명 확인 필요 | `08:19`     | 높음 (08 확인에 필수)        |

권장 순서:

1. **pgTAP 시그니처 확인** (원인 5 사전 조건) — `is_false` 서명만 알면 08이 통째로 해제된다.
2. **원인 1 forward-fix migration** 작성 (`0015_..._fix_guest_rate_ok.sql`) → 11 해소.
3. **원인 3·4** 테스트 수정(캐스트·오류 코드) → 07 해소.
4. **원인 2** 정책 이름·테이블 권한 결정 → 09/10 해소.
5. 원인 5 수정 → 08 해소.
6. `supabase db reset` → `supabase test db` 전체 통과 재확인.

> 모든 마이그레이션 수정은 README의 forward-fix 정책(적용된 파일 미수정, 새 번호로 추가)을
> 따르고, 이후 `supabase db reset`/`supabase test db`로 재검증해야 한다.

---

## 6. 해소 기록 (2026-08-10)

아래 §5 권장 순서대로 수정·검증하여 5개 원인을 모두 해소했다(`supabase test db` 전체 통과).

### 적용한 수정 (5개 원인)

| #   | 원인                               | 수정                                                                      | 방법                                                                                                                                        |
| --- | ---------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `guest_rate_ok` 파라미터/컬럼 충돌 | **서버 forward-fix** `0015_fix_guest_rate_ok.sql`                         | PostgreSQL은 `CREATE OR REPLACE`로 입력 파라미터 이름을 바꾸지 못함(42P13) → `DROP FUNCTION` 후 `p_bucket_key`로 재정의, 권한 재부여        |
| 2   | 정책 이름 불일치·09 UPDATE 권한    | **테스트 수정** (사용자 결정: A)                                          | `policies_are`를 실제 이름(`release_policies_select_public`/`environment_versions_select_public`)으로, 09 UPDATE는 `throws_ok('42501')`으로 |
| 3   | 07 `is()` bigint/int               | **테스트 수정**                                                           | `::bigint` → `::int` (2곳)                                                                                                                  |
| 4   | `export_account_data` 28000/42501  | **서버 forward-fix** `0016_export_account_data_anon.sql` (사용자 결정: B) | anon에 EXECUTE 재부여 → 함수 본문이 `28000` 반환. 테스트 기대(`28000`) 유지                                                                 |
| 5   | `is_false` 해석 실패               | **테스트 수정**                                                           | pgTAP 1.3.3에 `is_false`/`is_true`가 **없음**을 확인 → `is(false, expr, 'desc')`로 9곳 교체                                                 |

### 원인 1·3 해소 후 표면화된 후속 테스트 보정

- `11_guest_abuse`: service_role의 `guest_rate_events` 직접 INSERT가 42501로 차단됨(원인 1 수정 전에는 함수가 깨져 0 실행). 실제 기록 경로인 `guest_rate_ok` 호출로 시딩하도록 변경, plan 8→10.
- `07` test 19: 첫 `prune(90)`이 오래된 batch·rejected를 함께 지워 두 번째 호출이 0 반환. 새 오래된 rejected 행을 넣어 재검증하도록 보정.

### 검증 결과

- `supabase db reset` — migration `0001`~`0016` 적용 성공 (`0015`·`0016` 포함)
- `supabase test db` — 11 files, 173 tests, **전체 통과**

---

## 7. (참고) 검증 현황 (2026-08-10, §6 수정·재검증 반영)

> 처음 이 문서를 쓸 당시는 최초 실기동에서 서버 검증이 실패한 상태였으나, §6의
> 5개 원인 수정·재검증으로 해소되었다. 아래는 해소 후 확인된 최신 상태다.

- `uv run ruff check .` : 통과
- `uv run ruff format --check .` : 통과 (87 files)
- `uv run ty check` : 통과
- `uv run pytest` : 252 passed, 4 skipped
- `supabase db reset` : 성공 (0001~0016 적용, pgtap 설치)
- `supabase test db` : **통과** — 11 files, 173 tests 전체 통과 (§6)
- 클라이언트 자동 검증(진입 조건 7)과 서버 검증(진입 조건 3) 모두 충족 (2026-08-10).
