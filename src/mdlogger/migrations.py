"""SQLite 로컬 스키마의 순차 migration과 백업 복구를 관리한다."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LATEST_SCHEMA_VERSION = 5

# 마이그레이션 사전 백업 보존 정책(운영 결정, open-items 항목 3): 백업은 내부
# 전용이며, 새 백업을 만들면 이전 백업을 최근 keep개만 남기고 정리한다.
# 사용자에게 별도로 노출하지 않고, 실패 시 복구 안내로만 사용한다.
BACKUP_RETENTION = 1


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """migration 실행 결과와 생성된 복구용 백업 경로."""

    from_version: int
    to_version: int
    backup_path: Path | None


class MigrationError(RuntimeError):
    """migration 실패와 복구에 사용할 검증된 백업 정보를 전달한다."""

    def __init__(self, message: str, *, backup_path: Path | None = None) -> None:
        super().__init__(message)
        self.backup_path = backup_path


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _table_names(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name"
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _database_signature(
    conn: sqlite3.Connection,
) -> tuple[int, tuple[str, ...], int | None]:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    tables = _table_names(conn)
    games_count = (
        int(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
        if "games" in tables
        else None
    )
    return version, tables, games_count


def _verify_integrity(conn: sqlite3.Connection) -> None:
    result = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    if result != "ok":
        raise MigrationError(f"SQLite integrity check failed: {result}")


def _database_path(conn: sqlite3.Connection) -> Path | None:
    for _, name, filename in conn.execute("PRAGMA database_list").fetchall():
        if name == "main" and filename:
            return Path(str(filename)).resolve()
    return None


def _create_verified_backup(
    conn: sqlite3.Connection, db_path: Path, from_version: int
) -> Path:
    backup_path = db_path.with_name(f"{db_path.name}.pre-migration-v{from_version}.bak")
    temporary_path = backup_path.with_name(
        f".{backup_path.name}.{uuid.uuid4().hex}.tmp"
    )
    expected_signature = _database_signature(conn)

    try:
        backup_conn = sqlite3.connect(temporary_path)
        try:
            conn.backup(backup_conn)
            _verify_integrity(backup_conn)
            if _database_signature(backup_conn) != expected_signature:
                raise MigrationError(
                    "Migration backup verification did not match the source DB"
                )
        finally:
            backup_conn.close()

        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, backup_path)
        return backup_path
    finally:
        temporary_path.unlink(missing_ok=True)


def _retain_backups(db_path: Path, keep: int = BACKUP_RETENTION) -> None:
    """백업 보존 정책 적용: 이 DB의 마이그레이션 사전 백업을 최근 keep개만 남긴다.

    백업 이름은 버전 키(`<db>.pre-migration-v<version>.bak`)지만 보존 우선순위는
    버전 번호가 아니라 **파일 생성 시각**으로 판단한다. 버전 번호순 정렬은 어떤
    경우에 방금 만든 백업을 지워 `MigrationResult.backup_path`를 죽은 경로로
    만들 수 있어, 최신(가장 방금 생성된) 백업을 항상 보존한다. 다른 DB 파일이나
    실제 DB(`-wal`/`-shm`)는 건드리지 않는다.
    """
    pattern = re.compile(rf"^{re.escape(db_path.name)}\.pre-migration-v(\d+)\.bak$")
    backups: list[Path] = []
    for path in db_path.parent.glob("*.bak"):
        if pattern.match(path.name):
            backups.append(path)
    backups.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in backups[keep:]:
        path.unlink(missing_ok=True)


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split(maxsplit=1)[0]
    if name not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _migration_1(conn: sqlite3.Connection) -> None:
    """기존 games 스키마를 단계 1 baseline으로 맞춘다."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            id          INTEGER PRIMARY KEY,
            played_at   TEXT,
            result      TEXT,
            turn_order  TEXT,
            my_deck     TEXT,
            opp_deck    TEXT,
            turns       INTEGER,
            end_reason  TEXT,
            score_after INTEGER,
            note        TEXT
        )
        """
    )
    _add_column(conn, "games", "my_deck TEXT")


def _game_payload(row: sqlite3.Row) -> str:
    return json.dumps(dict(row), ensure_ascii=False, separators=(",", ":"))


def _migration_2(conn: sqlite3.Connection) -> None:
    """동기화 준비용 games 필드와 로컬 metadata/outbox 테이블을 추가한다."""
    game_columns = (
        "sync_id TEXT",
        "play_context_id TEXT",
        "standing_kind TEXT",
        "rank_tier_before TEXT",
        "rank_tier_after TEXT",
        "rank_division_before INTEGER",
        "rank_division_after INTEGER",
        "rating_before INTEGER",
        "rating_after INTEGER",
        "event_points_before INTEGER",
        "event_points_after INTEGER",
        "local_updated_at TEXT",
        "remote_version INTEGER",
        "sync_status TEXT",
        "deleted_at TEXT",
        "last_sync_error TEXT",
        "import_batch_id TEXT",
    )
    for definition in game_columns:
        _add_column(conn, "games", definition)

    table_statements = (
        """
        CREATE TABLE IF NOT EXISTS database_metadata (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version INTEGER NOT NULL,
            owner_id TEXT,
            profile_kind TEXT,
            created_at TEXT NOT NULL,
            last_opened_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            remote_user_id TEXT,
            last_pulled_version INTEGER NOT NULL DEFAULT 0,
            last_successful_sync_at TEXT,
            initial_sync_completed INTEGER NOT NULL DEFAULT 0,
            last_server_schema_version INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sync_outbox (
            id INTEGER PRIMARY KEY,
            game_sync_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            payload_version INTEGER NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT,
            last_error_code TEXT,
            last_error_detail TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sync_conflicts (
            id INTEGER PRIMARY KEY,
            game_sync_id TEXT NOT NULL,
            local_payload TEXT NOT NULL,
            remote_payload TEXT NOT NULL,
            base_remote_version INTEGER,
            detected_at TEXT NOT NULL,
            resolution TEXT,
            resolved_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS import_batches (
            id TEXT PRIMARY KEY,
            archive_id TEXT NOT NULL,
            archive_checksum TEXT NOT NULL,
            source_profile_kind TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            imported_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0
        )
        """,
    )
    for statement in table_statements:
        conn.execute(statement)

    migrated_at = _now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO database_metadata
            (id, schema_version, owner_id, profile_kind, created_at, last_opened_at)
        VALUES (1, ?, NULL, NULL, ?, ?)
        """,
        (LATEST_SCHEMA_VERSION, migrated_at, migrated_at),
    )
    conn.execute("INSERT OR IGNORE INTO sync_state (id) VALUES (1)")

    rows = conn.execute("SELECT * FROM games ORDER BY id").fetchall()
    for row in rows:
        sync_id = row["sync_id"] or str(uuid.uuid4())
        local_updated_at = row["local_updated_at"] or migrated_at
        sync_status = row["sync_status"] or "pending"
        conn.execute(
            """
            UPDATE games
            SET sync_id=?, local_updated_at=?, sync_status=?
            WHERE id=?
            """,
            (sync_id, local_updated_at, sync_status, row["id"]),
        )

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_games_sync_id ON games(sync_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_outbox_retry"
        " ON sync_outbox(next_retry_at, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_conflicts_game"
        " ON sync_conflicts(game_sync_id, resolved_at)"
    )

    pending_rows = conn.execute(
        """
        SELECT * FROM games
        WHERE sync_status = 'pending'
          AND NOT EXISTS (
              SELECT 1 FROM sync_outbox WHERE game_sync_id = games.sync_id
          )
        ORDER BY id
        """
    ).fetchall()
    for row in pending_rows:
        conn.execute(
            """
            INSERT INTO sync_outbox
                (game_sync_id, operation, payload_version, payload, created_at)
            VALUES (?, 'upsert', 1, ?, ?)
            """,
            (row["sync_id"], _game_payload(row), migrated_at),
        )


def _migration_3(conn: sqlite3.Connection) -> None:
    """신규 분석 observation에 기록 시점 UTC offset을 보존한다."""
    _add_column(conn, "games", "timezone_offset_minutes INTEGER")


def _migration_4(conn: sqlite3.Connection) -> None:
    """단계 8의 3-way merge를 위한 마지막 서버 payload를 보존한다."""
    _add_column(conn, "games", "base_remote_payload TEXT")


def _migration_5(conn: sqlite3.Connection) -> None:
    """하드닝 H4: 신규 기록의 월별 환경 version을 보존한다.

    기존 행은 추측하지 않고 NULL로 유지한다(로드맵 7.6). 오프라인이거나
    환경을 모르는 신규 기록도 NULL로 저장되고 소급 부여하지 않는다.
    """
    _add_column(conn, "games", "environment_version_id TEXT")


Migration = Callable[[sqlite3.Connection], None]
MIGRATIONS: dict[int, Migration] = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,
    4: _migration_4,
    5: _migration_5,
}


def migrate(conn: sqlite3.Connection) -> MigrationResult:
    """DB를 최신 버전으로 올리고 실패 시 원본 트랜잭션을 복구한다."""
    _verify_integrity(conn)
    from_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if from_version > LATEST_SCHEMA_VERSION:
        raise MigrationError(
            f"DB schema version {from_version} is newer than supported version "
            f"{LATEST_SCHEMA_VERSION}"
        )
    if from_version == LATEST_SCHEMA_VERSION:
        return MigrationResult(from_version, from_version, None)

    db_path = _database_path(conn)
    backup_path = None
    if db_path is not None and _table_names(conn):
        backup_path = _create_verified_backup(conn, db_path, from_version)
        _retain_backups(db_path)

    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        for version in range(from_version + 1, LATEST_SCHEMA_VERSION + 1):
            migration = MIGRATIONS[version]
            migration(conn)
            conn.execute(f"PRAGMA user_version = {version}")
        conn.execute(
            "UPDATE database_metadata SET schema_version=? WHERE id=1",
            (LATEST_SCHEMA_VERSION,),
        )
        conn.commit()
    except Exception as error:
        conn.rollback()
        try:
            _verify_integrity(conn)
        except MigrationError as integrity_error:
            raise MigrationError(
                "Migration failed and rollback integrity verification failed",
                backup_path=backup_path,
            ) from integrity_error
        raise MigrationError(
            "Migration failed; the transaction was rolled back",
            backup_path=backup_path,
        ) from error
    finally:
        conn.row_factory = original_row_factory

    return MigrationResult(from_version, LATEST_SCHEMA_VERSION, backup_path)


def restore_backup(db_path: Path, backup_path: Path) -> None:
    """검증된 백업을 닫힌 DB 경로에 원자적으로 복원한다.

    손상·누락된 백업은 raw ``sqlite3.DatabaseError`` 대신 ``MigrationError``로
    감싼다(호출자가 복구 안내를 일관되게 처리). 파일 URI는 ``Path.as_uri()``로
    조립해 특수 문자(``#``, ``?`` 등)가 있는 경로도 안전하게 열린다.
    """
    try:
        backup_conn = sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True)
        try:
            _verify_integrity(backup_conn)
        finally:
            backup_conn.close()
    except sqlite3.Error as error:
        raise MigrationError(
            "백업이 손상되었거나 열 수 없습니다.", backup_path=backup_path
        ) from error

    temporary_path = db_path.with_name(f".{db_path.name}.{uuid.uuid4().hex}.restore")
    try:
        shutil.copy2(backup_path, temporary_path)
        restored_conn = sqlite3.connect(temporary_path)
        try:
            _verify_integrity(restored_conn)
        finally:
            restored_conn.close()
        for suffix in ("-wal", "-shm"):
            db_path.with_name(f"{db_path.name}{suffix}").unlink(missing_ok=True)
        os.replace(temporary_path, db_path)
        if os.name != "nt":
            db_path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)
