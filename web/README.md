# MDLogger Web (3단계)

로그인 필수 온라인 반응형 웹앱 (React + TypeScript + Vite SPA).

기준 문서: `docs/phase3-web-implementation-spec.md`.

## 요구 사항

- Node.js 20+ (개발 환경: v22)
- Supabase hosted project (URL + publishable anon key)

## 설정

`.env.example`을 참고해 `.env.development`/`.env.preview`/`.env.production`에
Supabase URL과 publishable(anon) key를 넣는다. service-role key는 절대 넣지 않는다.

## 명령

```sh
npm install        # 의존성 설치
npm run dev        # 로컬 개발 서버
npm run build      # 타입 검사 + 정적 자산 빌드
npm run lint       # ESLint
npm test           # Vitest 단위 테스트
npm run preview    # 빌드 결과 미리보기
```

## 구조

- `src/theme/` — 디자인 토큰(CSS 변수)·강조색 프리셋·테마 적용 (데스크톱 `ui/theme.py`와 동일 의미)
- `src/settings/` — 웹 설정 모델·검증·저장소 (데스크톱 `app_settings.py`와 동일 키)
- `src/lib/` — 환경 변수·Supabase 클라이언트
- `src/routes/` — 화면(기록/통계/기록 목록/설정/로그인)
- `src/components/` — 공용 컴포넌트(내비게이션 셸)

## 구현 단계

- [x] 3-A 프로젝트 기반 (Vite+React+TS, 환경 분리, 라우팅, 디자인 토큰)
- [x] 3-B 인증·계정 (로그인/회원가입/인증/재설정/로그아웃/계정 운영)
- [x] 3-C 서버 데이터 계약 + `deck-catalog` + 덱 캐시 마이그레이션
- [ ] 3-D 핵심 기록 흐름
- [ ] 3-E 기록 목록·통계·설정(+수동 동기화)
- [ ] 3-F 반응형·접근성 검증
- [ ] 3-G 보안·운영·배포
- [ ] 3-H PWA/TWA 후속 준비 + 전체 회귀
