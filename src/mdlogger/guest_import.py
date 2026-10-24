"""게스트 DB 기록을 등록 계정 로컬 DB로 비파괴 import한다.

게스트가 신규 회원가입하거나 기존 계정으로 로그인할 때, 현재 게스트 DB의 기록을
등록 계정 DB에 옮기고 private games 동기화 outbox에 등록한다. 원본 게스트 DB는
수정하거나 삭제하지 않는다(SQLite Online Backup으로 일관된 스냅숏 사용).

재실행 안전성:
- 같은 게스트 DB(안정 checksum)를 대상 계정에 이미 완료한 import가 있으면 다시
  import하지 않는다(``import_batches`` 완료 marker 기준).
- ``sync_id`` 가 대상 DB에 이미 있으면 중복 생성하지 않는다(분석 observation 중복 방지).
- 하나의 SQLite transaction으로 처리하므로 중간 종료 시 전체 rollback되고 안전하게
  재개할 수 있다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import db
from .paths import copy_database_via_backup
from .profiles import ProfileKind

# import 시 대상 games에 보존하는 값 필드(서버 private payload + 기록 생성 시각).
_IMPORTED_VALUE_FIELDS = (
    "played_at",
    "result",
    "turn_order",
    "my_deck",
    "opp_deck",
    "turns",
    "end_reason",
    "note",
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
    "timezone_offset_minutes",
    "environment_version_id",
)


@dataclass(frozen=True, slots=True)
class GuestImportResult:
    """게스트 기록 import 결과와 재실행 여부."""

    source_path: Path
    target_path: Path
    imported_count: int
    skipped_count: int
    failed_count: int
    already_imported: bool

    @property
    def total(self) -> int:
        return self.imported_count + self.skipped_count


class GuestImportError(RuntimeError):
    """게스트 기록 import를 완료하지 못했을 때 발생한다."""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _core_fields_signature(conn: sqlite3.Connection) -> str:
    """기록 수와 핵심 필드 순서를 포함하는 안정 checksum."""
    rows = conn.execute(
        "SELECT played_at, result, turn_order, my_deck, opp_deck, turns,"
        " end_reason, note, sync_id"
        " FROM games WHERE deleted_at IS NULL ORDER BY id"
    ).fetchall()
    digest = hashlib.sha256()
    for row in rows:
        for value in row:
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\x00")
    return digest.hexdigest()


def _completed_batch_matches(
    conn: sqlite3.Connection,
    source_profile_kind: ProfileKind,
    checksum: str,
    expected_count: int,
) -> bool:
    row = conn.execute(
        """
        SELECT imported_count, skipped_count, failed_count
        FROM import_batches
        WHERE source_profile_kind=? AND archive_checksum=? AND completed_at IS NOT NULL
        ORDER BY started_at DESC LIMIT 1
        """,
        (source_profile_kind.value, checksum),
    ).fetchone()
    if row is None:
        return False
    return (
        row["failed_count"] == 0
        and int(row["imported_count"]) + int(row["skipped_count"]) == expected_count
    )


def _open_source_copy(
    source_path: Path,
    temp_dir: Path,
    *,
    source_connection: sqlite3.Connection | None = None,
    snapshot_provider: Callable[[Path], None] | None = None,
) -> sqlite3.Connection:
    """소유 연결 또는 읽기 전용 원본에서 검증된 스냅숏을 만든다.

    소유 연결을 제공하면 원본을 추가로 열지 않는다. 경로만 제공한 경우 SQLite가
    읽기에 필요한 사이드카를 만들 수 있지만 원본의 기록·스키마는 수정하지 않는다.
    """
    if snapshot_provider is not None and source_connection is not None:
        raise ValueError("스냅숏 공급자와 원본 연결은 함께 지정할 수 없습니다.")
    if source_connection is not None:
        actual = next(
            (
                row[2]
                for row in source_connection.execute("PRAGMA database_list")
                if row[1] == "main"
            ),
            None,
        )
        if not actual or Path(actual).resolve() != source_path.resolve():
            raise GuestImportError("게스트 원본 경로와 연결이 일치하지 않습니다.")
    temp_db = temp_dir / "source.db"
    if snapshot_provider is not None:
        snapshot_provider(temp_db)
    else:
        copy_database_via_backup(
            source_connection if source_connection is not None else source_path, temp_db
        )
    conn = sqlite3.connect(
        f"{temp_db.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0
    )
    conn.row_factory = sqlite3.Row
    return conn


def import_guest_records(
    source_path: Path,
    target_path: Path,
    *,
    source_profile_kind: ProfileKind = ProfileKind.GUEST,
    source_connection: sqlite3.Connection | None = None,
    snapshot_provider: Callable[[Path], None] | None = None,
) -> GuestImportResult:
    """게스트 DB 기록을 대상 계정 DB로 원자적으로 import한다."""
    try:
        with tempfile.TemporaryDirectory(
            prefix=".mdlogger-import-", dir=target_path.parent
        ) as temp_dir:
            source_conn = _open_source_copy(
                source_path,
                Path(temp_dir),
                source_connection=source_connection,
                snapshot_provider=snapshot_provider,
            )
            try:
                checksum = _core_fields_signature(source_conn)
                rows = source_conn.execute(
                    "SELECT * FROM games WHERE deleted_at IS NULL ORDER BY id"
                ).fetchall()
            finally:
                source_conn.close()
    except (sqlite3.Error, OSError) as error:
        raise GuestImportError(
            f"게스트 DB를 읽을 수 없습니다: {source_path}"
        ) from error

    target_conn = db.connect(target_path)
    try:
        db.init_db(target_conn)
        target_conn.execute("BEGIN IMMEDIATE")
        if _completed_batch_matches(
            target_conn, source_profile_kind, checksum, len(rows)
        ):
            return GuestImportResult(
                source_path,
                target_path,
                imported_count=0,
                skipped_count=len(rows),
                failed_count=0,
                already_imported=True,
            )

        existing = {
            str(row[0])
            for row in target_conn.execute("SELECT sync_id FROM games").fetchall()
        }
        batch_id = str(uuid.uuid4())
        started_at = _now_iso()
        imported = 0
        skipped = 0
        with target_conn:
            target_conn.execute(
                """
                INSERT INTO import_batches
                    (id, archive_id, archive_checksum, source_profile_kind,
                     started_at, imported_count, skipped_count, failed_count)
                VALUES (?, ?, ?, ?, ?, 0, 0, 0)
                """,
                (
                    batch_id,
                    batch_id,
                    checksum,
                    source_profile_kind.value,
                    started_at,
                ),
            )
            for row in rows:
                sync_id = str(row["sync_id"])
                if sync_id in existing:
                    skipped += 1
                    continue
                _insert_imported_game(target_conn, row, batch_id)
                existing.add(sync_id)
                imported += 1
            target_conn.execute(
                """
                UPDATE import_batches
                SET completed_at=?, imported_count=?, skipped_count=?, failed_count=0
                WHERE id=?
                """,
                (_now_iso(), imported, skipped, batch_id),
            )
    finally:
        target_conn.close()

    return GuestImportResult(
        source_path,
        target_path,
        imported_count=imported,
        skipped_count=skipped,
        failed_count=0,
        already_imported=False,
    )


def _insert_imported_game(
    conn: sqlite3.Connection, row: sqlite3.Row, batch_id: str
) -> None:
    """기존 기록을 보존한 채 대상 games에 넣고 outbox에 등록한다."""
    values = {
        field: row[field] for field in _IMPORTED_VALUE_FIELDS if field in row.keys()
    }
    values["sync_status"] = "pending"
    values["import_batch_id"] = batch_id
    values["deleted_at"] = None
    values["remote_version"] = None
    values["base_remote_payload"] = None
    values["last_sync_error"] = None

    columns = tuple(values.keys())
    placeholders = ", ".join(f":{column}" for column in columns)
    conn.execute(
        f"INSERT INTO games ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    sync_id = str(values["sync_id"])
    conn.execute(
        """
        INSERT INTO sync_outbox
            (game_sync_id, operation, payload_version, payload, created_at)
        VALUES (?, 'upsert', ?, ?, ?)
        """,
        (
            sync_id,
            db.PAYLOAD_VERSION,
            json.dumps(values, ensure_ascii=False, separators=(",", ":")),
            _now_iso(),
        ),
    )
