"""화면2 (상세 입력): "전적 입력 취소" 배너 + 승/패 선택 + 입력 폼 + 확인."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .detail_form import DetailForm
from .theme import scaled, set_style_property
from .widgets import ResultSelect


class DetailView(QWidget):
    back_requested = Signal()
    confirmed = Signal(dict)  # 폼 값(result 포함)

    def __init__(self, decks: list[str], parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(scaled(14), scaled(10), scaled(14), scaled(10))
        root.setSpacing(scaled(8))

        # 상단 배너 (클릭 = 입력 취소, 메인 화면 복귀). secondary 버튼.
        self._banner = QPushButton("전적 입력 취소")
        self._banner.setCursor(Qt.CursorShape.PointingHandCursor)
        self._banner.setMinimumHeight(scaled(36))
        self._banner.setAccessibleName("전적 입력 취소")
        self._banner.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        set_style_property(self._banner, "role", "secondary")
        self._banner.clicked.connect(self.back_requested)
        root.addWidget(self._banner)

        # 승/패 선택 (배너 바로 아래, 초록/빨강 legacy 유지)
        self._result_select = ResultSelect()
        self._result_select.changed.connect(self._on_result_changed)
        root.addWidget(self._result_select)

        # 입력 폼 (작은 화면에서는 DetailView 바깥 스크롤 영역으로 접근 보장)
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
        self._confirm.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        set_style_property(self._confirm, "role", "primary")
        self._confirm.clicked.connect(self._on_confirm)
        root.addWidget(self._confirm)

    def _on_result_changed(self, result: str) -> None:
        self.form.set_result(result)
        self._status.clear()

    def set_mode(self, mode) -> None:
        """선택된 GameMode를 폼에 전달한다 (spec §6.2)."""
        self.form.set_mode(mode)

    def result(self) -> str | None:
        return self._result_select.value()

    def reset_result(self) -> None:
        """새 입력 시작 시 승/패 선택을 초기화한다."""
        self._result_select.setValue(None)
        self.form.set_result(None)

    def _on_confirm(self) -> None:
        result = self._result_select.value()
        if result is None:
            self._status.setText("승/패를 선택하세요")
            return
        values = self.form.values()
        if values is None:
            self._status.setText(self.form.validation_error() or "입력값을 확인하세요")
            return
        values["result"] = result
        self._status.clear()
        self.confirmed.emit(values)
