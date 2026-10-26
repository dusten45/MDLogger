# MDLogger Web

React + TypeScript + Vite 기반의 로그인 필수 웹앱이다. 기록 입력·수정·삭제,
개인 통계·기록 목록, 계정 관리와 취향 설정 동기화를 제공한다.
서버 계약은 [Supabase README](../supabase/README.md), 배포 기준은
[릴리스 문서](../docs/release.md)를 따른다.

## 개발

Node.js는 루트 [`.nvmrc`](../.nvmrc)의 버전을 사용한다. 아래 명령은 `web/`에서 실행한다.

```sh
npm ci --no-audit
npm run dev
```

`.env.example`을 참고해 로컬 전용 `.env.development`에
`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`를 설정한다. 로컬 Supabase 또는
명시적으로 허가된 테스트 프로젝트를 사용한다. 프런트엔드가 localhost에서
실행되어도 지정한 서버에는 실제 요청이 전달된다.

배포 환경은 같은 두 변수와 `VITE_BUILD_ID`에 대상 commit SHA를 제공한다.
publishable(anon) key만 브라우저에 포함할 수 있으며 service-role/secret key와
DB 비밀번호는 환경 파일·번들에 넣지 않는다.

| 명령 | 용도 |
| --- | --- |
| `npm run lint` | ESLint |
| `npm test` | Vitest 및 Node 검사 |
| `npm run build` | 타입 검사, 정적 자산·Service Worker 빌드 |
| `npm run preview` | 빌드 결과 로컬 미리보기 |
| `npm run generate:icons` | 원본 아이콘에서 PWA 파생 자산 생성 |
| `npm run generate:licenses` | 제3자 고지 재생성 |

## 배포 전 검사

배포 환경 변수를 설정하고 lint·테스트를 통과시킨 뒤, 게시 없이 산출물을 검사한다.

```sh
npm audit
npm run check:deploy-env
npm run check:licenses
npm run check:license-artifacts
npm run build
npm run check:license-bundle
npm run strip:source-maps
npm run check:secrets
```

`npm run deploy`는 위 검사 후 **실제 Cloudflare 배포**까지 수행한다.
이 명령 자체에는 lint와 테스트가 없으므로 별도로 통과시켜야 한다.
수동 [Deploy web workflow](../.github/workflows/web-deploy.yml)는 이 검사들을
포함하며 `preview`/`production`을 구분하고 production을 `main`으로 제한한다.
일반 `build`는 라이선스 검증용 source map을 남기므로 `dist/`를 그대로 게시하지 않는다.

## PWA 경계

- Manifest, 표준·maskable 아이콘, 정적 앱 셸 precache, 설치 안내와 업데이트 알림을 구현했다.
- 정적 앱 셸만 오프라인에서 사용할 수 있다. 경기 조회·저장·통계는 온라인 전용이며 Supabase 요청을 Service Worker에 캐시하지 않는다.
- IndexedDB 경기 저장소나 영속적인 오프라인 outbox는 없다. 미확인 생성 요청의 재시도 상태는 로그인 범위의 메모리에만 유지되며 새로고침·탭 종료 뒤 복구를 보장하지 않는다.
- 새 버전은 알림 후 사용자가 새로고침한다. `/sw.js`와 `/manifest.webmanifest`의 `no-cache` 및 CSP는 [`public/_headers`](public/_headers)에서 관리한다.
- Android TWA는 미구현 제안이다. 도입 여부는 장기 소유 HTTPS 도메인, Digital Asset Links, 패키지명·서명, 인증 callback과 Play 정책을 별도로 검토해 결정한다.

## 코드 위치

- `src/auth/`, `src/games/`: 인증, 서버 RPC와 경기 계약
- `src/routes/`, `src/components/`: 화면과 공용 UI
- `src/settings/`, `src/theme/`: 로컬 취향 설정, 수동 동기화, 테마
- `src/lib/`, `vite.config.ts`, `public/`: 환경 설정, PWA, 정적 자산·헤더
- `scripts/`: 아이콘·라이선스 생성, 배포 환경·산출물 검사
