"""프로필별 background push worker와 Qt 상태 signal."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Event, Lock, Thread
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from ..remote.games import RegisteredGamesError, RegisteredGamesErrorKind
from .engine import SyncEngine
from .models import (
    ConflictResolutionResult,
    StaleConflictError,
    SyncConflict,
    SyncPhase,
    SyncStatus,
)


@dataclass(frozen=True, slots=True)
class _ResolutionRequest:
    request_id: str
    conflict_id: int
    resolution: str
    merged_payload: dict | None
    expected_remote_version: int | None
    expected_local_revision: str


class SyncCoordinator(QObject):
    """UI 연결을 공유하지 않는 단일 profile 양방향 sync coordinator.

    동기화와 최신 서버 확인이 필요한 충돌 해결은 작업 스레드에서 실행한다.
    충돌 조회와 outbox 재시도만 짧은 로컬 연결로 직접 실행한다.
    """

    status_changed = Signal(object)
    resolution_finished = Signal(object)

    _DEFAULT_STATUS = SyncStatus(
        phase=SyncPhase.PENDING,
        pending_count=0,
        failed_count=0,
    )

    def __init__(self, engine: SyncEngine, *, interval_seconds: float = 30.0) -> None:
        super().__init__()
        self._engine = engine
        self._interval_seconds = interval_seconds
        self._wake = Event()
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._resume_requested = False
        self._resolutions: SimpleQueue[_ResolutionRequest] = SimpleQueue()
        # 초기 상태는 I/O 없이 기본값으로 시작하고 첫 tick에서 worker가
        # 실제 상태로 갱신한다(P1-5).
        self._status = self._DEFAULT_STATUS

    @property
    def status(self) -> SyncStatus:
        with self._lock:
            return self._status

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._start_locked()

    def _start_locked(self) -> None:
        self._stop.clear()
        self._thread = Thread(
            target=self._run,
            name="mdlogger-game-sync",
            daemon=True,
        )
        self._thread.start()

    def resume(self) -> None:
        """종료 대기 중이면 작업 종료 뒤 한 번만 재개한다."""
        with self._lock:
            if self._thread is not None:
                if self._stop.is_set():
                    self._resume_requested = True
                else:
                    self._wake.set()
                return
            self._start_locked()

    def request_sync(self, *, retry_failed: bool = False) -> None:
        if retry_failed:
            # 로컬 SQLite 쓰기라 호출자(UI) thread에서 즉시 실행한다. 실패하면
            # 예외가 그대로 전파되어 호출부가 사용자에게 안내할 수 있다(A-2).
            self._engine.retry_failed()
        self._wake.set()

    def list_conflicts(self) -> list[SyncConflict]:
        # 로컬 SQLite 읽기(ms 수준)라 worker를 거치지 않는다. worker가 느린
        # 네트워크 사이클에 묶여도 즉시 반환한다(P1-5 회귀 근본 해결).
        return self._engine.list_conflicts()

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: dict | None = None,
        *,
        expected_remote_version: int | None = None,
        expected_local_revision: str,
    ) -> str:
        """해결을 예약하고 요청 ID를 반환한다. 실패 시 UI의 초안은 유지한다."""
        if self._stop.is_set():
            raise RuntimeError("종료된 프로필에서는 충돌을 해결할 수 없습니다.")
        request_id = uuid4().hex
        self._resolutions.put(
            _ResolutionRequest(
                request_id,
                conflict_id,
                resolution,
                deepcopy(merged_payload),
                expected_remote_version,
                expected_local_revision,
            )
        )
        self._wake.set()
        return request_id

    def _resolve_pending(self) -> None:
        while not self._stop.is_set():
            try:
                request = self._resolutions.get_nowait()
            except Empty:
                return
            try:
                self._engine.resolve_conflict(
                    request.conflict_id,
                    request.resolution,
                    request.merged_payload,
                    expected_remote_version=request.expected_remote_version,
                    expected_local_revision=request.expected_local_revision,
                    is_cancelled=self._stop.is_set,
                )
                result = ConflictResolutionResult(
                    request.request_id, request.conflict_id, True
                )
            except Exception as error:  # noqa: BLE001 - 요청 실패가 작업 스레드를 종료하지 않는다
                retryable = isinstance(error, RegisteredGamesError) and error.kind in (
                    RegisteredGamesErrorKind.NETWORK,
                    RegisteredGamesErrorKind.SERVER,
                    RegisteredGamesErrorKind.RATE_LIMITED,
                )
                result = ConflictResolutionResult(
                    request.request_id,
                    request.conflict_id,
                    False,
                    str(error),
                    retryable=retryable,
                    stale=isinstance(error, StaleConflictError),
                )
            if not self._stop.is_set():
                self.resolution_finished.emit(result)

    def stop(self, *, timeout_seconds: float = 5.0) -> bool:
        """worker가 종료됐는지 반환한다. 타임아웃이면 False로 알린다."""
        with self._lock:
            self._resume_requested = False
            self._stop.set()
            self._wake.set()
            thread = self._thread
        if thread is None:
            self._discard_queued_resolutions()
            return True
        thread.join(timeout_seconds)
        # join이 타임아웃되면 worker가 아직 떠나는 중이므로 _thread를
        # 유지해 start()가 중복 실행되는 것을 막는다(P1-3).
        if thread.is_alive():
            return False
        self._discard_queued_resolutions()
        with self._lock:
            return self._thread is None

    def _discard_queued_resolutions(self) -> None:
        while True:
            try:
                self._resolutions.get_nowait()
            except Empty:
                return

    def _set_status(self, status: SyncStatus) -> None:
        if self._stop.is_set():
            return
        with self._lock:
            self._status = status
        self.status_changed.emit(status)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self._resolve_pending()
                    if self._stop.is_set():
                        break
                    self._tick()
                except Exception as error:  # noqa: BLE001 - 작업 오류를 상태로 전달한다
                    self._set_status(
                        SyncStatus(
                            phase=SyncPhase.FAILED,
                            pending_count=self._status.pending_count,
                            failed_count=self._status.failed_count,
                            last_error=str(error),
                            conflict_count=self._status.conflict_count,
                            initial_sync_completed=self._status.initial_sync_completed,
                            last_pulled_version=self._status.last_pulled_version,
                        )
                    )
                    self._wake.wait(self._interval_seconds)
                    self._wake.clear()
        finally:
            self._discard_queued_resolutions()
            with self._lock:
                self._thread = None
                if self._resume_requested:
                    self._resume_requested = False
                    self._start_locked()

    def _tick(self) -> None:
        current = self._engine.status()
        self._set_status(
            SyncStatus(
                phase=SyncPhase.SYNCING,
                pending_count=current.pending_count,
                failed_count=current.failed_count,
                last_error=current.last_error,
                conflict_count=current.conflict_count,
                initial_sync_completed=current.initial_sync_completed,
                last_pulled_version=current.last_pulled_version,
            )
        )
        status = self._engine.run_once()
        self._set_status(status)
        if status.phase is SyncPhase.PENDING:
            return
        self._wake.wait(self._interval_seconds)
        self._wake.clear()
