"""MDLogger 휴대용 아카이브(.mdlogger-export) 내보내기·가져오기 테스트."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mdlogger import db
from mdlogger.checksum import sha256_file
from mdlogger.portable import (
    CHECKSUMS_FILENAME,
    MANIFEST_FILENAME,
    PORTABLE_FORMAT_VERSION,
    RECORDS_FILENAME,
    PortableArchiveError,
    PortableImportResult,
    export_portable_archive,
    import_portable_archive,
)
from mdlogger.profiles import ProfileKind

PLAYED_AT = "2026-06-19T10:00:00"


def _make_source_db(path: Path, count: int = 3) -> list[str]:
    """기록 DB를 만들고 count건을 넣어 sync_id를 반환한다."""
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
                "score_after": 1600 + index,
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


def _import_batch(target: Path) -> sqlite3.Row:
    conn = db.connect(target)
    try:
        return conn.execute("SELECT * FROM import_batches").fetchone()
    finally:
        conn.close()


def test_export_creates_expected_archive_layout(tmp_path: Path):
    source = tmp_path / "source.db"
    _make_source_db(source, count=2)
    archive = tmp_path / "out.mdlogger-export"

    export_portable_archive(
        archive, db.get_all_games(db.connect(source)), profile_kind=ProfileKind.GUEST
    )

    assert archive.is_dir()
    assert sorted(p.name for p in archive.iterdir()) == sorted(
        [MANIFEST_FILENAME, RECORDS_FILENAME, CHECKSUMS_FILENAME]
    )
    manifest = json.loads((archive / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["format_version"] == PORTABLE_FORMAT_VERSION
    assert manifest["record_count"] == 2
    assert manifest["source_profile_kind"] == ProfileKind.GUEST.value
    assert manifest["included_sections"] == ["games"]

    # checksums.sha256 는 manifest 와 records 를 모두 지칭한다.
    checksum_lines = (archive / CHECKSUMS_FILENAME).read_text(encoding="ascii")
    assert (
        f"{sha256_file(archive / MANIFEST_FILENAME)}  {MANIFEST_FILENAME}"
        in checksum_lines
    )
    assert (
        f"{sha256_file(archive / RECORDS_FILENAME)}  {RECORDS_FILENAME}"
        in checksum_lines
    )


def test_round_trip_preserves_fields_and_registers_outbox(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    sync_ids = _make_source_db(source, count=3)
    archive = tmp_path / "out.mdlogger-export"

    export_portable_archive(
        archive,
        db.get_all_games(db.connect(source)),
        profile_kind=ProfileKind.REGISTERED,
    )
    result = import_portable_archive(archive, target)

    assert isinstance(result, PortableImportResult)
    assert result.imported_count == 3
    assert result.skipped_count == 0
    assert result.already_imported is False
    assert result.source_profile_kind is ProfileKind.REGISTERED

    rows = _target_rows(target)
    assert [str(row["sync_id"]) for row in rows] == sync_ids
    assert [row["played_at"] for row in rows] == [
        f"2026-06-{19 + i:02d}T10:00:00" for i in range(3)
    ]
    assert [row["note"] for row in rows] == ["메모0", "메모1", "메모2"]
    assert [row["score_after"] for row in rows] == [1600, 1601, 1602]
    assert [row["environment_version_id"] for row in rows] == [
        "env-0",
        "env-1",
        "env-2",
    ]
    assert all(row["sync_status"] == "pending" for row in rows)
    assert all(row["deleted_at"] is None for row in rows)
    assert _outbox_count(target) == 3


def test_reimport_same_archive_is_idempotent(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=2)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    first = import_portable_archive(archive, target)
    second = import_portable_archive(archive, target)

    assert first.imported_count == 2
    assert first.already_imported is False
    assert second.imported_count == 0
    assert second.skipped_count == 2
    assert second.already_imported is True
    assert len(_target_rows(target)) == 2
    assert _outbox_count(target) == 2


def test_import_dedups_by_sync_id_when_target_has_records(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    sync_ids = _make_source_db(source, count=2)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    # 대상 DB에 이미 첫 번째 sync_id가 존재한다.
    conn = db.connect(target)
    db.init_db(conn)
    conn.execute(
        "INSERT INTO games (played_at, result, turn_order, opp_deck, turns,"
        " end_reason, score_after, note, sync_id, sync_status)"
        " VALUES (?, 'win', 'first', '기존', 4, 'regular', 100, '기존메모', ?, 'synced')",
        (PLAYED_AT, sync_ids[0]),
    )
    conn.commit()
    conn.close()
    before = len(_target_rows(target))

    result = import_portable_archive(archive, target)

    assert result.imported_count == 1
    assert result.skipped_count == 1
    rows = _target_rows(target)
    assert len(rows) == before + 1
    existing = {str(row["sync_id"]) for row in rows}
    assert existing == set(sync_ids)
    imported = next(row for row in rows if row["sync_id"] == sync_ids[1])
    assert imported["note"] == "메모1"


def test_import_records_provenance_in_batch(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=1)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(
        archive, db.get_all_games(db.connect(source)), profile_kind=ProfileKind.GUEST
    )

    import_portable_archive(archive, target)

    batch = _import_batch(target)
    assert (
        batch["archive_id"]
        == json.loads((archive / MANIFEST_FILENAME).read_text(encoding="utf-8"))[
            "archive_id"
        ]
    )
    assert batch["source_profile_kind"] == ProfileKind.GUEST.value
    assert batch["completed_at"] is not None
    assert batch["imported_count"] == 1


def test_import_rejects_tampered_checksum_without_touching_target(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=2)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    # records.ndjson 을 수정해 checksum 이 어긋나게 한다.
    records_path = archive / RECORDS_FILENAME
    records_path.write_text(
        records_path.read_text(encoding="utf-8") + '{"sync_id":"x"}\n',
        encoding="utf-8",
    )

    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, target)
    assert not target.exists()


def test_import_rejects_unsupported_format_version(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=1)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    manifest_path = archive / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = PORTABLE_FORMAT_VERSION + 1
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, target)
    assert not target.exists()


def test_import_rejects_corrupt_json_line(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=1)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    (archive / RECORDS_FILENAME).write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, target)
    assert not target.exists()


def test_import_rejects_unexpected_extra_file(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=1)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    (archive / "payload.sh").write_text("echo pwned\n", encoding="utf-8")

    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, target)
    assert not target.exists()


def test_import_rejects_symlink_in_archive(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=1)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    # 체크섬 우회/경로 탈출을 시도하는 심볼릭 링크를 아카이브에 끼워 넣는다.
    outside = tmp_path / "outside.txt"
    outside.write_text("sensitive\n", encoding="utf-8")
    (archive / "records.ndjson").unlink()
    (archive / "records.ndjson").symlink_to(outside)

    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, target)
    assert not target.exists()


def test_import_rejects_missing_file(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=1)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    (archive / RECORDS_FILENAME).unlink()

    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, target)
    assert not target.exists()
