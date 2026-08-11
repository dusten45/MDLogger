"""화면2 (상세 입력): 결과 상태 헤더(결과 변경) + 입력 폼 + 확인."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ..enums import RESULT_LABELS
from .detail_form import DetailForm
from .theme import set_style_property


class DetailView(QWidget):
    back_requested = Signal()
    confirmed = Signal(dict)  # 폼 값(result/played_at 제외)

    def __init__(self, decks: list[str], parent=None):
        super().__init__(parent)
        self._result: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # 결과 상태 헤더 (클릭 = 결과 다시 고르기). 테두리 있는 secondary 버튼.
        self._banner = QPushButton()
        self._banner.setCursor(Qt.CursorShape.PointingHandCursor)
        self._banner.setMinimumHeight(36)
        self._banner.setAccessibleName("현재 결과를 다시 고르기")
        self._banner.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        set_style_property(self._banner, "role", "secondary")
        self._banner.clicked.connect(self.back_requested)
        root.addWidget(self._banner)

        # 입력 폼 (스크롤 없이 한 화면에 모두 표시)
        self.form = DetailForm(decks)
        root.addWidget(self.form)

        # 오류 상태줄 (theme의 danger tone)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        set_style_property(self._status, "tone", "danger")
        root.addWidget(self._status)

        root.addStretch(1)

        # 확인
        self._confirm = QPushButton("확인")
        self._confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm.setDefault(True)
        self._confirm.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        set_style_property(self._confirm, "role", "primary")
        self._confirm.clicked.connect(self._on_confirm)
        root.addWidget(self._confirm)

    def set_result(self, result: str) -> None:
        self._result = result
        label = RESULT_LABELS.get(result, result)
        self._banner.setText(f"{label}  ·  결과 변경")
        self._status.clear()

    def result(self) -> str | None:
        return self._result

    def _on_confirm(self) -> None:
        values = self.form.values()
        if values is None:
            self._status.setText("내 덱 / 상대 덱을 후보에서 정확히 선택하세요")
            self.form.focus_first_invalid()
            return
        self._status.clear()
        self.confirmed.emit(values)
