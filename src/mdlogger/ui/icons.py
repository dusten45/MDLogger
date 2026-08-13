"""테마 인식 단색 SVG 아이콘 로드.

아이콘은 앱 패키지 안의 ``ui/icons/``에 SVG로 보관하며 ``importlib.resources``로
읽는다(``decks.py``의 번들 덱 카탈로그와 같은 패키징 방식 — hatchling이 패키지
데이터로 포함하고 PyInstaller가 `importlib.resources` 사용을 추적해 함께 번들한다).

각 아이콘은 단색(원본 `stroke="black"`)이며, `_ThemeIconEngine`이 paint 시점에
``current_colors()``로 결정된 테마 색상으로 다시 칠한다. 따라서 라이트/다크 전환과
``QIcon.Mode``(normal/active/disabled) 상태가 모두 색상 토큰을 따른다. 재배포 가능한
외부 아이콘 패키지 의존성은 추가하지 않으며, 아이콘은 기능을 텍스트로도 설명할 수
있도록 버튼에는 텍스트(label/tooltip)와 쌍으로 사용한다.
"""

from __future__ import annotations

import importlib.resources
from functools import cache

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import ColorTokens, current_colors

_ICON_PACKAGE = "mdlogger.ui"
_ICON_DIR = "icons"

# 아이콘 이름 → 번들 SVG 파일명. 추가 아이콘이 필요하면 여기에 등록한다.
_ICON_FILES: dict[str, str] = {
    "undo": "undo.svg",
    "minus": "minus.svg",
    "plus": "plus.svg",
}

# 앱 아이콘(번들 PNG). 루트 `icon/DuelistCup.png`와 같은 그림을 패키지에 번들해
# 런타임(창·태스크바) 및 배포 빌드에 사용한다. hatchling/pyinstaller가 패키지
# 데이터로 포함한다.
_APP_ICON_FILE = "DuelistCup.png"


@cache
def _svg_bytes(name: str) -> bytes | None:
    """번들 SVG를 읽는다. 파일이 없거나 패키지 접근이 실패하면 None."""
    filename = _ICON_FILES.get(name)
    if filename is None:
        return None
    try:
        ref = importlib.resources.files(_ICON_PACKAGE)
        for part in (_ICON_DIR, filename):
            ref = ref.joinpath(part)
        return ref.read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None


def _tint_pixmap(svg: bytes, color: QColor, size: QSize) -> QPixmap:
    """SVG를 렌더링한 뒤 불투명 픽셀만 ``color``로 칠해 단색 아이콘을 만든다."""
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(svg)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter, QRectF(pixmap.rect()))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color)
    finally:
        painter.end()
    return pixmap


def _color_for_mode(mode: QIcon.Mode, colors: ColorTokens) -> QColor:
    """``QIcon.Mode``에 따라 칠할 색상 토큰을 고른다."""
    if mode is QIcon.Mode.Disabled:
        return QColor(colors.text_disabled)
    if mode is QIcon.Mode.Active:
        return QColor(colors.accent)
    return QColor(colors.text_primary)


class _ThemeIconEngine(QIconEngine):
    """paint 시점의 테마 색상으로 단색 아이콘을 다시 칠하는 아이콘 엔진."""

    def __init__(self, svg: bytes) -> None:
        super().__init__()
        self._svg = svg

    def _render(self, size: QSize, mode: QIcon.Mode) -> QPixmap:
        return _tint_pixmap(self._svg, _color_for_mode(mode, current_colors()), size)

    def paint(
        self,
        painter: QPainter,
        rect: QRect,
        mode: QIcon.Mode,
        state: QIcon.State,
    ) -> None:
        painter.drawPixmap(rect, self._render(rect.size(), mode))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self._render(size, mode)

    def clone(self) -> QIconEngine:
        return _ThemeIconEngine(self._svg)


def load_icon(name: str) -> QIcon | None:
    """테마에 반응하는 단색 아이콘을 반환한다. SVG가 없으면 None.

    None일 때 호출자는 버튼 텍스트나 tooltip으로 동작을 계속 설명할 수 있다.
    """
    svg = _svg_bytes(name)
    if svg is None:
        return None
    return QIcon(_ThemeIconEngine(svg))


@cache
def application_icon() -> QIcon | None:
    """앱 아이콘(번들 `DuelistCup.png`)을 반환한다. 패키지에 없으면 None.

    창 타이틀바·태스크바용 정적 아이콘. 테마에 따라 다시 칠하지 않으며,
    Windows 실행 파일(EXE) 아이콘(`MDLogger.spec`의 ``icon``)과 같은 그림이다.
    ``importlib.resources`` 바이트를 QPixmap으로 읽어 frozen(onedir)에서도
    아카이브 경로 문제 없이 동작한다.
    """
    try:
        ref = importlib.resources.files(_ICON_PACKAGE).joinpath(
            _ICON_DIR, _APP_ICON_FILE
        )
        pixmap = QPixmap()
        if not pixmap.loadFromData(ref.read_bytes()):
            return None
        return QIcon(pixmap)
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None
