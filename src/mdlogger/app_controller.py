"""현재 로컬 프로필의 서비스와 창 수명 주기를 조정한다."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .game_service import GameService
from .game_sync.models import SyncConflict
from .profiles import ProfileContext, ProfileManager


class ProfileWindow(Protocol):
    """계정 범위 창이 컨트롤러에 제공하는 최소 수명 주기 계약."""

    def show(self) -> None: ...

    def close_profile_windows(self) -> None: ...


ServiceFactory = Callable[[ProfileContext], GameService]
WindowFactory = Callable[[GameService, ProfileContext], ProfileWindow]


class SyncScope(Protocol):
    @property
    def status(self) -> Any: ...

    def start(self) -> None: ...

    def request_sync(self, *, retry_failed: bool = False) -> None: ...

    def list_conflicts(self) -> list[SyncConflict]: ...

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: dict | None = None,
        *,
        expected_remote_version: int | None = None,
    ) -> None: ...

    def stop(self, *, timeout_seconds: float = 5.0) -> None: ...


SyncFactory = Callable[[ProfileContext], SyncScope | None]


class AppController:
    """프로필 전환마다 계정 범위 서비스와 창을 새로 구성한다."""

    def __init__(
        self,
        profiles: ProfileManager,
        service_factory: ServiceFactory,
        window_factory: WindowFactory,
        sync_factory: SyncFactory | None = None,
    ):
        self._profiles = profiles
        self._service_factory = service_factory
        self._window_factory = window_factory
        self._sync_factory = sync_factory
        self._current_profile: ProfileContext | None = None
        self._games: GameService | None = None
        self._window: ProfileWindow | None = None
        self._sync: SyncScope | None = None

    @property
    def current_profile(self) -> ProfileContext | None:
        return self._current_profile

    @property
    def current_window(self) -> ProfileWindow | None:
        return self._window

    @property
    def current_game_count(self) -> int:
        return self._games.count_games() if self._games is not None else 0

    @property
    def sync_status(self) -> Any | None:
        return self._sync.status if self._sync is not None else None

    def request_sync(self, *, retry_failed: bool = False) -> None:
        if self._sync is not None:
            self._sync.request_sync(retry_failed=retry_failed)

    def list_conflicts(self) -> list[SyncConflict]:
        return self._sync.list_conflicts() if self._sync is not None else []

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: dict | None = None,
        *,
        expected_remote_version: int | None = None,
    ) -> None:
        if self._sync is not None:
            self._sync.resolve_conflict(
                conflict_id,
                resolution,
                merged_payload,
                expected_remote_version=expected_remote_version,
            )

    def start_guest(self) -> None:
        self.switch_profile(self._profiles.guest())

    def login_registered(self, remote_user_id: str, display_name: str) -> None:
        self.switch_profile(self._profiles.registered(remote_user_id, display_name))

    def logout(self) -> None:
        """등록 계정의 로컬 DB를 보존한 채 지속형 게스트로 돌아간다."""
        self.start_guest()

    def switch_profile(self, profile: ProfileContext) -> None:
        """기존 창과 연결을 정리한 뒤 새 프로필 범위를 시작한다."""
        self._close_current_scope()
        self._profiles.prepare_database(profile)

        games = self._service_factory(profile)
        try:
            window = self._window_factory(games, profile)
        except Exception:
            games.close()
            raise

        try:
            self._profiles.remember_profile(profile)
        except Exception:
            window.close_profile_windows()
            games.close()
            raise

        try:
            sync = (
                self._sync_factory(profile) if self._sync_factory is not None else None
            )
        except Exception:
            window.close_profile_windows()
            games.close()
            raise

        self._current_profile = profile
        self._games = games
        self._window = window
        self._sync = sync
        if sync is not None:
            attach_sync = getattr(window, "set_sync_coordinator", None)
            if callable(attach_sync):
                attach_sync(sync)
        window.show()
        if sync is not None:
            sync.start()

    def close(self) -> None:
        self._close_current_scope()

    def _close_current_scope(self) -> None:
        sync = self._sync
        window = self._window
        games = self._games
        self._sync = None
        self._window = None
        self._games = None
        self._current_profile = None

        try:
            if sync is not None:
                sync.stop()
        finally:
            try:
                if window is not None:
                    window.close_profile_windows()
            finally:
                # 정리 중 예외가 나도 연결은 반드시 해제해 Windows 파일 락을
                # 남기지 않는다(P1-9).
                if games is not None:
                    games.close()
