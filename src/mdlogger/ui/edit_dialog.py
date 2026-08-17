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
from ..models import GameMode, StandingKind
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

        # 현재 모드 표시 (spec §5.4: 저장된 모드를 확인)
        mode = self._row_mode()
        mode_label = QLabel(f"모드: {mode.display_name if mode else '알 수 없음'}")
        set_style_property(mode_label, "tone", "muted")
        layout.addWidget(mode_label)

        # 입력 폼 (모드별 상태 입력 분기)
        self.form = DetailForm(decks)
        self.form.set_mode(mode)
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

    def _row_mode(self) -> GameMode | None:
        """기존 레코드의 standing_kind/play_context_id로 편집용 GameMode 구성 (spec §6.3)."""
        kind = self._row["standing_kind"]
        if not kind:
            return None
        ctx = self._row["play_context_id"]
        display_name = ""
        for mode in self._games.get_play_modes():
            if mode["play_context_id"] == ctx:
                display_name = str(mode["display_name"])
                break
        return GameMode(
            id="",
            standing_kind=StandingKind(str(kind)),
            display_name=display_name,
            play_context_id=ctx,
        )

    def _on_save(self) -> None:
        values = self.form.values()
        if values is None:
            self._status.setText(self.form.validation_error() or "입력값을 확인하세요")
            return
        record = {
            **values,
            "result": self._result.value(),
            # played_at(게임 시각)은 보존
            "played_at": self._row["played_at"],
        }
        self._games.update_game(self._id, record)
        self.accept()
