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

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__, db
from .checksum import sha256_file
from .enums import END_REASON_LABELS, RANK_TIER_LABELS, RESULT_LABELS, TURN_ORDER_LABELS
from .local_reset import sync_directory
from .paths import secure_data_file
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
    if archive_dir.exists() or archive_dir.is_symlink():
        raise PortableArchiveError(f"아카이브가 이미 존재합니다: {archive_dir}")
    if len(rows) > MAX_RECORD_COUNT:
        raise PortableArchiveError("기록 수가 아카이브 한도를 초과합니다.")
    records = [_record_dict(row) for row in rows]
    seen: set[str] = set()
    for line_number, record in enumerate(records, 1):
        _validate_record(record, line_number, payload_version=PAYLOAD_VERSION)
        if record["sync_id"] in seen:
            raise PortableArchiveError(f"기록 {line_number}행의 sync_id가 중복됩니다.")
        seen.add(record["sync_id"])

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

    _validate_manifest(manifest)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{archive_dir.name}.", dir=archive_dir.parent)
    )
    try:
        total_bytes = 0
        with (temporary / RECORDS_FILENAME).open("wb") as file:
            for record in records:
                encoded = (
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                ).encode("utf-8")
                total_bytes += len(encoded)
                if total_bytes > MAX_RECORDS_BYTES:
                    raise PortableArchiveError(
                        "records.ndjson의 크기가 한도를 초과합니다."
                    )
                file.write(encoded)
        (temporary / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_checksums(temporary)
        # 실제 reader로 검증한 완성본만 게시한다. 긴 메모도 양쪽 계약이 동일하다.
        _read_archive(temporary)
        for file_path in temporary.iterdir():
            secure_data_file(file_path)
            with file_path.open("r+b") as file:
                os.fsync(file.fileno())
        sync_directory(temporary)
        if archive_dir.exists() or archive_dir.is_symlink():
            raise PortableArchiveError(f"아카이브가 이미 존재합니다: {archive_dir}")
        temporary.rename(archive_dir)
        sync_directory(archive_dir.parent)
    except (OSError, UnicodeError, ValueError) as error:
        raise PortableArchiveError(
            "아카이브 내보내기를 완료하지 못했습니다."
        ) from error
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
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
    manifest, source_kind, records, archive_checksum = _read_archive(archive_dir)

    target_conn = db.connect(target_path)
    try:
        db.init_db(target_conn)
        target_conn.execute("BEGIN IMMEDIATE")
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
    if not archive_dir.is_dir() or archive_dir.is_symlink():
        raise PortableArchiveError(f"Not a directory: {archive_dir}")
    entries = list(archive_dir.iterdir())
    # 심볼릭 링크는 아카이브 밖 파일을 가리킬 수 있어 체크섬 우회/경로 탈출
    # 표면이 된다. 압축 풀기가 아닌 단일 디렉터리 구조이므로 링크는 항상 거부한다.
    if any(entry.is_symlink() for entry in entries):
        raise PortableArchiveError("Symlink is not allowed in archive")
    if any(not entry.is_file() for entry in entries):
        raise PortableArchiveError("Unexpected subdirectory in archive")
    names = {entry.name for entry in entries}
    expected = {MANIFEST_FILENAME, RECORDS_FILENAME, CHECKSUMS_FILENAME}
    if names != expected:
        unexpected = sorted(names ^ expected)
        raise PortableArchiveError(
            f"Unexpected files in archive: {', '.join(unexpected)}"
        )


def _read_archive(archive_dir: Path) -> tuple[dict, ProfileKind, list[dict], str]:
    """검증한 바이트를 그대로 파싱하여 검사 도중 파일 교체의 영향을 받지 않는다."""
    try:
        _validate_archive_layout(archive_dir)
        contents = {}
        for name, limit in (
            (MANIFEST_FILENAME, MAX_MANIFEST_BYTES),
            (RECORDS_FILENAME, MAX_RECORDS_BYTES),
            (CHECKSUMS_FILENAME, MAX_CHECKSUMS_BYTES),
        ):
            with (archive_dir / name).open("rb") as file:
                data = file.read(limit + 1)
            if len(data) > limit:
                raise PortableArchiveError(f"{name}의 크기가 한도를 초과합니다.")
            contents[name] = data
        _verify_checksums(contents)
        manifest = _json_object(contents[MANIFEST_FILENAME].decode("utf-8"))
        source_kind = _validate_manifest(manifest)
        records = _read_records(
            contents[RECORDS_FILENAME],
            manifest["record_count"],
            manifest["payload_version"],
        )
        return (
            manifest,
            source_kind,
            records,
            hashlib.sha256(contents[RECORDS_FILENAME]).hexdigest(),
        )
    except (OSError, ValueError, RecursionError) as error:
        raise PortableArchiveError(
            "아카이브를 읽을 수 없거나 JSON 형식이 올바르지 않습니다."
        ) from error


def _json_object(text: str):
    def reject_constant(value: str):
        raise ValueError("유한하지 않은 JSON 숫자입니다.")

    def unique_keys(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("JSON 필드가 중복됩니다.")
            result[key] = value
        return result

    return json.loads(
        text, parse_constant=reject_constant, object_pairs_hook=unique_keys
    )


def _validate_manifest(manifest) -> ProfileKind:
    if not isinstance(manifest, dict):
        raise PortableArchiveError("manifest.json must be a JSON object")

    format_version = manifest.get("format_version")
    if type(format_version) is not int or format_version != PORTABLE_FORMAT_VERSION:
        raise PortableArchiveError(
            f"Unsupported archive format_version: {format_version!r}"
        )
    # payload 계약 버전이 다르면(예: v1 score_after 아카이브) 필드가 조용히
    # 유실되지 않도록 거부한다(정책 B-a', 레거시 없음).
    payload_version = manifest.get("payload_version")
    if type(payload_version) is not int or payload_version != PAYLOAD_VERSION:
        raise PortableArchiveError(
            f"Unsupported archive payload_version: {payload_version!r}"
        )
    archive_id = manifest.get("archive_id")
    if (
        not isinstance(archive_id, str)
        or not archive_id
        or len(archive_id) > MAX_STRING_LENGTH
    ):
        raise PortableArchiveError("manifest.json missing archive_id")

    source_value = manifest.get("source_profile_kind")
    try:
        source_kind = ProfileKind(source_value)
    except (TypeError, ValueError) as error:
        raise PortableArchiveError(
            f"manifest.json has invalid source_profile_kind: {source_value!r}"
        ) from error

    record_count = manifest.get("record_count")
    if (
        type(record_count) is not int
        or record_count < 0
        or record_count > MAX_RECORD_COUNT
    ):
        raise PortableArchiveError(
            f"manifest.json has invalid record_count: {record_count!r}"
        )

    if manifest.get("included_sections") != [INCLUDED_SECTION_GAMES]:
        raise PortableArchiveError("아카이브의 포함 항목이 올바르지 않습니다.")
    for key in ("archive_id", "created_at", "source_app_version"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value or len(value) > MAX_STRING_LENGTH:
            raise PortableArchiveError(f"아카이브의 {key} 값이 올바르지 않습니다.")
        try:
            value.encode("utf-8")
            if key == "created_at":
                datetime.fromisoformat(value)
        except (ValueError, UnicodeError) as error:
            raise PortableArchiveError(
                f"아카이브의 {key} 값이 올바르지 않습니다."
            ) from error
    return source_kind


def _verify_checksums(contents: dict[str, bytes]) -> None:
    digest_by_name: dict[str, str] = {}
    for line in contents[CHECKSUMS_FILENAME].decode("ascii").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise PortableArchiveError("checksums.sha256 is malformed")
        digest, name = parts
        if (
            name not in (MANIFEST_FILENAME, RECORDS_FILENAME)
            or name in digest_by_name
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise PortableArchiveError("체크섬 항목이 올바르지 않거나 중복됩니다.")
        digest_by_name[name] = digest
    if set(digest_by_name) != {MANIFEST_FILENAME, RECORDS_FILENAME}:
        raise PortableArchiveError("checksums.sha256 is missing entries")
    for name in (MANIFEST_FILENAME, RECORDS_FILENAME):
        actual = hashlib.sha256(contents[name]).hexdigest()
        if actual != digest_by_name[name]:
            raise PortableArchiveError(f"{name} checksum mismatch (tampered archive)")


def _read_records(data: bytes, expected_count: int, payload_version: int) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()
    with io.StringIO(data.decode("utf-8")) as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = _json_object(stripped)
            except (ValueError, RecursionError) as error:
                raise PortableArchiveError(
                    f"records.ndjson: invalid JSON on line {line_number}"
                ) from error
            _validate_record(record, line_number, payload_version=payload_version)
            if record["sync_id"] in seen:
                raise PortableArchiveError(
                    f"기록 {line_number}행의 sync_id가 중복됩니다."
                )
            seen.add(record["sync_id"])
            records.append(record)
            if len(records) > expected_count:
                raise PortableArchiveError(
                    "실제 기록 수가 선언한 기록 수를 초과합니다."
                )
    if len(records) != expected_count:
        raise PortableArchiveError(
            f"record_count mismatch: manifest says {expected_count},"
            f" found {len(records)}"
        )
    return records


def _validate_record(
    record, line_number: int, *, payload_version: int = PAYLOAD_VERSION
) -> None:
    """v2 기록을 변환 없이 검증한다. 이관된 모드 미지정 기록의 NULL은 보존한다."""
    if type(payload_version) is not int or payload_version != PAYLOAD_VERSION:
        raise PortableArchiveError("지원하지 않는 기록 계약 버전입니다.")
    if not isinstance(record, dict):
        raise PortableArchiveError(
            f"records.ndjson: line {line_number} is not a JSON object"
        )
    if len(record) > MAX_RECORD_FIELDS:
        raise PortableArchiveError(
            f"records.ndjson: line {line_number} has too many fields"
        )
    required = {
        "played_at",
        "result",
        "turn_order",
        "opp_deck",
        "turns",
        "end_reason",
        "sync_id",
    }
    if not required <= record.keys() or record.keys() - set(PORTABLE_RECORD_FIELDS):
        raise PortableArchiveError(
            f"기록 {line_number}행의 필수 필드가 없거나 알 수 없는 필드가 있습니다."
        )
    sync_id = record.get("sync_id")
    if not isinstance(sync_id, str) or not sync_id:
        raise PortableArchiveError(
            f"records.ndjson: line {line_number} has invalid sync_id"
        )
    integer_fields = {
        "turns",
        "rank_division_before",
        "rank_division_after",
        "rating_before",
        "rating_after",
        "event_points_before",
        "event_points_after",
        "timezone_offset_minutes",
    }
    nullable_core_fields = {"opp_deck", "turns", "end_reason"}
    for key, value in record.items():
        if value is None and (key not in required or key in nullable_core_fields):
            continue
        if key in integer_fields:
            valid = type(value) is int and -(2**63) <= value < 2**63
        else:
            valid = isinstance(value, str)
            if valid:
                try:
                    byte_count = len(value.encode("utf-8"))
                except UnicodeError:
                    valid = False
                else:
                    valid = (
                        byte_count <= MAX_RECORDS_BYTES
                        if key == "note"
                        else len(value) <= MAX_STRING_LENGTH
                    )
        if not valid:
            raise PortableArchiveError(
                f"기록 {line_number}행의 {key} 타입 또는 크기가 올바르지 않습니다."
            )
    for key, choices in (
        ("result", RESULT_LABELS),
        ("turn_order", TURN_ORDER_LABELS),
        ("end_reason", END_REASON_LABELS),
    ):
        if record[key] is not None and record[key] not in choices:
            raise PortableArchiveError(
                f"기록 {line_number}행의 {key} 값이 올바르지 않습니다."
            )
    if record["turns"] is not None and record["turns"] < 0:
        raise PortableArchiveError(
            f"기록 {line_number}행의 턴 수는 0 이상이어야 합니다."
        )
    offset = record.get("timezone_offset_minutes")
    if offset is not None and not -1440 < offset < 1440:
        raise PortableArchiveError(
            f"기록 {line_number}행의 시간대 오프셋이 올바르지 않습니다."
        )
    for key in ("played_at", "local_updated_at"):
        value = record.get(key)
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value)
                if len(value) < 19 or (
                    key == "played_at" and parsed.tzinfo is not None
                ):
                    raise ValueError
            except ValueError as error:
                raise PortableArchiveError(
                    f"기록 {line_number}행의 {key} 날짜가 올바르지 않습니다."
                ) from error
    kind = record.get("standing_kind")
    snapshots = {
        "rank": {
            "rank_tier_before",
            "rank_tier_after",
            "rank_division_before",
            "rank_division_after",
        },
        "rating": {"rating_before", "rating_after"},
        "event_points": {"event_points_before", "event_points_after"},
    }
    if kind is not None and kind not in snapshots:
        raise PortableArchiveError(f"기록 {line_number}행의 모드가 올바르지 않습니다.")
    for snapshot_kind, fields in snapshots.items():
        if snapshot_kind != kind and any(record.get(key) is not None for key in fields):
            raise PortableArchiveError(
                f"기록 {line_number}행의 모드와 점수 필드가 일치하지 않습니다."
            )
    if kind is None and record.get("play_context_id") is not None:
        raise PortableArchiveError(
            f"기록 {line_number}행의 모드 없는 문맥은 지원하지 않습니다."
        )
    if kind == "rank":
        for suffix in ("before", "after"):
            tier, division = (
                record.get(f"rank_tier_{suffix}"),
                record.get(f"rank_division_{suffix}"),
            )
            if tier is None and division is None:
                continue
            if (
                tier not in RANK_TIER_LABELS
                or division is None
                or not 1 <= division <= 5
            ):
                raise PortableArchiveError(
                    f"기록 {line_number}행의 랭크 조합이 올바르지 않습니다."
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
    return (
        row["failed_count"] == 0
        and int(row["imported_count"]) + int(row["skipped_count"]) == expected_count
    )


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
