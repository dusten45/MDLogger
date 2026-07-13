"""SQLite 데이터 계층: 스키마, CRUD, 통계 쿼리.

연결은 호출자가 ``connect()`` 로 만들어 함수에 넘긴다(테스트는 ``:memory:`` 사용).
played_at 은 로컬 ISO 타임스탬프 'YYYY-MM-DDTHH:MM:SS' 로 저장한다.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .paths import DB_PATH, ensure_data_dir

# 내보내기/표시 공용 컬럼 순서 (스키마와 동일)
COLUMNS = [
    "id",
    "played_at",
    "result",
    "turn_order",
    "my_deck",
    "opp_deck",
    "turns",
    "end_reason",
    "score_after",
    "note",
]

# insert/update 가 다루는 필드(자동 증가 id 제외)
_FIELDS = COLUMNS[1:]


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """연결 생성. 기본 경로일 때만 data 디렉터리를 보장한다."""
    if db_path == DB_PATH:
        ensure_data_dir()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
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
    # 기존 DB 마이그레이션: my_deck 컬럼이 없으면 추가(구버전 데이터 보존)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(games)").fetchall()]
    if "my_deck" not in cols:
        conn.execute("ALTER TABLE games ADD COLUMN my_deck TEXT")
    conn.commit()


def _payload(data: dict) -> dict:
    """insert/update 바인딩용 정규화 페이로드."""
    payload = {
        "played_at": data.get("played_at") or datetime.now().isoformat(timespec="seconds"),
        "result": data["result"],
        "turn_order": data["turn_order"],
        "my_deck": data.get("my_deck") or "",
        "opp_deck": data["opp_deck"],
        "turns": int(data["turns"]),
        "end_reason": data["end_reason"],
        "score_after": int(data["score_after"]),
        "note": data.get("note") or "",
    }
    return payload


def insert_game(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO games
            (played_at, result, turn_order, my_deck, opp_deck, turns, end_reason, score_after, note)
        VALUES
            (:played_at, :result, :turn_order, :my_deck, :opp_deck, :turns, :end_reason, :score_after, :note)
        """,
        _payload(data),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_game(conn: sqlite3.Connection, game_id: int, data: dict) -> None:
    payload = _payload(data)
    payload["id"] = game_id
    conn.execute(
        """
        UPDATE games SET
            played_at=:played_at, result=:result, turn_order=:turn_order,
            my_deck=:my_deck, opp_deck=:opp_deck, turns=:turns, end_reason=:end_reason,
            score_after=:score_after, note=:note
        WHERE id=:id
        """,
        payload,
    )
    conn.commit()


def delete_game(conn: sqlite3.Connection, game_id: int) -> None:
    conn.execute("DELETE FROM games WHERE id=?", (game_id,))
    conn.commit()


def get_game(conn: sqlite3.Connection, game_id: int) -> Optional[sqlite3.Row]:
    """id 로 단일 레코드 조회(없으면 None)."""
    return conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()


def get_last_game(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """가장 최근 레코드 1건(없으면 None). 되돌리기 확인 표시용."""
    return conn.execute(
        "SELECT * FROM games ORDER BY played_at DESC, id DESC LIMIT 1"
    ).fetchone()


def delete_last(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """가장 최근 레코드 1건을 삭제하고 그 행을 반환(없으면 None)."""
    row = get_last_game(conn)
    if row is None:
        return None
    conn.execute("DELETE FROM games WHERE id=?", (row["id"],))
    conn.commit()
    return row


def get_last_score(conn: sqlite3.Connection) -> int:
    """가장 최근 레코드의 누적 점수(없으면 0). 점수 프리필 기준."""
    row = conn.execute(
        "SELECT score_after FROM games ORDER BY played_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None or row["score_after"] is None:
        return 0
    return int(row["score_after"])


def get_last_my_deck(conn: sqlite3.Connection) -> str:
    """가장 최근 레코드의 내 덱(없으면 ""). 내 덱 프리필 기준."""
    row = conn.execute(
        "SELECT my_deck FROM games ORDER BY played_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None or row["my_deck"] is None:
        return ""
    return str(row["my_deck"])


def get_today_record(conn: sqlite3.Connection) -> tuple[int, int]:
    """오늘(로컬) 승/패 수."""
    today = date.today().isoformat()
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(result='win'), 0)  AS wins,
            COALESCE(SUM(result='lose'), 0) AS losses
        FROM games
        WHERE substr(played_at, 1, 10) = ?
        """,
        (today,),
    ).fetchone()
    return int(row["wins"]), int(row["losses"])


def count_games(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"])


def get_all_games(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM games ORDER BY played_at ASC, id ASC"
    ).fetchall()


def get_summary(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT result, turn_order, turns FROM games").fetchall()
    total = len(rows)
    wins = sum(1 for r in rows if r["result"] == "win")
    first = [r for r in rows if r["turn_order"] == "first"]
    second = [r for r in rows if r["turn_order"] == "second"]
    first_wins = sum(1 for r in first if r["result"] == "win")
    second_wins = sum(1 for r in second if r["result"] == "win")
    turns_vals = [r["turns"] for r in rows if r["turns"] is not None]

    def rate(w: int, n: int) -> float:
        return (w / n * 100.0) if n else 0.0

    return {
        "total": total,
        "wins": wins,
        "losses": total - wins,
        "winrate": rate(wins, total),
        "first_games": len(first),
        "first_wins": first_wins,
        "first_winrate": rate(first_wins, len(first)),
        "second_games": len(second),
        "second_wins": second_wins,
        "second_winrate": rate(second_wins, len(second)),
        "avg_turns": (sum(turns_vals) / len(turns_vals)) if turns_vals else 0.0,
    }


def get_score_series(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """시계열용: played_at 순으로 (played_at, score_after, result)."""
    return conn.execute(
        "SELECT played_at, score_after, result FROM games ORDER BY played_at ASC, id ASC"
    ).fetchall()


def get_deck_matchups(
    conn: sqlite3.Connection, turn_filter: Optional[str] = None
) -> list[dict]:
    """opp_deck 별 (games/wins/losses/winrate). turn_filter='first'|'second' 교차 필터."""
    sql = (
        "SELECT opp_deck,"
        " COUNT(*) AS games,"
        " COALESCE(SUM(result='win'), 0)  AS wins,"
        " COALESCE(SUM(result='lose'), 0) AS losses"
        " FROM games"
    )
    params: list = []
    if turn_filter in ("first", "second"):
        sql += " WHERE turn_order=?"
        params.append(turn_filter)
    sql += " GROUP BY opp_deck ORDER BY games DESC, opp_deck ASC"

    out: list[dict] = []
    for r in conn.execute(sql, params).fetchall():
        games = int(r["games"])
        wins = int(r["wins"])
        out.append(
            {
                "deck": r["opp_deck"],
                "games": games,
                "wins": wins,
                "losses": int(r["losses"]),
                "winrate": (wins / games * 100.0) if games else 0.0,
            }
        )
    return out
