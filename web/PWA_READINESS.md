# PWA/TWA 후속 준비 상태

현재 `web/`은 **브라우저 URL로 사용하는 온라인 전용 SPA**다. PWA 설치 기능과 TWA APK는
의도적으로 구현하지 않았으며, service worker·web app manifest·offline cache가 없다.

## 이번 단계에서 준비한 기반

- Cloudflare Workers Static Assets의 HTTPS 배포 경로와 SPA fallback (`wrangler.jsonc`)
- 이메일 인증 callback을 포함한 새로고침 가능한 클라이언트 라우팅
- safe-area를 고려한 모바일 레이아웃과 예측 가능한 브라우저 뒤로가기
- 정사각형 아이콘 원본 `public/icon-source.png`
  - 원본: 저장소 루트 `icon/DuelistCup.png`
  - 현재 크기: 216×216 PNG
  - 브라우저 favicon으로 연결됨
- 배포 build ID/git commit의 표시와 경기 변경 `client_version` 전달

## 후속 PWA 작업

PWA 마일스톤에서 다음을 **별도 설계·검증**한다.

1. `manifest.webmanifest`를 추가하고, 앱 이름·short name·테마 색·display mode를 확정한다.
2. `icon-source.png`에서 목적별 192×192, 512×512, maskable 아이콘을 생성하고 Android Chrome에서
   설치 아이콘·splash를 확인한다.
3. 온라인 전용 정책에 맞는 service worker 정책을 결정한다. 경기 데이터·인증 응답은 캐시하지 않고,
   네트워크 불가 시에는 명확한 안내 화면만 제공하는 방안을 기본으로 검토한다.
4. 설치·업데이트·로그아웃·이메일 인증 callback·오래된 캐시와 Supabase 세션의 상호작용을 실제
   Android Chrome에서 E2E 검증한다.

## 후속 TWA 작업

TWA는 안정된 PWA와 장기 소유 HTTPS 도메인이 확정된 뒤에만 진행한다. 도메인 소유권
연결(디지털 에셋 링크), Android package name, release signing, Play 정책 및 인증 callback 예외를
별도 릴리스 기준으로 검증한다.
