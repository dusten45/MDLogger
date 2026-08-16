"""기본 모드/마지막 모드 설정 저장·적용 헬퍼 (spec §6.4).

계획 2(통합 설정 창)에서 흡수할 최소 구조로, GameService를 통해
``database_metadata``의 ``default_mode``/``last_used_mode``를 읽고 쓴다.
"""

from __future__ import annotations

from typing import Protocol

# default_mode 특수값: 직전 사용 모드를 따름 (spec §3.1).
DEFAULT_MODE_LAST_USED = "last_used"


class _ModeStore(Protocol):
    def get_default_mode(self) -> str | None: ...

    def set_default_mode(self, mode_id: str | None) -> None: ...

    def get_last_used_mode(self) -> str | None: ...

    def set_last_used_mode(self, mode_id: str | None) -> None: ...

    def resolve_default_mode_id(self) -> str | None: ...


class ModeSettings:
    """기본/마지막 모드 설정 접근 헬퍼 (GameService 또는 repository 주입)."""

    def __init__(self, store: _ModeStore):
        self._store = store

    @property
    def default_mode(self) -> str | None:
        return self._store.get_default_mode()

    def set_default_mode(self, mode_id: str | None) -> None:
        self._store.set_default_mode(mode_id)

    @property
    def last_used_mode(self) -> str | None:
        return self._store.get_last_used_mode()

    def set_last_used_mode(self, mode_id: str | None) -> None:
        self._store.set_last_used_mode(mode_id)

    def resolve_default(self) -> str | None:
        """앱 시작 시 사용할 기본 모드 id (spec §6.1)."""
        return self._store.resolve_default_mode_id()
