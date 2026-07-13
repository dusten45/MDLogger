"""화면1 (결과 선택): 오늘 전적 + 큰 승/패 버튼 + 되돌리기/통계."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..enums import RESULT_COLORS


def _big_result_button(text: str, color: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(120)
    btn.setStyleSheet(
        f"""
        QPushButton {{
            background:{color}; color:white; border:none; border-radius:12px;
            font-size:40px; font-weight:800;
        }}
        QPushButton:hover {{ background:{color}; opacity:0.9; }}
        QPushButton:pressed {{ padding-top:3px; }}
        """
    )
    return btn


class ResultView(QWidget):
    result_chosen = Signal(str)  # 'win' | 'lose'
    undo_requested = Signal()
    stats_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # 오늘 전적
        self._today = QLabel("오늘 전적  0승 0패")
        self._today.setAlignment(Qt.AlignCenter)
        self._today.setStyleSheet("font-size:18px; font-weight:700; color:#1a1a1a;")
        root.addWidget(self._today)

        # 큰 승/패 버튼
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        win_btn = _big_result_button("승", RESULT_COLORS["win"])
        lose_btn = _big_result_button("패", RESULT_COLORS["lose"])
        win_btn.clicked.connect(lambda: self.result_chosen.emit("win"))
        lose_btn.clicked.connect(lambda: self.result_chosen.emit("lose"))
        buttons.addWidget(win_btn)
        buttons.addWidget(lose_btn)
        root.addLayout(buttons, 1)

        # 하단: 되돌리기 / 통계
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self._undo = QPushButton("↶ 마지막 기록 취소")
        self._undo.setCursor(Qt.PointingHandCursor)
        self._undo.setMinimumHeight(36)
        self._undo.setEnabled(False)
        self._undo.clicked.connect(self.undo_requested)
        stats_btn = QPushButton("통계 / 기록")
        stats_btn.setCursor(Qt.PointingHandCursor)
        stats_btn.setMinimumHeight(36)
        stats_btn.clicked.connect(self.stats_requested)
        bottom.addWidget(self._undo)
        bottom.addWidget(stats_btn)
        root.addLayout(bottom)

    def set_today_record(self, wins: int, losses: int) -> None:
        self._today.setText(f"오늘 전적  {wins}승 {losses}패")

    def set_undo_enabled(self, enabled: bool) -> None:
        self._undo.setEnabled(enabled)
