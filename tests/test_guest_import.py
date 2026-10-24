"""게스트 DB에서 등록 계정 DB로의 비파괴 import 테스트."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mdlogger import db
from mdlogger.guest_import import (
    GuestImportError,
    GuestImportResult,
    import_guest_records,
)
from mdlogger.profiles import ProfileKind

PLAYED_AT = "2026-06-19T10:00:00"


def _make_guest_db(path: Path, count: int = 3) -> list[str]:
    """게스트 스키마 DB를 만들고 count건을 넣어 sync_id를 반환한다."""
    conn = db.connect(path)
    db.init_db(conn)
    sync_ids = []
    for index in range(count):
        game_id = db.insert_game(
            conn,
            {
                "played_at": f"2026-06-{19 + index:02d}T10:00:00",
                "result": "win" if index % 2 == 0 else "lose",
                "turn_order": "first" if index % 2 == 0 else "second",
                "my_deck": f"덱{index}",
                "opp_deck": f"상대{index}",
                "turns": 4 + index,
                "end_reason": "regular",
                "standing_kind": "event_points",
                "play_context_id": "dc_cup_2026_08",
                "event_points_before": 0,
                "event_points_after": 1600 + index,
                "note": f"메모{index}",
            },
        )
        with conn:
            conn.execute(
                "UPDATE games SET environment_version_id=? WHERE id=?",
                (f"env-{index}", game_id),
            )
        sync_ids.append(
            str(
                conn.execute(
                    "SELECT sync_id FROM games WHERE id=?", (game_id,)
                ).fetchone()[0]
            )
        )
    conn.close()
    return sync_ids


def _target_rows(target: Path) -> list[sqlite3.Row]:
    conn = db.connect(target)
    try:
        return conn.execute(
            "SELECT * FROM games WHERE deleted_at IS NULL ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _outbox_count(target: Path) -> int:
    conn = db.connect(target)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0])
    finally:
        conn.close()


def test_import_preserves_values_order_and_played_at(tmp_path: Path):
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    sync_ids = _make_guest_db(guest, count=3)

    result = import_guest_records(guest, target)

    assert isinstance(result, GuestImportResult)
    assert result.imported_count == 3
    assert result.skipped_count == 0
    assert result.already_imported is False

    rows = _target_rows(target)
    assert [str(row["sync_id"]) for row in rows] == sync_ids
    assert [row["played_at"] for row in rows] == [
        f"2026-06-{19 + i:02d}T10:00:00" for i in range(3)
    ]
    assert [row["note"] for row in rows] == ["메모0", "메모1", "메모2"]
    assert [row["event_points_after"] for row in rows] == [1600, 1601, 1602]
    assert [row["environment_version_id"] for row in rows] == [
        "env-0",
        "env-1",
        "env-2",
    ]
    assert all(row["sync_status"] == "pending" for row in rows)
    assert all(row["deleted_at"] is None for row in rows)
    assert _outbox_count(target) == 3


def test_import_rerun_is_idempotent(tmp_path: Path):
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    _make_guest_db(guest, count=2)

    first = import_guest_records(guest, target)
    second = import_guest_records(guest, target)

    assert first.imported_count == 2
    assert first.already_imported is False
    assert second.imported_count == 0
    assert second.skipped_count == 2
    assert second.already_imported is True
    assert len(_target_rows(target)) == 2
    assert _outbox_count(target) == 2


def test_import_dedups_by_sync_id_when_target_already_has_records(tmp_path: Path):
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    sync_ids = _make_guest_db(guest, count=2)

    # 대상 DB에 이미 첫 번째 sync_id가 존재하는 상황을 만든다.
    conn = db.connect(target)
    db.init_db(conn)
    conn.execute(
        "INSERT INTO games (played_at, result, turn_order, opp_deck, turns,"
        " end_reason, note, sync_id, sync_status)"
        " VALUES (?, 'win', 'first', '기존', 4, 'regular', '기존메모', ?, 'synced')",
        (PLAYED_AT, sync_ids[0]),
    )
    conn.commit()
    conn.close()
    before = len(_target_rows(target))

    result = import_guest_records(guest, target)

    assert result.imported_count == 1
    assert result.skipped_count == 1
    rows = _target_rows(target)
    assert len(rows) == before + 1
    existing = {str(row["sync_id"]) for row in rows}
    assert existing == set(sync_ids)
    imported = next(row for row in rows if row["sync_id"] == sync_ids[1])
    assert imported["note"] == "메모1"


def test_import_preserves_source_unchanged(tmp_path: Path):
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    _make_guest_db(guest, count=3)

    before = _target_rows(guest)
    import_guest_records(guest, target)
    after = _target_rows(guest)

    assert [tuple(row) for row in before] == [tuple(row) for row in after]


def test_import_checksum_mismatch_creates_new_batch(tmp_path: Path):
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    _make_guest_db(guest, count=2)

    first = import_guest_records(guest, target)
    # 게스트에 기록을 추가해 checksum이 달라지게 한다.
    conn = db.connect(guest)
    db.insert_game(
        conn,
        {
            "played_at": "2026-07-01T09:00:00",
            "result": "win",
            "turn_order": "first",
            "opp_deck": "새상대",
            "turns": 3,
            "end_reason": "regular",
            "standing_kind": "event_points",
            "play_context_id": "dc_cup_2026_08",
            "event_points_before": 0,
            "event_points_after": 1900,
            "note": "추가",
        },
    )
    conn.close()

    second = import_guest_records(guest, target)

    assert first.imported_count == 2
    assert second.imported_count == 1
    assert second.skipped_count == 2
    assert second.already_imported is False
    assert len(_target_rows(target)) == 3


def test_import_target_paths_source_profile_kind(tmp_path: Path):
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    _make_guest_db(guest, count=1)

    result = import_guest_records(guest, target, source_profile_kind=ProfileKind.GUEST)
    assert result.imported_count == 1

    conn = db.connect(target)
    try:
        row = conn.execute("SELECT source_profile_kind FROM import_batches").fetchone()
        assert row["source_profile_kind"] == ProfileKind.GUEST.value
    finally:
        conn.close()


def test_import_opens_source_read_only_without_sidecars(tmp_path: Path):
    """읽기 전용 백업은 원본의 DELETE 저널 모드와 기록을 변경하지 않는다."""
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    _make_guest_db(guest, count=2)

    # 원본 journal mode를 DELETE로 강제해두고 import 후에도 유지되는지 본다.
    conn = sqlite3.connect(guest)
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.close()

    import_guest_records(guest, target)

    # db.connect는 WAL을 다시 켜므로 raw read-only 연결로 journal mode를 확인한다.
    conn = sqlite3.connect(f"file:{guest}?mode=ro", uri=True)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode == "delete"
    assert not (guest.with_name(guest.name + "-wal")).exists()
    assert not (guest.with_name(guest.name + "-shm")).exists()


def test_import_owned_wal_source_creates_no_additional_sidecars(tmp_path: Path):
    """소유 연결을 제공하면 원본을 추가로 열거나 사이드카를 추가하지 않는다."""
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    _make_guest_db(guest, count=2)
    conn = sqlite3.connect(guest)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = {path.name for path in tmp_path.glob("guest.db*")}
    try:
        result = import_guest_records(guest, target, source_connection=conn)
        assert result.imported_count == 2
        assert {path.name for path in tmp_path.glob("guest.db*")} == before
        assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 2
    finally:
        conn.close()


def test_import_active_wal_source_preserves_committed_data(tmp_path: Path):
    """커밋됐지만 체크포인트 전인 기록도 스냅숏에 보존한다."""
    guest = tmp_path / "guest.db"
    target = tmp_path / "registered.db"
    _make_guest_db(guest, count=2)
    # insert_game은 커밋하지만 연결을 유지하면 WAL에 기록이 남는다.
    conn = db.connect(guest)
    db.insert_game(
        conn,
        {
            "played_at": "2026-08-07T11:00:00",
            "result": "lose",
            "turn_order": "second",
            "my_deck": "커밋덱",
            "opp_deck": "커밋상대",
            "turns": 3,
            "end_reason": "regular",
            "standing_kind": "event_points",
            "play_context_id": "dc_cup_2026_08",
            "event_points_before": 0,
            "event_points_after": 1400,
            "note": "체크포인트 전 커밋",
        },
    )
    # 연결을 유지한 상태에서 가져온다.
    try:
        result = import_guest_records(guest, target)
    finally:
        conn.close()

    assert result.imported_count == 3
    rows = _target_rows(target)
    assert any(row["note"] == "체크포인트 전 커밋" for row in rows)
    # 마지막 소유 연결을 닫으면 SQLite가 사이드카를 정리한다.
    assert not (guest.with_name(guest.name + "-shm")).exists()
    games = db.connect(guest)
    try:
        count = int(
            games.execute(
                "SELECT COUNT(*) FROM games WHERE deleted_at IS NULL"
            ).fetchone()[0]
        )
    finally:
        games.close()
    assert count == 3


def test_import_pre_v2_source_raises_guest_import_error(tmp_path: Path):
    """P1-8: 구버전(pre-v2) 게스트 DB는 raw sqlite 오류가 아닌 GuestImportError로 감싼다."""
    guest = tmp_path / "pre_v2.db"
    target = tmp_path / "registered.db"
    conn = sqlite3.connect(guest)
    conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(GuestImportError):
        import_guest_records(guest, target)


def test_import_snapshot_survives_checkpoint_between_open_and_backup(
    tmp_path, monkeypatch
):
    from mdlogger import paths

    guest = tmp_path / "게스트#?.db"
    target = tmp_path / "account.db"
    _make_guest_db(guest, count=1)
    writer = db.connect(guest)
    db.insert_game(
        writer,
        {
            "result": "win",
            "turn_order": "first",
            "opp_deck": "상대",
            "turns": 3,
            "end_reason": "regular",
            "standing_kind": "event_points",
            "event_points_after": 1500,
            "note": "WAL 커밋",
        },
    )
    real_connect = sqlite3.connect

    class CheckpointConnection(sqlite3.Connection):
        def backup(self, destination, *args, **kwargs):
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return super().backup(destination, *args, **kwargs)

    def open_with_checkpoint(path, *args, **kwargs):
        if str(path).startswith("file:") and "mode=ro" in str(path):
            kwargs["factory"] = CheckpointConnection
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(paths.sqlite3, "connect", open_with_checkpoint)
    try:
        result = import_guest_records(guest, target)
        assert result.imported_count == 2
        assert len(_target_rows(target)) == 2
        assert db.count_games(writer) == 2
    finally:
        writer.close()


def test_import_corrupt_source_leaves_target_unchanged(tmp_path):
    guest, target = tmp_path / "bad.db", tmp_path / "target.db"
    guest.write_bytes(b"not a database")
    _make_guest_db(target, count=1)
    before = [tuple(row) for row in _target_rows(target)]
    with pytest.raises(GuestImportError):
        import_guest_records(guest, target)
    assert [tuple(row) for row in _target_rows(target)] == before
    assert not list(tmp_path.glob(".mdlogger-import-*"))


def test_import_uses_snapshot_provider_without_opening_source(tmp_path):
    from mdlogger.paths import copy_database_via_backup

    actual, nominal, target = (
        tmp_path / "actual.db",
        tmp_path / "absent.db",
        tmp_path / "target.db",
    )
    _make_guest_db(actual, count=2)
    source = sqlite3.connect(actual)
    calls = []

    def snapshot(destination):
        calls.append(destination)
        copy_database_via_backup(source, destination)

    try:
        result = import_guest_records(nominal, target, snapshot_provider=snapshot)
        assert result.imported_count == 2
        assert len(calls) == 1
        assert not nominal.exists()
        assert not calls[0].exists()
    finally:
        source.close()


def test_import_excludes_uncommitted_rows_without_changing_writer_transaction(tmp_path):
    guest, target = tmp_path / "guest.db", tmp_path / "target.db"
    _make_guest_db(guest, count=1)
    writer = db.connect(guest)
    writer.execute(
        "INSERT INTO games (sync_id, note) VALUES ('uncommitted-id', '미커밋')"
    )
    try:
        result = import_guest_records(guest, target)
        assert result.imported_count == 1
        assert writer.in_transaction
        assert writer.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 2
        assert len(_target_rows(target)) == 1
    finally:
        writer.rollback()
        writer.close()
