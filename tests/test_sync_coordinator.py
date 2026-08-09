"""background sync coordinator의 thread/종료 동작 테스트."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import cast

from mdlogger.game_service import GameService
from mdlogger.game_sync.coordinator import SyncCoordinator
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
