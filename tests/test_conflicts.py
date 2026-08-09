"""단계 8 pull cursor, 3-way merge, tombstone conflict 테스트."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from mdlogger import db
from mdlogger.game_service import GameService
from mdlogger.game_sync.repository import SyncRepository
from mdlogger.profiles import ProfileManager

ACCOUNT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SYNC_ID = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 8, 8, 12, 0, 0)


def remote_game(
    version: int,
    *,
    sync_id: str = SYNC_ID,
    note: str = "기준 메모",
    turns: int = 4,
    deleted_at: str | None = None,
) -> dict:
    return {
        "id": sync_id,
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "테스트 덱",
        "opp_deck": "상대 덱",
        "turns": turns,
        "end_reason": "regular",
        "score_after": 1500,
        "note": note,
        "play_context_id": None,
        "standing_kind": None,
        "rank_tier_before": None,
        "rank_tier_after": None,
        "rank_division_before": None,
        "rank_division_after": None,
        "rating_before": None,
        "rating_after": None,
        "event_points_before": None,
        "event_points_after": None,
        "timezone_offset_minutes": 540,
        "deleted_at": deleted_at,
        "change_version": version,
        "payload_version": 1,
        "source_kind": "native",
        "created_at": "2026-08-07T01:00:00+00:00",
        "updated_at": "2026-08-07T01:00:00+00:00",
    }


def local_payload(*, note: str, turns: int = 4) -> dict:
    return {
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "테스트 덱",
        "opp_deck": "상대 덱",
        "turns": turns,
        "end_reason": "regular",
        "score_after": 1500,
        "note": note,
    }


def prepare(tmp_path: Path):
    profiles = ProfileManager(tmp_path)
    profile = profiles.registered(ACCOUNT_ID, "user@example.com")
    profiles.prepare_database(profile)
    repository = SyncRepository.open(profile.database_path)
    games = GameService.open(profile.database_path)
    return profile, repository, games


def test_pull_auto_merges_disjoint_fields_and_rebases_outbox(tmp_path: Path):
    profile, repository, games = prepare(tmp_path)
    repository.apply_pull_batch(
        [remote_game(1)], completed_at=NOW, initial_sync_completed=True
    )
    connection = db.connect(profile.database_path)
    game_id = connection.execute(
        "SELECT id FROM games WHERE sync_id=?", (SYNC_ID,)
    ).fetchone()[0]
    connection.close()
    games.update_game(game_id, local_payload(note="이 장치 메모"))

    cursor = repository.apply_pull_batch(
        [remote_game(2, turns=7)], completed_at=NOW, initial_sync_completed=True
    )

    connection = db.connect(profile.database_path)
    try:
        row = connection.execute(
            "SELECT * FROM games WHERE sync_id=?", (SYNC_ID,)
        ).fetchone()
        outbox = connection.execute(
            "SELECT payload FROM sync_outbox WHERE game_sync_id=? ORDER BY id DESC",
            (SYNC_ID,),
        ).fetchone()
        payload = json.loads(outbox["payload"])
        assert cursor == 2
        assert row["turns"] == 7
        assert row["note"] == "이 장치 메모"
        assert row["remote_version"] == 2
        assert row["sync_status"] == "pending"
        assert payload["turns"] == 7
        assert payload["note"] == "이 장치 메모"
        assert payload["remote_version"] == 2
        assert repository.list_conflicts() == []
    finally:
        connection.close()
        games.close()
        repository.close()


def test_same_field_and_update_delete_conflicts_preserve_both_sides(tmp_path: Path):
    profile, repository, games = prepare(tmp_path)
    repository.apply_pull_batch(
        [remote_game(1)], completed_at=NOW, initial_sync_completed=True
    )
    connection = db.connect(profile.database_path)
    game_id = connection.execute(
        "SELECT id FROM games WHERE sync_id=?", (SYNC_ID,)
    ).fetchone()[0]
    connection.close()
    games.update_game(game_id, local_payload(note="로컬 수정"))

    repository.apply_pull_batch(
        [remote_game(2, note="서버 수정")],
        completed_at=NOW,
        initial_sync_completed=True,
    )

    conflicts = repository.list_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0].local_payload["note"] == "로컬 수정"
    assert conflicts[0].remote_payload["note"] == "서버 수정"
    conflict_status = repository.status()
    assert conflict_status.conflict_count == 1
    assert conflict_status.pending_count == 0
    assert conflict_status.phase.value == "synced"
    assert repository.pull_cursor() == 2

    repository.resolve_conflict(conflicts[0].id, "local")
    connection = db.connect(profile.database_path)
    try:
        row = connection.execute(
            "SELECT * FROM games WHERE sync_id=?", (SYNC_ID,)
        ).fetchone()
        outbox = connection.execute(
            "SELECT operation, payload FROM sync_outbox WHERE game_sync_id=?",
            (SYNC_ID,),
        ).fetchone()
        assert row["note"] == "로컬 수정"
        assert row["remote_version"] == 2
        assert row["sync_status"] == "pending"
        assert outbox["operation"] == "upsert"
        assert json.loads(outbox["payload"])["remote_version"] == 2
        assert repository.status().conflict_count == 0
    finally:
        connection.close()
        games.close()
        repository.close()


def test_remote_tombstone_conflicts_with_local_edit_and_can_be_accepted(
    tmp_path: Path,
):
    profile, repository, games = prepare(tmp_path)
    repository.apply_pull_batch(
        [remote_game(1)], completed_at=NOW, initial_sync_completed=True
    )
    connection = db.connect(profile.database_path)
    game_id = connection.execute(
        "SELECT id FROM games WHERE sync_id=?", (SYNC_ID,)
    ).fetchone()[0]
    connection.close()
    games.update_game(game_id, local_payload(note="삭제와 충돌하는 수정"))

    repository.apply_pull_batch(
        [remote_game(2, deleted_at="2026-08-08T03:00:00+00:00")],
        completed_at=NOW,
        initial_sync_completed=True,
    )
    conflict = repository.list_conflicts()[0]
    repository.resolve_conflict(conflict.id, "remote")

    connection = db.connect(profile.database_path)
    try:
        row = connection.execute(
            "SELECT * FROM games WHERE sync_id=?", (SYNC_ID,)
        ).fetchone()
        assert row["deleted_at"] is not None
        assert row["sync_status"] == "synced"
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sync_outbox WHERE game_sync_id=?", (SYNC_ID,)
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()
        games.close()
        repository.close()


def test_stale_conflict_dialog_cannot_rebase_over_newer_remote_payload(
    tmp_path: Path,
):
    profile, repository, games = prepare(tmp_path)
    repository.apply_pull_batch(
        [remote_game(1)], completed_at=NOW, initial_sync_completed=True
    )
    connection = db.connect(profile.database_path)
    game_id = connection.execute(
        "SELECT id FROM games WHERE sync_id=?", (SYNC_ID,)
    ).fetchone()[0]
    connection.close()
    games.update_game(game_id, local_payload(note="로컬 수정"))
    repository.apply_pull_batch(
        [remote_game(2, note="서버 수정")],
        completed_at=NOW,
        initial_sync_completed=True,
    )
    stale = repository.list_conflicts()[0]
    repository.apply_pull_batch(
        [remote_game(3, note="더 최신 서버 수정")],
        completed_at=NOW,
        initial_sync_completed=True,
    )

    with pytest.raises(ValueError, match="다시 변경"):
        repository.resolve_conflict(
            stale.id,
            "local",
            expected_remote_version=int(stale.remote_payload["change_version"]),
        )

    latest = repository.list_conflicts()[0]
    assert latest.remote_payload["change_version"] == 3
    assert latest.remote_payload["note"] == "더 최신 서버 수정"
    assert repository.status().conflict_count == 1
    games.close()
    repository.close()


def test_pull_batch_failure_rolls_back_rows_and_cursor(tmp_path: Path):
    profile, repository, games = prepare(tmp_path)
    second_id = "22222222-2222-4222-8222-222222222222"

    with pytest.raises(ValueError, match="순서"):
        repository.apply_pull_batch(
            [remote_game(1), remote_game(1, sync_id=second_id)],
            completed_at=NOW,
            initial_sync_completed=False,
        )

    connection = db.connect(profile.database_path)
    try:
        assert repository.pull_cursor() == 0
        assert connection.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
        state = connection.execute(
            "SELECT initial_sync_completed FROM sync_state WHERE id=1"
        ).fetchone()
        assert state[0] == 0
    finally:
        connection.close()
        games.close()
        repository.close()
