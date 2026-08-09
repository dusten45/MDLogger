# MDLogger Supabase 서버 자산

이 디렉터리는 로드맵 단계 4의 서버 스키마·RLS·서버 함수와 자동화된 RLS
공격 테스트를 버전 관리한다. 애플리케이션 코드와 같은 repository에서
관리한다(로드맵 15장).

## 구성

| 경로                                           | 내용                                                                                           |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `migrations/0001_profiles.sql`                 | 개인용 `profiles`, 공용 `updated_at` 트리거                                                    |
| `migrations/0002_games.sql`                    | 개인용 `games`(naive ISO `played_at` 보존)와 `devices`                                         |
| `migrations/0003_rls.sql`                      | 등록 사용자의 소유자 전용 RLS 정책                                                             |
| `migrations/0004_change_version.sql`           | 서버 부여 `change_version` sequence와 서버 관리 필드 강제 트리거                               |
| `migrations/0005_analytics_projection.sql`     | `analytics` 스키마, 등록 games projection 트리거, 게스트용 제한된 ingest 함수                  |
| `migrations/0006_account_operations.sql`       | 계정 삭제용 서버 함수 인터페이스(`delete_account_data`)                                        |
| `migrations/0007_push_timezone_projection.sql` | 단계 7 push: 기록 시각 UTC offset 보존·timezone projection                                     |
| `migrations/0008_guest_upsert.sql`             | 단계 7 push: 게스트 upsert/withdraw ingest(필드 allowlist + idempotent)                        |
| `migrations/0009_stage8_sync.sql`              | 단계 8: change-version cursor, 낙관적 동시성 게임 mutation, 장치 등록/ack                      |
| `migrations/0010_account_operations.sql`       | 단계 11: 계정 데이터 내보내기·장치 해제·guest ingest 진단 정리                                 |
| `migrations/0011_permission_forward_fix.sql`   | 하드닝 H2: 함수 EXECUTE 명시 회수, projection 철회 가드, RLS 활성화, profiles 서버 필드 트리거 |
| `migrations/0012_release_policy.sql`           | 하드닝 H3: 릴리스 정책(최소 지원 버전·킬 스위치), 읽기 전용 RLS                                |
| `migrations/0013_environment_version.sql`      | 하드닝 H4: 환경 기준정보 + games에 환경/클라 버전 배선, projection 보정, ingest 거부           |
| `migrations/0014_guest_abuse.sql`              | 하드닝 H5: guest ingest rate limit 카운터·검사 함수(installation/IP)                           |
| `migrations/0015_fix_guest_rate_ok.sql`        | forward-fix: `guest_rate_ok` 파라미터/컬럼 이름 충돌 해소(`p_bucket_key`로 DROP·재정의)        |
| `migrations/0016_export_account_data_anon.sql` | forward-fix: anon `export_account_data` EXECUTE 재부여 → 본문이 28000(인증 필요) 반환          |
| `functions/guest-ingest/`                      | Guest Ingest Edge Function(필드 allowlist + rate limit 포함)                                   |
| `functions/account-delete/`                    | 계정 삭제 Edge Function(auth 먼저 삭제 → FK cascade, service_role)                             |
| `tests/database/`                              | pgTAP 기반 R4 공격 테스트(`01`~`11`)                                                           |

## 보안 경계 요약

- 클라이언트는 publishable(anon) key만 사용한다. service-role/secret key는
  Edge Function 환경 변수(`SUPABASE_SERVICE_ROLE_KEY`)로만 존재하며 이
  repository와 데스크톱 앱에 포함되지 않는다.
- `games`/`profiles`/`devices`는 RLS로 소유자 본인만 접근한다. 클라이언트
  물리 `DELETE`는 없고 개인 기록 삭제는 `deleted_at` tombstone UPDATE다.
- `user_id`, `created_at`, `updated_at`, `change_version`은 트리거가 서버
  값으로 강제한다. `profiles`의 `id`/`created_at`(불변)/`updated_at`도 트리거가
  강제한다(하드닝 H2).
- 등록 RPC·trigger 함수의 EXECUTE는 `anon`/`authenticated`에서 명시적으로
  회수한다(`from public, anon, authenticated`). `next_game_change_version`은
  소유권 검사가 없는 쓰기 함수이므로 특히 차단된다(하드닝 B2).
- `analytics` 테이블(`contributor_salt`, `duel_observations`,
  `ingestion_batches`, `rejected_observations`)과 `game_change_cursors`에 RLS를
  켜 기본 전면 거부로 둔다. `security definer` 함수는 소유자로 실행돼 그대로
  동작한다(하드닝 H-1).
- 분석 observation은 한 번 철회되면 어떤 경로의 upsert로도 `withdrawn_at`을
  지우지 않는다. 철회 마커는 무기한 보존된다(하드닝 M3, 로드맵 결정 6).
- `analytics` 스키마는 anon/authenticated 접근이 없다. 등록 기록은 DB
  trigger로, 게스트 기록은 service_role 전용 `public.ingest_guest_batch`
  wrapper(Edge Function 경유)로만 들어온다. 두 경로 모두 game UUID
  (`sync_id`)를 observation key로 사용해 import 후에도 중복되지 않는다.
- 분석 행에는 note, 이메일, 표시 이름, 직접 auth user ID가 존재하지 않고
  salt 기반 pseudonym(`contributor_key`)만 저장된다.

## 로컬 검증 절차 (Supabase CLI + Docker 필요)

```bash
supabase start          # 로컬 개발 스택 기동
supabase db reset       # migrations/ 전체를 빈 로컬 DB에 적용
supabase test db        # tests/database/ 의 pgTAP 공격 테스트 실행
supabase functions serve guest-ingest   # Edge Function 로컬 실행(선택)
```

`supabase test db`는 각 테스트를 트랜잭션으로 실행하고 롤백하므로 로컬
데이터를 남기지 않는다. 모든 migration 변경은 hosted 적용 전에 이 절차를
통과해야 한다.

### Fedora rootless Podman + Supabase CLI 2.109.1

이 개발 환경은 Supabase CLI 2.109.1을 고정해 사용한다. 해당 CLI가 생성하는
Edge Runtime bootstrap은 `/tmp/supabase-functions-serve-main-*/index.ts`에서
`/root/index.ts`로 `:ro` bind mount되는데, Fedora SELinux의 `user_tmp_t`는
컨테이너에서 읽을 수 없어 `failed to create the graph: Permission denied`가
발생한다. 사용자 worker의 함수 소스 bind도 기본 `user_home_t`에서는 읽을
수 없다. CLI 업그레이드나 SELinux 전체 비활성화 대신 전용 임시 디렉터리와
`supabase/functions` 하위만 `container_file_t`로 제한한다.

새 셸이 기본 Docker 소켓(`/var/run/docker.sock`)을 선택하면 먼저 rootless Podman
사용자 소켓을 명시한다.

```bash
export DOCKER_HOST=unix:///run/user/1000/podman/podman.sock
mkdir -p /tmp/mdlogger-supabase-cli
chcon -t container_file_t /tmp/mdlogger-supabase-cli
chcon -R -t container_file_t supabase/functions
TMPDIR=/tmp/mdlogger-supabase-cli supabase functions serve guest-ingest
```

`/tmp`가 비워졌거나 재부팅한 뒤에는 앞의 `mkdir`/`chcon`을 다시 실행한다.
checkout이나 SELinux context 복원 후 함수 source가 다시 `user_home_t`가 되면
`supabase/functions`의 `chcon`도 다시 실행한다. 프로젝트 전체에 `chcon`을
적용하거나 `chmod 777`, SELinux 비활성화를 하지 않는다. 이 우회는 로컬 함수
실행에만 필요하며 migration/pgTAP이나 hosted 배포의 보안 정책을 바꾸지 않는다.

## hosted production 적용 경계

결정 11에 따라 초기에는 local 개발 환경과 hosted production 프로젝트 한
개를 사용한다. hosted 프로젝트 생성·지역 선택·환경 변수 설정은 소유자의
운영 작업이다.

1. 로컬에서 `supabase db reset`과 `supabase test db`가 통과한 commit만
   적용 대상으로 한다.
2. 소유자 장비에서만 `supabase link --project-ref <production-ref>` 후
   `supabase db push`로 migration을 적용하고,
   `supabase functions deploy guest-ingest account-delete`로 Edge Function을
   배포한다.
3. CI/개발 장비에 production 자격 증명을 두지 않는다.
4. hosted staging은 운영 규모와 위험이 커진 뒤 같은 절차로 추가한다.

## rollback / forward-fix 절차

이미 적용된 migration 파일은 수정하지 않는다.

- **원칙은 forward-fix다.** 문제가 있는 스키마는 새 번호의 migration
  (`0007_...` 이후)으로 수정한다. 파괴적 수정(컬럼 삭제·의미 변경)은 새
  컬럼 추가 → 데이터 이관 → 구 컬럼 정리의 다단계 migration으로 나눈다.
- **적용 전 실패:** 로컬 검증에서 실패한 migration은 파일을 수정한 뒤
  `supabase db reset`으로 처음부터 재검증한다(아직 어디에도 적용되지 않은
  파일만 수정 가능).
- **production 적용 직후 결함:** 데이터 유실이 없는 결함은 forward-fix
  migration으로 되돌리는 SQL을 작성해 같은 절차로 적용한다. 이미 사용된
  `environment_version`/`play_context` 의미는 수정하지 않고 새 version을
  만든다(로드맵 7.6).
- **데이터 파괴 사고:** Supabase 프로젝트의 PITR/백업 복원을 사용한다.
  복원 후에는 클라이언트 `last_pulled_version`이 서버보다 앞설 수 있으므로
  full reconciliation(로드맵 17.3 C)을 강제해야 한다.
- 모든 rollback/forward-fix는 적용 전에 tests/database/ 공격 테스트를
  다시 통과해야 한다.

### 부분 적용·재개 (하드닝 H-7)

- 마이그레이션은 새 migration 파일 기준으로 한 번에 적용한다. 하나의
  migration 안에서 실패(예: `0009`의 unique index 생성 실패)하면 중단 지점에
  부분 적용 상태가 남는다.
- **안전한 재개**: 아직 어디에도 적용되지 않은 로컬 검증 실패는 파일을 수정한
  뒤 `supabase db reset`으로 처음부터 재검증한다. hosted에 부분 적용됐다면
  실패한 migration의 앞부분을 재실행 가능한 형태로 forward-fix로 보완하는
  대신, 문제가 되는 구간을 새 migration으로 수정해 처음부터 표준 절차로
  적용한다. 일반적으로 `supabase db reset`(개발) 또는 역방향 SQL(운영, 데이터
  유실 없는 경우)을 사용한다.
- `0005`의 `contributor_salt` 1회성 insert는 `id=true` 싱글톤 제약으로 두 번
  실행 시 안전하게 실패한다(중복 삽입이 아닌 중단 지점 검출 수단). 재개는 위
  절차를 따른다. 이런 1회성 데이터 부작용은 forward-fix로 만들지 않고 새 행 추가
  시에는 unattached insert가 아니라 guarded insert를 사용한다.

## 이 sandbox에서의 한계

Docker 기반 local Supabase는 에이전트 sandbox에서 실행할 수 없으므로,
pgTAP 테스트와 Edge Function은 소유자 환경에서 위 절차로 실행해 검증한다.
