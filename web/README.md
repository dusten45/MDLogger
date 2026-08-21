# MDLogger Web (3단계)

로그인 필수 온라인 반응형 웹앱 (React + TypeScript + Vite SPA).

기준 문서: `docs/phase3-web-implementation-spec.md`.

## 요구 사항

- Node.js 20+ (개발 환경: v22)
- Supabase hosted project (URL + publishable anon key)

## 설정

`.env.example`을 참고해 `.env.development`/`.env.preview`/`.env.production`에
Supabase URL과 publishable(anon) key를 넣는다. 배포 시에는 `VITE_BUILD_ID`에 git
commit을 주입한다. service-role key는 절대 넣지 않는다.

## 명령

```sh
npm install        # 의존성 설치
npm run generate:icons # PWA 표준 및 Maskable 아이콘 생성
npm run dev        # 로컬 개발 서버
npm run build      # 타입 검사 + 정적 자산 및 PWA Service Worker 빌드
npm run lint       # ESLint
npm test              # Vitest·Node secret 검사 단위 테스트
npm run check:deploy-env # 배포용 Supabase 환경 변수를 검사
npm run check:secrets    # dist에 server secret이 없는지 검사
npm run preview          # 빌드 결과 미리보기
npm run deploy        # 빌드·secret 검사 후 Cloudflare Workers 배포
```

## 구조

- `src/theme/` — 디자인 토큰(CSS 변수)·강조색 프리셋·테마 적용 (데스크톱 `ui/theme.py`와 동일 의미)
- `src/settings/` — 웹 설정 모델·검증·저장소 (데스크톱 `app_settings.py`와 동일 키)
- `src/lib/` — 환경 변수·Supabase 클라이언트·네트워크/PWA 설치 훅
- `src/routes/` — 화면(기록/통계/기록 목록/설정/로그인)
- `src/components/` — 공용 컴포넌트(내비게이션 셸·오프라인 안내 배너·업데이트 알림)
- `public/` — Cloudflare 보안/캐시 헤더와 PWA 다목적 아이콘 자산
- `scripts/` — 아이콘 생성 및 배포 산출물 secret 검사

## 구현 단계

- [x] 3-A 프로젝트 기반 (Vite+React+TS, 환경 분리, 라우팅, 디자인 토큰)
- [x] 3-B 인증·계정 (로그인/회원가입/인증/재설정/로그아웃/계정 운영)
- [x] 3-C 서버 데이터 계약 + `deck-catalog` + 덱 캐시 마이그레이션
- [x] 3-D 핵심 기록 흐름
- [x] 3-E 기록 목록·통계·설정(+수동 동기화)
- [x] 3-F 반응형·접근성 검증
- [x] 3-G 보안·운영·배포
- [x] 4단계 PWA 도입 (Web App Manifest, Service Worker App Shell Precache, 오프라인 안내, 업데이트 알림, 설치 UX)

## 보안·운영·PWA

- CSP 및 `sw.js`/`manifest.webmanifest` no-cache 헤더는 `public/_headers`에서 관리한다.
- `npm run check:secrets`는 service-role key·service-role JWT·URL 임베드 자격 증명을
  배포 산출물에서 차단한다. publishable(anon) key는 허용한다.
- 배포·롤백·Supabase Auth URL allowlist·개인정보 공개 전 조건은
  `docs/operations/web-deployment-runbook.md`를 따른다.
- PWA는 온라인 전용 데이터 정책을 유지하며, 정적 앱 셸만 캐시하고 Supabase API는 Network-Only로 동작한다.
  상세 내용은 `PWA_READINESS.md` 및 `docs/phase4-pwa-implementation-plan.md`를 참조한다.
