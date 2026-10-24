"""MDLogger 휴대용 아카이브(.mdlogger-export) 내보내기·가져오기 테스트."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from mdlogger import db, portable
from mdlogger.checksum import sha256_file
from mdlogger.game_sync.repository import SyncRepository
from mdlogger.portable import (
    CHECKSUMS_FILENAME,
    MANIFEST_FILENAME,
    PAYLOAD_VERSION,
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
    assert [row["event_points_after"] for row in rows] == [1600, 1601, 1602]
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
        " end_reason, note, sync_id, sync_status)"
        " VALUES (?, 'win', 'first', '기존', 4, 'regular', '기존메모', ?, 'synced')",
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


def test_import_rejects_unsupported_payload_version(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "registered.db"
    _make_source_db(source, count=1)
    archive = tmp_path / "out.mdlogger-export"
    export_portable_archive(archive, db.get_all_games(db.connect(source)))

    manifest_path = archive / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["payload_version"] = PAYLOAD_VERSION - 1
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


def _source_records(directory: Path, count: int = 2) -> list[dict]:
    source = directory / "source.db"
    _make_source_db(source, count=count)
    connection = db.connect(source)
    try:
        return [portable._record_dict(row) for row in db.get_all_games(connection)]
    finally:
        connection.close()


def _rewrite_records(archive: Path, records: list[dict]) -> None:
    (archive / RECORDS_FILENAME).write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    portable._write_checksums(archive)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_points_after", "not-an-integer"),
        ("event_points_after", True),
        ("event_points_after", 2**63),
        ("event_points_after", float("nan")),
        ("event_points_after", float("inf")),
        ("turns", 2.5),
        ("turns", -1),
        ("turns", False),
        ("opp_deck", 123),
        ("end_reason", {}),
        ("result", "draw"),
        ("turn_order", "unknown"),
        ("end_reason", "unknown"),
        ("standing_kind", "unknown"),
        ("rating_after", 1000),
        ("note", {"text": "메모"}),
        ("played_at", "2026-02-30T10:00:00"),
        ("played_at", "2026-06-19T10:00:00Z"),
        ("timezone_offset_minutes", True),
        ("timezone_offset_minutes", 1440),
    ],
)
def test_invalid_last_record_is_rejected_before_target_changes(tmp_path, field, value):
    records = _source_records(tmp_path)
    archive, target = tmp_path / "out", tmp_path / "target.db"
    export_portable_archive(archive, records)
    _make_source_db(target, count=1)
    before = target.read_bytes()
    records[-1][field] = value
    _rewrite_records(archive, records)

    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, target)
    assert target.read_bytes() == before
    assert len(_target_rows(target)) == 1
    assert _outbox_count(target) == 1


@pytest.mark.parametrize(
    "field",
    ["played_at", "result", "turn_order", "opp_deck", "turns", "end_reason", "sync_id"],
)
def test_writer_and_reader_reject_missing_core_fields(tmp_path, field):
    records = _source_records(tmp_path)
    archive = tmp_path / "out"
    export_portable_archive(archive, records)
    del records[-1][field]
    _rewrite_records(archive, records)
    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, tmp_path / "target.db")
    with pytest.raises(PortableArchiveError):
        export_portable_archive(tmp_path / "bad-export", records)
    assert not (tmp_path / "target.db").exists()
    assert not (tmp_path / "bad-export").exists()


@pytest.mark.parametrize("length", [10_000, 10_001, 40_000])
def test_long_hangul_notes_round_trip_without_truncation(tmp_path, length):
    records = _source_records(tmp_path, count=1)
    records[0]["note"] = "한" * length
    records[0]["played_at"] = "2026-10-24T17:23:42.123456"
    archive, target = tmp_path / "out", tmp_path / "target.db"
    export_portable_archive(archive, records)
    import_portable_archive(archive, target)
    row = _target_rows(target)[0]
    assert portable._record_dict(row) == records[0]


def test_nullable_migrated_v2_record_round_trips_exactly(tmp_path):
    records = _source_records(tmp_path, count=1)
    for field in (
        "standing_kind",
        "play_context_id",
        "event_points_before",
        "event_points_after",
        "my_deck",
        "note",
        "timezone_offset_minutes",
        "environment_version_id",
    ):
        records[0][field] = None
    archive, target = tmp_path / "legacy-v2", tmp_path / "target.db"
    export_portable_archive(archive, records)
    import_portable_archive(archive, target)
    assert portable._record_dict(_target_rows(target)[0]) == records[0]


@pytest.mark.parametrize("kind", ["rank", "rating"])
def test_other_standing_kinds_round_trip(tmp_path, kind):
    records = _source_records(tmp_path, count=1)
    records[0].update(
        standing_kind=kind, event_points_before=None, event_points_after=None
    )
    if kind == "rank":
        records[0].update(
            rank_tier_before="gold",
            rank_tier_after="gold",
            rank_division_before=5,
            rank_division_after=4,
        )
    else:
        records[0].update(rating_before=1500, rating_after=1530)
    archive, target = tmp_path / "out", tmp_path / "target.db"
    export_portable_archive(archive, records)
    import_portable_archive(archive, target)
    assert portable._record_dict(_target_rows(target)[0]) == records[0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format_version", True),
        ("payload_version", 2.0),
        ("record_count", True),
        ("included_sections", []),
        ("source_profile_kind", {}),
        ("archive_id", {}),
    ],
)
def test_manifest_contract_rejects_wrong_types_before_target_creation(
    tmp_path, field, value
):
    records = _source_records(tmp_path, count=1)
    archive = tmp_path / "out"
    export_portable_archive(archive, records)
    manifest_path = archive / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    portable._write_checksums(archive)
    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, tmp_path / "target.db")
    assert not (tmp_path / "target.db").exists()


def test_record_byte_limit_is_symmetric_and_failed_export_is_not_published(
    tmp_path, monkeypatch
):
    records = _source_records(tmp_path, count=1)
    records[0]["note"] = "한글" * 100
    archive = tmp_path / "valid"
    export_portable_archive(archive, records)
    monkeypatch.setattr(
        portable, "MAX_RECORDS_BYTES", (archive / RECORDS_FILENAME).stat().st_size - 1
    )
    with pytest.raises(PortableArchiveError):
        export_portable_archive(tmp_path / "too-large", records)
    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, tmp_path / "target.db")
    assert not (tmp_path / "too-large").exists()
    assert not list(tmp_path.glob(".too-large.*"))
    assert not (tmp_path / "target.db").exists()


def test_import_outbox_failure_rolls_back_every_record_and_batch(tmp_path):
    records = _source_records(tmp_path)
    archive, target = tmp_path / "out", tmp_path / "target.db"
    export_portable_archive(archive, records)
    connection = db.connect(target)
    db.init_db(connection)
    connection.execute(
        "CREATE TRIGGER fail_second BEFORE INSERT ON sync_outbox "
        "WHEN (SELECT COUNT(*) FROM sync_outbox) = 1 "
        "BEGIN SELECT RAISE(ABORT, 'outbox failure'); END"
    )
    connection.close()
    with pytest.raises(sqlite3.IntegrityError):
        import_portable_archive(archive, target)
    connection = db.connect(target)
    try:
        for table in ("games", "sync_outbox", "import_batches"):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )
    finally:
        connection.close()


def test_reader_rejects_unknown_fields_instead_of_silently_dropping_them(tmp_path):
    records = _source_records(tmp_path, count=1)
    archive = tmp_path / "out"
    export_portable_archive(archive, records)
    records[0]["unknown_field"] = "보존할 수 없는 값"
    _rewrite_records(archive, records)
    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, tmp_path / "target.db")
    assert not (tmp_path / "target.db").exists()


def test_duplicate_archive_ids_are_rejected(tmp_path):
    records = _source_records(tmp_path)
    archive = tmp_path / "out"
    export_portable_archive(archive, records)
    records[1]["sync_id"] = records[0]["sync_id"]
    _rewrite_records(archive, records)
    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, tmp_path / "target.db")
    with pytest.raises(PortableArchiveError):
        export_portable_archive(tmp_path / "duplicate", records)


@pytest.mark.parametrize("turns", [None, 0])
def test_minimal_server_v2_pull_can_be_exported_and_restored_exactly(tmp_path, turns):
    remote = {
        "id": "11111111-1111-4111-8111-111111111111",
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "note": "중복 저장하지 않을 메모",
        "standing_kind": "event_points",
        "play_context_id": "dc_cup_2026_08",
        "event_points_after": 10000,
        "payload_version": 2,
        "change_version": 1,
        "updated_at": "2026-08-07T10:01:00+00:00",
    }
    if turns is not None:
        remote["turns"] = turns
    source = db.connect(tmp_path / "synced.db")
    try:
        db.init_db(source)
        repository = SyncRepository(source)
        assert (
            repository.apply_pull_batch(
                [remote],
                completed_at=datetime(2026, 8, 7, 10, 1),
                initial_sync_completed=True,
            )
            == 1
        )
        records = [portable._record_dict(row) for row in db.get_all_games(source)]
    finally:
        source.close()
    assert records[0]["opp_deck"] is None
    assert records[0]["end_reason"] is None
    assert records[0]["turns"] == turns
    archive, target = tmp_path / "synced-export", tmp_path / "restored.db"
    export_portable_archive(archive, records, profile_kind=ProfileKind.REGISTERED)
    assert import_portable_archive(archive, target).imported_count == 1
    assert portable._record_dict(_target_rows(target)[0]) == records[0]


@pytest.mark.parametrize("turns", [None, 0])
def test_existing_v2_archive_with_nullable_trio_round_trips(tmp_path, turns):
    records = _source_records(tmp_path, count=1)
    archive, target = tmp_path / "old-v2", tmp_path / "restored.db"
    export_portable_archive(archive, records)
    records[0].update(opp_deck=None, turns=turns, end_reason=None)
    _rewrite_records(archive, records)
    assert import_portable_archive(archive, target).imported_count == 1
    restored = portable._record_dict(_target_rows(target)[0])
    assert restored == records[0]
    reexported = tmp_path / "reexported"
    export_portable_archive(reexported, [restored])
    second_target = tmp_path / "second.db"
    assert import_portable_archive(reexported, second_target).imported_count == 1
    assert portable._record_dict(_target_rows(second_target)[0]) == records[0]


@pytest.mark.parametrize("field", ["played_at", "result", "turn_order", "sync_id"])
def test_nullable_v2_fields_do_not_make_core_identifiers_nullable(tmp_path, field):
    records = _source_records(tmp_path, count=1)
    archive = tmp_path / "out"
    export_portable_archive(archive, records)
    records[0][field] = None
    _rewrite_records(archive, records)
    with pytest.raises(PortableArchiveError):
        import_portable_archive(archive, tmp_path / "target.db")
    with pytest.raises(PortableArchiveError):
        export_portable_archive(tmp_path / "invalid", records)
    assert not (tmp_path / "target.db").exists()
