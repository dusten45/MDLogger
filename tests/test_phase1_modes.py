"""1단계: 모드/랭크 도메인·DB·모드 관리 테스트 (spec §8)."""

from __future__ import annotations

import pytest

from mdlogger import db
from mdlogger.models import RankStanding, RankTierError


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def _game(**over):
    base = {
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "내 덱",
        "opp_deck": "상대 덱",
        "turns": 4,
        "end_reason": "regular",
        "standing_kind": "event_points",
        "play_context_id": "dc_cup_2026_08",
        "event_points_before": 0,
        "event_points_after": 1000,
        "note": "",
    }
    base.update(over)
    return base


# ----- 도메인: RankStanding (spec §2.2, §8.1) -----


def test_rank_standing_promote_within_tier():
    assert RankStanding("gold", 3).promoted() == RankStanding("gold", 2)


def test_rank_standing_promote_across_tier():
    assert RankStanding("gold", 1).promoted() == RankStanding("platinum", 5)


def test_rank_standing_promote_at_master_1_keeps():
    assert RankStanding("master", 1).promoted() == RankStanding("master", 1)


def test_rank_standing_demote_within_tier():
    assert RankStanding("gold", 3).demoted() == RankStanding("gold", 4)


def test_rank_standing_demote_across_tier():
    assert RankStanding("gold", 5).demoted() == RankStanding("silver", 1)


def test_rank_standing_demote_at_rookie_5_keeps():
    assert RankStanding("rookie", 5).demoted() == RankStanding("rookie", 5)


def test_rank_standing_invalid_division():
    with pytest.raises(RankTierError):
        RankStanding("gold", 0)
    with pytest.raises(RankTierError):
        RankStanding("gold", 6)
    with pytest.raises(RankTierError):
        RankStanding("unknown", 3)


def test_rank_standing_label():
    assert RankStanding("gold", 3).label == "골드 3"


# ----- DB: 모드 프리필/시리즈 (spec §5) -----


def test_get_last_standing_and_rating():
    conn = make_conn()
    assert db.get_last_standing(conn, "rank-2026-08") is None
    assert db.get_last_rating(conn, "rating-2026-08") is None

    db.insert_game(
        conn,
        _game(
            standing_kind="rank",
            play_context_id="rank_2026_08",
            rank_tier_before="gold",
            rank_division_before=3,
            rank_tier_after="gold",
            rank_division_after=2,
        ),
    )
    db.insert_game(
        conn,
        _game(
            played_at="2026-08-07T11:00:00",
            standing_kind="rating",
            play_context_id="rating_2026_08",
            rating_before=1000,
            rating_after=1020,
        ),
    )
    assert db.get_last_standing(conn, "rank-2026-08") == ("gold", 2)
    assert db.get_last_rating(conn, "rating-2026-08") == 1020


def test_get_rank_series_and_rating_series():
    conn = make_conn()
    db.insert_game(
        conn,
        _game(
            standing_kind="rank",
            play_context_id="rank_2026_08",
            rank_tier_before="gold",
            rank_division_before=3,
            rank_tier_after="gold",
            rank_division_after=2,
        ),
    )
    db.insert_game(
        conn,
        _game(
            standing_kind="rating",
            play_context_id="rating_2026_08",
            rating_before=1000,
            rating_after=1020,
        ),
    )
    rank_series = db.get_rank_series(conn, "rank-2026-08")
    assert len(rank_series) == 1
    assert rank_series[0]["rank_tier_after"] == "gold"
    assert rank_series[0]["rank_division_after"] == 2
    rating_series = db.get_rating_series(conn, "rating-2026-08")
    assert len(rating_series) == 1
    assert rating_series[0]["rating_after"] == 1020


def test_get_score_series_mode_filter_and_all_empty():
    conn = make_conn()
    db.insert_game(conn, _game(event_points_after=1000))
    db.insert_game(
        conn,
        _game(
            played_at="2026-08-07T11:00:00",
            play_context_id="wcq_2026",
            event_points_after=500,
        ),
    )
    series = db.get_score_series(conn, "dc-cup-2026-08")
    assert len(series) == 1
    assert series[0]["event_points_after"] == 1000
    # A1: 전체에서는 그래프를 그리지 않는다 (spec §5.4)
    assert db.get_score_series(conn, None) == []


def test_get_summary_mode_filter():
    conn = make_conn()
    db.insert_game(conn, _game())
    db.insert_game(
        conn,
        _game(played_at="2026-08-07T11:00:00", play_context_id="wcq_2026"),
    )
    assert db.get_summary(conn)["total"] == 2
    assert db.get_summary(conn, "dc-cup-2026-08")["total"] == 1
    assert db.get_summary(conn, "wcq-2026")["total"] == 1


def test_get_deck_matchups_mode_filter():
    conn = make_conn()
    db.insert_game(conn, _game(opp_deck="블루아이즈"))
    db.insert_game(
        conn,
        _game(
            played_at="2026-08-07T11:00:00",
            play_context_id="wcq_2026",
            opp_deck="블루아이즈",
        ),
    )
    all_matchups = db.get_deck_matchups(conn)
    assert all_matchups[0]["games"] == 2
    dc_matchups = db.get_deck_matchups(conn, mode_id="dc-cup-2026-08")
    assert dc_matchups[0]["games"] == 1


# ----- DB: play_modes CRUD + 기본/마지막 모드 (spec §6.4) -----


def test_play_modes_crud_and_default_last_mode():
    conn = make_conn()
    assert len(db.get_play_modes(conn)) == 4
    assert len(db.get_active_play_modes(conn)) == 4

    db.insert_play_mode(
        conn,
        {
            "id": "wcq-2027",
            "standing_kind": "event_points",
            "display_name": "2027 WCQ",
            "play_context_id": "wcq_2027",
            "sort_order": 9,
            "is_active": True,
            "season_label": "2027",
        },
    )
    assert db.get_play_mode(conn, "wcq-2027") is not None
    db.update_play_mode(
        conn,
        "wcq-2027",
        {
            "standing_kind": "event_points",
            "display_name": "2027 WCQ",
            "play_context_id": "wcq_2027",
            "sort_order": 9,
            "is_active": False,
            "season_label": "2027",
        },
    )
    updated = db.get_play_mode(conn, "wcq-2027")
    assert updated is not None and updated["is_active"] == 0
    db.delete_play_mode(conn, "wcq-2027")
    assert db.get_play_mode(conn, "wcq-2027") is None

    # 기본/마지막 모드 결정 (spec §6.1)
    assert db.resolve_default_mode_id(conn) == "rank-2026-08"  # 첫 활성
    db.set_last_used_mode(conn, "dc-cup-2026-08")
    assert db.resolve_default_mode_id(conn) == "dc-cup-2026-08"
    db.set_default_mode(conn, "wcq-2026")
    assert db.resolve_default_mode_id(conn) == "wcq-2026"
    db.set_default_mode(conn, "last_used")
    assert db.resolve_default_mode_id(conn) == "dc-cup-2026-08"


# ----- DB: outbox payload v2 (spec §4.4) -----


def test_outbox_payload_version_is_2():
    conn = make_conn()
    db.insert_game(conn, _game())
    row = conn.execute("SELECT payload_version FROM sync_outbox").fetchone()
    assert row[0] == 2


# ----- 모드 기준정보 동기화 (spec §4.8) -----


def test_sync_play_modes_rebuilds_local_cache():
    conn = make_conn()
    remote = [
        {
            "id": "rank-2026-09",
            "standing_kind": "rank",
            "display_name": "랭크",
            "play_context_id": "rank_2026_09",
            "sort_order": 0,
            "is_active": True,
            "season_label": "26.09",
        },
        {
            "id": "dc-cup-2026-09",
            "standing_kind": "event_points",
            "display_name": "26.09 DC컵",
            "play_context_id": "dc_cup_2026_09",
            "sort_order": 2,
            "is_active": False,
            "season_label": "26.09",
        },
    ]
    from mdlogger.game_sync.modes import sync_play_modes

    count = sync_play_modes(conn, remote)
    assert count == 2
    modes = db.get_play_modes(conn)
    assert [m["id"] for m in modes] == ["rank-2026-09", "dc-cup-2026-09"]
    dc = db.get_play_mode(conn, "dc-cup-2026-09")
    assert dc is not None and dc["is_active"] == 0


# ----- 모드 관리 대화상자 CRUD (spec §6.7) -----


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


def test_settings_dialog_sets_default_mode(qapp):
    from mdlogger.game_service import GameService
    from mdlogger.ui.settings_dialog import SettingsDialog

    games = GameService.open(":memory:")
    dlg = SettingsDialog(games)
    dlg._default.setValue("wcq-2026")
    dlg._on_save()
    assert games.get_default_mode() == "wcq-2026"
    games.close()


def test_mode_manager_dialog_crud(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from mdlogger.game_service import GameService
    from mdlogger.ui.mode_manager import ModeManagerDialog

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    games = GameService.open(":memory:")
    dlg = ModeManagerDialog(games)
    assert dlg._table.rowCount() == 4

    # 추가
    games.insert_play_mode(
        {
            "id": "wcq-2027",
            "standing_kind": "event_points",
            "display_name": "2027 WCQ",
            "play_context_id": "wcq_2027",
            "sort_order": 9,
            "is_active": True,
            "season_label": "2027",
        }
    )
    dlg._refresh()
    assert dlg._table.rowCount() == 5

    # 활성/비활성 전환
    dlg._table.selectRow(4)
    dlg._toggle_active()
    toggled = games.get_play_mode("wcq-2027")
    assert toggled is not None and toggled["is_active"] == 0

    # 삭제
    dlg._table.selectRow(4)
    dlg._delete()
    assert games.get_play_mode("wcq-2027") is None

    games.close()
