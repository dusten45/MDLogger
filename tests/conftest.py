"""GUI 테스트의 네이티브 자원을 애플리케이션보다 먼저 정리한다."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown() -> Iterator[None]:
    """fixture를 복구한 뒤, 앱이 살아 있을 때 닫힌 창까지 삭제한다."""
    app = QApplication.instance()
    try:
        yield
    finally:
        if isinstance(app, QApplication) and isValid(app):
            # 자식 시그널 정리 중 부모가 재진입 삭제되지 않도록 래퍼를 유지한다.
            widgets = app.allWidgets()
            for widget in widgets:
                if isValid(widget):
                    widget.close()
            # pyqtgraph 등 자식 위젯의 close 정리 이후에 네이티브 부모를 삭제한다.
            for widget in widgets:
                if isValid(widget) and widget.isWindow():
                    widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
