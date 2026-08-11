"""기존 레코드 편집 다이얼로그 (DetailForm 재사용 + 결과 토글).

단계 3(§9.4): `theme.py` 토큰과 역할 기반 스타일을 사용해 필드 레이블(muted),
오류 상태(danger), 저장(primary)/취소(ghost) 버튼을 구성한다.
"""

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
from .theme import METRICS, FontRole, font_for_role, set_style_property
from .widgets import SingleSelect


def _caption(text: str) -> QLabel:
    lbl = QLabel(text)
    set_style_property(lbl, "tone", "muted")
    lbl.setFont(font_for_role(lbl.font(), FontRole.LABEL))
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
        layout.setSpacing(METRICS.space_2)

        # 결과 토글 (승=세그먼트 역할, color_map은 하위 호환용)
        self._result = SingleSelect(RESULTS, color_map=RESULT_COLORS)
        self._result.setValue(row["result"])
        layout.addWidget(_caption("결과"))
        layout.addWidget(self._result)

        # 입력 폼
        self.form = DetailForm(decks)
        self.form.set_values(row)
        layout.addWidget(self.form)

        # 경고 (danger tone)
        self._status = QLabel("")
        set_style_property(self._status, "tone", "danger")
        layout.addWidget(self._status)

        # 저장 / 취소 (저장=primary, 취소=ghost)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        save_btn.setText("저장")
        cancel_btn.setText("취소")
        set_style_property(save_btn, "role", "primary")
        set_style_property(cancel_btn, "role", "ghost")
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
