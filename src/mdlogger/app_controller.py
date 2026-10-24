"""현재 로컬 프로필의 서비스와 창 수명 주기를 조정한다."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QObject, Signal

from .game_service import GameService
from .game_sync.models import SyncConflict
from .profiles import ProfileContext, ProfileKind, ProfileManager


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
        expected_local_revision: str,
    ) -> str: ...

    def stop(self, *, timeout_seconds: float = 5.0) -> bool: ...

    def resume(self) -> None: ...


SyncFactory = Callable[[ProfileContext], SyncScope | None]


class AppController(QObject):
    """프로필 전환마다 계정 범위 서비스와 창을 새로 구성한다."""

    profile_closing = Signal()

    def __init__(
        self,
        profiles: ProfileManager,
        service_factory: ServiceFactory,
        window_factory: WindowFactory,
        sync_factory: SyncFactory | None = None,
    ):
        super().__init__()
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

    @property
    def resolution_finished(self) -> Any:
        return getattr(self._sync, "resolution_finished", None)

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: dict | None = None,
        *,
        expected_remote_version: int | None = None,
        expected_local_revision: str,
    ) -> str:
        if self._sync is not None:
            return self._sync.resolve_conflict(
                conflict_id,
                resolution,
                merged_payload,
                expected_remote_version=expected_remote_version,
                expected_local_revision=expected_local_revision,
            )
        raise ValueError("동기화 연결을 사용할 수 없어 충돌을 해결할 수 없습니다.")

    def backup_guest_to(self, destination: Path) -> None:
        if (
            self._games is None
            or self._current_profile is None
            or self._current_profile.kind is not ProfileKind.GUEST
        ):
            raise ValueError("현재 게스트 프로필의 스냅숏을 만들 수 없습니다.")
        self._games.backup_to(destination)

    def pause_for_update(self) -> bool:
        """창과 연결은 유지하면서 설치 전에 동기화 작업을 정지한다."""
        return self._sync is None or self._sync.stop() is not False

    def resume_after_update(self) -> None:
        if self._sync is not None:
            self._sync.resume()

    def start_guest(self) -> None:
        self.switch_profile(self._profiles.guest())

    def login_registered(self, remote_user_id: str, display_name: str) -> None:
        self.switch_profile(self._profiles.registered(remote_user_id, display_name))

    def switch_profile(self, profile: ProfileContext) -> None:
        """새 프로필 DB를 검증·준비한 뒤 기존 창과 연결을 정리하고 새 범위를 시작한다.

        새 DB 준비가 실패하면 기존 scope를 아직 닫지 않아 사용자를 화면 없는
        상태로 두지 않는다(B-2).
        """
        # 새 프로필 DB의 소유권·스키마를 먼저 검증한다. 실패하면 여기서 예외가
        # 나며 기존 scope는 그대로 유지된다.
        self._profiles.prepare_database(profile)

        self._close_current_scope()

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

    def close_for_data_reset(self) -> bool:
        """동기화 worker가 완전히 멈춘 경우에만 초기화용으로 범위를 닫는다."""
        sync = self._sync
        if sync is not None and sync.stop() is False:
            return False
        self._close_current_scope(sync_already_stopped=sync is not None)
        return True

    def _close_current_scope(self, *, sync_already_stopped: bool = False) -> None:
        self.profile_closing.emit()
        sync = self._sync
        window = self._window
        games = self._games
        self._sync = None
        self._window = None
        self._games = None
        self._current_profile = None

        try:
            if sync is not None and not sync_already_stopped:
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
