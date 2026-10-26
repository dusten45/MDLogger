"""앱 진입점: QApplication 구성, DB 초기화, 메인 창 표시."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from . import sync as deck_sync
from ._version import __version__
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
from .profile_router import CONSENT_VERSION, ProfileRouter
from .profiles import ProfileManager
from .release_policy import resolve_policy_for_startup
from .remote.config import get_remote_config
from .remote.games import RegisteredGamesClient
from .remote.guest_ingest import GuestIngestClient
from .remote.settings_sync import SettingsSyncClient
from .ui.focus import install_pointer_focus_only
from .ui.icons import application_icon
from .ui.main_window import MainWindow
from .ui.result_view import set_result_motion_enabled
from .ui.theme import apply_theme
from .update_controller import UpdateController
from .updater import (
    acknowledge_update_startup,
    acquire_application_mutex,
    authorize_update,
    cancel_update,
    check_update,
    download_update,
    launch_update,
)


def main() -> None:
    app = QApplication(sys.argv)
    install_pointer_focus_only(app)
    app.setApplicationName("MDLogger")
    if not acquire_application_mutex():
        QMessageBox.information(
            None, "MDLogger 실행 중", "이미 실행 중이거나 업데이트가 진행 중입니다."
        )
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(DATA_DIR / "mdlogger.lock"))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(0):
        QMessageBox.information(
            None,
            "MDLogger 실행 중",
            "이 데이터 폴더를 사용하는 앱이 이미 실행 중입니다.",
        )
        return
    _app_icon = application_icon()
    if _app_icon is not None:
        app.setWindowIcon(_app_icon)  # 모든 창의 타이틀바·태스크바 아이콘

    # 설정을 창 생성 전에 로드해 테마·강조색·UI 크기를 먼저 적용한다(spec §6.4).
    settings_repo = SettingsRepository()
    settings = settings_repo.load()
    settings_warning = settings_repo.load_warning
    _theme_controller = apply_theme(
        app,
        mode=settings.theme_mode,
        accent=settings.accent_color,
        ui_scale=settings.ui_scale,
    )
    # 저사양 모드/애니메이션 감소에 따라 승/패 버튼 애니메이션을 시작부터 적용한다.
    set_result_motion_enabled(not effective_reduce_motion(settings))

    profiles = ProfileManager()
    deck_sync.start_background_sync()  # 복구 완료 후 비차단 덱 갱신을 시작한다.
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

    credential_store = KeyringCredentialStore()
    sessions = (
        SessionManager(SupabaseAccountService(remote_config), credential_store)
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

        engine = SyncEngine(
            profile,
            registered_client=registered_client,
            guest_client=guest_client,
            modes_client=(
                GameModesClient(remote_config) if remote_config is not None else None
            ),
            session_manager=sessions,
            can_sync=lambda: (
                _online_allowed
                and profiles.has_data_consent(CONSENT_VERSION)
                and controller.current_profile is not None
                and controller.current_profile.local_profile_id
                == profile.local_profile_id
            ),
        )
        return SyncCoordinator(engine)

    def _build_window(games: GameService, profile) -> MainWindow:
        window = MainWindow(games, load_decks(), profile, theme=_theme_controller)
        # 메모 설정은 설정 창에서 바뀔 수 있으므로 최신값을 다시 읽는다.
        window.set_memo_enabled(settings_repo.load().memo_enabled)
        window.set_score_input_mode(settings_repo.load().score_input_mode)
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
        credential_store=credential_store,
        settings_store=settings_repo,
        settings_sync_client=settings_sync_client,
    )

    def update_parent() -> QWidget:
        window = controller.current_window
        return window if isinstance(window, QWidget) else router.auth_window

    updates = UpdateController(
        __version__,
        parent_window=update_parent,
        ready_to_install=router.ready_for_update,
        begin_handoff=router.begin_update,
        handoff_is_current=router.update_is_current,
        end_handoff=router.end_update,
        pause=controller.pause_for_update,
        resume=controller.resume_after_update,
        data_dir=DATA_DIR,
        check=lambda: check_update(__version__),
        download=download_update,
        launch=launch_update,
        authorize=authorize_update,
        cancel=cancel_update,
        parent=app,
    )
    router.set_update_handler(lambda: updates.check_for_updates(manual=True))
    try:
        router.start()
        acknowledge_update_startup(__version__)
        if settings_warning:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(
                    QApplication.activeWindow(), "기본 설정으로 복구", settings_warning
                ),
            )
        QTimer.singleShot(1500, updates.check_for_updates)
        exit_code = app.exec()
    finally:
        updates.close()
        router.close()
        controller.close()
        instance_lock.unlock()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
