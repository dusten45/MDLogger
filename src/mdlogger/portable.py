"""MDLogger 휴대용 아카이브(.mdlogger-export) 내보내기·가져오기.

휴대용 아카이브는 CSV/XLSX 와 달리 완전한 round-trip 형식으로, 하나의 디렉터리 안에
세 파일로 구성된다(옵션 암호화는 초기 범위 제외, §17.E):

    manifest.json      - 포맷 버전, archive_id, 기록 수 등 메타데이터
    records.ndjson     - 기록 한 줄당 하나의 JSON 객체
    checksums.sha256   - manifest.json 과 records.ndjson 의 SHA-256

보안 규칙(§10.2):
- 개인 ``note`` 는 포함하되 token/password/publishable key 는 포함하지 않는다.
- 기본 아카이브는 평문이며, 파일을 가진 사람이 note 를 읽을 수 있음을 내보내기 전에 알려야 한다.
- 파일 크기, 행 수, 문자열 길이, 필드 수, 경로(파일 목록)에 상한을 둔다.
- checksum 을 검증하고, 알 수 없는 format version 은 추측해 가져오지 않는다.
- 전체 import 는 단일 SQLite transaction 으로 처리한다(중간 실패 시 rollback).

중복 방지(§10.3):
- ``import_batches`` 에 archive_id 와 archive checksum 을 기록한다.
- 같은 아카이브(같은 archive_id + checksum)를 다시 가져오면 기본적으로 건너뛴다.
- 대상 DB 에 이미 있는 sync_id 는 건너뛴다(중복 관찰 방지).
- 가져온 기록은 private games 동기화 outbox 에 upsert 로 등록한다.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__, db
from .checksum import sha256_file
from .profiles import ProfileKind

MANIFEST_FILENAME = "manifest.json"
RECORDS_FILENAME = "records.ndjson"
CHECKSUMS_FILENAME = "checksums.sha256"

# 이 구현이 쓰고 읽는 포맷 버전. 알 수 없는 버전은 거부한다.
PORTABLE_FORMAT_VERSION = 1
# sync_outbox 의 payload_version 과 별개로, 아카이브 records 의 페이로드 계약 버전.
PAYLOAD_VERSION = 2
INCLUDED_SECTION_GAMES = "games"

# 검증 한도(§10.2).
MAX_MANIFEST_BYTES = 1_000_000
MAX_RECORDS_BYTES = 64 * 1024 * 1024
MAX_CHECKSUMS_BYTES = 1_000_000
MAX_RECORD_COUNT = 1_000_000
MAX_RECORD_FIELDS = 64
MAX_STRING_LENGTH = 10_000

# 휴대용 아카이브에 보존하는 기록 값 필드(전체 round-trip 용).
PORTABLE_RECORD_FIELDS = (
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


class PortableArchiveError(RuntimeError):
    """휴대용 아카이브 내보내기/가져오기를 완료하지 못했을 때 발생한다.

    손상·변조·과대 혹은 지원하지 않는 아카이브는 이 예외로 거부된다.
    """


@dataclass(frozen=True, slots=True)
class PortableImportResult:
    """휴대용 아카이브 import 결과와 재실행 여부."""

    archive_path: Path
    target_path: Path
    archive_id: str
    source_profile_kind: ProfileKind
    imported_count: int
    skipped_count: int
    failed_count: int
    already_imported: bool

    @property
    def total(self) -> int:
        return self.imported_count + self.skipped_count


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _record_dict(row) -> dict:
    """sqlite3.Row 또는 dict 에서 휴대용 필드만 추출한 정규화 dict."""
    return {
        field: row[field] for field in PORTABLE_RECORD_FIELDS if field in row.keys()
    }


# ---------------------------------------------------------------------------
# 내보내기(writer)
# ---------------------------------------------------------------------------


def export_portable_archive(
    path: str | Path,
    rows: Sequence,
    *,
    profile_kind: ProfileKind = ProfileKind.GUEST,
    source_app_version: str | None = None,
) -> Path:
    """기록을 휴대용 아카이브 디렉터리로 내보낸다.

    ``path`` 는 생성할 아카이브 디렉터리(예: ``my_export.mdlogger-export``)다.
    이미 존재하면 재사용하지 않고 오류를 던진다. 반환값은 생성된 디렉터리 경로.
    """
    archive_dir = Path(path)
    try:
        archive_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError as error:
        raise PortableArchiveError(f"Archive already exists: {archive_dir}") from error

    records = [_record_dict(row) for row in rows]
    if len(records) > MAX_RECORD_COUNT:
        raise PortableArchiveError(
            f"record count {len(records)} exceeds limit {MAX_RECORD_COUNT}"
        )

    manifest = {
        "format_version": PORTABLE_FORMAT_VERSION,
        "archive_id": str(uuid.uuid4()),
        "created_at": _now_iso(),
        "source_app_version": source_app_version or __version__,
        "source_profile_kind": profile_kind.value,
        "record_count": len(records),
        "payload_version": PAYLOAD_VERSION,
        "included_sections": [INCLUDED_SECTION_GAMES],
    }

    records_path = archive_dir / RECORDS_FILENAME
    with records_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    manifest_path = archive_dir / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    _write_checksums(archive_dir)
    return archive_dir


def _write_checksums(archive_dir: Path) -> None:
    """manifest.json 과 records.ndjson 의 SHA-256 을 sha256sum 형식으로 쓴다."""
    lines = []
    for name in (MANIFEST_FILENAME, RECORDS_FILENAME):
        digest = sha256_file(archive_dir / name)
        lines.append(f"{digest}  {name}\n")
    (archive_dir / CHECKSUMS_FILENAME).write_text("".join(lines), encoding="ascii")


# ---------------------------------------------------------------------------
# 가져오기(reader)
# ---------------------------------------------------------------------------


def import_portable_archive(
    archive_path: str | Path,
    target_path: str | Path,
) -> PortableImportResult:
    """휴대용 아카이브를 대상 DB 로 원자적으로 가져온다.

    검증에 실패하거나 아카이브가 지원되지 않으면 ``PortableArchiveError`` 를
    던지고 대상 DB 는 변경하지 않는다. 가져온 기록은 sync_outbox 에 upsert 로
    등록하므로 이후 기존 동기화 엔진이 서버에 업로드한다.
    """
    archive_dir = Path(archive_path)
    _validate_archive_layout(archive_dir)
    manifest, source_kind = _read_manifest(archive_dir)
    _verify_checksums(archive_dir)
    records = _read_records(archive_dir, manifest["record_count"])
    archive_checksum = sha256_file(archive_dir / RECORDS_FILENAME)

    target_conn = db.connect(target_path)
    try:
        db.init_db(target_conn)
        if _completed_batch_matches(
            target_conn,
            manifest["archive_id"],
            archive_checksum,
            source_kind,
            len(records),
        ):
            return PortableImportResult(
                archive_dir,
                Path(target_path),
                archive_id=manifest["archive_id"],
                source_profile_kind=source_kind,
                imported_count=0,
                skipped_count=len(records),
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
                    manifest["archive_id"],
                    archive_checksum,
                    source_kind.value,
                    started_at,
                ),
            )
            for record in records:
                sync_id = str(record["sync_id"])
                if sync_id in existing:
                    skipped += 1
                    continue
                _insert_record(target_conn, record, batch_id)
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

    return PortableImportResult(
        archive_dir,
        Path(target_path),
        archive_id=manifest["archive_id"],
        source_profile_kind=source_kind,
        imported_count=imported,
        skipped_count=skipped,
        failed_count=0,
        already_imported=False,
    )


def _validate_archive_layout(archive_dir: Path) -> None:
    """아카이브 디렉터리가 예상 파일만 정확히 포함하는지(경로 검증) 확인한다."""
    if not archive_dir.is_dir():
        raise PortableArchiveError(f"Not a directory: {archive_dir}")
    entries = list(archive_dir.iterdir())
    # 심볼릭 링크는 아카이브 밖 파일을 가리킬 수 있어 체크섬 우회/경로 탈출
    # 표면이 된다. 압축 풀기가 아닌 단일 디렉터리 구조이므로 링크는 항상 거부한다.
    if any(entry.is_symlink() for entry in entries):
        raise PortableArchiveError("Symlink is not allowed in archive")
    if any(entry.is_dir() for entry in entries):
        raise PortableArchiveError("Unexpected subdirectory in archive")
    names = {entry.name for entry in entries}
    expected = {MANIFEST_FILENAME, RECORDS_FILENAME, CHECKSUMS_FILENAME}
    if names != expected:
        unexpected = sorted(names ^ expected)
        raise PortableArchiveError(
            f"Unexpected files in archive: {', '.join(unexpected)}"
        )


def _read_manifest(archive_dir: Path) -> tuple[dict, ProfileKind]:
    manifest_path = archive_dir / MANIFEST_FILENAME
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise PortableArchiveError("manifest.json exceeds size limit")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PortableArchiveError("manifest.json is not valid UTF-8 JSON") from error
    if not isinstance(manifest, dict):
        raise PortableArchiveError("manifest.json must be a JSON object")

    format_version = manifest.get("format_version")
    if format_version != PORTABLE_FORMAT_VERSION:
        raise PortableArchiveError(
            f"Unsupported archive format_version: {format_version!r}"
        )
    # payload 계약 버전이 다르면(예: v1 score_after 아카이브) 필드가 조용히
    # 유실되지 않도록 거부한다(정책 B-a', 레거시 없음).
    payload_version = manifest.get("payload_version")
    if payload_version != PAYLOAD_VERSION:
        raise PortableArchiveError(
            f"Unsupported archive payload_version: {payload_version!r}"
        )
    archive_id = manifest.get("archive_id")
    if not isinstance(archive_id, str) or not archive_id:
        raise PortableArchiveError("manifest.json missing archive_id")

    source_value = manifest.get("source_profile_kind")
    try:
        source_kind = ProfileKind(source_value)
    except ValueError as error:
        raise PortableArchiveError(
            f"manifest.json has invalid source_profile_kind: {source_value!r}"
        ) from error

    record_count = manifest.get("record_count")
    if (
        not isinstance(record_count, int)
        or record_count < 0
        or record_count > MAX_RECORD_COUNT
    ):
        raise PortableArchiveError(
            f"manifest.json has invalid record_count: {record_count!r}"
        )

    return manifest, source_kind


def _verify_checksums(archive_dir: Path) -> None:
    checksums_path = archive_dir / CHECKSUMS_FILENAME
    if checksums_path.stat().st_size > MAX_CHECKSUMS_BYTES:
        raise PortableArchiveError("checksums.sha256 exceeds size limit")
    digest_by_name: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="ascii").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise PortableArchiveError("checksums.sha256 is malformed")
        digest, name = parts
        if name in (MANIFEST_FILENAME, RECORDS_FILENAME):
            digest_by_name[name] = digest
    if set(digest_by_name) != {MANIFEST_FILENAME, RECORDS_FILENAME}:
        raise PortableArchiveError("checksums.sha256 is missing entries")
    for name in (MANIFEST_FILENAME, RECORDS_FILENAME):
        actual = sha256_file(archive_dir / name)
        if actual != digest_by_name[name]:
            raise PortableArchiveError(f"{name} checksum mismatch (tampered archive)")


def _read_records(archive_dir: Path, expected_count: int) -> list[dict]:
    records_path = archive_dir / RECORDS_FILENAME
    if records_path.stat().st_size > MAX_RECORDS_BYTES:
        raise PortableArchiveError("records.ndjson exceeds size limit")

    records: list[dict] = []
    with records_path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise PortableArchiveError(
                    f"records.ndjson: invalid JSON on line {line_number}"
                ) from error
            _validate_record(record, line_number)
            records.append(record)
    if len(records) != expected_count:
        raise PortableArchiveError(
            f"record_count mismatch: manifest says {expected_count},"
            f" found {len(records)}"
        )
    return records


def _validate_record(record, line_number: int) -> None:
    if not isinstance(record, dict):
        raise PortableArchiveError(
            f"records.ndjson: line {line_number} is not a JSON object"
        )
    if len(record) > MAX_RECORD_FIELDS:
        raise PortableArchiveError(
            f"records.ndjson: line {line_number} has too many fields"
        )
    sync_id = record.get("sync_id")
    if not isinstance(sync_id, str) or not sync_id:
        raise PortableArchiveError(
            f"records.ndjson: line {line_number} has invalid sync_id"
        )
    for key, value in record.items():
        if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
            raise PortableArchiveError(
                f"records.ndjson: line {line_number} field {key!r} too long"
            )


def _completed_batch_matches(
    conn: sqlite3.Connection,
    archive_id: str,
    archive_checksum: str,
    source_profile_kind: ProfileKind,
    expected_count: int,
) -> bool:
    """같은 아카이브를 이미 완료했는지 확인한다(중복 재import 방지)."""
    row = conn.execute(
        """
        SELECT imported_count, skipped_count, failed_count
        FROM import_batches
        WHERE archive_id=? AND archive_checksum=? AND source_profile_kind=?
          AND completed_at IS NOT NULL
        ORDER BY started_at DESC LIMIT 1
        """,
        (archive_id, archive_checksum, source_profile_kind.value),
    ).fetchone()
    if row is None:
        return False
    return int(row["imported_count"]) + int(row["skipped_count"]) == expected_count


def _insert_record(conn: sqlite3.Connection, record: dict, batch_id: str) -> None:
    """휴대용 기록을 대상 games 에 넣고 outbox 에 upsert 를 등록한다."""
    values = {
        field: record[field] for field in PORTABLE_RECORD_FIELDS if field in record
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
            PAYLOAD_VERSION,
            json.dumps(values, ensure_ascii=False, separators=(",", ":")),
            _now_iso(),
        ),
    )


__all__ = [
    "MANIFEST_FILENAME",
    "RECORDS_FILENAME",
    "CHECKSUMS_FILENAME",
    "PORTABLE_FORMAT_VERSION",
    "PAYLOAD_VERSION",
    "PORTABLE_RECORD_FIELDS",
    "PortableArchiveError",
    "PortableImportResult",
    "export_portable_archive",
    "import_portable_archive",
]
