"""강조색 프리셋과 글자 크기 배율 테스트 (계획 2, spec §5.1~§5.2)."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QFont

from mdlogger.ui.theme import (
    ACCENT_PRESETS,
    DARK_COLORS,
    LIGHT_COLORS,
    FontRole,
    ThemeMode,
    apply_ui_scale,
    colors_for_mode,
    contrast_ratio,
    current_ui_scale,
    font_for_role,
)


@pytest.fixture(autouse=True)
def _reset_ui_scale():
    yield
    apply_ui_scale(1.0)


def test_all_accent_presets_meet_contrast_targets() -> None:
    for preset in ACCENT_PRESETS.values():
        assert contrast_ratio(preset.light_text_on_accent, preset.light) >= 4.5
        assert contrast_ratio(preset.dark_text_on_accent, preset.dark) >= 4.5
        assert contrast_ratio(preset.light, LIGHT_COLORS.surface) >= 3.0
        assert contrast_ratio(preset.dark, DARK_COLORS.surface) >= 3.0


def test_blue_accent_returns_identity_constants() -> None:
    assert colors_for_mode(ThemeMode.LIGHT, accent="blue") is LIGHT_COLORS
    assert colors_for_mode(ThemeMode.DARK, accent="blue") is DARK_COLORS


def test_unknown_accent_falls_back_to_blue() -> None:
    assert colors_for_mode(ThemeMode.LIGHT, accent="red") is LIGHT_COLORS
    assert colors_for_mode(ThemeMode.DARK, accent="nope") is DARK_COLORS


def test_non_blue_accent_derives_accent_fields() -> None:
    colors = colors_for_mode(ThemeMode.LIGHT, accent="teal")
    assert colors.accent == ACCENT_PRESETS["teal"].light
    assert colors.text_on_accent == ACCENT_PRESETS["teal"].light_text_on_accent
    assert colors.chart_primary == ACCENT_PRESETS["teal"].light
    assert colors.accent != LIGHT_COLORS.accent

    dark = colors_for_mode(ThemeMode.DARK, accent="amber")
    assert dark.accent == ACCENT_PRESETS["amber"].dark
    assert dark.text_on_accent == ACCENT_PRESETS["amber"].dark_text_on_accent


def test_font_for_role_applies_ui_scale() -> None:
    base = QFont("Example Sans")
    base.setPointSizeF(10.0)

    apply_ui_scale(1.0)
    title_default = font_for_role(base, FontRole.TITLE)

    apply_ui_scale(1.25)
    title_scaled = font_for_role(base, FontRole.TITLE)

    assert current_ui_scale() == 1.25
    assert title_scaled.pointSizeF() == pytest.approx(title_default.pointSizeF() * 1.25)
