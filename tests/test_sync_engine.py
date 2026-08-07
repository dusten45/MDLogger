"""단계 7 outbox push engine 및 fault-injection 테스트."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from mdlogger import db
from mdlogger.game_service import GameService
from mdlogger.game_sync.engine import SyncEngine
from mdlogger.game_sync.models import SyncPhase
from mdlogger.profiles import ProfileContext, ProfileManager
from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig
from mdlogger.remote.errors import NetworkError
from mdlogger.remote.games import RegisteredGamesClient
from mdlogger.remote.guest_ingest import GuestIngestClient

CONFIG = RemoteConfig(base_url="https://example.supabase.co", anon_key="anon-key")
ACCOUNT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def sample(note: str = "개인 메모") -> dict:
    return {
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "테스트 덱",
        "opp_deck": "상대 덱",
        "turns": 4,
        "end_reason": "regular",
        "score_after": 1500,
        "note": note,
    }


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 7, 10, 0, 0)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class StatefulTransport:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []
        self.remote_games: dict[str, dict] = {}
        self.guest_batches: dict[str, dict] = {}

    def request(self, method, url, headers, body, timeout):
        payload = json.loads(body.decode()) if body else None
        request = {"method": method, "url": url, "headers": headers, "body": payload}
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if callable(outcome):
            return outcome(self, request)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def registered_ok(transport: StatefulTransport, request: dict) -> HttpResponse:
    rows = request["body"]
    response_rows = []
    for row in rows:
        transport.remote_games[row["id"]] = row
        response_rows.append({"id": row["id"], "change_version": 7})
    return HttpResponse(status=201, body=json.dumps(response_rows).encode())


def registered_apply_then_drop(
    transport: StatefulTransport, request: dict
) -> HttpResponse:
    for row in request["body"]:
        transport.remote_games[row["id"]] = row
    raise NetworkError("응답 유실")


def guest_ok(transport: StatefulTransport, request: dict) -> HttpResponse:
    payload = request["body"]
    batch_id = payload["batch_id"]
    replayed = batch_id in transport.guest_batches
    transport.guest_batches.setdefault(batch_id, payload)
    return HttpResponse(
        status=200,
        body=json.dumps(
            {
                "batch_id": batch_id,
                "accepted": 0 if replayed else len(payload["observations"]),
                "skipped": len(payload["observations"]) if replayed else 0,
                "rejected": 0,
                "replayed": replayed,
            }
        ).encode(),
    )


def guest_apply_then_drop(transport: StatefulTransport, request: dict) -> HttpResponse:
    payload = request["body"]
    transport.guest_batches[payload["batch_id"]] = payload
    raise NetworkError("응답 유실")


def prepare_registered(tmp_path: Path) -> tuple[ProfileContext, GameService]:
    manager = ProfileManager(tmp_path)
    profile = manager.registered(ACCOUNT_ID, "user@example.com")
    manager.prepare_database(profile)
    return profile, GameService.open(profile.database_path)


def prepare_guest(tmp_path: Path) -> tuple[ProfileContext, GameService]:
    manager = ProfileManager(tmp_path)
    profile = manager.guest()
    manager.prepare_database(profile)
    return profile, GameService.open(profile.database_path)


def outbox_rows(profile: ProfileContext):
    connection = db.connect(profile.database_path)
    try:
        return connection.execute("SELECT * FROM sync_outbox ORDER BY id").fetchall()
    finally:
        connection.close()


def test_local_commit_and_outbox_survive_immediate_service_close(tmp_path: Path):
    profile, games = prepare_guest(tmp_path)
    games.insert_game(sample())
    games.close()

    reopened = GameService.open(profile.database_path)
    try:
        assert reopened.count_games() == 1
        assert len(outbox_rows(profile)) == 1
    finally:
        reopened.close()


def test_registered_latest_change_is_batched_once_and_acknowledged(tmp_path: Path):
    profile, games = prepare_registered(tmp_path)
    game_id = games.insert_game(sample("처음"))
    games.update_game(game_id, sample("수정"))
    transport = StatefulTransport([registered_ok])
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
    )

    status = engine.run_once()

    assert status.phase is SyncPhase.SYNCED
    assert len(transport.requests[0]["body"]) == 1
    assert transport.requests[0]["body"][0]["note"] == "수정"
    assert outbox_rows(profile) == []
    games.close()


def test_acknowledgement_preserves_edit_created_while_request_is_in_flight(
    tmp_path: Path,
):
    profile, games = prepare_registered(tmp_path)
    game_id = games.insert_game(sample("전송 시작값"))

    def update_during_request(
        transport: StatefulTransport, request: dict
    ) -> HttpResponse:
        games.update_game(game_id, sample("요청 중 새 수정"))
        return registered_ok(transport, request)

    transport = StatefulTransport([update_during_request, registered_ok])
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
    )

    first = engine.run_once()
    second = engine.run_once()

    assert first.phase is SyncPhase.PENDING
    assert first.pending_count == 1
    assert second.phase is SyncPhase.SYNCED
    assert transport.requests[0]["body"][0]["note"] == "전송 시작값"
    assert transport.requests[1]["body"][0]["note"] == "요청 중 새 수정"
    games.close()


def test_registered_response_loss_retries_same_uuid_without_remote_duplicate(
    tmp_path: Path,
):
    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    clock = Clock()
    transport = StatefulTransport([registered_apply_then_drop, registered_ok])
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
        now=clock,
    )

    first = engine.run_once()
    clock.advance(10)
    second = engine.run_once()

    assert first.phase is SyncPhase.OFFLINE
    assert second.phase is SyncPhase.SYNCED
    first_id = transport.requests[0]["body"][0]["id"]
    second_id = transport.requests[1]["body"][0]["id"]
    assert first_id == second_id
    assert list(transport.remote_games) == [first_id]
    games.close()


def test_registered_401_refreshes_once_and_retries_batch(tmp_path: Path):
    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    transport = StatefulTransport(
        [HttpResponse(status=401, body=b'{"code":"jwt_expired"}'), registered_ok]
    )
    refreshed: list[bool] = []
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "expired-token",
        token_refresher=lambda: refreshed.append(True) or "fresh-token",
    )

    status = engine.run_once()

    assert status.phase is SyncPhase.SYNCED
    assert refreshed == [True]
    assert transport.requests[0]["headers"]["Authorization"] == "Bearer expired-token"
    assert transport.requests[1]["headers"]["Authorization"] == "Bearer fresh-token"
    games.close()


def test_guest_response_loss_reuses_batch_id_and_never_sends_note(tmp_path: Path):
    profile, games = prepare_guest(tmp_path)
    games.insert_game(sample("절대 전송 금지"))
    clock = Clock()
    transport = StatefulTransport([guest_apply_then_drop, guest_ok])
    engine = SyncEngine(
        profile,
        guest_client=GuestIngestClient(
            CONFIG,
            profile.installation_id,
            client=JsonHttpClient(transport),
        ),
        now=clock,
    )

    first = engine.run_once()
    clock.advance(10)
    second = engine.run_once()

    assert first.phase is SyncPhase.OFFLINE
    assert second.phase is SyncPhase.SYNCED
    first_body, second_body = (request["body"] for request in transport.requests)
    assert first_body["batch_id"] == second_body["batch_id"]
    assert first_body["observations"][0]["op"] == "upsert"
    assert "note" not in json.dumps(first_body, ensure_ascii=False)
    assert isinstance(first_body["observations"][0]["timezone_offset_minutes"], int)
    assert len(transport.guest_batches) == 1
    games.close()


def test_missing_remote_config_keeps_local_record_pending(tmp_path: Path):
    profile, games = prepare_guest(tmp_path)
    games.insert_game(sample())

    status = SyncEngine(profile).run_once()

    assert status.phase is SyncPhase.OFFLINE
    assert status.pending_count == 1
    assert games.count_games() == 1
    games.close()
