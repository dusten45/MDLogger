# MDLogger 운영 Runbook(단계 11)

이 문서는 로드맵 13장 단계 11의 완료 조건 중 "운영 runbook과 장애 대응 절차
작성", "key/token 유출 대응 절차 작성" 을 충족한다. 게스트 ingest 진단 정리,
계정 삭제, 장치 해제, 백업/복구, key rotation, 유출 대응을 다룬다.

## 1. 환경 구성: local / production

| 항목                  | local 개발                         | production                          |
| --------------------- | ---------------------------------- | ----------------------------------- |
| Supabase CLI          | 2.109.1 고정                       | 소유자 장비만 사용                  |
| 데이터베이스          | `supabase start` (Docker)          | hosted project (지역은 결정 17.3 G) |
| publishable(anon) key | `.env`/환경 변수                   | hosted 프로젝트의 anon key          |
| service-role key      | Edge Function 서버 환경 변수만     | hosted 프로젝트의 service-role key  |
| 테스트                | `supabase test db`                 | staging에서 동일 절차               |

클라이언트 앱은 `MDLOGGER_SUPABASE_URL`과 `MDLOGGER_SUPABASE_ANON_KEY` 두
환경 변수만 읽는다(`remote/config.py`). service-role/secret key는
`remote/config.py` 어디에도 들어가지 않는다.

## 2. 확인 절차 (로컬 검증)

```bash
supabase start
supabase db reset          # migrations/ 전체 적용
supabase test db           # tests/database/ pgTAP 공격 테스트
supabase functions serve guest-ingest account-delete
```

모든 migration/함수 변경은 hosted 적용 전에 이 절차를 통과해야 한다. 이
sandbox는 Docker 기반 Supabase를 실행할 수 없으므로 소유자 환경에서 수행한다.

## 3. 계정 데이터 내보내기 (사용자 요청 대응)

사용자가 개인 데이터 사본을 요청하면 클라이언트의 "내 데이터 내보내기"가
`export_account_data` RPC를 호출해 profile·games·devices를 JSON으로 저장한다.

- 분석용 `duel_observations`는 내보내기에 포함되지 않는다(로드맵 12.4).
- 게스트 계정은 auth 프로필이 없으므로 내보내기 대상이 아니다. 게스트는
  휴대용 아카이브(단계 10)를 사용한다.

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
  모든 `devices` 행을 삭제한다. 이 장치의 로컬 세션은 유지되나, 다음 시작 시
  저장된 refresh token이 서버에서 폐기됐으므로 재로그인이 필요하다.
- "특정 장치 해제": `revoke_device(installation_id)` RPC. 해당 장치만
  해제한다.

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

## 7. 보존 정책

- 개인용 `games.deleted_at` **tombstone**: 무기한 보존. 모든 장치가 삭제
  version을 확인할 때까지 보존한다(로드맵 9.3).
- 분석용 `duel_observations.withdrawn_at` **마커**: 무기한 보존. 기본 분석
  dataset에서 제외된 상태를 영구히 기록한다.
- guest ingest **진단** 메타데이터(ingestion_batches, rejected_observations):
  90일 후 정리 대상. 분석 observation과 분리되어 있다.

## 8. 백업과 복구

- Supabase PITR/연속 백업을 활성화한다(hosted). 로컬은 SQL 덤프로 산출물을
  보관한다.
- **복구 rehearsal**: 백업에서 복원한 뒤 다음을 확인한다.
  1. RLS 정책이 복원되는가(`\dp`로 acl 확인).
  2. 서버 함수와 트리거가 유지되는가(`\df`, `\dft`).
  3. `auth.users`/`auth.schema_migrations`가 함께 복원되는가.
  4. 클라이언트 `last_pulled_version`이 복원된 서버보다 앞서면 full
     reconciliation을 강제한다(결정 17.3 C).
- 복원은 데이터 파괴 사고 시에만 사용한다. 일반 결함은 forward-fix
  migration으로 대응한다(README rollback 절 참고).

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

이메일 템플릿(가입 확인, 비밀번호 재설정)과 auth rate limit은 Supabase
Dashboard의 Auth 설정에서 소유자가 구성한다(로드맵 단계 11). guest ingest
rate limit·이상 탐지·Turnstile은 `guest-ingest`의 `checkAbuseGuards` 확장
경계에 추가한다(로드맵 12.3).
