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
    "environment_version_id",
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


def test_migration_5_preserves_existing_null_environment(tmp_path: Path):
    """v4 이전 DB를 v5로 올려도 기존 행의 환경은 추측 없이 NULL로 유지된다."""
    conn = db.connect(tmp_path / "games.db")
    conn.execute("PRAGMA user_version = 4")
    conn.execute(
        "CREATE TABLE database_metadata ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " schema_version INTEGER NOT NULL, owner_id TEXT, profile_kind TEXT,"
        " created_at TEXT NOT NULL, last_opened_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO database_metadata (id, schema_version, created_at, last_opened_at)"
        " VALUES (1, 4, '2026-08-01T00:00:00', '2026-08-01T00:00:00')"
    )
    conn.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, played_at TEXT, result TEXT,"
        " turn_order TEXT, opp_deck TEXT, turns INTEGER, end_reason TEXT,"
        " score_after INTEGER, note TEXT, sync_id TEXT, local_updated_at TEXT,"
        " sync_status TEXT, timezone_offset_minutes INTEGER,"
        " base_remote_payload TEXT)"
    )
    conn.execute(
        "INSERT INTO games (played_at, result, turn_order, opp_deck, turns,"
        " end_reason, score_after, note, sync_id, local_updated_at, sync_status)"
        " VALUES ('2026-08-07T10:00:00', 'win', 'first', '블루아이즈', 5,"
        "        'regular', 2600, '', 's1', '2026-08-07T10:00:00', 'synced')"
    )
    conn.commit()

    db.init_db(conn)

    assert _version(conn) == migrations.LATEST_SCHEMA_VERSION
    assert "environment_version_id" in _columns(conn, "games")
    row = conn.execute("SELECT environment_version_id FROM games").fetchone()
    assert row["environment_version_id"] is None
    conn.close()


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

    with pytest.raises(migrations.MigrationError):
        migrations.restore_backup(db_path, backup_path)

    assert db_path.read_bytes() == b"original"


def test_retain_backups_keeps_only_latest(tmp_path: Path):
    """운영 결정: 마이그레이션 사전 백업은 최근 1개만 남기고 정리한다."""
    db_path = tmp_path / "games.db"
    oldest = tmp_path / "games.db.pre-migration-v1.bak"
    middle = tmp_path / "games.db.pre-migration-v2.bak"
    latest = tmp_path / "games.db.pre-migration-v3.bak"
    oldest.write_bytes(b"old1")
    middle.write_bytes(b"old2")
    latest.write_bytes(b"new")
    # 생성 시각으로 최근을 판단하도록 mtime을 명시적으로 다르게 설정한다.
    os.utime(oldest, (1_000, 1_000))
    os.utime(middle, (2_000, 2_000))
    os.utime(latest, (3_000, 3_000))
    # 다른 DB의 백업과 임시 파일은 절대 건드리지 않아야 한다.
    (tmp_path / "accounts.db.pre-migration-v7.bak").write_bytes(b"other-db")
    (tmp_path / "games.db.pre-migration-v9.bak.tmp").write_bytes(b"tmp")

    migrations._retain_backups(db_path)

    assert latest.exists()
    assert latest.read_bytes() == b"new"
    assert not oldest.exists()
    assert not middle.exists()
    assert (tmp_path / "accounts.db.pre-migration-v7.bak").exists()
    assert (tmp_path / "games.db.pre-migration-v9.bak.tmp").exists()


def test_retain_backups_keeps_most_recently_created_not_highest_version(tmp_path: Path):
    """P2-2: 버전 번호가 아니라 생성 시각 기준으로 최근 백업을 보존한다.

    방금 만든 백업이 과거의 더 높은 버전 번호 백업보다 오래된 권한·시각으로
    정렬되지 않도록, 가장 최근에 생성된 백업을 항상 남긴다. 이로써
    ``MigrationResult.backup_path``가 죽은 경로가 되는 경우를 막는다.
    """
    db_path = tmp_path / "games.db"
    stale_higher = tmp_path / "games.db.pre-migration-v9.bak"
    fresh = tmp_path / "games.db.pre-migration-v3.bak"
    stale_higher.write_bytes(b"stale-higher")
    fresh.write_bytes(b"fresh")
    # fresh가 stale_higher보다 나중에 생성되도록 mtime을 조정한다.
    os.utime(stale_higher, (1_000, 1_000))
    os.utime(fresh, (2_000, 2_000))

    migrations._retain_backups(db_path)

    assert fresh.exists()
    assert not stale_higher.exists()
