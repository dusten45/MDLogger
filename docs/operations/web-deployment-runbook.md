# MDLogger 웹 운영·배포 runbook

이 문서는 `web/` React SPA를 Cloudflare Workers Static Assets에 배포하고, 장애 시
안전하게 이전 버전으로 되돌리는 운영 절차다. 웹은 로그인 필수 온라인 서비스이며
데이터 권한은 Supabase Auth와 PostgreSQL RLS가 최종적으로 강제한다.

> 웹의 공식 도메인은 아직 확정되지 않았다. 도메인이 정해지기 전에는 Cloudflare가
> 제공하는 Worker 서브도메인으로 preview만 운영한다.

## 1. 배포 전 1회 설정

### 1.1 Cloudflare

1. Cloudflare에서 Workers 배포 권한만 가진 API token을 만든다.
2. GitHub 저장소의 `preview`, `production` Environment를 만든다.
3. 각 Environment에 다음 값을 등록한다.

| 이름 | GitHub 저장 위치 | 설명 |
| --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | Secret | Workers 배포 권한 API token |
| `CLOUDFLARE_ACCOUNT_ID` | Variable | Cloudflare account ID |
| `VITE_SUPABASE_URL` | Variable | Hosted Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Variable | Supabase publishable(anon) key |

`VITE_SUPABASE_ANON_KEY`는 브라우저에 공개되는 키지만, 값을 일관되게 환경별로
관리하기 위해 GitHub Environment variable에 둔다. **`SUPABASE_SERVICE_ROLE_KEY`,
`sb_secret_` 값, 데이터베이스 비밀번호는 어떤 GitHub 변수·웹 환경 파일·번들에도
넣지 않는다.**

### 1.2 Supabase Auth URL Configuration

Supabase 대시보드 **Authentication → URL Configuration**에 배포 도메인별 URL을
등록한다.

| 항목 | 값 |
| --- | --- |
| Site URL | 운영 웹앱 루트 URL (예: `https://app.example.com`) |
| Redirect URLs | `<origin>/auth/callback`, `<origin>/login`을 포함하는 와일드카드 (예: `https://app.example.com/**`) |

개발 환경도 다음처럼 허용 목록에 별도로 둔다.

```text
http://localhost:5173/**
```

등록하지 않으면 이메일 인증과 비밀번호 재설정 링크가 `redirect URL not allowed`로
실패한다. 허용할 필요가 없는 외부 도메인 또는 와일드카드를 등록하지 않는다.

### 1.3 Supabase와 브라우저 보안 확인

- Auth의 이메일 인증을 활성화하고, 로그인·회원가입·재설정·callback을 각 Environment에서 확인한다.
- `deck-catalog`, `account-delete`, `revoke-sessions` Edge Function의 JWT 검증을 유지한다.
- 브라우저 번들에는 publishable(anon) key만 포함한다. 실제 데이터 읽기·쓰기 권한은 RLS로 검증한다.
- 정적 자산의 CSP 등 보안 헤더는 `web/public/_headers`에서 관리한다. Cloudflare 대시보드에서
  별도의 header transform rule을 추가하면 이 파일의 정책과 충돌하지 않는지 확인한다.

## 2. 배포 절차

1. `main`에서 CI의 Python·웹 검사 전체가 통과한 commit을 선택한다.
2. GitHub Actions의 **Deploy web** workflow를 수동 실행한다.
3. 먼저 `target=preview`와 preview Worker 이름으로 배포한다.
4. preview URL에서 다음을 확인한다.
   - 새로고침해도 `/`, `/stats`, `/history`, `/settings`, `/auth/callback` 라우팅이 유지된다.
   - 로그인·회원가입 이메일 인증·비밀번호 재설정·로그아웃이 동작한다.
   - 기록 생성·수정·삭제와 설정 동기화가 올바른 본인 계정 데이터에만 적용된다.
   - `curl -I <preview-url>` 응답에 CSP, `X-Content-Type-Options`, `Referrer-Policy`,
     `Permissions-Policy`, `Cross-Origin-Opener-Policy`, HSTS가 포함된다.
   - 설정 화면의 `웹 버전`이 배포한 commit SHA와 일치한다.
5. 확인 후 `target=production`으로 같은 commit을 배포한다. production은 `main`에서만 실행된다.
6. 공식 도메인을 연결한 뒤 Supabase Auth의 Site URL과 Redirect URLs에 해당 도메인을 추가하고
   이메일 링크까지 다시 확인한다.

workflow는 Vite 빌드·ESLint·Vitest·정적 보안 헤더 포함 여부·번들의 server secret 검사를
모두 통과해야 Cloudflare에 배포한다. `VITE_BUILD_ID`에는 workflow의 commit SHA가 자동
주입되며, 경기 쓰기의 `client_version`과 설정 화면의 웹 버전에 사용된다.

로컬에서 배포 전 같은 검사를 수행하려면 다음을 사용한다.

```sh
cd web
VITE_SUPABASE_URL=https://<project-ref>.supabase.co \
VITE_SUPABASE_ANON_KEY=sb_publishable_... \
VITE_BUILD_ID=<git-commit> \
npm run build
npm run lint
npm test
npm run check:secrets
```

Cloudflare 자격 증명과 환경 변수를 설정한 로컬 운영 환경에서만 다음 명령을 실행한다.

```sh
npm run deploy
```

## 3. 롤백

웹은 정적 SPA이고 데이터 마이그레이션을 수행하지 않는다. 따라서 Cloudflare Worker의
이전 버전을 다시 배포하는 방식으로 롤백한다.

1. Cloudflare 대시보드 **Workers & Pages → mdlogger-web → Deployments**에서 직전 정상
   버전을 확인한다.
2. 대시보드에서 해당 버전의 **Rollback**을 실행하거나, 인증된 운영 환경에서 다음을 실행한다.

```sh
cd web
npx wrangler rollback --name mdlogger-web --message "rollback to last known good web build"
```

특정 버전으로 되돌려야 하면 Dashboard에서 version ID를 확인한 뒤 `wrangler rollback`에
그 ID를 지정한다. 롤백은 즉시 새 배포를 만들어 모든 트래픽에 적용하므로, 실행 직후
로그인·기록 생성·보호 URL 새로고침을 확인한다.

롤백 대상이 Supabase 스키마와 호환되는지도 확인한다. 웹은 현재 기존 RPC와 테이블을
재사용하므로 웹만 롤백해도 되지만, 향후 서버 계약을 변경하면 **서버 마이그레이션을
삭제하거나 되돌리지 않는 전방 호환 배포**를 원칙으로 한다.

## 4. 장애 대응

| 증상 | 즉시 조치 |
| --- | --- |
| Cloudflare 정적 자산 장애 | Cloudflare 상태 페이지 확인 후, 필요하면 마지막 정상 Worker 버전으로 롤백한다. |
| Supabase Auth 장애 | 로그인/보호 화면의 재시도 안내를 확인하고 Supabase 상태 페이지를 확인한다. 세션·경기 데이터를 브라우저 로컬 DB에 저장해 우회하지 않는다. |
| PostgREST/RPC/Edge Function 장애 | 앱의 오류 메시지로 저장 성공처럼 보이지 않는지 확인하고, 요청을 재시도한다. 장기 장애면 사용자에게 서버 장애 사실을 공지한다. |
| `deck-catalog` 원본 Gist 장애 | 정상 서버 캐시가 있으면 stale 목록을 계속 제공한다. 캐시도 없으면 503으로 재시도를 안내한다. |
| secret 검사 실패 | 배포를 중단한다. `dist/`에서 지적한 값을 제거하고, 유출 가능성이 있으면 해당 키를 즉시 폐기·재발급한다. |

오류 추적 도구는 아직 도입하지 않았다. 도입하기 전에는 수집 항목, 사용자 식별자 처리,
보존 기간, 국외 이전을 포함한 개인정보 검토를 완료해야 한다.

## 5. 개인정보와 계정 삭제 안내

정식 공개 전 서비스의 개인정보 처리방침 URL을 footer 또는 설정 화면의 계정 삭제
동선에서 제공한다. 최소한 다음을 명시한다.

- 수집·저장하는 계정 정보와 경기 기록의 항목 및 목적
- Supabase·Cloudflare·GitHub Gist를 포함한 처리 업체와 보존 정책
- `계정 데이터 내보내기`, `모든 기기 로그아웃`, `계정 삭제`의 동작과 계정 삭제의 비가역성
- 문의 및 삭제 요청 처리 방법

현재 계정 삭제는 설정 화면에서 명시적 확인 후 기존 `account-delete` Edge Function으로
수행한다. 처리방침 URL이 확정되기 전에는 공식 공개 배포를 진행하지 않는다.
