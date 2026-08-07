"""애플리케이션 테마 토큰과 생성 로직 테스트."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette

from mdlogger.ui.theme import (
    DARK_COLORS,
    LIGHT_COLORS,
    FontRole,
    ThemeMode,
    build_palette,
    build_stylesheet,
    colors_for_mode,
    contrast_ratio,
    font_for_role,
    resolve_theme_mode,
)


@pytest.mark.parametrize(
    ("scheme", "expected"),
    [
        (Qt.ColorScheme.Light, ThemeMode.LIGHT),
        (Qt.ColorScheme.Dark, ThemeMode.DARK),
        (Qt.ColorScheme.Unknown, ThemeMode.LIGHT),
    ],
)
def test_system_theme_resolution(scheme: Qt.ColorScheme, expected: ThemeMode) -> None:
    assert resolve_theme_mode(ThemeMode.SYSTEM, scheme) is expected


def test_explicit_theme_ignores_system_scheme() -> None:
    assert resolve_theme_mode(ThemeMode.LIGHT, Qt.ColorScheme.Dark) is ThemeMode.LIGHT
    assert resolve_theme_mode(ThemeMode.DARK, Qt.ColorScheme.Light) is ThemeMode.DARK


def test_colors_for_mode_falls_back_to_light_for_system() -> None:
    assert colors_for_mode(ThemeMode.LIGHT) is LIGHT_COLORS
    assert colors_for_mode(ThemeMode.DARK) is DARK_COLORS
    assert colors_for_mode(ThemeMode.SYSTEM) is LIGHT_COLORS


@pytest.mark.parametrize("colors", [LIGHT_COLORS, DARK_COLORS])
def test_representative_color_pairs_meet_contrast_targets(colors) -> None:
    assert contrast_ratio(colors.text_primary, colors.surface) >= 4.5
    assert contrast_ratio(colors.text_secondary, colors.surface) >= 4.5
    assert contrast_ratio(colors.text_on_accent, colors.accent) >= 4.5
    assert contrast_ratio(colors.border_strong, colors.surface) >= 3.0
    assert contrast_ratio(colors.focus_ring, colors.background) >= 3.0


def test_stylesheet_uses_semantic_roles_and_supported_qss() -> None:
    stylesheet = build_stylesheet(LIGHT_COLORS)

    assert 'QPushButton[role="primary"]' in stylesheet
    assert 'QPushButton[role="result-win"]' in stylesheet
    assert 'QFrame[surface="section"]' in stylesheet
    assert 'QLineEdit[invalid="true"]' in stylesheet
    assert stylesheet.rfind('QPushButton[role="primary"]:disabled') > stylesheet.rfind(
        'QPushButton[role="primary"] {'
    )
    assert "opacity" not in stylesheet


def test_palette_maps_semantic_surface_and_text_colors() -> None:
    palette = build_palette(DARK_COLORS)

    assert palette.color(QPalette.ColorRole.Window).name().upper() == "#11151B"
    assert palette.color(QPalette.ColorRole.Text).name().upper() == "#F2F4F7"
    assert palette.color(QPalette.ColorRole.Highlight).name().upper() == "#7EA2FF"


def test_font_roles_derive_from_system_font_without_changing_family() -> None:
    base = QFont("Example Sans")
    base.setPointSizeF(10.0)

    title = font_for_role(base, FontRole.TITLE)
    caption = font_for_role(base, FontRole.CAPTION)

    assert title.family() == base.family()
    assert title.pointSizeF() > base.pointSizeF()
    assert title.weight() == QFont.Weight.DemiBold
    assert caption.pointSizeF() >= 9.0
