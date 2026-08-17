"""공통 위젯(`SearchableDeckCombo` 등) 동작 테스트."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication

from mdlogger.ui.widgets import SearchableDeckCombo

_DECKS = ["서브테러", "테라나이트", "신유희왕"]


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def _make_combo(qapp: QApplication):
    combo = SearchableDeckCombo()
    combo.set_decks(_DECKS)
    combo.show()
    qapp.processEvents()
    return combo


def _send_input_method(line_edit, preedit: str, commit: str | None = None) -> None:
    """IME 입력 이벤트를 line edit에 보낸다 (조합 preedit 또는 commit)."""
    event = QInputMethodEvent(preedit, [])
    if commit is not None:
        event.setCommitString(commit)
    QApplication.sendEvent(line_edit, event)


def test_programmatic_deck_updates_do_not_open_the_completer(
    qapp: QApplication,
) -> None:
    combo = SearchableDeckCombo()
    combo.set_decks(_DECKS)
    combo.show()
    qapp.processEvents()

    completer = combo.completer()
    assert completer is not None
    popup = completer.popup()
    assert popup is not None
    assert not popup.isVisible()

    combo.setEditText("테")
    qapp.processEvents()
    assert not popup.isVisible()
    combo.close()


def test_completer_filters_on_commit(qapp: QApplication) -> None:
    combo = _make_combo(qapp)
    line_edit = combo.lineEdit()
    assert line_edit is not None
    line_edit.setFocus()
    qapp.processEvents()

    _send_input_method(line_edit, "", commit="테")
    qapp.processEvents()
    completer = combo.completer()
    assert completer is not None
    assert completer.completionPrefix() == "테"
    assert completer.completionCount() == 2  # '테' 포함 2개

    combo.close()


def test_completer_updates_during_ime_preedit(qapp: QApplication) -> None:
    """한글 등 IME 조합(commit 전) 단계에서도 completer가 실시간으로 갱신돼야 한다."""
    combo = _make_combo(qapp)
    line_edit = combo.lineEdit()
    assert line_edit is not None
    line_edit.setFocus()
    qapp.processEvents()

    # 조합 중: '테' (commit 전) → 팝업이 뜨고 매칭 항목이 보여야 한다
    _send_input_method(line_edit, "테")
    qapp.processEvents()
    completer = combo.completer()
    assert completer is not None
    popup = completer.popup()
    assert popup is not None
    assert completer.completionPrefix() == "테"
    assert completer.completionCount() == 2
    assert popup.isVisible()

    # 조합 중: '테라' 로 확장 → 실시간으로 1개로 줄어든다
    _send_input_method(line_edit, "테라")
    qapp.processEvents()
    assert completer.completionPrefix() == "테라"
    assert completer.completionCount() == 1
    assert popup.isVisible()

    combo.close()


def test_completer_updates_when_text_set_without_textEdited(qapp: QApplication) -> None:
    """실제 Linux IME가 `textEdited` 없이 텍스트만 바꿔 commit하는 경우에도
    실시간 필터링·팝업이 떠야 한다 (`textChanged` 경로).
    """
    combo = _make_combo(qapp)
    line_edit = combo.lineEdit()
    assert line_edit is not None
    line_edit.setFocus()
    qapp.processEvents()

    # setText는 textEdited가 아닌 textChanged만 발화한다 (일부 IME commit과 동일)
    line_edit.setText("테")
    qapp.processEvents()
    completer = combo.completer()
    assert completer is not None
    popup = completer.popup()
    assert popup is not None
    assert completer.completionPrefix() == "테"
    assert completer.completionCount() == 2
    assert popup.isVisible()

    line_edit.setText("테라")
    qapp.processEvents()
    assert completer.completionPrefix() == "테라"
    assert completer.completionCount() == 1
    assert popup.isVisible()

    combo.close()


def test_completer_hides_popup_when_no_match_during_preedit(qapp: QApplication) -> None:
    combo = _make_combo(qapp)
    line_edit = combo.lineEdit()
    assert line_edit is not None
    line_edit.setFocus()
    qapp.processEvents()

    # 매칭이 없는 조합 중에는 팝업이 떠 있으면 안 된다
    _send_input_method(line_edit, "ㅁㄴㅇ")
    qapp.processEvents()
    completer = combo.completer()
    assert completer is not None
    popup = completer.popup()
    assert popup is not None
    assert completer.completionCount() == 0
    assert not popup.isVisible()

    combo.close()
