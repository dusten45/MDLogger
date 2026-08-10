"""background sync coordinator의 thread/종료 동작 테스트."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import cast

from mdlogger.game_service import GameService
from mdlogger.game_sync.coordinator import SyncCoordinator, _Command
from mdlogger.game_sync.engine import SyncEngine
from mdlogger.game_sync.models import SyncPhase, SyncStatus
from mdlogger.profiles import ProfileManager
from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig
from mdlogger.remote.guest_ingest import GuestIngestClient

CONFIG = RemoteConfig(base_url="https://example.supabase.co", anon_key="anon-key")


class OkTransport:
    def request(self, method, url, headers, body, timeout):
        payload = json.loads(body.decode())
        return HttpResponse(
            status=200,
            body=json.dumps(
                {
                    "batch_id": payload["batch_id"],
                    "accepted": len(payload["observations"]),
                    "skipped": 0,
                    "rejected": 0,
                    "replayed": False,
                }
            ).encode(),
        )


def sample() -> dict:
    return {
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "테스트 덱",
        "opp_deck": "상대 덱",
        "turns": 4,
        "end_reason": "regular",
        "score_after": 1500,
        "note": "로컬 전용",
    }


class ConflictEngine:
    def __init__(self) -> None:
        self.run_count = 0
        self._status = SyncStatus(
            SyncPhase.SYNCED,
            pending_count=0,
            failed_count=0,
            conflict_count=1,
        )

    def status(self) -> SyncStatus:
        return self._status

    def run_once(self) -> SyncStatus:
        self.run_count += 1
        return self._status


def test_unresolved_conflict_waits_for_interval_instead_of_busy_loop():
    engine = ConflictEngine()
    coordinator = SyncCoordinator(cast(SyncEngine, engine), interval_seconds=0.5)

    coordinator.start()
    time.sleep(0.08)
    coordinator.stop()

    assert engine.run_count == 1


def test_worker_uses_own_sqlite_connection_and_stops_cleanly(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    profile = manager.guest()
    manager.prepare_database(profile)
    games = GameService.open(profile.database_path)
    games.insert_game(sample())
    engine = SyncEngine(
        profile,
        guest_client=GuestIngestClient(
            CONFIG,
            profile.installation_id,
            client=JsonHttpClient(OkTransport()),
        ),
    )
    coordinator = SyncCoordinator(engine, interval_seconds=0.05)

    coordinator.start()
    deadline = time.monotonic() + 2
    while coordinator.status.phase is not SyncPhase.SYNCED:
        assert games.count_games() == 1
        if time.monotonic() >= deadline:
            raise AssertionError(
                "background sync가 제한 시간 안에 완료되지 않았습니다."
            )
        time.sleep(0.01)
    coordinator.stop()

    assert coordinator._thread is None
    assert games.count_games() == 1
    games.close()


def test_worker_survives_unexpected_exception_and_reports_failed(tmp_path: Path):
    """P1-2: RemoteError 외 예외가 나도 worker가 조용히 죽지 않는다."""

    class ExplodingEngine:
        def status(self) -> SyncStatus:
            return SyncStatus(SyncPhase.SYNCED, pending_count=0, failed_count=0)

        def run_once(self) -> SyncStatus:
            raise RuntimeError("예상치 못한 worker 오류")

    coordinator = SyncCoordinator(
        cast(SyncEngine, ExplodingEngine()), interval_seconds=0.05
    )
    coordinator.start()
    deadline = time.monotonic() + 1
    while coordinator.status.phase is not SyncPhase.FAILED:
        if time.monotonic() >= deadline:
            raise AssertionError("worker가 실패 상태를 보고하지 않았습니다.")
        time.sleep(0.01)

    assert coordinator.status.last_error == "예상치 못한 worker 오류"
    # worker가 살아 있어 start()가 no-op이어도 stop()으로 끝낼 수 있다.
    coordinator.stop()
    assert coordinator._thread is None


def test_stop_keeps_thread_when_join_times_out():
    """P1-3: join이 타임아웃되면 _thread를 유지해 start() 중복 실행을 막는다."""

    class BlockingEngine:
        def status(self) -> SyncStatus:
            return SyncStatus(SyncPhase.SYNCING, pending_count=0, failed_count=0)

        def run_once(self) -> SyncStatus:
            # stop 이벤트를 무시하고 계속 블로킹한다.
            while True:
                time.sleep(0.01)

    coordinator = SyncCoordinator(
        cast(SyncEngine, BlockingEngine()), interval_seconds=0.05
    )
    coordinator.start()
    time.sleep(0.08)

    coordinator.stop(timeout_seconds=0.05)
    # worker가 아직 떠나는 중이므로 스레드 참조를 유지해야 한다.
    assert coordinator._thread is not None

    # 하드 배리어: stop 후 start()가 새 스레드를 만들지 않는다.
    coordinator.start()
    assert coordinator._thread is not None


def test_commands_are_offloaded_to_worker_thread():
    """P1-5: engine 연산은 UI thread가 아닌 worker thread에서 실행된다."""

    class RecordingEngine:
        def __init__(self) -> None:
            self.thread_id: int | None = None
            self._status = SyncStatus(SyncPhase.SYNCED, pending_count=0, failed_count=0)

        def status(self) -> SyncStatus:
            return self._status

        def run_once(self) -> SyncStatus:
            return self._status

        def retry_failed(self) -> None:
            import threading

            self.thread_id = threading.current_thread().ident

    engine = RecordingEngine()
    coordinator = SyncCoordinator(cast(SyncEngine, engine), interval_seconds=0.05)
    coordinator.start()
    worker_thread = coordinator._thread
    assert worker_thread is not None
    coordinator._post(_Command("retry_failed"))
    # worker가 명령을 처리할 때까지 대기한다.
    deadline = time.monotonic() + 1
    while engine.thread_id is None:
        if time.monotonic() >= deadline:
            raise AssertionError("worker가 명령을 처리하지 않았습니다.")
        time.sleep(0.01)
    coordinator.stop()

    assert worker_thread.ident == engine.thread_id
