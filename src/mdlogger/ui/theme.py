"""애플리케이션 전역 디자인 토큰과 라이트·다크 테마 적용."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QProxyStyle,
    QStyleFactory,
    QWidget,
)


class _ScaledStyle(QProxyStyle):
    """현재 UI 배율을 Qt 기본 스타일의 픽셀 메트릭에도 적용한다.

    명시적으로 QSS/레이아웃 값을 설정하지 않은 위젯의 기본 margin, indicator,
    목록 행 높이, 스크롤바 등도 앱 시작 배율에 맞춰 생성된다.
    """

    def __init__(self, base_style, ui_scale: float) -> None:
        super().__init__(base_style)
        self._ui_scale = ui_scale

    def set_ui_scale(self, ui_scale: float) -> None:
        self._ui_scale = ui_scale

    def pixelMetric(self, metric, option=None, widget=None) -> int:
        value = super().pixelMetric(metric, option, widget)
        return max(1, round(value * self._ui_scale)) if value > 0 else value


class ThemeMode(StrEnum):
    """사용자가 선택할 수 있는 테마 모드."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class FontRole(StrEnum):
    """시스템 기본 글꼴에서 파생하는 타이포그래피 역할."""

    DISPLAY = "display"
    TITLE = "title"
    SECTION = "section"
    BODY = "body"
    LABEL = "label"
    CAPTION = "caption"
    NUMERIC = "numeric"


@dataclass(frozen=True, slots=True)
class ColorTokens:
    """한 테마에서 사용하는 의미 기반 색상 토큰."""

    background: str
    surface: str
    surface_subtle: str
    surface_raised: str
    text_primary: str
    text_secondary: str
    text_disabled: str
    text_on_accent: str
    border: str
    border_strong: str
    divider: str
    focus_ring: str
    accent: str
    accent_hover: str
    accent_pressed: str
    selection: str
    success: str
    success_subtle: str
    danger: str
    danger_subtle: str
    warning: str
    warning_subtle: str
    chart_axis: str
    chart_grid: str
    chart_primary: str
    chart_secondary: str
    chart_marker: str


@dataclass(frozen=True, slots=True)
class AccentTokens:
    """강조색 프리셋의 라이트/다크 accent와 대비 검증된 text_on_accent."""

    light: str
    dark: str
    light_text_on_accent: str
    dark_text_on_accent: str


_ui_scale = 1.0
_application_base_font: QFont | None = None
_scaled_style: _ScaledStyle | None = None


def scaled(value: int) -> int:
    """100% 기준 크기를 현재 전역 UI 배율로 조정한다 (최소 1px)."""
    return max(1, round(value * _ui_scale))


class MetricTokens:
    """플랫폼·테마 독립 크기 토큰. 각 속성은 전역 UI 배율이 곱해진 값이다.

    ``motion_duration_ms``는 시간 값이므로 배율을 적용하지 않는다.
    """

    # 100% 기준 값
    _space_1: int = 4
    _space_2: int = 8
    _space_3: int = 12
    _space_4: int = 16
    _space_6: int = 24
    _space_8: int = 32
    _control_height_small: int = 34
    _control_height: int = 38
    _control_height_primary: int = 44
    _result_height: int = 104
    _radius_control: int = 8
    _radius_surface: int = 12
    _border_width: int = 1
    _focus_width: int = 2
    _icon_small: int = 16
    _icon_medium: int = 20
    _icon_large: int = 24
    _motion_duration_ms: int = 0

    @property
    def space_1(self) -> int:
        return scaled(self._space_1)

    @property
    def space_2(self) -> int:
        return scaled(self._space_2)

    @property
    def space_3(self) -> int:
        return scaled(self._space_3)

    @property
    def space_4(self) -> int:
        return scaled(self._space_4)

    @property
    def space_6(self) -> int:
        return scaled(self._space_6)

    @property
    def space_8(self) -> int:
        return scaled(self._space_8)

    @property
    def control_height_small(self) -> int:
        return scaled(self._control_height_small)

    @property
    def control_height(self) -> int:
        return scaled(self._control_height)

    @property
    def control_height_primary(self) -> int:
        return scaled(self._control_height_primary)

    @property
    def result_height(self) -> int:
        return scaled(self._result_height)

    @property
    def radius_control(self) -> int:
        return scaled(self._radius_control)

    @property
    def radius_surface(self) -> int:
        return scaled(self._radius_surface)

    @property
    def border_width(self) -> int:
        return scaled(self._border_width)

    @property
    def focus_width(self) -> int:
        return scaled(self._focus_width)

    @property
    def icon_small(self) -> int:
        return scaled(self._icon_small)

    @property
    def icon_medium(self) -> int:
        return scaled(self._icon_medium)

    @property
    def icon_large(self) -> int:
        return scaled(self._icon_large)

    @property
    def motion_duration_ms(self) -> int:
        return self._motion_duration_ms


METRICS = MetricTokens()

# 검증된 강조색 프리셋 (spec §2.2, §5.1). 각 프리셋은 라이트/다크 accent hex와
# WCAG 대비(accent vs text_on_accent ≥ 4.5:1, accent vs surface ≥ 3:1)를 통과하는
# text_on_accent를 담는다.
ACCENT_PRESETS: dict[str, AccentTokens] = {
    "blue": AccentTokens(
        light="#356AE6",
        dark="#7EA2FF",
        light_text_on_accent="#FFFFFF",
        dark_text_on_accent="#11151B",
    ),
    "indigo": AccentTokens(
        light="#4F46E5",
        dark="#A5B4FC",
        light_text_on_accent="#FFFFFF",
        dark_text_on_accent="#11151B",
    ),
    "teal": AccentTokens(
        light="#0F766E",
        dark="#5EEAD4",
        light_text_on_accent="#FFFFFF",
        dark_text_on_accent="#11151B",
    ),
    "magenta": AccentTokens(
        light="#A21CAF",
        dark="#F0ABFC",
        light_text_on_accent="#FFFFFF",
        dark_text_on_accent="#11151B",
    ),
    "amber": AccentTokens(
        light="#B45309",
        dark="#FCD34D",
        light_text_on_accent="#FFFFFF",
        dark_text_on_accent="#11151B",
    ),
}

LIGHT_COLORS = ColorTokens(
    background="#F5F7FA",
    surface="#FFFFFF",
    surface_subtle="#EEF2F6",
    surface_raised="#FFFFFF",
    text_primary="#18202A",
    text_secondary="#667085",
    text_disabled="#8A94A3",
    text_on_accent="#FFFFFF",
    border="#D8DEE8",
    border_strong="#7B8798",
    divider="#D8DEE8",
    focus_ring="#356AE6",
    accent="#356AE6",
    accent_hover="#2857C7",
    accent_pressed="#2048A8",
    selection="#DCE7FF",
    success="#168A5B",
    success_subtle="#E8F6EF",
    danger="#C43D4B",
    danger_subtle="#FCECEF",
    warning="#946200",
    warning_subtle="#FFF4D6",
    chart_axis="#667085",
    chart_grid="#D8DEE8",
    chart_primary="#356AE6",
    chart_secondary="#168A5B",
    chart_marker="#C43D4B",
)

DARK_COLORS = ColorTokens(
    background="#11151B",
    surface="#191F28",
    surface_subtle="#222A35",
    surface_raised="#252E3A",
    text_primary="#F2F4F7",
    text_secondary="#A7B0BE",
    text_disabled="#737E8E",
    text_on_accent="#11151B",
    border="#343E4D",
    border_strong="#667085",
    divider="#343E4D",
    focus_ring="#7EA2FF",
    accent="#7EA2FF",
    accent_hover="#95B3FF",
    accent_pressed="#668CE8",
    selection="#26395F",
    success="#52C78C",
    success_subtle="#17392B",
    danger="#FF7A86",
    danger_subtle="#45242B",
    warning="#F5B942",
    warning_subtle="#423616",
    chart_axis="#A7B0BE",
    chart_grid="#343E4D",
    chart_primary="#7EA2FF",
    chart_secondary="#52C78C",
    chart_marker="#FF7A86",
)


def colors_for_mode(mode: ThemeMode, accent: str = "blue") -> ColorTokens:
    """명시적인 라이트·다크 모드의 색상 토큰을 반환한다.

    ``accent``은 ``ACCENT_PRESETS``의 강조색 id다. 기본 ``blue``는 기존 상수를
    그대로 반환해 기존 동작과 객체 동일성을 보존한다. 미지 id는 ``blue``로 폴백.
    """

    dark = mode is ThemeMode.DARK
    base = DARK_COLORS if dark else LIGHT_COLORS
    preset = ACCENT_PRESETS.get(accent)
    if preset is None or accent == "blue":
        return base
    return _with_accent(base, preset, dark=dark)


def resolve_theme_mode(
    mode: ThemeMode, color_scheme: Qt.ColorScheme = Qt.ColorScheme.Unknown
) -> ThemeMode:
    """시스템 색상 체계를 앱 테마로 변환하고 불명확하면 라이트로 fallback한다."""

    if mode is not ThemeMode.SYSTEM:
        return mode
    if color_scheme is Qt.ColorScheme.Dark:
        return ThemeMode.DARK
    return ThemeMode.LIGHT


def system_theme_mode(app: QApplication) -> ThemeMode:
    """현재 Qt가 감지한 시스템 색상 체계를 해석한다."""

    return resolve_theme_mode(ThemeMode.SYSTEM, app.styleHints().colorScheme())


def current_colors(app: QApplication | None = None) -> ColorTokens:
    """현재 해석된 테마 모드의 색상 토큰을 반환한다.

    `ThemeController`가 앱에 설정한 `themeMode` 속성을 우선하고, 없으면 시스템
    색상 체계로 판별한다. pyqtgraph처럼 QSS에 반응하지 않는 위젯이 테마를
    따라가는 데 사용한다.
    """

    if app is None:
        instance = QApplication.instance()
        if not isinstance(instance, QApplication):
            return LIGHT_COLORS
        app = instance
    mode = app.property("themeMode")
    accent = app.property("accentColor")
    accent_id = accent if isinstance(accent, str) else "blue"
    if isinstance(mode, str):
        try:
            return colors_for_mode(ThemeMode(mode), accent=accent_id)
        except ValueError:
            pass
    return colors_for_mode(system_theme_mode(app), accent=accent_id)


def relative_luminance(color: str) -> float:
    """`#RRGGBB` 색상의 WCAG 상대 휘도를 계산한다."""

    value = color.removeprefix("#")
    if len(value) != 6:
        raise ValueError("색상은 #RRGGBB 형식이어야 합니다.")

    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """두 `#RRGGBB` 색상의 WCAG 대비율을 반환한다."""

    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _shade(color: str, factor: float) -> str:
    """`#RRGGBB`의 각 채널을 `factor`배만큼 어두운/밝은 색으로 만든다.

    `factor < 1`은 어둡게, `> 1`은 밝게. hover처럼 미묘한 상태 변화에 쓴다.
    """

    value = color.removeprefix("#")
    if len(value) != 6:
        return color

    def channel(index: int) -> int:
        return min(255, int(round(int(value[index : index + 2], 16) * factor)))

    return f"#{channel(0):02x}{channel(2):02x}{channel(4):02x}"


def _mix(foreground: str, background: str, ratio: float) -> str:
    """`foreground`를 `ratio` 비율로 `background`에 섞은 `#RRGGBB`를 만든다.

    ``selection``처럼 accent의 미묘한 틴트를 만들 때 쓴다.
    """

    fg = foreground.removeprefix("#")
    bg = background.removeprefix("#")
    if len(fg) != 6 or len(bg) != 6:
        return foreground

    def channel(index: int) -> int:
        f = int(fg[index : index + 2], 16)
        b = int(bg[index : index + 2], 16)
        return min(255, int(round(f * ratio + b * (1 - ratio))))

    return f"#{channel(0):02x}{channel(2):02x}{channel(4):02x}"


def _with_accent(
    colors: ColorTokens, preset: AccentTokens, *, dark: bool
) -> ColorTokens:
    """기본 색상 토큰의 accent 관련 필드를 프리셋에서 파생해 교체한다 (spec §5.1)."""

    accent = preset.dark if dark else preset.light
    text_on_accent = preset.dark_text_on_accent if dark else preset.light_text_on_accent
    if dark:
        hover = _shade(accent, 1.15)
        pressed = _shade(accent, 0.88)
        selection = _mix(accent, colors.background, 0.28)
    else:
        hover = _shade(accent, 0.88)
        pressed = _shade(accent, 0.72)
        selection = _mix(accent, "#FFFFFF", 0.18)
    return replace(
        colors,
        accent=accent,
        accent_hover=hover,
        accent_pressed=pressed,
        focus_ring=accent,
        selection=selection,
        text_on_accent=text_on_accent,
        chart_primary=accent,
    )


def font_for_role(base_font: QFont, role: FontRole) -> QFont:
    """시스템 기본 글꼴을 보존하면서 역할에 맞는 크기와 굵기를 파생한다.

    역할 배율에 전역 ``ui_scale``(UI 크기 설정)을 곱한다(spec §5.2).
    """

    font = QFont(base_font)
    base_size = base_font.pointSizeF()
    app = QApplication.instance()
    if (
        isinstance(app, QApplication)
        and _application_base_font is not None
        and base_font == app.font()
    ):
        base_size = _application_base_font.pointSizeF()
    if base_size <= 0:
        base_size = 10.0

    scale, weight = {
        FontRole.DISPLAY: (1.7, QFont.Weight.Bold),
        FontRole.TITLE: (1.35, QFont.Weight.DemiBold),
        FontRole.SECTION: (1.08, QFont.Weight.DemiBold),
        FontRole.BODY: (1.0, QFont.Weight.Normal),
        FontRole.LABEL: (1.0, QFont.Weight.Medium),
        FontRole.CAPTION: (0.92, QFont.Weight.Normal),
        FontRole.NUMERIC: (1.35, QFont.Weight.DemiBold),
    }[role]
    font.setPointSizeF(max(1.0, base_size * scale * _ui_scale))
    font.setWeight(weight)
    return font


def current_ui_scale() -> float:
    """현재 전역 UI 배율을 반환한다."""
    return _ui_scale


def _scale_font(font: QFont, scale: float) -> QFont:
    """100% 기준 앱 글꼴을 목표 UI 배율로 조정한다."""
    scaled_font = QFont(font)
    if (point_size := font.pointSizeF()) > 0:
        scaled_font.setPointSizeF(point_size * scale)
    elif (pixel_size := font.pixelSize()) > 0:
        scaled_font.setPixelSize(max(1, round(pixel_size * scale)))
    return scaled_font


def apply_ui_scale(scale: float, app: QApplication | None = None) -> None:
    """앱 시작 전에 전역 UI 배율을 적용한다.

    이미 열린 창은 현재 모양을 유지한다. ``SettingsWindow``는 이 값을 저장만
    하며, 다음 앱 실행에서 창·글꼴·스타일·기본 Qt 메트릭을 함께 생성한다.
    """
    global _application_base_font, _scaled_style, _ui_scale

    _ui_scale = scale
    if app is None:
        instance = QApplication.instance()
        app = instance if isinstance(instance, QApplication) else None
    if app is None:
        return

    if _application_base_font is None:
        _application_base_font = QFont(app.font())
    if _scaled_style is None:
        _scaled_style = _ScaledStyle(app.style(), scale)
        app.setStyle(_scaled_style)
    else:
        _scaled_style.set_ui_scale(scale)

    app.setFont(_scale_font(_application_base_font, scale))
    app.setStyleSheet(build_stylesheet(current_colors(app)))


def set_style_property(widget: QWidget, name: str, value: str | bool | None) -> None:
    """동적 스타일 속성을 바꾸고 해당 위젯만 다시 polish한다."""

    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def build_palette(colors: ColorTokens) -> QPalette:
    """Qt 기본 위젯과 대화상자도 테마를 따르도록 앱 팔레트를 생성한다."""

    palette = QPalette()
    role_colors = {
        QPalette.ColorRole.Window: colors.background,
        QPalette.ColorRole.WindowText: colors.text_primary,
        QPalette.ColorRole.Base: colors.surface,
        QPalette.ColorRole.AlternateBase: colors.surface_subtle,
        QPalette.ColorRole.ToolTipBase: colors.surface_raised,
        QPalette.ColorRole.ToolTipText: colors.text_primary,
        QPalette.ColorRole.Text: colors.text_primary,
        QPalette.ColorRole.Button: colors.surface_subtle,
        QPalette.ColorRole.ButtonText: colors.text_primary,
        QPalette.ColorRole.BrightText: colors.text_on_accent,
        QPalette.ColorRole.Link: colors.accent,
        QPalette.ColorRole.Highlight: colors.accent,
        QPalette.ColorRole.HighlightedText: colors.text_on_accent,
        QPalette.ColorRole.PlaceholderText: colors.text_secondary,
    }
    for role, color in role_colors.items():
        palette.setColor(role, QColor(color))

    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    ):
        palette.setColor(disabled, role, QColor(colors.text_disabled))
    palette.setColor(disabled, QPalette.ColorRole.Button, QColor(colors.surface_subtle))
    return palette


def build_stylesheet(colors: ColorTokens, metrics: MetricTokens = METRICS) -> str:
    """의미 역할과 안정적인 상태 표현을 포함한 애플리케이션 QSS를 생성한다."""

    return f"""
QWidget {{
    background-color: {colors.background};
    color: {colors.text_primary};
}}
QMainWindow, QDialog {{
    background-color: {colors.background};
}}
QToolTip {{
    background-color: {colors.surface_raised};
    color: {colors.text_primary};
    border: {metrics.border_width}px solid {colors.border_strong};
    padding: {metrics.space_1}px {metrics.space_2}px;
}}
QLabel {{
    background-color: transparent;
}}
QLabel[role="title"] {{ font-weight: 600; }}
QLabel[role="section"] {{ font-weight: 600; }}
QLabel[tone="muted"] {{ color: {colors.text_secondary}; }}
QLabel[tone="success"] {{ color: {colors.success}; }}
QLabel[tone="danger"] {{ color: {colors.danger}; }}
QFrame[role="danger-divider"] {{
    background-color: {colors.danger};
}}
QFrame[surface="card"], QFrame[surface="summary-card"], QFrame[surface="section"] {{
    background-color: {colors.surface};
    border: {metrics.border_width}px solid {colors.border};
    border-radius: {metrics.radius_surface}px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
    min-height: {metrics.control_height_small}px;
    background-color: {colors.surface};
    color: {colors.text_primary};
    border: {metrics.focus_width}px solid {colors.border_strong};
    border-radius: {metrics.radius_control}px;
    padding: 0 {metrics.space_2}px;
    selection-background-color: {colors.selection};
    selection-color: {colors.text_primary};
}}
QTextEdit, QPlainTextEdit {{ padding: {metrics.space_2}px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {colors.focus_ring};
}}
QLineEdit[invalid="true"], QComboBox[invalid="true"], QSpinBox[invalid="true"],
QDoubleSpinBox[invalid="true"], QTextEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{
    border-color: {colors.danger};
    background-color: {colors.danger_subtle};
}}
QLineEdit[warning="true"], QComboBox[warning="true"], QSpinBox[warning="true"],
QDoubleSpinBox[warning="true"], QTextEdit[warning="true"], QPlainTextEdit[warning="true"] {{
    border-color: {colors.warning};
    background-color: {colors.warning_subtle};
}}
QPushButton {{
    min-height: {metrics.control_height_small}px;
    background-color: {colors.surface_subtle};
    color: {colors.text_primary};
    border: {metrics.focus_width}px solid {colors.border_strong};
    border-radius: {metrics.radius_control}px;
    padding: 0 {metrics.space_3}px;
}}
QPushButton:hover {{ background-color: {colors.surface_raised}; }}
QPushButton:pressed {{ background-color: {colors.selection}; }}
QPushButton:focus {{ border-color: {colors.focus_ring}; }}
QPushButton:disabled {{
    background-color: {colors.surface_subtle};
    color: {colors.text_disabled};
    border-color: {colors.border};
}}
QPushButton[role="primary"] {{
    min-height: {metrics.control_height_primary}px;
    background-color: {colors.accent};
    color: {colors.text_on_accent};
    border-color: {colors.accent};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background-color: {colors.accent_hover};
    border-color: {colors.accent_hover};
}}
QPushButton[role="primary"]:pressed {{
    background-color: {colors.accent_pressed};
    border-color: {colors.accent_pressed};
}}
QPushButton[role="primary"]:focus {{ border-color: {colors.text_on_accent}; }}
QPushButton[role="secondary"] {{ background-color: {colors.surface}; }}
QPushButton[role="ghost"] {{
    background-color: transparent;
    border-color: transparent;
}}
QPushButton[role="ghost"]:hover {{
    background-color: {colors.surface_subtle};
    border-color: {colors.border};
}}
QPushButton[role="ghost"]:focus {{ border-color: {colors.focus_ring}; }}
QPushButton[role="danger"] {{
    background-color: {colors.danger};
    color: {colors.text_on_accent};
    border-color: {colors.danger};
}}
QPushButton[role="danger"]:hover {{ background-color: {colors.danger_subtle}; color: {colors.danger}; }}
QPushButton[role="danger"]:focus {{ border-color: {colors.text_on_accent}; }}
QPushButton[role="result-win"] {{
    min-height: {metrics.result_height}px;
    background-color: {colors.success_subtle};
    color: {colors.success};
    border-color: {colors.success};
    font-weight: 600;
}}
QPushButton[role="result-loss"] {{
    min-height: {metrics.result_height}px;
    background-color: {colors.danger_subtle};
    color: {colors.danger};
    border-color: {colors.danger};
    font-weight: 600;
}}
QPushButton[role="result-win"]:hover {{
    background-color: {_shade(colors.success_subtle, 0.97)};
    border-color: {_shade(colors.success, 0.9)};
}}
QPushButton[role="result-loss"]:hover {{
    background-color: {_shade(colors.danger_subtle, 0.97)};
    border-color: {_shade(colors.danger, 0.9)};
}}
QPushButton[role="result-win"]:checked {{
    background-color: {colors.success};
    color: {colors.text_on_accent};
    border-color: {colors.success};
}}
QPushButton[role="result-loss"]:checked {{
    background-color: {colors.danger};
    color: {colors.text_on_accent};
    border-color: {colors.danger};
}}
QPushButton[role="result-win"]:pressed, QPushButton[role="result-loss"]:pressed {{
    border-color: {colors.focus_ring};
}}
QPushButton[role="result-win"]:focus, QPushButton[role="result-loss"]:focus {{
    border-color: {colors.focus_ring};
}}
QPushButton[role="result-win"]:checked:focus, QPushButton[role="result-loss"]:checked:focus {{
    border-color: {colors.text_on_accent};
}}
QPushButton[role="result-win"][compact="true"],
QPushButton[role="result-loss"][compact="true"] {{
    min-height: {metrics.control_height}px;
}}
QPushButton[role="segment"] {{
    background-color: {colors.surface};
    border-radius: {metrics.radius_control}px;
}}
QPushButton[role="segment"]:checked {{
    background-color: {colors.selection};
    color: {colors.text_primary};
    border-color: {colors.accent};
    font-weight: 600;
}}
QPushButton[role="segment"]:focus {{ border-color: {colors.focus_ring}; }}
QPushButton[role="icon"] {{
    min-width: {metrics.control_height_small}px;
    max-width: {metrics.control_height_small}px;
    padding: 0;
}}
QPushButton[role="primary"]:disabled, QPushButton[role="secondary"]:disabled,
QPushButton[role="ghost"]:disabled, QPushButton[role="danger"]:disabled,
QPushButton[role="result-win"]:disabled, QPushButton[role="result-loss"]:disabled,
QPushButton[role="segment"]:disabled, QPushButton[role="icon"]:disabled {{
    background-color: {colors.surface_subtle};
    color: {colors.text_disabled};
    border-color: {colors.border};
}}
QAbstractItemView {{
    background-color: {colors.surface};
    alternate-background-color: {colors.surface_subtle};
    color: {colors.text_primary};
    border: {metrics.border_width}px solid {colors.border};
    selection-background-color: {colors.selection};
    selection-color: {colors.text_primary};
    outline: 0;
}}
QAbstractItemView:focus {{ border: {metrics.focus_width}px solid {colors.focus_ring}; }}
QTableWidget[statsTable="true"]::item:selected {{
    border: {metrics.focus_width}px solid {colors.accent};
}}
QHeaderView::section {{
    background-color: {colors.surface_subtle};
    color: {colors.text_primary};
    padding: {metrics.space_2}px;
    border: 0;
    border-bottom: {metrics.border_width}px solid {colors.border_strong};
}}
QTabWidget::pane {{
    border: {metrics.border_width}px solid {colors.border};
    background-color: {colors.surface};
}}
QTabBar::tab {{
    min-height: {metrics.control_height_small}px;
    padding: 0 {metrics.space_3}px;
    color: {colors.text_secondary};
    border-bottom: {metrics.focus_width}px solid transparent;
}}
QTabBar::tab:selected {{
    color: {colors.text_primary};
    border-bottom-color: {colors.accent};
    font-weight: 600;
}}
QTabBar::tab:focus {{ border-bottom-color: {colors.focus_ring}; }}
""".strip()


def _fusion_style_name() -> str | None:
    for style_name in QStyleFactory.keys():
        if style_name.casefold() == "fusion":
            return style_name
    return None


class ThemeController(QObject):
    """앱 테마를 적용하고 시스템 색상 체계 변경을 추적한다."""

    theme_changed = Signal(ThemeMode)
    accent_changed = Signal(str)

    def __init__(
        self,
        app: QApplication,
        mode: ThemeMode = ThemeMode.SYSTEM,
        accent: str = "blue",
    ) -> None:
        super().__init__(app)
        self._app = app
        self._mode = mode
        self._accent = accent
        self._resolved_mode = ThemeMode.LIGHT
        app.styleHints().colorSchemeChanged.connect(self._on_color_scheme_changed)
        self.apply()

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def accent(self) -> str:
        return self._accent

    @property
    def resolved_mode(self) -> ThemeMode:
        return self._resolved_mode

    def set_mode(self, mode: ThemeMode) -> None:
        if self._mode is mode:
            return
        self._mode = mode
        self.apply()

    def set_accent(self, accent: str) -> None:
        if self._accent == accent:
            return
        self._accent = accent
        self.apply()
        self.accent_changed.emit(accent)

    def apply(self) -> None:
        resolved_mode = (
            system_theme_mode(self._app)
            if self._mode is ThemeMode.SYSTEM
            else self._mode
        )
        colors = colors_for_mode(resolved_mode, accent=self._accent)
        self._app.setPalette(build_palette(colors))
        self._app.setStyleSheet(build_stylesheet(colors))
        self._app.setProperty("themeMode", resolved_mode.value)
        self._app.setProperty("accentColor", self._accent)
        changed = self._resolved_mode is not resolved_mode
        self._resolved_mode = resolved_mode
        if changed:
            self.theme_changed.emit(resolved_mode)

    @Slot(Qt.ColorScheme)
    def _on_color_scheme_changed(self, _color_scheme: Qt.ColorScheme) -> None:
        if self._mode is ThemeMode.SYSTEM:
            self.apply()


def apply_theme(
    app: QApplication,
    mode: ThemeMode = ThemeMode.SYSTEM,
    accent: str = "blue",
    ui_scale: float = 1.0,
) -> ThemeController:
    """Fusion을 사용할 수 있으면 선택하고 앱 테마 제어기를 생성한다."""
    global _scaled_style

    fusion_style = _fusion_style_name()
    if fusion_style is not None:
        app.setStyle(fusion_style)
    _scaled_style = None
    apply_ui_scale(ui_scale, app)
    return ThemeController(app, mode, accent)
