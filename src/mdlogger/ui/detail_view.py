"""화면2 (상세 입력): 색 결과 헤더(되돌리기) + 입력 폼 + 확인."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..enums import RESULT_COLORS, RESULT_LABELS
from .detail_form import DetailForm


class DetailView(QWidget):
    back_requested = Signal()
    confirmed = Signal(dict)  # 폼 값(result/played_at 제외)

    def __init__(self, decks: list[str], parent=None):
        super().__init__(parent)
        self._result: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        # 색 결과 헤더 (클릭 = 결과 다시 고르기)
        self._banner = QPushButton()
        self._banner.setCursor(Qt.CursorShape.PointingHandCursor)
        self._banner.setMinimumHeight(48)
        self._banner.clicked.connect(self.back_requested)
        root.addWidget(self._banner)

        # 입력 폼
        self.form = DetailForm(decks)
        root.addWidget(self.form)

        # 경고 상태줄
        self._status = QLabel("")
        self._status.setStyleSheet("color:#c62828; font-size:12px;")
        root.addWidget(self._status)

        root.addStretch(1)

        # 확인
        self._confirm = QPushButton("확인")
        self._confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm.setMinimumHeight(46)
        self._confirm.setDefault(True)
        self._confirm.setStyleSheet(
            "QPushButton { background:#1565c0; color:white; border:none;"
            " border-radius:8px; font-size:17px; font-weight:700; }"
            " QPushButton:hover { background:#1257a8; }"
        )
        self._confirm.clicked.connect(self._on_confirm)
        root.addWidget(self._confirm)

    def set_result(self, result: str) -> None:
        self._result = result
        color = RESULT_COLORS[result]
        label = RESULT_LABELS[result]
        self._banner.setText(f"{label}   ·   결과 다시 고르기 ↺")
        self._banner.setStyleSheet(
            f"QPushButton {{ background:{color}; color:white; border:none;"
            f" border-radius:8px; font-size:18px; font-weight:800; text-align:center; }}"
        )
        self._status.clear()

    def result(self) -> str | None:
        return self._result

    def _on_confirm(self) -> None:
        values = self.form.values()
        if values is None:
            self._status.setText("내 덱 / 상대 덱을 후보에서 정확히 선택하세요")
            self.form.focus_deck()
            return
        self._status.clear()
        self.confirmed.emit(values)
