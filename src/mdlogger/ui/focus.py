"""마우스 중심 UI를 위한 전역 포커스 정책."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

_FILTER_OBJECT_NAME = "pointerFocusOnlyFilter"
_TAB_FOCUS_PROPERTY = "tabFocusEnabled"


def allow_tab_focus(root: QWidget) -> None:
    """지정한 위젯과 그 자식에서 Tab·Shift+Tab 포커스를 허용한다."""
    root.setProperty(_TAB_FOCUS_PROPERTY, True)


def _allows_tab_focus(watched: QObject) -> bool:
    widget = watched if isinstance(watched, QWidget) else QApplication.focusWidget()
    while widget is not None:
        if bool(widget.property(_TAB_FOCUS_PROPERTY)):
            return True
        widget = widget.parentWidget()
    return False


class PointerFocusOnlyFilter(QObject):
    """허용한 입력 폼 외에는 Tab과 Shift+Tab 포커스 이동을 막는다."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                return not _allows_tab_focus(watched)
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
