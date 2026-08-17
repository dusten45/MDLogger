"""마우스 중심 UI를 위한 전역 포커스 정책."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

_FILTER_OBJECT_NAME = "pointerFocusOnlyFilter"


class PointerFocusOnlyFilter(QObject):
    """Tab과 Shift+Tab으로 위젯 포커스를 옮기지 못하게 한다."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                return True
        return super().eventFilter(watched, event)


def restrict_focus_to_pointer(root: QWidget) -> None:
    """창의 모든 자식 위젯에서 Tab 포커스를 마우스 클릭 포커스로 바꾼다."""

    for widget in [root, *root.findChildren(QWidget)]:
        if widget.focusPolicy() & Qt.FocusPolicy.TabFocus:
            widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)


def install_pointer_focus_only(app: QApplication) -> None:
    """앱 전체에 Tab 탐색을 차단하는 키 이벤트 필터를 한 번만 설치한다."""

    if app.findChild(QObject, _FILTER_OBJECT_NAME) is not None:
        return
    focus_filter = PointerFocusOnlyFilter(app)
    focus_filter.setObjectName(_FILTER_OBJECT_NAME)
    app.installEventFilter(focus_filter)
