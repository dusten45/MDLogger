"""기존 레코드 편집 다이얼로그 (DetailForm 재사용 + 결과 토글)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from ..enums import RESULT_COLORS, RESULTS
from ..game_service import GameService
from .detail_form import DetailForm
from .widgets import SingleSelect


def _caption(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#555; font-size:12px; font-weight:600; margin-top:2px;")
    return lbl


class EditDialog(QDialog):
    def __init__(self, games: GameService, decks: list[str], row, parent=None):
        super().__init__(parent)
        self._games = games
        self._row = row
        self._id = int(row["id"])

        self.setWindowTitle("기록 편집")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 결과 토글 (승=초록/패=빨강)
        self._result = SingleSelect(RESULTS, color_map=RESULT_COLORS)
        self._result.setValue(row["result"])
        layout.addWidget(_caption("결과"))
        layout.addWidget(self._result)

        # 입력 폼
        self.form = DetailForm(decks)
        self.form.set_values(row)
        layout.addWidget(self.form)

        # 경고
        self._status = QLabel("")
        self._status.setStyleSheet("color:#c62828; font-size:12px;")
        layout.addWidget(self._status)

        # 저장 / 취소
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        values = self.form.values()
        if values is None:
            self._status.setText("상대 덱을 후보에서 선택하세요 (부분 입력이 모호함)")
            return
        record = {
            **values,
            "result": self._result.value(),
            # played_at(게임 시각)은 보존
            "played_at": self._row["played_at"],
        }
        self._games.update_game(self._id, record)
        self.accept()
