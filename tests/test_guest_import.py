"""게스트 DB에서 등록 계정 DB로의 비파괴 import 테스트."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mdlogger import db
from mdlogger.guest_import import GuestImportResult, import_guest_records
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
                "score_after": 1600 + index,
                "note": f"메모{index}",
            },
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
    assert [row["score_after"] for row in rows] == [1600, 1601, 1602]
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
        " end_reason, score_after, note, sync_id, sync_status)"
        " VALUES (?, 'win', 'first', '기존', 4, 'regular', 100, '기존메모', ?, 'synced')",
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
            "score_after": 1900,
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
