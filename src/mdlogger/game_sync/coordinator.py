"""프로필별 background push worker와 Qt 상태 signal."""

from __future__ import annotations

from threading import Event, Lock, Thread

from PySide6.QtCore import QObject, Signal

from .engine import SyncEngine
from .models import SyncPhase, SyncStatus


class SyncCoordinator(QObject):
    """UI 연결을 공유하지 않는 단일 profile push coordinator."""

    status_changed = Signal(object)

    def __init__(self, engine: SyncEngine, *, interval_seconds: float = 30.0) -> None:
        super().__init__()
        self._engine = engine
        self._interval_seconds = interval_seconds
        self._wake = Event()
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._status = engine.status()

    @property
    def status(self) -> SyncStatus:
        with self._lock:
            return self._status

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(
            target=self._run,
            name="mdlogger-game-sync",
            daemon=True,
        )
        self._thread.start()

    def request_sync(self, *, retry_failed: bool = False) -> None:
        if retry_failed:
            self._engine.retry_failed()
        self._wake.set()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout_seconds)
            self._thread = None

    def _set_status(self, status: SyncStatus) -> None:
        if self._stop.is_set():
            return
        with self._lock:
            self._status = status
        self.status_changed.emit(status)

    def _run(self) -> None:
        while not self._stop.is_set():
            current = self._engine.status()
            if current.pending_count:
                self._set_status(
                    SyncStatus(
                        phase=SyncPhase.SYNCING,
                        pending_count=current.pending_count,
                        failed_count=current.failed_count,
                        last_error=current.last_error,
                    )
                )
                status = self._engine.run_once()
                self._set_status(status)
                if status.phase in (SyncPhase.SYNCED, SyncPhase.PENDING):
                    continue
            self._wake.wait(self._interval_seconds)
            self._wake.clear()
