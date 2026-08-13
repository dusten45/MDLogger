"""단색 SVG 아이콘 로드·테마 리컬러·fallback 테스트 (단계 4).

아이콘은 `importlib.resources`로 패키지 데이터에서 읽고, `_ThemeIconEngine`이
paint 시점의 테마 색상으로 다시 칠한다. 라이트/다크와 disabled 상태가 색상
토큰을 따르며, SVG가 없으면 None 으로 돌아가 호출자가 텍스트로 동작을 설명할
수 있음을 검증한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QApplication

from mdlogger.ui import icons
from mdlogger.ui.theme import DARK_COLORS, LIGHT_COLORS


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def test_known_icon_names_load():
    for name in ("undo", "minus", "plus"):
        icon = icons.load_icon(name)
        assert icon is not None
        assert not icon.isNull()


def test_unknown_icon_name_returns_none():
    assert icons.load_icon("does-not-exist") is None


def test_icons_bundled_in_package():
    for name, filename in icons._ICON_FILES.items():
        svg = icons._svg_bytes(name)
        assert svg is not None, f"{name} ({filename}) 번들 누락"
        assert svg.lstrip().startswith(b"<svg")


def test_application_icon_bundled_and_loads(qapp):
    icon = icons.application_icon()
    assert icon is not None, "번들 앱 아이콘(DuelistCup.png) 누락"
    assert not icon.isNull()


def test_tint_pixmap_is_square_and_tinted(qapp):
    svg = icons._svg_bytes("plus")
    assert svg is not None
    pixmap = icons._tint_pixmap(svg, QColor("#112233"), QSize(24, 24))
    assert pixmap.size() == QSize(24, 24)
    # plus 아이콘의 중심은 세로·가로 획이 교차해 불투명 → 칠한 색이어야 한다
    center = pixmap.toImage().pixelColor(12, 12)
    assert center.alpha() > 0
    assert center.name().upper() == "#112233"


def _make_engine(name: str) -> icons._ThemeIconEngine:
    svg = icons._svg_bytes(name)
    assert svg is not None
    return icons._ThemeIconEngine(svg)


def _render_center_color(engine: icons._ThemeIconEngine, mode: QIcon.Mode) -> str:
    pixmap = engine.pixmap(QSize(24, 24), mode, QIcon.State.Off)
    return pixmap.toImage().pixelColor(12, 12).name().upper()


def test_engine_renders_theme_specific_text_color(qapp):
    app = qapp
    engine = _make_engine("plus")
    app.setProperty("themeMode", "light")
    assert _render_center_color(engine, QIcon.Mode.Normal) == (
        LIGHT_COLORS.text_primary.upper()
    )
    app.setProperty("themeMode", "dark")
    assert _render_center_color(engine, QIcon.Mode.Normal) == (
        DARK_COLORS.text_primary.upper()
    )
    app.setProperty("themeMode", None)


def test_engine_disabled_mode_uses_disabled_color(qapp):
    app = qapp
    engine = _make_engine("minus")
    app.setProperty("themeMode", "light")
    assert _render_center_color(engine, QIcon.Mode.Disabled) == (
        LIGHT_COLORS.text_disabled.upper()
    )
    app.setProperty("themeMode", None)


def test_engine_active_mode_uses_accent_color(qapp):
    app = qapp
    engine = _make_engine("plus")
    app.setProperty("themeMode", "dark")
    assert _render_center_color(engine, QIcon.Mode.Active) == (
        DARK_COLORS.accent.upper()
    )
    app.setProperty("themeMode", None)
