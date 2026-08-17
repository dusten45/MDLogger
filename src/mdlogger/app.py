"""앱 진입점: QApplication 구성, DB 초기화, 메인 창 표시."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import sync as deck_sync
from .app_controller import AppController
from .app_settings import SettingsRepository, effective_reduce_motion
from .auth.credential_store import KeyringCredentialStore
from .auth.session_manager import SessionManager
from .auth.supabase_auth import SupabaseAccountService
from .decks import load_decks
from .environment import refresh_from_server
from .game_service import GameService
from .game_sync.coordinator import SyncCoordinator
from .game_sync.engine import SyncEngine
from .game_sync.modes import GameModesClient
from .paths import DATA_DIR
from .profile_router import ProfileRouter
from .profiles import ProfileManager
from .release_policy import resolve_policy_for_startup
from .remote.config import get_remote_config
from .remote.games import RegisteredGamesClient
from .remote.guest_ingest import GuestIngestClient
from .remote.settings_sync import SettingsSyncClient
from .ui.icons import application_icon
from .ui.main_window import MainWindow
from .ui.result_view import set_result_motion_enabled
from .ui.theme import apply_theme


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("MDLogger")
    _app_icon = application_icon()
    if _app_icon is not None:
        app.setWindowIcon(_app_icon)  # 모든 창의 타이틀바·태스크바 아이콘

    # 설정을 창 생성 전에 로드해 테마·강조색·글자 크기를 먼저 적용한다(spec §6.4).
    settings_repo = SettingsRepository()
    settings = settings_repo.load()
    _theme_controller = apply_theme(
        app,
        mode=settings.theme_mode,
        accent=settings.accent_color,
        font_scale=settings.font_scale,
    )
    # 저사양 모드/애니메이션 감소에 따라 승/패 버튼 애니메이션을 시작부터 적용한다.
    set_result_motion_enabled(not effective_reduce_motion(settings))

    deck_sync.start_background_sync()  # 비차단; 다음 상세 진입에서 자동 반영
    decks = load_decks()
    profiles = ProfileManager()
    remote_config = get_remote_config()

    # 릴리스 정책: 최소 지원 미만이면 온라인(로그인·업로드·pull)을 차단한다.
    # 로컬 기록과 내보내기는 영향받지 않는다(로드맵 17.3.J). 조회 실패는
    # 마지막 캐시를 사용하고, 정책이 없으면 최신 동작을 보존한다.
    # 어떤 예외도 앱 시작을 막지 않는다(모듈 약속, P1-12).
    try:
        _release_policy, _online_allowed = resolve_policy_for_startup(
            remote_config, DATA_DIR / "release_policy_cache.json"
        )
    except Exception:  # noqa: BLE001
        _release_policy, _online_allowed = None, True
    if not _online_allowed:
        remote_config = None

    # 현재 환경 version을 조회·캐시해 신규 기록에만 부여한다(하드닝 H4).
    # 오프라인이거나 조회 실패시 NULL로 두고 소급 부여하지 않는다.
    refresh_from_server(remote_config)

    sessions = (
        SessionManager(SupabaseAccountService(remote_config), KeyringCredentialStore())
        if remote_config is not None
        else None
    )

    settings_sync_client = (
        SettingsSyncClient(remote_config) if remote_config is not None else None
    )

    def sync_factory(profile):
        registered_client = (
            RegisteredGamesClient(remote_config) if remote_config is not None else None
        )
        guest_client = (
            GuestIngestClient(remote_config, profile.installation_id)
            if remote_config is not None
            else None
        )

        def access_token() -> str | None:
            session = sessions.session if sessions is not None else None
            if session is None or session.account.user_id != profile.remote_user_id:
                return None
            return session.tokens.access_token

        def refresh_token() -> str | None:
            if sessions is None or profile.remote_user_id is None:
                return None
            session = sessions.refresh_for_sync(profile.remote_user_id)
            return session.tokens.access_token if session is not None else None

        engine = SyncEngine(
            profile,
            registered_client=registered_client,
            guest_client=guest_client,
            modes_client=(
                GameModesClient(remote_config) if remote_config is not None else None
            ),
            token_provider=access_token,
            token_refresher=refresh_token,
        )
        return SyncCoordinator(engine)

    def _build_window(games: GameService, profile) -> MainWindow:
        window = MainWindow(games, decks, profile, theme=_theme_controller)
        # 메모 설정은 설정 창에서 바뀔 수 있으므로 최신값을 다시 읽는다.
        window.set_memo_enabled(settings_repo.load().memo_enabled)
        return window

    controller = AppController(
        profiles,
        service_factory=lambda profile: GameService.open(profile.database_path),
        window_factory=_build_window,
        sync_factory=sync_factory,
    )
    router = ProfileRouter(
        profiles,
        controller,
        sessions,
        settings_store=settings_repo,
        settings_sync_client=settings_sync_client,
    )
    try:
        router.start()
        exit_code = app.exec()
    finally:
        router.close()
        controller.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
