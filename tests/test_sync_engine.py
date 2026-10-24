"""단계 8 양방향 sync engine 및 fault-injection 테스트."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from mdlogger import db
from mdlogger.game_service import GameService
from mdlogger.game_sync.engine import SyncEngine
from mdlogger.game_sync.models import StaleConflictError, SyncPhase
from mdlogger.profiles import ProfileContext, ProfileManager
from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig
from mdlogger.remote.errors import NetworkError
from mdlogger.remote.games import RegisteredGamesClient, RegisteredGamesError
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
        "standing_kind": "event_points",
        "play_context_id": "dc_cup_2026_08",
        "event_points_before": 0,
        "event_points_after": 1500,
        "note": note,
    }


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 7, 10, 0, 0)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class RegisteredTransport:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.remote_games: dict[str, dict] = {}
        self.version = 0
        self.drop_apply_response_once = False
        self.reject_first_request = False
        self.rate_limit_first_request = None
        self.on_apply = None
        self.on_fetch = None

    def request(self, method, url, headers, body, timeout):
        payload = json.loads(body.decode()) if body else None
        request = {"method": method, "url": url, "headers": headers, "body": payload}
        self.requests.append(request)
        if self.reject_first_request:
            self.reject_first_request = False
            return HttpResponse(status=401, body=b'{"code":"jwt_expired"}')
        if self.rate_limit_first_request is not None:
            retry_after, self.rate_limit_first_request = (
                self.rate_limit_first_request,
                None,
            )
            body_text = json.dumps(
                {"retry_after_seconds": retry_after} if retry_after is not None else {}
            )
            return HttpResponse(status=429, body=body_text.encode())
        if url.endswith("/rpc/register_or_touch_device"):
            return HttpResponse(status=200, body=b"{}")
        if url.endswith("/rpc/apply_game_changes"):
            assert isinstance(payload, dict)
            if self.on_apply is not None:
                callback, self.on_apply = self.on_apply, None
                callback()
            results = [self._apply(change) for change in payload["changes"]]
            if self.drop_apply_response_once:
                self.drop_apply_response_once = False
                raise NetworkError("응답 유실")
            return HttpResponse(
                status=200, body=json.dumps({"results": results}).encode()
            )
        if "/games?" in url:
            query = parse_qs(urlsplit(url).query)
            if "id" in query:
                if self.on_fetch is not None:
                    callback, self.on_fetch = self.on_fetch, None
                    callback()
                row = self.remote_games.get(query["id"][0].removeprefix("eq."))
                return HttpResponse(
                    status=200, body=json.dumps([row] if row else []).encode()
                )
            match = re.search(r"change_version=gt\.(\d+)", url)
            cursor = int(match.group(1)) if match else 0
            rows = sorted(
                (
                    row
                    for row in self.remote_games.values()
                    if row["change_version"] > cursor
                ),
                key=lambda row: row["change_version"],
            )
            limit_match = re.search(r"limit=(\d+)", url)
            limit = int(limit_match.group(1)) if limit_match else len(rows)
            return HttpResponse(status=200, body=json.dumps(rows[:limit]).encode())
        if url.endswith("/rpc/acknowledge_device_version"):
            return HttpResponse(status=200, body=b"{}")
        raise AssertionError(url)

    def _apply(self, change: dict) -> dict:
        game_id = change["id"]
        current = self.remote_games.get(game_id)
        expected = change.get("expected_change_version")
        operation = change["op"]
        if operation == "create" and current is None:
            row = {"id": game_id, **change["payload"], "deleted_at": None}
        elif operation == "delete" and expected is None:
            # delete-if-exists(P0-1): 대상이 없으면 멱등 무조작, 있으면 soft delete.
            if current is None:
                return {"id": game_id, "status": "applied", "change_version": None}
            row = dict(current)
            row["deleted_at"] = "2026-08-07T01:00:00+00:00"
        elif (
            current is not None
            and expected == current["change_version"]
            and (
                (operation == "update" and current.get("deleted_at") is None)
                or operation == "delete"
                or (operation == "restore" and current.get("deleted_at") is not None)
            )
        ):
            row = dict(current)
            if operation == "delete":
                row["deleted_at"] = "2026-08-07T01:00:00+00:00"
            else:
                row.update(change["payload"])
                if operation == "restore":
                    row["deleted_at"] = None
        else:
            return {
                "id": game_id,
                "status": "conflict",
                "current_change_version": (
                    current["change_version"] if current is not None else None
                ),
                "remote": current,
            }
        self.version += 1
        row.update(
            change_version=self.version,
            payload_version=1,
            source_kind="native",
            created_at="2026-08-07T01:00:00+00:00",
            updated_at="2026-08-07T01:00:00+00:00",
        )
        self.remote_games[game_id] = row
        return {"id": game_id, "status": "applied", "change_version": self.version}


class GuestTransport:
    def __init__(self, *, drop_once: bool = False) -> None:
        self.drop_once = drop_once
        self.requests: list[dict] = []
        self.batches: dict[str, dict] = {}

    def request(self, method, url, headers, body, timeout):
        payload = json.loads(body.decode())
        self.requests.append({"body": payload})
        batch_id = payload["batch_id"]
        replayed = batch_id in self.batches
        self.batches.setdefault(batch_id, payload)
        if self.drop_once:
            self.drop_once = False
            raise NetworkError("응답 유실")
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


def test_registered_push_then_pull_acknowledges_and_completes_initial_sync(
    tmp_path: Path,
):
    profile, games = prepare_registered(tmp_path)
    game_id = games.insert_game(sample("처음"))
    games.update_game(game_id, sample("수정"))
    transport = RegisteredTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
    )

    status = engine.run_once()

    assert status.phase is SyncPhase.SYNCED
    assert status.initial_sync_completed is True
    apply_request = next(
        request
        for request in transport.requests
        if request["url"].endswith("/rpc/apply_game_changes")
    )
    assert len(apply_request["body"]["changes"]) == 1
    assert apply_request["body"]["changes"][0]["payload"]["note"] == "수정"
    assert outbox_rows(profile) == []
    games.close()


def test_large_1000_game_sync_completes(tmp_path: Path):
    """하드닝 N-8: 오프라인에서 1,000건을 쌓아도 전체가 동기화된다(§14.4)."""
    profile, games = prepare_registered(tmp_path)
    for index in range(1000):
        games.insert_game(sample(f"memo {index}"))
    games.close()

    transport = RegisteredTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
    )
    for _ in range(500):
        engine.run_once()
        if not outbox_rows(profile):
            break

    assert len(transport.remote_games) == 1000
    assert outbox_rows(profile) == []

    connection = db.connect(profile.database_path)
    try:
        synced = int(
            connection.execute(
                "SELECT count(*) FROM games WHERE sync_status='synced'"
            ).fetchone()[0]
        )
        kept = int(
            connection.execute(
                "SELECT count(*) FROM games WHERE deleted_at IS NULL"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert synced == 1000
    assert kept == 1000


def test_acknowledgement_preserves_edit_created_while_request_is_in_flight(
    tmp_path: Path,
):
    profile, games = prepare_registered(tmp_path)
    game_id = games.insert_game(sample("전송 시작값"))
    transport = RegisteredTransport()
    transport.on_apply = lambda: games.update_game(game_id, sample("요청 중 새 수정"))
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
    apply_requests = [
        request
        for request in transport.requests
        if request["url"].endswith("/rpc/apply_game_changes")
    ]
    assert apply_requests[0]["body"]["changes"][0]["payload"]["note"] == "전송 시작값"
    assert (
        apply_requests[1]["body"]["changes"][0]["payload"]["note"] == "요청 중 새 수정"
    )
    games.close()


def test_registered_response_loss_retries_uuid_and_accepts_matching_remote(
    tmp_path: Path,
):
    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    clock = Clock()
    transport = RegisteredTransport()
    transport.drop_apply_response_once = True
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
    assert len(transport.remote_games) == 1
    assert outbox_rows(profile) == []
    games.close()


def test_registered_401_refreshes_once_and_retries_cycle(tmp_path: Path):
    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    transport = RegisteredTransport()
    transport.reject_first_request = True
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


def test_large_initial_sync_resumes_from_committed_cursor_after_restart(tmp_path: Path):
    transport = RegisteredTransport()
    for index in range(205):
        transport._apply(
            {
                "op": "create",
                "id": f"00000000-0000-4000-8000-{index:012d}",
                "payload": {
                    "played_at": "2026-08-07T10:00:00",
                    "result": "win",
                    "turn_order": "first",
                    "my_deck": "테스트 덱",
                    "opp_deck": "상대 덱",
                    "turns": 4,
                    "end_reason": "regular",
                    "score_after": 1500,
                    "note": str(index),
                    "timezone_offset_minutes": 540,
                },
            }
        )
    profile, games = prepare_registered(tmp_path)
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))

    first_engine = SyncEngine(
        profile, registered_client=client, token_provider=lambda: "token"
    )
    first = first_engine.run_once()
    assert first.phase is SyncPhase.PENDING
    assert first.last_pulled_version == 100
    assert games.count_games() == 100

    resumed_engine = SyncEngine(
        profile, registered_client=client, token_provider=lambda: "token"
    )
    second = resumed_engine.run_once()
    third = resumed_engine.run_once()
    assert second.phase is SyncPhase.PENDING
    assert second.last_pulled_version == 200
    assert third.phase is SyncPhase.SYNCED
    assert third.last_pulled_version == 205
    assert third.initial_sync_completed is True
    assert games.count_games() == 205
    games.close()


def test_deleted_never_synced_registered_game_is_not_created_live(
    tmp_path: Path,
):
    """P0-1-A: 첫 동기화 전 생성→삭제는 서버에 살아있는 신규 기록으로 만들어지지 않는다.

    remote_version이 없는(서버에 한 번도 기록되지 않은) 삭제는 delete-if-exists
    envelope로 전송되어 서버에서 멱등 무조작 처리된다. create로 변환되어 살아있는
    신규 기록이 생기지 않는다.
    """
    profile, games = prepare_registered(tmp_path)
    game_id = games.insert_game(sample("삭제될 기록"))
    games.delete_game(game_id)
    transport = RegisteredTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
    )

    status = engine.run_once()

    assert status.phase is SyncPhase.SYNCED
    # 서버에 살아있는 신규 기록이 생기지 않는다(delete-if-exists 멱등 무조작).
    assert transport.remote_games == {}
    apply_request = next(
        request
        for request in transport.requests
        if request["url"].endswith("/rpc/apply_game_changes")
    )
    changes = apply_request["body"]["changes"]
    assert len(changes) == 1
    assert changes[0]["op"] == "delete"
    assert changes[0]["payload"] == {}
    assert changes[0]["expected_change_version"] is None
    assert outbox_rows(profile) == []

    connection = db.connect(profile.database_path)
    try:
        deleted = int(
            connection.execute(
                "SELECT count(*) FROM games WHERE deleted_at IS NOT NULL"
            ).fetchone()[0]
        )
        live = int(
            connection.execute(
                "SELECT count(*) FROM games WHERE deleted_at IS NULL"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert deleted == 1
    assert live == 0
    games.close()


def test_response_lost_create_then_delete_does_not_resurrect(tmp_path: Path):
    """P0-1-B: create 응답 유실 뒤 삭제해도 pull이 서버 기록을 되살리지 않는다.

    create가 서버에 적용됐지만 응답이 유실되어 로컬 remote_version은 여전히 None인
    상태에서 삭제하면, delete-if-exists가 서버에도 soft delete를 적용한다. 그 결과
    pull이 살아있는 기록을 가져오지 못해 국소 삭제 상태가 유지된다.
    """
    profile, games = prepare_registered(tmp_path)
    game_id = games.insert_game(sample("응답 유실 후 삭제"))
    transport = RegisteredTransport()
    transport.drop_apply_response_once = True
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
    )

    # create 전송(서버 적용) → 응답 유실 → 이어서 로컬 삭제·다시 동기화.
    engine.run_once()
    assert len(transport.remote_games) == 1
    games.delete_game(game_id)
    engine.run_once()

    # 서버에는 살아있는 기록이 없다(delete-if-exists로 soft delete됨).
    assert [g for g in transport.remote_games.values() if g["deleted_at"] is None] == []
    assert outbox_rows(profile) == []

    connection = db.connect(profile.database_path)
    try:
        deleted = int(
            connection.execute(
                "SELECT count(*) FROM games WHERE deleted_at IS NOT NULL"
            ).fetchone()[0]
        )
        live = int(
            connection.execute(
                "SELECT count(*) FROM games WHERE deleted_at IS NULL"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert deleted == 1
    assert live == 0
    games.close()


def test_two_device_create_update_delete_round_trip(tmp_path: Path):
    transport = RegisteredTransport()
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))

    manager_a = ProfileManager(tmp_path / "pc-a")
    profile_a = manager_a.registered(ACCOUNT_ID, "user@example.com")
    manager_a.prepare_database(profile_a)
    games_a = GameService.open(profile_a.database_path)
    engine_a = SyncEngine(
        profile_a, registered_client=client, token_provider=lambda: "token"
    )

    manager_b = ProfileManager(tmp_path / "pc-b")
    profile_b = manager_b.registered(ACCOUNT_ID, "user@example.com")
    manager_b.prepare_database(profile_b)
    games_b = GameService.open(profile_b.database_path)
    engine_b = SyncEngine(
        profile_b, registered_client=client, token_provider=lambda: "token"
    )

    game_a_id = games_a.insert_game(sample("A 생성"))
    assert engine_a.run_once().phase is SyncPhase.SYNCED
    assert engine_b.run_once().phase is SyncPhase.SYNCED
    assert games_b.count_games() == 1

    game_b = games_b.get_last_game()
    assert game_b is not None
    games_b.update_game(game_b["id"], sample("B 수정"))
    assert engine_b.run_once().phase is SyncPhase.SYNCED
    assert engine_a.run_once().phase is SyncPhase.SYNCED
    updated_a = games_a.get_game(game_a_id)
    assert updated_a is not None
    assert updated_a["note"] == "B 수정"

    games_a.delete_game(game_a_id)
    assert engine_a.run_once().phase is SyncPhase.SYNCED
    assert engine_b.run_once().phase is SyncPhase.SYNCED
    assert games_b.count_games() == 0

    games_a.close()
    games_b.close()


def test_two_device_concurrent_update_and_update_delete_conflicts_are_resolvable(
    tmp_path: Path,
):
    transport = RegisteredTransport()
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))

    manager_a = ProfileManager(tmp_path / "pc-a")
    profile_a = manager_a.registered(ACCOUNT_ID, "user@example.com")
    manager_a.prepare_database(profile_a)
    games_a = GameService.open(profile_a.database_path)
    engine_a = SyncEngine(
        profile_a, registered_client=client, token_provider=lambda: "token"
    )

    manager_b = ProfileManager(tmp_path / "pc-b")
    profile_b = manager_b.registered(ACCOUNT_ID, "user@example.com")
    manager_b.prepare_database(profile_b)
    games_b = GameService.open(profile_b.database_path)
    engine_b = SyncEngine(
        profile_b, registered_client=client, token_provider=lambda: "token"
    )

    game_a_id = games_a.insert_game(sample("기준"))
    engine_a.run_once()
    engine_b.run_once()
    game_b = games_b.get_last_game()
    assert game_b is not None
    game_b_id = game_b["id"]

    games_a.update_game(game_a_id, sample("A 수정"))
    games_b.update_game(game_b_id, sample("B 수정"))
    engine_a.run_once()
    conflict_status = engine_b.run_once()
    assert conflict_status.conflict_count == 1
    conflict = engine_b.list_conflicts()[0]
    assert conflict.local_payload["note"] == "B 수정"
    assert conflict.remote_payload["note"] == "A 수정"
    engine_b.resolve_conflict(
        conflict.id,
        "remote",
        expected_remote_version=conflict.remote_payload["change_version"],
        expected_local_revision=conflict.local_revision,
    )
    resolved_b = games_b.get_game(game_b_id)
    assert resolved_b is not None
    assert resolved_b["note"] == "A 수정"

    games_a.update_game(game_a_id, sample("A 두 번째 수정"))
    games_b.delete_game(game_b_id)
    engine_a.run_once()
    delete_conflict_status = engine_b.run_once()
    assert delete_conflict_status.conflict_count == 1
    delete_conflict = engine_b.list_conflicts()[0]
    engine_b.resolve_conflict(
        delete_conflict.id,
        "local",
        expected_remote_version=delete_conflict.remote_payload["change_version"],
        expected_local_revision=delete_conflict.local_revision,
    )
    assert engine_b.run_once().conflict_count == 0
    assert engine_a.run_once().phase is SyncPhase.SYNCED
    assert games_a.count_games() == 0

    games_a.close()
    games_b.close()


def test_guest_response_loss_reuses_batch_id_and_never_sends_note(tmp_path: Path):
    profile, games = prepare_guest(tmp_path)
    games.insert_game(sample("절대 전송 금지"))
    clock = Clock()
    transport = GuestTransport(drop_once=True)
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
    assert len(transport.batches) == 1
    games.close()


def test_missing_remote_config_keeps_local_record_pending(tmp_path: Path):
    profile, games = prepare_guest(tmp_path)
    games.insert_game(sample())

    status = SyncEngine(profile).run_once()

    assert status.phase is SyncPhase.OFFLINE
    assert status.pending_count == 1
    assert games.count_games() == 1
    games.close()


def test_registered_429_is_retryable_and_honors_retry_after(tmp_path: Path):
    """P1-1: 등록 계정 429는 영구 실패가 아니라 rate-limited backoff로 재시도된다."""
    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    clock = Clock()
    transport = RegisteredTransport()
    transport.rate_limit_first_request = 60
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
        now=clock,
    )

    first = engine.run_once()
    assert first.phase is SyncPhase.OFFLINE
    assert first.pending_count == 1

    connection = db.connect(profile.database_path)
    try:
        row = connection.execute(
            "SELECT next_retry_at, last_error_code FROM sync_outbox WHERE id="
            "(SELECT MAX(id) FROM sync_outbox)"
        ).fetchone()
        assert row["next_retry_at"] != "9999-12-31T23:59:59"
        assert row["last_error_code"] == "rate_limited"
    finally:
        connection.close()

    # retry_after(60초)가 지나면 다시 전송된다.
    clock.advance(120)
    second = engine.run_once()
    assert second.phase is SyncPhase.SYNCED
    assert outbox_rows(profile) == []
    games.close()


def test_initial_sync_completed_not_downgraded_by_exact_batch(tmp_path: Path):
    """P1-4: 이미 완료된 initial sync가 정확히 100건 batch에서 0으로 되돌아가지 않는다."""
    transport = RegisteredTransport()
    for index in range(5):
        transport._apply(
            {
                "op": "create",
                "id": f"00000000-0000-4000-8000-{index:012d}",
                "payload": {
                    "played_at": "2026-08-07T10:00:00",
                    "result": "win",
                    "turn_order": "first",
                    "my_deck": "테스트 덱",
                    "opp_deck": "상대 덱",
                    "turns": 4,
                    "end_reason": "regular",
                    "score_after": 1500,
                    "note": str(index),
                    "timezone_offset_minutes": 540,
                },
            }
        )
    profile, games = prepare_registered(tmp_path)
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))
    engine = SyncEngine(
        profile, registered_client=client, token_provider=lambda: "token"
    )

    first = engine.run_once()
    assert first.initial_sync_completed is True

    # initial sync 완료 후 정확히 BATCH_SIZE(100)건짜리 pull batch가 오면
    # initial_sync_completed가 0으로 되돌려지면 안 된다(P1-4).
    connection = db.connect(profile.database_path)
    try:
        connection.execute("UPDATE sync_state SET initial_sync_completed=1 WHERE id=1")
    finally:
        connection.close()
    for index in range(5, 105):
        transport._apply(
            {
                "op": "create",
                "id": f"00000000-0000-4000-8000-{index:012d}",
                "payload": {
                    "played_at": "2026-08-07T10:00:00",
                    "result": "win",
                    "turn_order": "first",
                    "my_deck": "테스트 덱",
                    "opp_deck": "상대 덱",
                    "turns": 4,
                    "end_reason": "regular",
                    "score_after": 1500,
                    "note": str(index),
                    "timezone_offset_minutes": 540,
                },
            }
        )
    second = engine.run_once()
    assert second.initial_sync_completed is True
    assert second.last_pulled_version == 105
    games.close()


def conflicted_engine(tmp_path: Path):
    profile, games = prepare_registered(tmp_path)
    transport = RegisteredTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
    )
    game_id = games.insert_game(sample("기준"))
    engine.run_once()
    row = games.get_game(game_id)
    assert row is not None
    sync_id = row["sync_id"]
    transport._apply(
        {
            "op": "update",
            "id": sync_id,
            "expected_change_version": 1,
            "payload": sample("서버 수정"),
        }
    )
    games.update_game(game_id, sample("로컬 수정"))
    engine.run_once()
    return profile, games, transport, engine, game_id


def test_resolution_fetches_fresh_server_and_refuses_newer_payload(tmp_path: Path):
    profile, games, transport, engine, game_id = conflicted_engine(tmp_path)
    old = engine.list_conflicts()[0]
    transport._apply(
        {
            "op": "update",
            "id": old.game_sync_id,
            "expected_change_version": 2,
            "payload": sample("새 서버 수정"),
        }
    )
    with pytest.raises(StaleConflictError):
        engine.resolve_conflict(
            old.id,
            "remote",
            expected_remote_version=2,
            expected_local_revision=old.local_revision,
        )
    latest = engine.list_conflicts()[0]
    assert latest.remote_payload["change_version"] == 3
    assert games.get_game(game_id)["note"] == "로컬 수정"
    assert engine.status().last_pulled_version == 2
    assert len(outbox_rows(profile)) == 1
    assert parse_qs(urlsplit(transport.requests[-1]["url"]).query)["id"] == [
        f"eq.{old.game_sync_id}"
    ]
    games.close()


def test_resolution_offline_keeps_outbox_conflict_and_draft(tmp_path: Path):
    profile, games, transport, engine, game_id = conflicted_engine(tmp_path)
    conflict = engine.list_conflicts()[0]
    original = [dict(row) for row in outbox_rows(profile)]
    draft = sample("작성 중인 병합 초안")

    def fail():
        raise NetworkError("오프라인")

    transport.on_fetch = fail
    with pytest.raises(RegisteredGamesError):
        engine.resolve_conflict(
            conflict.id,
            "merged",
            draft,
            expected_remote_version=2,
            expected_local_revision=conflict.local_revision,
        )
    assert [dict(row) for row in outbox_rows(profile)] == original
    assert draft["note"] == "작성 중인 병합 초안"
    assert engine.list_conflicts()[0] == conflict
    assert games.get_game(game_id)["note"] == "로컬 수정"
    games.close()


def test_local_edit_during_fresh_fetch_is_not_overwritten(tmp_path: Path):
    _, games, transport, engine, game_id = conflicted_engine(tmp_path)
    conflict = engine.list_conflicts()[0]
    transport.on_fetch = lambda: games.update_game(game_id, sample("확인 도중 새 수정"))
    with pytest.raises(StaleConflictError):
        engine.resolve_conflict(
            conflict.id,
            "remote",
            expected_remote_version=2,
            expected_local_revision=conflict.local_revision,
        )
    assert games.get_game(game_id)["note"] == "확인 도중 새 수정"
    games.close()


def test_server_change_after_resolution_fetch_is_guarded_by_existing_cas(
    tmp_path: Path,
):
    _, games, transport, engine, game_id = conflicted_engine(tmp_path)
    conflict = engine.list_conflicts()[0]
    engine.resolve_conflict(
        conflict.id,
        "local",
        expected_remote_version=2,
        expected_local_revision=conflict.local_revision,
    )
    transport._apply(
        {
            "op": "update",
            "id": conflict.game_sync_id,
            "expected_change_version": 2,
            "payload": sample("확인 이후 서버 수정"),
        }
    )
    status = engine.run_once()
    assert status.conflict_count == 1
    assert games.get_game(game_id)["note"] == "로컬 수정"
    assert engine.list_conflicts()[0].remote_payload["note"] == "확인 이후 서버 수정"
    games.close()


@pytest.mark.parametrize("resolution", ["remote", "local"])
def test_missing_remote_conflict_can_be_resolved_after_verified_absence(
    tmp_path: Path, resolution: str
):
    profile, games, transport, engine, game_id = conflicted_engine(tmp_path)
    conflict = engine.list_conflicts()[0]
    transport.remote_games.clear()
    with pytest.raises(StaleConflictError):
        engine.resolve_conflict(
            conflict.id,
            resolution,
            expected_remote_version=2,
            expected_local_revision=conflict.local_revision,
        )
    missing = engine.list_conflicts()[0]
    assert missing.remote_payload["missing"] is True
    engine.resolve_conflict(
        missing.id, resolution, expected_local_revision=missing.local_revision
    )
    assert engine.list_conflicts() == []
    if resolution == "remote":
        assert games.count_games() == 0
        assert outbox_rows(profile) == []
    else:
        assert engine.run_once().phase is SyncPhase.SYNCED
        assert transport.remote_games[missing.game_sync_id]["note"] == "로컬 수정"
    games.close()


def test_engine_recovers_after_401_and_temporary_refresh_failure(tmp_path: Path):
    from test_session_manager import FakeAccountService, make_session

    from mdlogger.auth.credential_store import InMemoryCredentialStore
    from mdlogger.auth.models import AuthError, AuthErrorKind
    from mdlogger.auth.session_manager import SessionManager

    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    ids = [row["id"] for row in outbox_rows(profile)]
    clock = [0.0]
    service = FakeAccountService()
    manager = SessionManager(
        service, InMemoryCredentialStore(), now=lambda: clock[0], jitter=lambda _: 0
    )
    manager.activate(make_session())
    transport = RegisteredTransport()
    transport.reject_first_request = True
    service.refresh_result = AuthError(AuthErrorKind.NETWORK, "일시적인 연결 실패")
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=manager,
    )
    assert engine.run_once().phase is SyncPhase.OFFLINE
    assert [row["id"] for row in outbox_rows(profile)] == ids
    assert outbox_rows(profile)[0]["attempt_count"] == 0
    service.refresh_result = make_session("refresh-2")
    assert engine.run_once().phase is SyncPhase.OFFLINE
    assert len(service.refresh_calls) == 1
    clock[0] = 3
    assert engine.run_once().phase is SyncPhase.SYNCED
    assert outbox_rows(profile) == []
    games.close()


def test_online_gate_prevents_refresh_and_network(tmp_path: Path):
    from test_session_manager import FakeAccountService, make_session

    from mdlogger.auth.credential_store import InMemoryCredentialStore
    from mdlogger.auth.session_manager import SessionManager

    profile, games = prepare_registered(tmp_path)
    service = FakeAccountService()
    manager = SessionManager(service, InMemoryCredentialStore())
    manager.activate(make_session())
    transport = RegisteredTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=manager,
        can_sync=lambda: False,
    )
    assert engine.run_once().phase is SyncPhase.OFFLINE
    assert service.refresh_calls == []
    assert transport.requests == []
    games.close()


def test_offline_start_reconnects_without_access_token(tmp_path: Path):
    from test_session_manager import FakeAccountService, make_session

    from mdlogger.auth.credential_store import InMemoryCredentialStore
    from mdlogger.auth.models import AuthError, AuthErrorKind
    from mdlogger.auth.session_manager import SessionManager

    profile, games = prepare_registered(tmp_path)
    games.insert_game(sample())
    clock = [0.0]
    service = FakeAccountService()
    service.refresh_result = AuthError(AuthErrorKind.NETWORK, "오프라인 시작")
    store = InMemoryCredentialStore()
    store.save_refresh_token(ACCOUNT_ID, "refresh-1")
    manager = SessionManager(service, store, now=lambda: clock[0], jitter=lambda _: 0)
    manager.restore(ACCOUNT_ID)
    transport = RegisteredTransport()
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=manager,
    )
    assert engine.run_once().phase is SyncPhase.OFFLINE
    assert transport.requests == []
    service.refresh_result = make_session("refresh-2")
    clock[0] = 3
    assert engine.run_once().phase is SyncPhase.SYNCED
    assert outbox_rows(profile) == []
    games.close()


@pytest.mark.parametrize("revoked", [False, True])
def test_resolution_distinguishes_refresh_outage_and_revoked_session(
    tmp_path: Path, revoked: bool
):
    from test_session_manager import FakeAccountService, make_session

    from mdlogger.auth.credential_store import InMemoryCredentialStore
    from mdlogger.auth.models import AuthError, AuthErrorKind
    from mdlogger.auth.session_manager import SessionManager
    from mdlogger.remote.games import RegisteredGamesErrorKind

    profile, games, transport, previous, _ = conflicted_engine(tmp_path)
    conflict = previous.list_conflicts()[0]
    service = FakeAccountService()
    service.refresh_result = AuthError(
        AuthErrorKind.TOKEN_EXPIRED if revoked else AuthErrorKind.NETWORK, "갱신 실패"
    )
    manager = SessionManager(service, InMemoryCredentialStore())
    manager.activate(make_session())
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        session_manager=manager,
    )
    transport.reject_first_request = True
    with pytest.raises(RegisteredGamesError) as error:
        engine.resolve_conflict(
            conflict.id,
            "remote",
            expected_remote_version=2,
            expected_local_revision=conflict.local_revision,
        )
    assert error.value.kind is (
        RegisteredGamesErrorKind.AUTH_REQUIRED
        if revoked
        else RegisteredGamesErrorKind.NETWORK
    )
    assert engine.list_conflicts() == [conflict]
    games.close()


def test_online_permission_revoked_during_fresh_fetch_preserves_conflict(
    tmp_path: Path,
):
    profile, games, transport, previous, game_id = conflicted_engine(tmp_path)
    conflict = previous.list_conflicts()[0]
    allowed = [True]
    engine = SyncEngine(
        profile,
        registered_client=RegisteredGamesClient(
            CONFIG, client=JsonHttpClient(transport)
        ),
        token_provider=lambda: "token",
        can_sync=lambda: allowed[0],
    )
    transport.on_fetch = lambda: allowed.__setitem__(0, False)
    with pytest.raises(RegisteredGamesError):
        engine.resolve_conflict(
            conflict.id,
            "remote",
            expected_remote_version=2,
            expected_local_revision=conflict.local_revision,
        )
    assert engine.list_conflicts() == [conflict]
    assert games.get_game(game_id)["note"] == "로컬 수정"
    games.close()


@pytest.mark.parametrize(
    ("resolution", "selected_note", "accept_convergence"),
    [
        ("local", None, True),
        ("remote", None, False),
        ("merged", "로컬 수정", True),
        ("merged", "서버 수정", False),
        ("merged", "새 병합 메모", False),
    ],
)
def test_fresh_convergence_respects_selected_payload_and_requires_reconfirmation(
    tmp_path: Path,
    resolution: str,
    selected_note: str | None,
    accept_convergence: bool,
):
    profile, games, transport, engine, game_id = conflicted_engine(tmp_path)
    conflict = engine.list_conflicts()[0]
    pending_before = [dict(row) for row in outbox_rows(profile)]
    local_before = games.get_game(game_id)
    assert local_before is not None
    draft = {"note": selected_note} if resolution == "merged" else None
    original_draft = dict(draft) if draft is not None else None
    transport._apply(
        {
            "op": "update",
            "id": conflict.game_sync_id,
            "expected_change_version": 2,
            "payload": sample("로컬 수정"),
        }
    )
    if accept_convergence:
        engine.resolve_conflict(
            conflict.id,
            resolution,
            draft,
            expected_remote_version=2,
            expected_local_revision=conflict.local_revision,
        )
        assert engine.list_conflicts() == []
        assert outbox_rows(profile) == []
        assert games.get_game(game_id)["remote_version"] == 3
    else:
        with pytest.raises(StaleConflictError, match="최신 내용을 확인"):
            engine.resolve_conflict(
                conflict.id,
                resolution,
                draft,
                expected_remote_version=2,
                expected_local_revision=conflict.local_revision,
            )
        latest = engine.list_conflicts()[0]
        assert latest.id == conflict.id
        assert latest.local_revision == conflict.local_revision
        assert latest.remote_payload["change_version"] == 3
        assert latest.remote_payload["note"] == "로컬 수정"
        assert [dict(row) for row in outbox_rows(profile)] == pending_before
        assert (
            games.get_game(game_id)["remote_version"] == local_before["remote_version"]
        )
        assert engine.status().phase is SyncPhase.FAILED
        assert engine.status().conflict_count == 1
    assert draft == original_draft
    assert games.get_game(game_id)["note"] == "로컬 수정"
    assert engine.status().last_pulled_version == 2

    if accept_convergence:
        assert engine.run_once().last_pulled_version == 3
    else:
        # 새 비교 화면에서 이전 선택을 명시적으로 재확인한 뒤에만 반영한다.
        intended_note = (
            conflict.remote_payload["note"] if resolution == "remote" else selected_note
        )
        latest = engine.list_conflicts()[0]
        engine.resolve_conflict(
            latest.id,
            "merged",
            {"note": intended_note},
            expected_remote_version=3,
            expected_local_revision=latest.local_revision,
        )
        assert engine.list_conflicts() == []
        assert len(outbox_rows(profile)) == 1
        assert games.get_game(game_id)["note"] == intended_note
        assert games.get_game(game_id)["remote_version"] == 3
        assert engine.status().last_pulled_version == 2
        assert engine.run_once().last_pulled_version == 4
        assert transport.remote_games[conflict.game_sync_id]["note"] == intended_note
        assert outbox_rows(profile) == []
    games.close()
