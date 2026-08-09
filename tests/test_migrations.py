"""정식 로컬 SQLite migration과 복구 정책 테스트."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from mdlogger import db, migrations

PLAYED_AT = "2026-06-19T10:00:00"
LATEST_TABLES = {
    "database_metadata",
    "games",
    "import_batches",
    "sync_conflicts",
    "sync_outbox",
    "sync_state",
}
SYNC_COLUMNS = {
    "sync_id",
    "play_context_id",
    "standing_kind",
    "rank_tier_before",
    "rank_tier_after",
    "rank_division_before",
    "rank_division_after",
    "rating_before",
    "rating_after",
    "event_points_before",
    "event_points_after",
    "local_updated_at",
    "remote_version",
    "sync_status",
    "deleted_at",
    "last_sync_error",
    "import_batch_id",
    "base_remote_payload",
}


def _version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _create_old_db(path: Path, *, with_my_deck: bool) -> sqlite3.Connection:
    conn = db.connect(path)
    my_deck_column = ", my_deck TEXT" if with_my_deck else ""
    conn.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, played_at TEXT, result TEXT,"
        f" turn_order TEXT{my_deck_column}, opp_deck TEXT, turns INTEGER,"
        " end_reason TEXT, score_after INTEGER, note TEXT)"
    )
    columns = "played_at, result, turn_order, "
    values = f"'{PLAYED_AT}', 'win', 'first', "
    if with_my_deck:
        columns += "my_deck, "
        values += "'스네이크아이', "
    conn.execute(
        f"INSERT INTO games ({columns}opp_deck, turns, end_reason, score_after, note)"
        f" VALUES ({values}'블루아이즈', 5, 'regular', 2600, '원본 메모')"
    )
    conn.commit()
    return conn


@pytest.mark.parametrize("with_my_deck", [False, True])
def test_supported_old_databases_migrate_without_data_loss(
    tmp_path: Path, with_my_deck: bool
):
    conn = _create_old_db(tmp_path / "games.db", with_my_deck=with_my_deck)

    result = db.init_db(conn)

    assert result.from_version == 0
    assert result.to_version == migrations.LATEST_SCHEMA_VERSION
    assert result.backup_path is not None and result.backup_path.exists()
    if os.name != "nt":
        assert result.backup_path.stat().st_mode & 0o777 == 0o600
    assert _version(conn) == migrations.LATEST_SCHEMA_VERSION
    assert _tables(conn) == LATEST_TABLES
    assert SYNC_COLUMNS <= _columns(conn, "games")
    row = conn.execute("SELECT * FROM games").fetchone()
    assert row["played_at"] == PLAYED_AT
    assert row["score_after"] == 2600
    assert row["note"] == "원본 메모"
    assert row["my_deck"] == ("스네이크아이" if with_my_deck else None)
    assert row["sync_id"]
    assert row["play_context_id"] is None
    assert row["event_points_after"] is None
    assert row["sync_status"] == "pending"
    assert conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 1


@pytest.mark.parametrize("database", [":memory:", "file"])
def test_empty_database_migrates_to_latest(tmp_path: Path, database: str):
    path: Path | str = ":memory:" if database == ":memory:" else tmp_path / "empty.db"
    conn = db.connect(path)

    result = db.init_db(conn)

    assert _version(conn) == migrations.LATEST_SCHEMA_VERSION
    assert _tables(conn) == LATEST_TABLES
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
    assert result.backup_path is None


def test_migration_rerun_is_idempotent_and_keeps_uuid(tmp_path: Path):
    conn = _create_old_db(tmp_path / "games.db", with_my_deck=True)
    first = db.init_db(conn)
    before = conn.execute(
        "SELECT sync_id, played_at, local_updated_at FROM games"
    ).fetchone()
    outbox_before = conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]
    metadata_before = tuple(conn.execute("SELECT * FROM database_metadata").fetchone())

    second = db.init_db(conn)

    after = conn.execute(
        "SELECT sync_id, played_at, local_updated_at FROM games"
    ).fetchone()
    assert tuple(after) == tuple(before)
    assert (
        conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == outbox_before
    )
    assert tuple(conn.execute("SELECT * FROM database_metadata").fetchone()) == (
        metadata_before
    )
    assert first.backup_path is not None
    assert second.backup_path is None
    assert second.from_version == second.to_version == migrations.LATEST_SCHEMA_VERSION


def test_failed_migration_rolls_back_and_verified_backup_restores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    db_path = tmp_path / "games.db"
    conn = _create_old_db(db_path, with_my_deck=True)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()

    def fail_after_change(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE games ADD COLUMN should_rollback TEXT")
        connection.execute("UPDATE games SET played_at='changed'")
        raise RuntimeError("injected migration failure")

    monkeypatch.setitem(migrations.MIGRATIONS, 2, fail_after_change)

    with pytest.raises(migrations.MigrationError) as error_info:
        db.init_db(conn)

    error = error_info.value
    assert error.backup_path is not None and error.backup_path.exists()
    assert _version(conn) == 1
    assert "should_rollback" not in _columns(conn, "games")
    assert conn.execute("SELECT played_at FROM games").fetchone()[0] == PLAYED_AT
    conn.close()

    db_path.write_bytes(b"damaged after migration failure")
    migrations.restore_backup(db_path, error.backup_path)
    restored = sqlite3.connect(db_path)
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert _version(restored) == 1
        assert (
            restored.execute("SELECT played_at FROM games").fetchone()[0] == PLAYED_AT
        )
    finally:
        restored.close()


def test_restore_rejects_corrupt_backup(tmp_path: Path):
    db_path = tmp_path / "games.db"
    db_path.write_bytes(b"original")
    backup_path = tmp_path / "corrupt.bak"
    backup_path.write_bytes(b"not sqlite")

    with pytest.raises(sqlite3.DatabaseError):
        migrations.restore_backup(db_path, backup_path)

    assert db_path.read_bytes() == b"original"
