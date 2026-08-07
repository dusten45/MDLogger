"""SQLite 데이터 계층: 스키마, CRUD, 통계 쿼리.

연결은 호출자가 ``connect()`` 로 만들어 함수에 넘긴다(테스트는 ``:memory:`` 사용).
played_at 은 로컬 ISO 타임스탬프 'YYYY-MM-DDTHH:MM:SS' 로 저장한다.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

from .migrations import MigrationResult, migrate
from .paths import DB_PATH, ensure_data_dir, secure_data_file

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
    """연결 생성. 기본 경로일 때만 데이터 경로와 전용 권한을 보장한다."""
    is_default_path = db_path == DB_PATH
    if is_default_path:
        ensure_data_dir()
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    if is_default_path:
        secure_data_file(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> MigrationResult:
    """지원되는 모든 구버전 DB를 최신 로컬 스키마로 올린다."""
    return migrate(conn)


def _timezone_offset_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


def _payload(data: dict) -> dict:
    """insert/update 바인딩용 정규화 페이로드."""
    payload = {
        "played_at": data.get("played_at")
        or datetime.now().isoformat(timespec="seconds"),
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


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _enqueue_game_change(
    conn: sqlite3.Connection, game_id: int, operation: str, created_at: str
) -> None:
    row = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"Game {game_id} does not exist")
    conn.execute(
        """
        INSERT INTO sync_outbox
            (game_sync_id, operation, payload_version, payload, created_at)
        VALUES (?, ?, 1, ?, ?)
        """,
        (
            row["sync_id"],
            operation,
            json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")),
            created_at,
        ),
    )


def insert_game(conn: sqlite3.Connection, data: dict) -> int:
    payload = _payload(data)
    changed_at = _now_iso()
    payload.update(
        sync_id=str(uuid.uuid4()),
        local_updated_at=changed_at,
        sync_status="pending",
        timezone_offset_minutes=_timezone_offset_minutes(),
    )
    with conn:
        cur = conn.execute(
            """
            INSERT INTO games
                (played_at, result, turn_order, my_deck, opp_deck, turns,
                 end_reason, score_after, note, sync_id, local_updated_at, sync_status,
                 timezone_offset_minutes)
            VALUES
                (:played_at, :result, :turn_order, :my_deck, :opp_deck, :turns,
                 :end_reason, :score_after, :note, :sync_id, :local_updated_at,
                 :sync_status, :timezone_offset_minutes)
            """,
            payload,
        )
        if cur.lastrowid is None:
            raise RuntimeError("SQLite did not return an inserted row ID")
        game_id = cur.lastrowid
        _enqueue_game_change(conn, game_id, "upsert", changed_at)
    return game_id


def update_game(conn: sqlite3.Connection, game_id: int, data: dict) -> None:
    payload = _payload(data)
    changed_at = _now_iso()
    payload.update(id=game_id, local_updated_at=changed_at)
    with conn:
        cursor = conn.execute(
            """
            UPDATE games SET
                played_at=:played_at, result=:result, turn_order=:turn_order,
                my_deck=:my_deck, opp_deck=:opp_deck, turns=:turns,
                end_reason=:end_reason, score_after=:score_after, note=:note,
                local_updated_at=:local_updated_at, sync_status='pending',
                last_sync_error=NULL
            WHERE id=:id AND deleted_at IS NULL
            """,
            payload,
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Game {game_id} does not exist")
        _enqueue_game_change(conn, game_id, "upsert", changed_at)


def delete_game(conn: sqlite3.Connection, game_id: int) -> None:
    changed_at = _now_iso()
    with conn:
        cursor = conn.execute(
            """
            UPDATE games
            SET deleted_at=?, local_updated_at=?, sync_status='pending',
                last_sync_error=NULL
            WHERE id=? AND deleted_at IS NULL
            """,
            (changed_at, changed_at, game_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Game {game_id} does not exist")
        _enqueue_game_change(conn, game_id, "delete", changed_at)


def get_game(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row | None:
    """id 로 단일 레코드 조회(없으면 None)."""
    return conn.execute(
        "SELECT * FROM games WHERE id=? AND deleted_at IS NULL", (game_id,)
    ).fetchone()


def get_last_game(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """가장 최근 레코드 1건(없으면 None). 되돌리기 확인 표시용."""
    return conn.execute(
        "SELECT * FROM games WHERE deleted_at IS NULL"
        " ORDER BY played_at DESC, id DESC LIMIT 1"
    ).fetchone()


def delete_last(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """가장 최근 레코드 1건을 삭제하고 그 행을 반환(없으면 None)."""
    row = get_last_game(conn)
    if row is None:
        return None
    delete_game(conn, row["id"])
    return row


def get_last_score(conn: sqlite3.Connection) -> int:
    """가장 최근 레코드의 누적 점수(없으면 0). 점수 프리필 기준."""
    row = conn.execute(
        "SELECT score_after FROM games WHERE deleted_at IS NULL"
        " ORDER BY played_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None or row["score_after"] is None:
        return 0
    return int(row["score_after"])


def get_last_my_deck(conn: sqlite3.Connection) -> str:
    """가장 최근 레코드의 내 덱(없으면 ""). 내 덱 프리필 기준."""
    row = conn.execute(
        "SELECT my_deck FROM games WHERE deleted_at IS NULL"
        " ORDER BY played_at DESC, id DESC LIMIT 1"
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
        WHERE deleted_at IS NULL AND substr(played_at, 1, 10) = ?
        """,
        (today,),
    ).fetchone()
    return int(row["wins"]), int(row["losses"])


def count_games(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM games WHERE deleted_at IS NULL"
        ).fetchone()["n"]
    )


def get_all_games(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM games WHERE deleted_at IS NULL ORDER BY played_at ASC, id ASC"
    ).fetchall()


def get_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(result='win'), 0) AS wins,
            COALESCE(SUM(turn_order='first'), 0) AS first_games,
            COALESCE(SUM(turn_order='first' AND result='win'), 0) AS first_wins,
            COALESCE(SUM(turn_order='second'), 0) AS second_games,
            COALESCE(SUM(turn_order='second' AND result='win'), 0) AS second_wins,
            AVG(turns) AS avg_turns
        FROM games
        WHERE deleted_at IS NULL
        """
    ).fetchone()

    def rate(w: int, n: int) -> float:
        return (w / n * 100.0) if n else 0.0

    total = int(row["total"])
    wins = int(row["wins"])
    first_games = int(row["first_games"])
    second_games = int(row["second_games"])
    return {
        "total": total,
        "wins": wins,
        "losses": total - wins,
        "winrate": rate(wins, total),
        "first_games": first_games,
        "first_wins": int(row["first_wins"]),
        "first_winrate": rate(int(row["first_wins"]), first_games),
        "second_games": second_games,
        "second_wins": int(row["second_wins"]),
        "second_winrate": rate(int(row["second_wins"]), second_games),
        "avg_turns": row["avg_turns"] or 0.0,
    }


def get_score_series(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """시계열용: played_at 순으로 (played_at, score_after, result)."""
    return conn.execute(
        "SELECT played_at, score_after, result FROM games WHERE deleted_at IS NULL"
        " ORDER BY played_at ASC, id ASC"
    ).fetchall()


def get_deck_matchups(
    conn: sqlite3.Connection, turn_filter: str | None = None
) -> list[dict]:
    """opp_deck 별 (games/wins/losses/winrate). turn_filter='first'|'second' 교차 필터."""
    sql = (
        "SELECT opp_deck,"
        " COUNT(*) AS games,"
        " COALESCE(SUM(result='win'), 0)  AS wins,"
        " COALESCE(SUM(result='lose'), 0) AS losses"
        " FROM games"
        " WHERE deleted_at IS NULL"
    )
    params: list = []
    if turn_filter in ("first", "second"):
        sql += " AND turn_order=?"
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
