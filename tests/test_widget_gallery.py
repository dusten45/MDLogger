"""개발용 위젯 gallery 테스트 (단계 5 이후 항목 1).

픽셀 스크린샷 비교는 하지 않는다(스펙 §16). offscreen에서 WidgetGallery를 생성하고
라이트→다크 전환 후에도 위젯이 크래시 없이 생성·배치되는지 확인한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPushButton,
    QRadioButton,
)

from mdlogger.ui.theme import ThemeMode
from mdlogger.ui.widget_gallery import WidgetGallery


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def test_widget_gallery_instantiates_and_lays_out(qapp: QApplication) -> None:
    gallery = WidgetGallery()
    gallery.show()
    qapp.processEvents()

    # 주요 위젯·상태가 한 화면에 배치됨
    buttons = gallery.findChildren(QPushButton)
    assert any(
        b.property("role") in ("primary", "secondary", "ghost", "danger")
        for b in buttons
    )
    assert any(b.property("role") == "result-win" for b in buttons)
    assert any(b.property("role") == "result-loss" for b in buttons)
    assert any(not b.isEnabled() for b in buttons)  # disabled 상태 포함
    assert gallery.findChildren(QLineEdit)
    assert gallery.findChildren(QComboBox)
    assert gallery.findChildren(QCheckBox)

    gallery.close()


def test_widget_gallery_toggles_light_dark_without_crash(
    qapp: QApplication,
) -> None:
    gallery = WidgetGallery()
    gallery.show()
    qapp.processEvents()

    assert gallery.theme_controller is not None
    assert qapp.property("themeMode") == "light"
    # 라이트 QSS 배경 토큰이 적용되어 있어야 한다 (픽셀 비교가 아닌 QSS 내용 검증)
    assert "#F5F7FA" in qapp.styleSheet()

    gallery.set_theme_mode(ThemeMode.DARK)
    qapp.processEvents()
    assert qapp.property("themeMode") == "dark"
    assert "#11151B" in qapp.styleSheet()
    assert "#F5F7FA" not in qapp.styleSheet()

    gallery.set_theme_mode(ThemeMode.LIGHT)
    qapp.processEvents()
    assert qapp.property("themeMode") == "light"
    assert "#F5F7FA" in qapp.styleSheet()

    gallery.close()


def test_theme_toggle_combo_drives_theme_change(qapp: QApplication) -> None:
    """콤보 선택(사용자 조작 경로)이 실제로 테마를 바꾸는지 확인한다.

    itemData는 StrEnum을 문자열로 돌려주므로 `_on_theme_changed`가 다시
    ThemeMode로 변환해야 한다 — 이 경로는 set_theme_mode 직접 호출로는 검증되지
    않는다(회귀 방지).
    """
    gallery = WidgetGallery()
    gallery.show()
    qapp.processEvents()

    combo = gallery._theme_combo
    dark_index = combo.findData(ThemeMode.DARK)
    assert dark_index >= 0

    combo.setCurrentIndex(
        dark_index
    )  # 사용자가 '다크'를 선택한 것과 동일한 시그널 경로
    qapp.processEvents()
    assert qapp.property("themeMode") == "dark"
    assert "#11151B" in qapp.styleSheet()

    combo.setCurrentIndex(combo.findData(ThemeMode.LIGHT))
    qapp.processEvents()
    assert qapp.property("themeMode") == "light"

    gallery.close()


def test_radio_buttons_are_independent(qapp: QApplication) -> None:
    """QRadioButton의 미선택/선택됨/비활성이 서로 독립적으로 유지돼야 한다.

    같은 부모를 공유하면 QRadioButton이 자동 상호 배타 그룹이 되어, 하나를
    누르면 다른 것(특히 비활성)이 풀리는 문제가 있었다. 갤러리는 각 상태를
    동시에 보여줘야 하므로 비배타 그룹으로 묶는다.
    """
    gallery = WidgetGallery()
    radios = {r.text(): r for r in gallery.findChildren(QRadioButton)}
    unchecked = radios["미선택"]
    checked = radios["선택됨"]
    disabled = radios["비활성"]

    assert checked.isChecked() and disabled.isChecked()
    unchecked.click()  # 미선택을 눌러도 다른 것들이 풀리지 않아야 한다
    qapp.processEvents()
    assert unchecked.isChecked()
    assert checked.isChecked()
    assert disabled.isChecked()

    gallery.close()


def test_escape_does_not_close_gallery(qapp: QApplication) -> None:
    """ESC를 눌러도 개발용 갤러리가 닫히지 않아야 한다(QDialog 기본 reject 방지)."""
    gallery = WidgetGallery()
    gallery.show()
    qapp.processEvents()

    key = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    gallery.keyPressEvent(key)  # reject()가 호출되지 않으면 대화상자가 닫히지 않는다
    qapp.processEvents()

    assert gallery.isVisible()

    gallery.close()
