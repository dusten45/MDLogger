"""앱 진입점: QApplication 구성, DB 초기화, 메인 창 표시."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import db, sync
from .decks import load_decks
from .ui.main_window import MainWindow

APP_QSS = """
QWidget { font-size: 13px; }
QLineEdit, QComboBox {
    border: 1px solid #c4c4c4; border-radius: 6px; padding: 4px 6px; background: white;
}
QLineEdit:focus, QComboBox:focus { border-color: #1565c0; }
QPushButton {
    border: 1px solid #c4c4c4; border-radius: 6px; padding: 6px 10px; background: #f3f3f3;
}
QPushButton:hover { background: #e9e9e9; }
QPushButton:disabled { color: #aaa; background: #f7f7f7; }
QTableWidget { gridline-color: #e0e0e0; }
QHeaderView::section { background: #f0f0f0; padding: 4px; border: none; border-right: 1px solid #e0e0e0; }
"""


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("MD WCQ 로거")
    app.setStyleSheet(APP_QSS)

    conn = db.connect()
    db.init_db(conn)
    sync.start_background_sync()  # 비차단; 갱신은 다음 상세 진입에서 자동 반영
    decks = load_decks()

    window = MainWindow(conn, decks)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
