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

from .environment import current_environment_id
from .migrations import MigrationResult, migrate
from .models import StandingKind
from .paths import DB_PATH, ensure_data_dir, secure_data_file, secure_sidecars

# 내보내기/표시 공용 컬럼 순서 (spec §6.6 논리 재배치, score_after 제거)
COLUMNS = [
    "id",
    "played_at",
    "result",
    "standing_kind",
    "play_context_id",
    "turn_order",
    "my_deck",
    "opp_deck",
    "turns",
    "end_reason",
    "rank_tier_before",
    "rank_tier_after",
    "rank_division_before",
    "rank_division_after",
    "rating_before",
    "rating_after",
    "event_points_before",
    "event_points_after",
    "note",
]

# insert/update 가 다루는 필드(자동 증가 id 제외)
_FIELDS = COLUMNS[1:]

# insert/update SQL이 함께 다루는 동기화·서버 필드
_SYNC_FIELDS = (
    "sync_id",
    "local_updated_at",
    "sync_status",
    "timezone_offset_minutes",
    "environment_version_id",
)


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
        secure_sidecars(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> MigrationResult:
    """지원되는 모든 구버전 DB를 최신 로컬 스키마로 올린다."""
    return migrate(conn)


def _timezone_offset_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


# sync_outbox 에 기록하는 payload 계약 버전 (spec §4.1, v1 → v2).
PAYLOAD_VERSION = 2


def _int_or_none(value) -> int | None:
    """정수 또는 None으로 정규화. 빈 문자열/None은 None으로."""
    if value is None or value == "":
        return None
    return int(value)


def _payload(data: dict) -> dict:
    """insert/update 바인딩용 정규화 페이로드.

    모드(``standing_kind``)에 따라 해당 전후 스냅샷 필드만 채운다 (spec §2.4,
    §2.5-1). ``score_after``는 컬럼 자체가 없다(레거시 없음, 정책 B-a').
    """
    payload = {
        "played_at": data.get("played_at")
        or datetime.now().isoformat(timespec="seconds"),
        "result": data["result"],
        "turn_order": data["turn_order"],
        "my_deck": data.get("my_deck") or "",
        "opp_deck": data["opp_deck"],
        "turns": int(data["turns"]),
        "end_reason": data["end_reason"],
        "note": data.get("note") or "",
        "standing_kind": data.get("standing_kind"),
        "play_context_id": data.get("play_context_id"),
        "rank_tier_before": None,
        "rank_tier_after": None,
        "rank_division_before": None,
        "rank_division_after": None,
        "rating_before": None,
        "rating_after": None,
        "event_points_before": None,
        "event_points_after": None,
    }
    kind = payload["standing_kind"]
    if kind == StandingKind.EVENT_POINTS.value:
        payload["event_points_before"] = _int_or_none(data.get("event_points_before"))
        payload["event_points_after"] = _int_or_none(data.get("event_points_after"))
    elif kind == StandingKind.RANK.value:
        payload["rank_tier_before"] = data.get("rank_tier_before")
        payload["rank_tier_after"] = data.get("rank_tier_after")
        payload["rank_division_before"] = _int_or_none(data.get("rank_division_before"))
        payload["rank_division_after"] = _int_or_none(data.get("rank_division_after"))
    elif kind == StandingKind.RATING.value:
        payload["rating_before"] = _int_or_none(data.get("rating_before"))
        payload["rating_after"] = _int_or_none(data.get("rating_after"))
    else:
        raise ValueError(f"유효하지 않은 standing_kind: {kind!r}")
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
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            row["sync_id"],
            operation,
            PAYLOAD_VERSION,
            json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")),
            created_at,
        ),
    )


def _environment_id() -> str | None:
    """신규 기록에 부여할 현재 환경 version id(없으면 None). 테스트 주입용."""
    return current_environment_id()


def insert_game(conn: sqlite3.Connection, data: dict) -> int:
    payload = _payload(data)
    changed_at = _now_iso()
    payload.update(
        sync_id=str(uuid.uuid4()),
        local_updated_at=changed_at,
        sync_status="pending",
        timezone_offset_minutes=_timezone_offset_minutes(),
        environment_version_id=_environment_id(),
    )
    with conn:
        cur = conn.execute(
            """
            INSERT INTO games
                (played_at, result, turn_order, my_deck, opp_deck, turns,
                 end_reason, note, standing_kind, play_context_id,
                 rank_tier_before, rank_tier_after,
                 rank_division_before, rank_division_after,
                 rating_before, rating_after,
                 event_points_before, event_points_after,
                 sync_id, local_updated_at, sync_status,
                 timezone_offset_minutes, environment_version_id)
            VALUES
                (:played_at, :result, :turn_order, :my_deck, :opp_deck, :turns,
                 :end_reason, :note, :standing_kind, :play_context_id,
                 :rank_tier_before, :rank_tier_after,
                 :rank_division_before, :rank_division_after,
                 :rating_before, :rating_after,
                 :event_points_before, :event_points_after,
                 :sync_id, :local_updated_at, :sync_status,
                 :timezone_offset_minutes, :environment_version_id)
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
                end_reason=:end_reason, note=:note,
                standing_kind=:standing_kind, play_context_id=:play_context_id,
                rank_tier_before=:rank_tier_before,
                rank_tier_after=:rank_tier_after,
                rank_division_before=:rank_division_before,
                rank_division_after=:rank_division_after,
                rating_before=:rating_before, rating_after=:rating_after,
                event_points_before=:event_points_before,
                event_points_after=:event_points_after,
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


# 존재하지 않는 모드/문맥을 표시하는 sentinel. 실제 play_context_id와 겹치지
# 않는 값으로, SQL 필터에 그대로 전달되어도 매칭되는 행이 없어 빈 결과가 된다.
_UNKNOWN_CONTEXT = "\x00__unknown_mode__"


def _resolve_context(conn: sqlite3.Connection, mode_id: str | None) -> str | None:
    """play_modes.id → play_context_id.

    - ``mode_id=None``(전체)이면 ``None``을 돌려준다.
    - 존재하지 않는 모드나 ``play_context_id``가 NULL인 모드는 실제 문맥과
      절대 겹치지 않는 sentinel("``_UNKNOWN_CONTEXT``")을 돌려준다. 호출부는
      ``ctx is not None`` 필터를 그대로 적용해 '알 수 없는 모드는 빈 결과'가 되고,
      전체 통계로 오인하지 않는다(spec §5.7, §5.8).
    """
    if mode_id is None:
        return None
    row = conn.execute(
        "SELECT play_context_id FROM play_modes WHERE id=?", (mode_id,)
    ).fetchone()
    if row is None or row["play_context_id"] is None:
        return _UNKNOWN_CONTEXT
    return str(row["play_context_id"])


def get_last_score(conn: sqlite3.Connection, mode_id: str | None = None) -> int:
    """해당 점수 모드(문맥)의 마지막 누적 점수(없으면 0). 점수 프리필 기준 (spec §5.1)."""
    ctx = _resolve_context(conn, mode_id)
    if mode_id is not None and ctx is None:
        return 0
    if ctx is None:
        row = conn.execute(
            "SELECT event_points_after FROM games WHERE deleted_at IS NULL"
            " AND event_points_after IS NOT NULL"
            " ORDER BY played_at DESC, id DESC LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT event_points_after FROM games WHERE deleted_at IS NULL"
            " AND play_context_id=? AND event_points_after IS NOT NULL"
            " ORDER BY played_at DESC, id DESC LIMIT 1",
            (ctx,),
        ).fetchone()
    if row is None or row["event_points_after"] is None:
        return 0
    return int(row["event_points_after"])


def get_last_standing(conn: sqlite3.Connection, mode_id: str) -> tuple[str, int] | None:
    """해당 시즌 랭크 모드의 마지막 (티어, 단계). 없으면 None (spec §5.2)."""
    ctx = _resolve_context(conn, mode_id)
    if ctx is None:
        return None
    row = conn.execute(
        "SELECT rank_tier_after, rank_division_after FROM games"
        " WHERE deleted_at IS NULL AND play_context_id=?"
        " AND rank_tier_after IS NOT NULL AND rank_division_after IS NOT NULL"
        " ORDER BY played_at DESC, id DESC LIMIT 1",
        (ctx,),
    ).fetchone()
    if (
        row is None
        or row["rank_tier_after"] is None
        or row["rank_division_after"] is None
    ):
        return None
    return str(row["rank_tier_after"]), int(row["rank_division_after"])


def get_last_rating(conn: sqlite3.Connection, mode_id: str) -> int | None:
    """해당 시즌 레이팅 모드의 마지막 rating_after. 없으면 None (spec §5.3)."""
    ctx = _resolve_context(conn, mode_id)
    if ctx is None:
        return None
    row = conn.execute(
        "SELECT rating_after FROM games WHERE deleted_at IS NULL AND play_context_id=?"
        " AND rating_after IS NOT NULL"
        " ORDER BY played_at DESC, id DESC LIMIT 1",
        (ctx,),
    ).fetchone()
    if row is None or row["rating_after"] is None:
        return None
    return int(row["rating_after"])


def get_play_modes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """전체 모드 기준정보 (로컬 play_modes 캐시, sort_order 순)."""
    return conn.execute(
        "SELECT * FROM play_modes ORDER BY sort_order ASC, id ASC"
    ).fetchall()


def get_active_play_modes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """활성 모드만 (A3). 선택·기록 가능한 모드 목록."""
    return conn.execute(
        "SELECT * FROM play_modes WHERE is_active=1 ORDER BY sort_order ASC, id ASC"
    ).fetchall()


def get_play_mode(conn: sqlite3.Connection, mode_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM play_modes WHERE id=?", (mode_id,)).fetchone()


def insert_play_mode(conn: sqlite3.Connection, data: dict) -> None:
    """로컬 play_modes 캐시에 모드를 추가한다 (개발자 모드 관리 도구)."""
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO play_modes
                (id, standing_kind, display_name, play_context_id, sort_order,
                 is_active, season_label, created_at)
            VALUES (:id, :standing_kind, :display_name, :play_context_id,
                    :sort_order, :is_active, :season_label, :created_at)
            """,
            {
                "id": data["id"],
                "standing_kind": data["standing_kind"],
                "display_name": data["display_name"],
                "play_context_id": data.get("play_context_id"),
                "sort_order": data.get("sort_order") or 0,
                "is_active": 1 if data.get("is_active", True) else 0,
                "season_label": data.get("season_label"),
                "created_at": data.get("created_at") or _now_iso(),
            },
        )


def update_play_mode(conn: sqlite3.Connection, mode_id: str, data: dict) -> None:
    """로컬 play_modes 캐시 행을 갱신한다 (개발자 모드 관리 도구)."""
    with conn:
        cursor = conn.execute(
            """
            UPDATE play_modes SET
                standing_kind=:standing_kind,
                display_name=:display_name,
                play_context_id=:play_context_id,
                sort_order=:sort_order,
                is_active=:is_active,
                season_label=:season_label
            WHERE id=:id
            """,
            {
                "id": mode_id,
                "standing_kind": data["standing_kind"],
                "display_name": data["display_name"],
                "play_context_id": data.get("play_context_id"),
                "sort_order": data.get("sort_order") or 0,
                "is_active": 1 if data.get("is_active", True) else 0,
                "season_label": data.get("season_label"),
            },
        )
    if cursor.rowcount != 1:
        raise KeyError(f"Mode {mode_id} does not exist")


def delete_play_mode(conn: sqlite3.Connection, mode_id: str) -> None:
    """로컬 play_modes 캐시 행을 삭제한다 (개발자 모드 관리 도구)."""
    with conn:
        cursor = conn.execute("DELETE FROM play_modes WHERE id=?", (mode_id,))
    if cursor.rowcount != 1:
        raise KeyError(f"Mode {mode_id} does not exist")


def get_default_mode(conn: sqlite3.Connection) -> str | None:
    """database_metadata.default_mode (play_modes.id 또는 'last_used')."""
    row = conn.execute(
        "SELECT default_mode FROM database_metadata WHERE id=1"
    ).fetchone()
    return str(row["default_mode"]) if row is not None else None


def set_default_mode(conn: sqlite3.Connection, mode_id: str | None) -> None:
    with conn:
        conn.execute(
            "UPDATE database_metadata SET default_mode=? WHERE id=1", (mode_id,)
        )


def get_last_used_mode(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT last_used_mode FROM database_metadata WHERE id=1"
    ).fetchone()
    return str(row["last_used_mode"]) if row is not None else None


def set_last_used_mode(conn: sqlite3.Connection, mode_id: str | None) -> None:
    with conn:
        conn.execute(
            "UPDATE database_metadata SET last_used_mode=? WHERE id=1", (mode_id,)
        )


def resolve_default_mode_id(conn: sqlite3.Connection) -> str | None:
    """앱 시작 시 사용할 기본 모드 id를 결정한다 (spec §6.1).

    default_mode가 특정 모드면 그 모드, 'last_used'(또는 NULL)면 last_used_mode,
    그것도 없으면 첫 활성 모드. 활성 모드가 없으면 None.
    """
    active = get_active_play_modes(conn)
    if not active:
        return None
    default = get_default_mode(conn)
    if default and default != "last_used":
        for mode in active:
            if mode["id"] == default:
                return str(mode["id"])
    last_used = get_last_used_mode(conn)
    if last_used:
        for mode in active:
            if mode["id"] == last_used:
                return str(mode["id"])
    return str(active[0]["id"])


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


def get_summary(conn: sqlite3.Connection, mode_id: str | None = None) -> dict:
    ctx = _resolve_context(conn, mode_id)
    sql = """
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
    params: list = []
    if ctx is not None:
        sql += " AND play_context_id=?"
        params.append(ctx)
    row = conn.execute(sql, params).fetchone()

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


def get_score_series(
    conn: sqlite3.Connection, mode_id: str | None = None
) -> list[sqlite3.Row]:
    """선택 점수 모드 하나의 시계열 (A1: 전체에서는 그리지 않음, spec §5.4)."""
    ctx = _resolve_context(conn, mode_id)
    if ctx is None:
        return []
    return conn.execute(
        "SELECT played_at, event_points_after, result, standing_kind FROM games"
        " WHERE deleted_at IS NULL AND play_context_id=?"
        " AND standing_kind='event_points'"
        " ORDER BY played_at ASC, id ASC",
        (ctx,),
    ).fetchall()


def get_rank_series(
    conn: sqlite3.Connection, mode_id: str | None = None
) -> list[sqlite3.Row]:
    """랭크전만: (played_at, rank_tier_after, rank_division_after) (spec §5.5)."""
    ctx = _resolve_context(conn, mode_id)
    if ctx is None:
        return []
    return conn.execute(
        "SELECT played_at, rank_tier_after, rank_division_after, result FROM games"
        " WHERE deleted_at IS NULL AND play_context_id=?"
        " AND standing_kind='rank' AND rank_tier_after IS NOT NULL"
        " ORDER BY played_at ASC, id ASC",
        (ctx,),
    ).fetchall()


def get_rating_series(
    conn: sqlite3.Connection, mode_id: str | None = None
) -> list[sqlite3.Row]:
    """레이팅전만: (played_at, rating_after) (spec §5.6)."""
    ctx = _resolve_context(conn, mode_id)
    if ctx is None:
        return []
    return conn.execute(
        "SELECT played_at, rating_after, result FROM games"
        " WHERE deleted_at IS NULL AND play_context_id=?"
        " AND standing_kind='rating' AND rating_after IS NOT NULL"
        " ORDER BY played_at ASC, id ASC",
        (ctx,),
    ).fetchall()


def get_deck_matchups(
    conn: sqlite3.Connection,
    turn_filter: str | None = None,
    mode_id: str | None = None,
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
    ctx = _resolve_context(conn, mode_id)
    if ctx is not None:
        sql += " AND play_context_id=?"
        params.append(ctx)
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
