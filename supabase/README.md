# MDLogger Supabase

데스크톱과 웹이 공유하는 SQL 스키마·RLS·RPC 및 Edge Function 소스다.
아래는 **저장소 계약**이며 현재 hosted 배포 상태를 보증하지 않는다.

## 구성

`migrations/`에는 `0001`부터 `0031`까지 **31개 SQL 파일**이 있다.

| 범위 | 주요 역할 |
| --- | --- |
| `0001`~`0021` | 개인 기록·프로필·장치, RLS, change-version 동기화·CAS, 분석 projection, 계정 운영, 환경·릴리스 정책, 권한 보완 |
| `0022`~`0024` | 게임 모드와 전후 상태, 등록·게스트 payload v2 |
| `0025`~`0027` | 취향 설정, 점수 입력 방식, 덱 카탈로그 캐시 |
| `0028`~`0029` | 릴리스 정책 값 변경. `0029`는 hosted 적용 보류 경계가 있으므로 아래 주의사항 필수 |
| `0030` | `game_create_receipts`, 생성 요청 멱등성 및 기존 쓰기 계약 호환 wrapper |
| `0031` | 개인 기록 상태·통계·목록 읽기 모델 |

Edge Function은 **4개**이며 [`config.toml`](config.toml)에 모두 JWT 검증을 명시한다.

| 함수 | 역할 |
| --- | --- |
| `guest-ingest` | 로그인 없는 게스트의 분석 필드 allowlist 업로드, rate limit, upsert/withdraw |
| `account-delete` | 요청자 인증 후 Auth 삭제, 개인 데이터 FK cascade와 보완 정리 |
| `revoke-sessions` | 요청자 전체 refresh 세션 폐기와 장치 행 정리 |
| `deck-catalog` | 로그인 사용자용 Gist 프록시, 5분 캐시 재검증, 원본 장애 시 마지막 정상 목록 |

`tests/database/`에는 pgTAP 파일 **15개**(`01`~`14`, `17`)가 있다.
파일 수는 테스트 실행 또는 hosted 검증 완료를 뜻하지 않는다.

## 현재 계약

- 등록 쓰기는 `apply_game_changes(sync_schema_version=1, payload_version=2, changes)`를 사용한다. 수정은 `expected_change_version` CAS, 삭제는 tombstone이다. `played_at`은 로컬 naive ISO 문자열을 유지하고 UTC offset은 별도 필드다.
- `0030`의 생성 전용 `request_id`는 동일 요청의 성공 영수증을 재생한다. 같은 ID로 payload를 바꾸면 거절하며 이후 수정·삭제된 행을 되살리지 않는다. `request_id` 없는 기존 요청 형식도 유지한다.
- `0031`의 `get_record_state`, `get_game_statistics`, `list_game_history`는 본인 데이터만 RLS 아래 읽는다. 목록은 `(played_at, id)` 커서와 snapshot 변경 감지를 사용한다. 전체 사용자 메타 통계 API가 아니다.
- 취향 설정은 `user_settings`/`upsert_user_settings`로 수동 동기화한다. 장치 전용 설정은 업로드 대상이 아니다.
- 개인 기록과 분석용 `analytics.duel_observations`는 별도다. 분석 행에는 메모·이메일·직접 Auth user ID 대신 제한된 필드와 가명 키를 보관한다. 등록 기록 수정은 projection을 갱신하고 tombstone 및 게스트 withdraw는 철회 처리한다. 철회 마커는 upsert로 해제하지 않는다.
- 계정 삭제는 개인 데이터와 생성 영수증을 제거하지만 분석 관측을 일괄 철회하지 않는다. `export_account_data`는 profile·games·devices 사본이며 설정·Auth 정보·분석·생성 영수증을 포함한 전체 백업이 아니다.
- 클라이언트에는 publishable(anon) key만 둔다. service-role/secret key는 서버 전용이며 `analytics`와 내부 영수증 테이블에 대한 클라이언트 직접 접근을 허용하지 않는다.

## 로컬 검증

Supabase CLI와 로컬 컨테이너 런타임이 필요하다. **폐기 가능한 로컬 개발 DB**만
대상으로 루트에서 실행한다. `db reset`은 로컬 데이터도 지운다.

```sh
supabase start
supabase db reset --local
supabase test db --local
supabase functions serve
```

`--linked`나 원격 `--db-url`을 로컬 검사에 추가하지 않는다. 함수 환경 파일도
로컬 URL·키만 사용한다. 함수 실행에는 외부 Gist 조회가 있을 수 있으므로
로컬 DB 사용과 완전한 네트워크 격리는 별개다. 테스트·기능 확인을 위해
hosted 사용자 데이터를 조회하거나 소스 앱을 운영 서버에 자동 연결하지 않는다.

## Hosted 변경

대상 프로젝트, 백업·복구 수단, 적용 SQL과 구버전 호환성을 소유자가 확인한 뒤
별도로 승인된 변경만 실행한다. 이미 연결된 대상이 맞는지 확인한 운영 환경에서
다음은 **적용하지 않는 사전 확인**이다.

```sh
supabase migration list --linked
supabase db push --linked --dry-run
```

**`0029_release_policy_v100.sql`의 의도적인 적용 공백을 자동으로 메우지 않는다.**
이 파일은 최소 지원 버전과 최신 버전을 `1.0.0`으로 바꾼다. 이후 `0030`·`0031`이
적용되어 있어도 누락 이력을 오류로 단정할 수 없다. 로컬 reset은 31개를 모두
적용하므로 hosted 이력과 다를 수 있다. 실제 이력·정책을 먼저 확인하고,
전체 `db push`, `--include-all`, 이력 repair로 우회하지 않는다.

함수 배포도 별도 변경이다. 승인된 함수와 확인한 프로젝트만
`supabase functions deploy <function-name> --project-ref <verified-project-ref>`로
지정한다. 이미 적용된 SQL은 수정하지 않고 새 migration으로 forward-fix한다.
DB 복원과 릴리스 정책 상향은 일반 기능 배포에 묶지 않는다.
[릴리스 문서](../docs/release.md)를 운영 기준으로 사용한다.
