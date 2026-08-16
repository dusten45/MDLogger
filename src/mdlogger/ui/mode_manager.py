"""관리자(개발자) 전용 모드 관리 대화상자 (spec §6.7, P4).

로컬 ``play_modes`` 캐시를 관리한다. 원본은 서버 ``game_modes``(B2)이며, 이
대화상자는 개발자가 로컬 캐시를 추가·수정·활성/비활성 전환·삭제하는 도구다.
일반 사용자 빌드에는 노출하지 않는다(§6.7). 서버 기준정보와의 동기화는
``game_sync/modes.py``(1-H)가 담당한다.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..enums import STANDING_KINDS
from ..game_service import GameService
from .theme import METRICS, set_style_property


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    return item


class _ModeEditDialog(QDialog):
    """모드 추가/편집 폼."""

    def __init__(
        self,
        *,
        mode_id: str | None = None,
        standing_kind: str = "event_points",
        display_name: str = "",
        play_context_id: str = "",
        sort_order: int = 0,
        is_active: bool = True,
        season_label: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("모드 편집" if mode_id else "모드 추가")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(METRICS.space_2)

        form = QFormLayout()
        form.setSpacing(METRICS.space_2)

        self._id = QLineEdit(mode_id or "")
        self._id.setPlaceholderText("예: dc-cup-2026-08")
        self._id.setEnabled(mode_id is None)  # id는 생성 시에만
        form.addRow("모드 id", self._id)

        self._kind = QComboBox()
        for value, label in STANDING_KINDS:
            self._kind.addItem(label or value, value)
        index = self._kind.findData(standing_kind)
        if index >= 0:
            self._kind.setCurrentIndex(index)
        form.addRow("종류", self._kind)

        self._display = QLineEdit(display_name)
        self._display.setPlaceholderText("예: 26.08 DC컵")
        form.addRow("표시명", self._display)

        self._context = QLineEdit(play_context_id or "")
        self._context.setPlaceholderText("예: dc_cup_2026_08")
        form.addRow("문맥 id", self._context)

        self._season = QLineEdit(season_label or "")
        self._season.setPlaceholderText("예: 26.08")
        form.addRow("시즌 표기", self._season)

        self._sort = QLineEdit(str(sort_order))
        self._sort.setPlaceholderText("정렬 순서")
        form.addRow("정렬 순서", self._sort)

        self._active = QCheckBox("활성 (기록 추가 가능)")
        self._active.setChecked(is_active)
        form.addRow("", self._active)

        layout.addLayout(form)

        self._status = QLabel("")
        set_style_property(self._status, "tone", "danger")
        layout.addWidget(self._status)

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
        mode_id = self._id.text().strip()
        display = self._display.text().strip()
        if not mode_id or not display:
            self._status.setText("모드 id와 표시명은 필수입니다.")
            return
        try:
            sort_order = int(self._sort.text().strip() or "0")
        except ValueError:
            self._status.setText("정렬 순서는 정수여야 합니다.")
            return
        self._result = {
            "id": mode_id,
            "standing_kind": self._kind.currentData(),
            "display_name": display,
            "play_context_id": self._context.text().strip() or None,
            "sort_order": sort_order,
            "is_active": self._active.isChecked(),
            "season_label": self._season.text().strip() or None,
        }
        self.accept()

    def result_data(self) -> dict:
        return getattr(self, "_result", {})


class ModeManagerDialog(QDialog):
    """로컬 play_modes 캐시를 관리하는 개발자 대화상자."""

    def __init__(self, games: GameService, parent: QWidget | None = None):
        super().__init__(parent)
        self._games = games
        self.setWindowTitle("모드 관리 (개발자)")
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        layout.setSpacing(METRICS.space_2)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["id", "종류", "표시명", "문맥", "시즌", "활성"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("추가")
        edit_btn = QPushButton("편집")
        deactivate_btn = QPushButton("활성/비활성 전환")
        delete_btn = QPushButton("삭제")
        close_btn = QPushButton("닫기")
        for btn in (add_btn, edit_btn, deactivate_btn, delete_btn):
            set_style_property(btn, "role", "secondary")
        set_style_property(delete_btn, "role", "danger")
        add_btn.clicked.connect(self._add)
        edit_btn.clicked.connect(self._edit)
        deactivate_btn.clicked.connect(self._toggle_active)
        delete_btn.clicked.connect(self._delete)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(add_btn)
        buttons.addWidget(edit_btn)
        buttons.addWidget(deactivate_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._refresh()

    def _refresh(self) -> None:
        modes = self._games.get_play_modes()
        self._table.setRowCount(len(modes))
        for i, m in enumerate(modes):
            self._table.setItem(i, 0, _cell(str(m["id"])))
            self._table.setItem(i, 1, _cell(str(m["standing_kind"])))
            self._table.setItem(i, 2, _cell(str(m["display_name"])))
            self._table.setItem(i, 3, _cell(str(m["play_context_id"] or "")))
            self._table.setItem(i, 4, _cell(str(m["season_label"] or "")))
            self._table.setItem(i, 5, _cell("활성" if m["is_active"] else "비활성"))

    def _selected_mode_id(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return str(item.text()) if item is not None else None

    def _add(self) -> None:
        dlg = _ModeEditDialog()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._games.insert_play_mode(dlg.result_data())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "모드 추가 실패", f"모드를 추가하지 못했습니다.\n\n{exc}"
            )
            return
        self._refresh()

    def _edit(self) -> None:
        mode_id = self._selected_mode_id()
        if mode_id is None:
            QMessageBox.information(self, "편집", "편집할 모드를 먼저 선택하세요.")
            return
        row = self._games.get_play_mode(mode_id)
        if row is None:
            return
        dlg = _ModeEditDialog(
            mode_id=str(row["id"]),
            standing_kind=str(row["standing_kind"]),
            display_name=str(row["display_name"]),
            play_context_id=row["play_context_id"] or "",
            sort_order=int(row["sort_order"] or 0),
            is_active=bool(row["is_active"]),
            season_label=row["season_label"] or "",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        data["id"] = mode_id
        try:
            self._games.update_play_mode(mode_id, data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "모드 편집 실패", f"모드를 편집하지 못했습니다.\n\n{exc}"
            )
            return
        self._refresh()

    def _toggle_active(self) -> None:
        mode_id = self._selected_mode_id()
        if mode_id is None:
            QMessageBox.information(self, "전환", "전환할 모드를 먼저 선택하세요.")
            return
        row = self._games.get_play_mode(mode_id)
        if row is None:
            return
        self._games.update_play_mode(
            mode_id,
            {
                "standing_kind": str(row["standing_kind"]),
                "display_name": str(row["display_name"]),
                "play_context_id": row["play_context_id"],
                "sort_order": int(row["sort_order"] or 0),
                "is_active": not bool(row["is_active"]),
                "season_label": row["season_label"],
            },
        )
        self._refresh()

    def _delete(self) -> None:
        mode_id = self._selected_mode_id()
        if mode_id is None:
            QMessageBox.information(self, "삭제", "삭제할 모드를 먼저 선택하세요.")
            return
        reply = QMessageBox.question(
            self,
            "모드 삭제",
            f"모드 '{mode_id}'를 삭제할까요?\n(기존 기록 보존을 위해 비활성화를 권장합니다.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self._games.delete_play_mode(mode_id)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(
                    self, "모드 삭제 실패", f"모드를 삭제하지 못했습니다.\n\n{exc}"
                )
                return
            self._refresh()
