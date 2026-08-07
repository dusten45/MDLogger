"""db 계층 단위 테스트 (인메모리 SQLite)."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from mdlogger import db


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def sample(**over):
    base = dict(
        played_at="2026-06-19T10:00:00",
        result="win",
        turn_order="first",
        my_deck="스네이크아이",
        opp_deck="블루아이즈",
        turns=5,
        end_reason="regular",
        score_after=2600,
        note="",
    )
    base.update(over)
    return base


def _today_at(t: str) -> str:
    return f"{date.today().isoformat()}T{t}"


def test_insert_and_get_all():
    conn = make_conn()
    gid = db.insert_game(conn, sample())
    assert gid == 1
    rows = db.get_all_games(conn)
    assert len(rows) == 1
    assert rows[0]["opp_deck"] == "블루아이즈"
    assert rows[0]["result"] == "win"


def test_played_at_autofill():
    conn = make_conn()
    data = sample()
    data.pop("played_at")
    db.insert_game(conn, data)
    row = db.get_all_games(conn)[0]
    assert row["played_at"] and "T" in row["played_at"]


def test_last_score_prefill():
    conn = make_conn()
    assert db.get_last_score(conn) == 0  # 빈 DB -> 0
    db.insert_game(conn, sample(played_at="2026-06-19T10:00:00", score_after=2600))
    db.insert_game(conn, sample(played_at="2026-06-19T10:05:00", score_after=1300))
    assert db.get_last_score(conn) == 1300


def test_today_record():
    conn = make_conn()
    db.insert_game(conn, sample(played_at=_today_at("10:00:00"), result="win"))
    db.insert_game(conn, sample(played_at=_today_at("10:05:00"), result="lose"))
    db.insert_game(conn, sample(played_at="2020-01-01T10:00:00", result="win"))
    assert db.get_today_record(conn) == (1, 1)


def test_delete_last():
    conn = make_conn()
    db.insert_game(conn, sample(played_at="2026-06-19T10:00:00"))
    db.insert_game(conn, sample(played_at="2026-06-19T10:05:00", opp_deck="엑조디아"))
    removed = db.delete_last(conn)
    assert removed is not None
    assert removed["opp_deck"] == "엑조디아"
    assert len(db.get_all_games(conn)) == 1
    # 마지막 점수도 직전 레코드 기준으로 복원
    assert db.get_last_score(conn) == 2600


def test_delete_last_on_empty():
    conn = make_conn()
    assert db.delete_last(conn) is None


def test_update_game():
    conn = make_conn()
    gid = db.insert_game(conn, sample())
    db.update_game(
        conn, gid, sample(opp_deck="엔디미온", score_after=5200, result="lose")
    )
    row = db.get_all_games(conn)[0]
    assert row["opp_deck"] == "엔디미온"
    assert row["score_after"] == 5200
    assert row["result"] == "lose"


def test_summary_and_matchups():
    conn = make_conn()
    db.insert_game(
        conn, sample(turn_order="first", result="win", opp_deck="블루아이즈", turns=4)
    )
    db.insert_game(
        conn, sample(turn_order="first", result="lose", opp_deck="블루아이즈", turns=6)
    )
    db.insert_game(
        conn, sample(turn_order="second", result="win", opp_deck="엑조디아", turns=8)
    )

    s = db.get_summary(conn)
    assert s["total"] == 3
    assert s["wins"] == 2
    assert s["losses"] == 1
    assert abs(s["winrate"] - 66.6667) < 0.01
    assert s["first_games"] == 2
    assert abs(s["first_winrate"] - 50.0) < 1e-6
    assert s["second_games"] == 1
    assert abs(s["second_winrate"] - 100.0) < 1e-6
    assert abs(s["avg_turns"] - 6.0) < 1e-6

    m = {r["deck"]: r for r in db.get_deck_matchups(conn)}
    assert m["블루아이즈"]["games"] == 2
    assert m["블루아이즈"]["wins"] == 1
    assert m["블루아이즈"]["losses"] == 1
    assert abs(m["블루아이즈"]["winrate"] - 50.0) < 1e-6

    second_only = db.get_deck_matchups(conn, turn_filter="second")
    assert len(second_only) == 1
    assert second_only[0]["deck"] == "엑조디아"


def test_summary_empty():
    conn = make_conn()
    s = db.get_summary(conn)
    assert s["total"] == 0
    assert s["winrate"] == 0.0
    assert s["avg_turns"] == 0.0


def test_my_deck_roundtrip_and_prefill():
    conn = make_conn()
    assert db.get_last_my_deck(conn) == ""  # 빈 DB
    db.insert_game(conn, sample(my_deck="스네이크아이"))
    db.insert_game(conn, sample(played_at="2026-06-19T10:05:00", my_deck="티아라멘츠"))
    assert db.get_all_games(conn)[0]["my_deck"] == "스네이크아이"
    assert db.get_last_my_deck(conn) == "티아라멘츠"  # 직전값 프리필 기준


def test_update_keeps_my_deck():
    conn = make_conn()
    gid = db.insert_game(conn, sample(my_deck="스네이크아이"))
    db.update_game(conn, gid, sample(my_deck="센츄리온", opp_deck="엑조디아"))
    row = db.get_game(conn, gid)
    assert row is not None
    assert row["my_deck"] == "센츄리온"
    assert row["opp_deck"] == "엑조디아"


def test_migration_adds_my_deck():
    """my_deck 컬럼이 없는 구버전 DB도 init_db 가 ALTER 로 보강."""
    conn = db.connect(":memory:")
    conn.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, played_at TEXT, result TEXT,"
        " turn_order TEXT, opp_deck TEXT, turns INTEGER, end_reason TEXT,"
        " score_after INTEGER, note TEXT)"
    )
    conn.execute(
        "INSERT INTO games (played_at, result, turn_order, opp_deck, turns,"
        " end_reason, score_after, note)"
        " VALUES ('2026-06-19T10:00:00','win','first','블루아이즈',5,'regular',2600,'')"
    )
    conn.commit()

    db.init_db(conn)  # 마이그레이션 수행
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(games)").fetchall()]
    assert "my_deck" in cols
    assert db.get_all_games(conn)[0]["my_deck"] is None  # 기존 행은 NULL

    db.insert_game(conn, sample(my_deck="천년 사안"))
    assert db.get_last_my_deck(conn) == "천년 사안"


def test_game_changes_and_outbox_commit_together():
    conn = make_conn()

    game_id = db.insert_game(conn, sample())
    inserted = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    insert_event = conn.execute(
        "SELECT * FROM sync_outbox ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert inserted["sync_id"] == insert_event["game_sync_id"]
    assert insert_event["operation"] == "upsert"

    db.update_game(conn, game_id, sample(note="수정"))
    assert (
        conn.execute("SELECT sync_status FROM games WHERE id=?", (game_id,)).fetchone()[
            0
        ]
        == "pending"
    )
    assert conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 2

    db.delete_game(conn, game_id)
    deleted = conn.execute(
        "SELECT deleted_at FROM games WHERE id=?", (game_id,)
    ).fetchone()
    delete_event = conn.execute(
        "SELECT operation FROM sync_outbox ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert deleted["deleted_at"] is not None
    assert delete_event["operation"] == "delete"
    assert db.get_game(conn, game_id) is None
    assert db.count_games(conn) == 0


def test_outbox_failure_rolls_back_game_insert():
    conn = make_conn()
    conn.execute(
        """
        CREATE TRIGGER reject_outbox BEFORE INSERT ON sync_outbox
        BEGIN
            SELECT RAISE(ABORT, 'outbox unavailable');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="outbox unavailable"):
        db.insert_game(conn, sample())

    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 0


def test_outbox_failure_rolls_back_game_update_and_delete():
    conn = make_conn()
    game_id = db.insert_game(conn, sample(note="원본"))
    conn.execute("DELETE FROM sync_outbox")
    conn.execute(
        """
        CREATE TRIGGER reject_outbox BEFORE INSERT ON sync_outbox
        BEGIN
            SELECT RAISE(ABORT, 'outbox unavailable');
        END
        """
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="outbox unavailable"):
        db.update_game(conn, game_id, sample(note="변경"))
    row = conn.execute(
        "SELECT note, deleted_at FROM games WHERE id=?", (game_id,)
    ).fetchone()
    assert row["note"] == "원본"
    assert row["deleted_at"] is None

    with pytest.raises(sqlite3.IntegrityError, match="outbox unavailable"):
        db.delete_game(conn, game_id)
    row = conn.execute(
        "SELECT note, deleted_at FROM games WHERE id=?", (game_id,)
    ).fetchone()
    assert row["note"] == "원본"
    assert row["deleted_at"] is None
