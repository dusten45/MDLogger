"""최소 설정 대화상자: 기본 모드 선택 (spec §6.4, 계획 2 흡수 구조).

``database_metadata.default_mode``를 읽고 쓴다. 값은 활성 모드 id 목록 +
'이전 모드 기억'(``last_used``). 계획 2(통합 설정 창)에서 흡수할 최소 형태다.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..game_service import GameService
from ..settings import DEFAULT_MODE_LAST_USED, ModeSettings
from .theme import METRICS, FontRole, font_for_role, set_style_property
from .widgets import SingleSelect


class SettingsDialog(QDialog):
    def __init__(self, games: GameService, parent: QWidget | None = None):
        super().__init__(parent)
        self._games = games
        self._settings = ModeSettings(games)
        self.setWindowTitle("설정")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(METRICS.space_2)

        caption = QLabel("기본 모드")
        set_style_property(caption, "tone", "muted")
        caption.setFont(font_for_role(caption.font(), FontRole.LABEL))
        layout.addWidget(caption)

        modes = self._games.get_active_play_modes()
        options = [(DEFAULT_MODE_LAST_USED, "이전 모드 기억")] + [
            (str(m["id"]), str(m["display_name"])) for m in modes
        ]
        self._default = SingleSelect(options)
        current = self._settings.default_mode
        if current is None or current == DEFAULT_MODE_LAST_USED:
            self._default.setValue(DEFAULT_MODE_LAST_USED)
        else:
            self._default.setValue(current)
        layout.addWidget(self._default)

        hint = QLabel("앱 시작 시 기록할 모드를 선택합니다.")
        set_style_property(hint, "tone", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setText("저장")
        set_style_property(save_btn, "role", "primary")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        self._settings.set_default_mode(self._default.value())
        self.accept()
