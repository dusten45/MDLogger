"""핵심 기록 흐름의 실제 Qt 클릭·다이얼로그 통합 테스트 (open-items 항목 1).

기존 검증은 offscreen 스모크와 mock 기반 단위 테스트로 구성되어 있고, 실제
위젯을 클릭해 화면1(결과 선택) → 화면2(상세 입력) → 저장/취소 흐름을 구동하는
자동 테스트가 없었다. 여기서는 Qt 스택 오프스크린에서 `QTest.mouseClick`으로
실제 버튼을 눌러 저장·취소·유효성 검증을 확인한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from mdlogger.game_service import GameService
from mdlogger.profiles import ProfileManager
from mdlogger.ui.main_window import MainWindow

DECKS = ["융합 덱", "싱크로 덱"]


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def _click(button: QPushButton) -> None:
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def _find_button(parent, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"버튼을 찾지 못함: {text!r}")


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
