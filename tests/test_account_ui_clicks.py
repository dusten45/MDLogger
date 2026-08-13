"""계정·동기화 다이얼로그의 실제 Qt 클릭 테스트 (open-items 항목 1 잔여분 B).

네트워크/세션에 의존하지 않는 부분에 집중한다: 게스트/등록 상태에 따라
`AccountDialog`가 보여주는 버튼과, 각 버튼이 내보내는 시그널, 닫기 동작을
offscreen에서 실제 클릭으로 구동해 검증한다. (로그인 제출·서버 동기화 등은
네트워크/세션 의존이라 범위에서 제외하고 기존 mock 단위 테스트가 담당한다.)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QPushButton

from mdlogger.game_service import GameService
from mdlogger.profiles import ProfileManager
from mdlogger.ui.account_views import AccountDialog
from mdlogger.ui.main_window import MainWindow

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


def _button_texts(dialog) -> list[str]:
    return [btn.text() for btn in dialog.findChildren(QPushButton)]


def test_open_account_button_in_main_window_emits_request(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("mdlogger.ui.main_window.load_decks", lambda: list(DECKS))
    profiles = ProfileManager(tmp_path)
    profile = profiles.guest()
    profiles.prepare_database(profile)
    games = GameService.open(profile.database_path)
    window = MainWindow(games, DECKS, profile)
    window.show()
    qapp.processEvents()

    fired = []
    window.account_requested.connect(lambda: fired.append(True))
    _click(_find_button(window._result_view, "계정"))
    qapp.processEvents()

    assert fired == [True]

    window.close_profile_windows()
    games.close()


def test_guest_account_dialog_shows_guest_only_actions_and_signals(qapp):
    dialog = AccountDialog("게스트", "게스트 · 로컬 저장", registered=False)
    dialog.show()
    qapp.processEvents()

    texts = _button_texts(dialog)
    assert "로그인 또는 회원가입" in texts
    assert "지금 동기화" in texts
    assert "닫기" in texts
    # 등록 전용 동작은 게스트에서 노출하지 않는다
    for hidden in (
        "다른 계정으로 전환",
        "로그아웃",
        "모든 기기에서 로그아웃",
        "내 데이터 내보내기",
        "계정 삭제",
    ):
        assert hidden not in texts

    sync_fired = []
    login_fired = []
    dialog.sync_requested.connect(lambda: sync_fired.append(True))
    dialog.login_requested.connect(lambda: login_fired.append(True))

    _click(_find_button(dialog, "지금 동기화"))
    qapp.processEvents()
    assert sync_fired == [True]
    assert login_fired == []

    _click(_find_button(dialog, "로그인 또는 회원가입"))
    qapp.processEvents()
    assert login_fired == [True]

    # 닫기 클릭 → 모달 거부로 닫힘, 상태 텍스트는 잔류(창만 닫힘)
    status_label = next(
        lbl for lbl in dialog.findChildren(QLabel) if lbl.text() == "게스트 · 로컬 저장"
    )
    assert status_label is not None
    _click(_find_button(dialog, "닫기"))
    qapp.processEvents()
    assert dialog.isVisible() is False

    dialog.close()


def test_registered_account_dialog_shows_registered_actions(qapp):
    dialog = AccountDialog("mdg_owner", "인증됨 · 로컬 저장", registered=True)
    dialog.show()
    qapp.processEvents()

    texts = _button_texts(dialog)
    for expected in (
        "지금 동기화",
        "다른 계정으로 전환",
        "로그아웃",
        "모든 기기에서 로그아웃",
        "내 데이터 내보내기",
        "계정 삭제",
        "닫기",
    ):
        assert expected in texts
    assert "로그인 또는 회원가입" not in texts

    # 닫기 클릭 → 모달 거부
    _click(_find_button(dialog, "닫기"))
    qapp.processEvents()
    assert dialog.isVisible() is False

    dialog.close()


def test_registered_dialog_shows_conflict_badge_when_conflicts_exist(qapp):
    dialog = AccountDialog(
        "mdg_owner", "인증됨 · 로컬 저장", registered=True, conflict_count=3
    )
    dialog.show()
    qapp.processEvents()

    assert _find_button(dialog, "동기화 충돌 3건 해결") is not None

    _click(_find_button(dialog, "닫기"))
    qapp.processEvents()
    dialog.close()
