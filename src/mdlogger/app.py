"""앱 진입점: QApplication 구성, DB 초기화, 메인 창 표시."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import sync as deck_sync
from .app_controller import AppController
from .auth.credential_store import KeyringCredentialStore
from .auth.session_manager import SessionManager
from .auth.supabase_auth import SupabaseAccountService
from .decks import load_decks
from .game_service import GameService
from .game_sync.coordinator import SyncCoordinator
from .game_sync.engine import SyncEngine
from .profile_router import ProfileRouter
from .profiles import ProfileManager
from .remote.config import config_from_environment
from .remote.games import RegisteredGamesClient
from .remote.guest_ingest import GuestIngestClient
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("MD WCQ 로거")
    _theme_controller = apply_theme(app)

    deck_sync.start_background_sync()  # 비차단; 다음 상세 진입에서 자동 반영
    decks = load_decks()
    profiles = ProfileManager()
    remote_config = config_from_environment()
    sessions = (
        SessionManager(SupabaseAccountService(remote_config), KeyringCredentialStore())
        if remote_config is not None
        else None
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
            token_provider=access_token,
            token_refresher=refresh_token,
        )
        return SyncCoordinator(engine)

    controller = AppController(
        profiles,
        service_factory=lambda profile: GameService.open(profile.database_path),
        window_factory=lambda games, profile: MainWindow(games, decks, profile),
        sync_factory=sync_factory,
    )
    router = ProfileRouter(profiles, controller, sessions)
    try:
        router.start()
        exit_code = app.exec()
    finally:
        router.close()
        controller.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
