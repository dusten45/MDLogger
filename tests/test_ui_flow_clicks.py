"""핵심 기록 흐름의 실제 Qt 클릭·다이얼로그 통합 테스트 (open-items 항목 1).

기존 검증은 offscreen 스모크와 mock 기반 단위 테스트로 구성되어 있고, 실제
위젯을 클릭해 화면1(결과 선택) → 화면2(상세 입력) → 저장/취소 흐름을 구동하는
자동 테스트가 없었다. 여기서는 Qt 스택 오프스크린에서 `QTest.mouseClick`으로
실제 버튼을 눌러 저장·취소·유효성 검증을 확인한다.

이 파일의 잔여분(open-items #1)으로 통계 창 렌더링과 편집/삭제 다이얼로그 흐름도
추가한다. 편집·삭제는 모달(`exec()`)로 열므로, 클릭 직전에 `QTimer.singleShot`으로
모달 이벤트 루프 안에서의 상호작용을 예약해 실제 다이얼로그를 구동한다.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QWidget,
)

from mdlogger import db, migrations
from mdlogger.game_service import GameService
from mdlogger.profiles import ProfileManager
from mdlogger.ui.edit_dialog import EditDialog
from mdlogger.ui.main_window import MainWindow
from mdlogger.ui.stats_window import StatsWindow

DECKS = ["융합 덱", "싱크로 덱"]


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def _click(button: QAbstractButton) -> None:
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def _find_button(parent, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"버튼을 찾지 못함: {text!r}")


def _create_old_guest_db(path: Path) -> None:
    """실제 마이그레이션 1~4를 순서대로 적용해 v4 로컬 스키마를 그대로 재현한다.

    (환경 버전 컬럼은 v5에서 추가되므로 v4까지로 끝낸다.)"""
    conn = db.connect(path)
    conn.execute("PRAGMA user_version = 0")
    for version in range(1, 5):  # 1~4 적용해 환경 버전 컬럼(v5) 전까지 재현
        migrations.MIGRATIONS[version](conn)
        conn.execute(f"PRAGMA user_version = {version}")
    conn.execute(
        "INSERT INTO games (played_at, result, turn_order, my_deck, opp_deck, turns,"
        " end_reason, score_after, note, sync_id, local_updated_at, sync_status)"
        " VALUES ('2026-08-07T10:00:00', 'win', 'first', '융합 덱', '블루아이즈', 5,"
        "        'regular', 2600, '구버전에서 마이그레이션됨', 'old1',"
        "        '2026-08-07T10:00:00', 'synced')"
    )
    conn.commit()
    conn.close()


def _open_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[MainWindow, GameService, ProfileManager]:
    # `MainWindow.show_detail`은 폼을 열 때 `load_decks()`(실제 decks.json)로 덱
    # 목록을 덮어쓴다. 테스트를 결정적으로 만들기 위해 고정 덱 목록으로 패치한다.
    monkeypatch.setattr("mdlogger.ui.main_window.load_decks", lambda: list(DECKS))
    profiles = ProfileManager(tmp_path)
    profile = profiles.guest()
    profiles.prepare_database(profile)
    games = GameService.open(profile.database_path)
    window = MainWindow(games, DECKS, profile)
    window.show()
    return window, games, profiles


def _fill_form(window: MainWindow, *, my_deck: str, opp_deck: str) -> None:
    form = window._detail_view.form
    form._my_deck.setEditText(my_deck)
    form._deck.setEditText(opp_deck)
    form._score.setText("1200")
    form._note.setText("통합 테스트 메모")


def _make_record(**overrides: str | int) -> dict:
    """통계/편집 테스트의 결정적 레코드를 만든다 (DetailForm.values()와 동일 키)."""
    record: dict = {
        "result": "win",
        "turn_order": "first",
        "my_deck": "융합 덱",
        "opp_deck": "싱크로 덱",
        "turns": 3,
        "end_reason": "regular",
        "score_after": 1200,
        "note": "",
    }
    record.update(overrides)
    return record


def _open_stats(window: MainWindow, qapp: QApplication) -> StatsWindow:
    """화면1의 '통계 / 기록' 버튼을 실제 클릭해 통계 창을 연다."""
    _click(_find_button(window._result_view, "통계 / 기록"))
    qapp.processEvents()
    stats = window._stats
    assert stats is not None
    return stats


def _select_records_row(stats: StatsWindow) -> None:
    """기록 관리 탭으로 전환하고 첫 행을 선택한다."""
    tabs = stats.findChild(QTabWidget)
    assert tabs is not None
    tabs.setCurrentIndex(1)
    stats._rtable.selectRow(0)
    stats._rtable.setCurrentCell(0, 0)


def _cell_text(table: QTableWidget, row: int, col: int) -> str:
    """테이블 셀의 표시 텍스트. 누락된 셀은 실패로 처리한다."""
    item = table.item(row, col)
    assert item is not None, f"셀({row},{col})이 비어 있다"
    return item.text()


def _schedule_modal_action(
    qapp: QApplication, action: Callable[[QWidget], None]
) -> None:
    """모달(`exec()`)이 열리기 전에, 그 이벤트 루프 안에서 action(modal)을 예약한다.

    편집/삭제 등의 모달 다이얼로그는 호출 스레드 블로킹으로 열리므로, 다음 클릭이
    `exec()`를 시작하자마자 단발 타이머가 발화해 실제 다이얼로그 위젯을 조작한다.
    """

    def _worker() -> None:
        modal = qapp.activeModalWidget()
        if modal is None or not modal.isVisible():
            raise AssertionError("모달 다이얼로그가 열리지 않았다")
        qapp.processEvents()
        action(modal)

    QTimer.singleShot(0, _worker)


def _confirm_delete(qapp: QApplication) -> None:
    def _interact(modal: QWidget) -> None:
        assert isinstance(modal, QMessageBox)
        yes = modal.button(QMessageBox.StandardButton.Yes)
        assert yes is not None
        _click(yes)

    _schedule_modal_action(qapp, _interact)


def test_save_flow_clicks_win_and_persists_record(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    window, games, _ = _open_window(tmp_path, monkeypatch)
    qapp.processEvents()

    # 화면1: 오늘 전적이 0승 0패로 시작
    assert window._stack.currentWidget() is window._result_view
    assert "0승 0패" in window._result_view._today.text()

    # '승' 결과 버튼 실제 클릭 → 화면2(상세 입력)로 이동
    _click(_find_button(window._result_view, "승"))
    qapp.processEvents()
    assert window._stack.currentWidget() is window._detail_view
    assert window._current_result == "win"

    # 상세를 채우고 '확인' 실제 클릭 → 저장 후 화면1 복귀
    _fill_form(window, my_deck="융합 덱", opp_deck="싱크로 덱")
    qapp.processEvents()
    _click(_find_button(window._detail_view, "확인"))
    qapp.processEvents()

    assert window._stack.currentWidget() is window._result_view
    assert games.count_games() == 1
    row = games.get_last_game()
    assert row is not None
    assert row["result"] == "win"
    assert row["opp_deck"] == "싱크로 덱"
    assert row["score_after"] == 1200
    assert row["note"] == "통합 테스트 메모"
    assert "1승 0패" in window._result_view._today.text()

    window.close_profile_windows()
    games.close()


def test_cancel_flow_returns_to_result_without_saving(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    window, games, _ = _open_window(tmp_path, monkeypatch)
    qapp.processEvents()

    # '패' 결과 선택 → 상세로 이동 후, 아무 입력 없이 결과 배너(뒤로) 클릭
    _click(_find_button(window._result_view, "패"))
    qapp.processEvents()
    assert window._stack.currentWidget() is window._detail_view
    assert window._current_result == "lose"

    _click(window._detail_view._banner)
    qapp.processEvents()
    assert window._stack.currentWidget() is window._result_view
    assert window._current_result is None
    assert games.count_games() == 0

    window.close_profile_windows()
    games.close()


def test_confirm_without_deck_selection_shows_validation_and_does_not_save(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    window, games, _ = _open_window(tmp_path, monkeypatch)
    qapp.processEvents()

    _click(_find_button(window._result_view, "승"))
    qapp.processEvents()
    assert window._stack.currentWidget() is window._detail_view

    # 내 덱/상대 덱을 선택하지 않은 채 확인 클릭 → 유효성 메시지, 저장 안 됨
    _click(_find_button(window._detail_view, "확인"))
    qapp.processEvents()

    assert "정확히 선택하세요" in window._detail_view._status.text()
    assert window._stack.currentWidget() is window._detail_view
    assert games.count_games() == 0

    window.close_profile_windows()
    games.close()


def test_stats_window_opens_and_renders_summary_and_records(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    window, games, _ = _open_window(tmp_path, monkeypatch)
    window.refresh_header()

    stats = _open_stats(window, qapp)
    _select_records_row(stats)

    # 데이터가 없을 때: 빈 요약/기록 테이블
    assert stats._card_total._value.text() == "0판 0승 0패"
    assert stats._rtable.rowCount() == 0

    # 기록 추가 후 새로고침 → 통계 창에 반영
    games.insert_game(_make_record(note="통계용 기록"))
    window.refresh_header()
    stats.refresh()

    assert stats._card_total._value.text() == "1판 1승 0패"
    assert stats._rtable.rowCount() == 1
    assert _cell_text(stats._rtable, 0, 2) == "승"  # 결과
    assert _cell_text(stats._rtable, 0, 5) == "싱크로 덱"  # 상대 덱
    assert _cell_text(stats._rtable, 0, 8) == "1200"  # 점수
    assert _cell_text(stats._rtable, 0, 9) == "통계용 기록"  # 메모

    window.close_profile_windows()
    games.close()


def test_edit_dialog_saves_changes_and_toggles_result(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    window, games, _ = _open_window(tmp_path, monkeypatch)
    games.insert_game(_make_record(note="원본 메모"))
    window.refresh_header()

    stats = _open_stats(window, qapp)
    _select_records_row(stats)

    def _interact(dlg: QWidget) -> None:
        assert isinstance(dlg, EditDialog)
        dlg._result.setValue("lose")  # 결과 토글 (승 → 패)
        dlg.form._note.setText("수정된 메모")
        _click(_find_button(dlg, "저장"))

    _schedule_modal_action(qapp, _interact)
    _click(_find_button(stats, "편집"))
    qapp.processEvents()

    gid = int(games.get_all_games()[0]["id"])
    updated = games.get_game(gid)
    assert updated is not None
    assert updated["result"] == "lose"
    assert updated["note"] == "수정된 메모"
    # 저장 쪽 실제 새로고침 경로(데이터_changed → refresh)를 통해 테이블 갱신 확인
    assert _cell_text(stats._rtable, 0, 2) == "패"
    assert _cell_text(stats._rtable, 0, 9) == "수정된 메모"

    window.close_profile_windows()
    games.close()


def test_edit_dialog_cancel_discards_changes(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    window, games, _ = _open_window(tmp_path, monkeypatch)
    games.insert_game(_make_record(note="원본 메모"))
    window.refresh_header()

    stats = _open_stats(window, qapp)
    _select_records_row(stats)

    def _interact(dlg: QWidget) -> None:
        assert isinstance(dlg, EditDialog)
        dlg.form._note.setText("반영되면 안 됨")
        _click(_find_button(dlg, "취소"))

    _schedule_modal_action(qapp, _interact)
    _click(_find_button(stats, "편집"))
    qapp.processEvents()

    gid = int(games.get_all_games()[0]["id"])
    unchanged = games.get_game(gid)
    assert unchanged is not None
    assert unchanged["note"] == "원본 메모"
    assert _cell_text(stats._rtable, 0, 9) == "원본 메모"

    window.close_profile_windows()
    games.close()


def test_delete_selected_removes_record_after_confirm(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    window, games, _ = _open_window(tmp_path, monkeypatch)
    games.insert_game(_make_record())
    window.refresh_header()

    stats = _open_stats(window, qapp)
    _select_records_row(stats)
    assert stats._rtable.rowCount() == 1

    _confirm_delete(qapp)
    _click(_find_button(stats, "삭제"))
    qapp.processEvents()

    assert games.count_games() == 0
    assert stats._rtable.rowCount() == 0

    window.close_profile_windows()
    games.close()


def test_startup_migrates_old_db_and_retains_backup(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """구버전(v4) DB를 실제 시작 경로로 열면 마이그레이션·백업 보존이 일어나고
    이후 실제 클릭 기록이 남는다. (마이그레이션/백업 확인 다이얼로그는 없으므로
    시작 경로 전체를 구동한다.)"""
    monkeypatch.setattr("mdlogger.ui.main_window.load_decks", lambda: list(DECKS))
    profiles = ProfileManager(tmp_path)
    profile = profiles.guest()
    db_path = profile.database_path
    _create_old_guest_db(db_path)

    guest_dir = db_path.parent
    stale_v2 = guest_dir / "games.db.pre-migration-v2.bak"
    stale_v3 = guest_dir / "games.db.pre-migration-v3.bak"
    stale_v2.write_bytes(b"stale2")
    stale_v3.write_bytes(b"stale3")

    # 실제 시작 경로: 마이그레이션 + 검증된 백업 생성/보존 + 소유권 귀속
    profiles.prepare_database(profile)

    # 백업 보존(최신 1개): 새 v4 백업만 남고 이전 스테일 백업은 정리된다
    backups = sorted(p.name for p in guest_dir.glob("games.db.pre-migration-v*.bak"))
    assert backups == ["games.db.pre-migration-v4.bak"]
    backup = guest_dir / "games.db.pre-migration-v4.bak"
    assert backup.stat().st_size > 0
    if os.name != "nt":
        assert backup.stat().st_mode & 0o777 == 0o600
    assert not stale_v2.exists()
    assert not stale_v3.exists()

    # 실제 앱 창을 열어 마이그레이션된 DB를 구동
    games = GameService.open(profile.database_path)
    window = MainWindow(games, DECKS, profile)
    window.show()
    qapp.processEvents()

    # 실제 클릭으로 신규 기록 추가 → 마이그레이션된 DB에 저장
    _click(_find_button(window._result_view, "승"))
    qapp.processEvents()
    _fill_form(window, my_deck="융합 덱", opp_deck="싱크로 덱")
    qapp.processEvents()
    _click(_find_button(window._detail_view, "확인"))
    qapp.processEvents()

    assert games.count_games() == 2
    migrated = games.get_all_games()
    assert migrated[0]["sync_id"] == "old1"
    assert migrated[0]["note"] == "구버전에서 마이그레이션됨"
    # 신규 기록은 오프라인 → 환경 버전 추측 없이 NULL
    assert migrated[1]["environment_version_id"] is None

    window.close_profile_windows()
    games.close()
