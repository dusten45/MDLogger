# PWA/TWA 준비 상태

현재 `web/`은 **PWA (Progressive Web App) 도입이 완료된 반응형 웹앱**이다.

## PWA 구현 완료 상태 (4단계 완료)

- **Web App Manifest (`manifest.webmanifest`)**: `vite-plugin-pwa`를 통해 자동 생성 및 주입
- **아이콘 자산**: 192×192, 512×512 표준 아이콘, Android Adaptive Icon 규격 192×192 / 512×512 Maskable 아이콘, 180×180 Apple Touch Icon 구비
- **Service Worker & App Shell Precache**: 정적 자산 프리캐시 + Supabase API Network-Only 정책 (온라인 전용 데이터 원칙 준수)
- **오프라인 안내 UI (`OfflineBanner`)**: 네트워크 단절 시 앱 셸 렌더링 및 비간섭형 오프라인 안내 배너 노출
- **무중단 업데이트 알림 (`ReloadPrompt`)**: 새 버전 감지 시 토스트 안내 및 사용자 승인 시 새로고침 활성화
- **PWA 설치 지원 (`useInstallPrompt`, `SettingsPage`)**: 데스크톱/Android Chrome 설치 프롬프트 캡처 및 설치 버튼, Standalone 감지 배지, iOS Safari 홈 화면 추가 안내
- **Standalone 모드 스타일링**: 텍스트 선택 방지, safe-area-inset 및 터치 하이라이트 최적화

## 후속 TWA 작업

TWA는 안정된 PWA와 장기 소유 HTTPS 도메인이 확정된 뒤에만 진행한다. 도메인 소유권
연결(디지털 에셋 링크), Android package name, release signing, Play 정책 및 인증 callback 예외를
별도 릴리스 기준으로 검증한다.
