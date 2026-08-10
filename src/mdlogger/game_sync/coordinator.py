"""프로필별 background push worker와 Qt 상태 signal."""

from __future__ import annotations

from threading import Event, Lock, Thread
from typing import Any

from PySide6.QtCore import QObject, Signal

from .engine import SyncEngine
from .models import SyncConflict, SyncPhase, SyncStatus


class SyncCoordinator(QObject):
    """UI 연결을 공유하지 않는 단일 profile 양방향 sync coordinator.

    engine이 소유하는 SQLite 연결은 worker thread에서만 접근한다(R7 스레딩
    경계). UI thread가 요청하는 연산은 command queue를 통해 worker로 넘겨
    UI thread를 블로킹 I/O에서 분리한다(P1-5).
    """

    status_changed = Signal(object)

    _COMMAND_TIMEOUT_SECONDS = 10.0
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
        # worker가 처리할 명령 큐. 초기 상태는 I/O 없이 기본값으로 시작하고
        # 첫 tick에서 worker가 실제 상태로 갱신한다(P1-5).
        self._command_lock = Lock()
        self._commands: list[_Command] = []
        self._status = self._DEFAULT_STATUS

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
            self._post(_Command("retry_failed"))
        self._wake.set()

    def list_conflicts(self) -> list[SyncConflict]:
        command = _Command("list_conflicts")
        self._post(command)
        if not command.wait(self._COMMAND_TIMEOUT_SECONDS):
            raise TimeoutError("동기화 worker가 충돌 목록 조회에 응답하지 않았습니다.")
        if command.error is not None:
            raise command.error
        return command.result

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: dict | None = None,
        *,
        expected_remote_version: int | None = None,
    ) -> None:
        self._post(
            _Command(
                "resolve_conflict",
                (conflict_id, resolution),
                {
                    "merged_payload": merged_payload,
                    "expected_remote_version": expected_remote_version,
                },
            )
        )

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout_seconds)
            # join이 타임아웃되면 worker가 아직 떠나는 중이므로 _thread를
            # 유지해 start()가 중복 실행되는 것을 막는다(P1-3).
            if not thread.is_alive():
                self._thread = None

    def _post(self, command: _Command) -> None:
        with self._command_lock:
            self._commands.append(command)
        self._wake.set()

    def _drain_commands(self) -> None:
        with self._command_lock:
            commands = self._commands
            self._commands = []
        for command in commands:
            try:
                self._execute_command(command)
            except Exception as error:  # noqa: BLE001 - 명령 실패를 호출자에게 전달
                command.error = error
            finally:
                command.done.set()

    def _execute_command(self, command: _Command) -> None:
        method = command.method
        if method == "retry_failed":
            self._engine.retry_failed()
        elif method == "list_conflicts":
            command.result = self._engine.list_conflicts()
        elif method == "resolve_conflict":
            kwargs = command.kwargs
            self._engine.resolve_conflict(
                command.args[0],
                command.args[1],
                kwargs.get("merged_payload"),
                expected_remote_version=kwargs.get("expected_remote_version"),
            )
        else:  # pragma: no cover - 알 수 없는 명령은 프로그래밍 오류
            raise ValueError(f"알 수 없는 sync 명령: {method}")

    def _set_status(self, status: SyncStatus) -> None:
        if self._stop.is_set():
            return
        with self._lock:
            self._status = status
        self.status_changed.emit(status)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as error:  # noqa: BLE001 - RemoteError 외 예외로
                # worker가 조용히 죽지 않게 상태만 갱신하고 계속 대기한다(P1-2).
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
        # 종료 전 남은 명령을 처리해 resolve_conflict 등이 반쯤 남지 않게 한다.
        self._drain_commands()

    def _tick(self) -> None:
        self._drain_commands()
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


class _Command:
    """worker thread에서 실행할 단일 명령과 결과/완료 동기화 객체."""

    __slots__ = ("method", "args", "kwargs", "result", "error", "done")

    def __init__(
        self,
        method: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.method = method
        self.args = args
        self.kwargs = kwargs or {}
        self.result: Any = None
        self.error: Exception | None = None
        self.done = Event()

    def wait(self, timeout: float | None = None) -> None:
        self.done.wait(timeout)
