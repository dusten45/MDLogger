"""별도 관리자 앱의 서버 모드/시즌 기준정보 관리 창."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..admin_modes import AdminModesError
from ..enums import STANDING_KINDS
from .theme import METRICS, scaled, set_style_property

T = TypeVar("T")


class ModesAdmin(Protocol):
    """관리자 창이 필요한 서버 기준정보 연산."""

    @property
    def base_url(self) -> str: ...

    def fetch(self) -> list[dict[str, Any]]: ...

    def upsert(self, mode: Mapping[str, Any]) -> dict[str, Any]: ...

    def delete(self, mode_id: str) -> dict[str, Any]: ...


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    return item


class _ModeEditor(QDialog):
    """서버 모드 생성 및 편집 폼."""

    def __init__(
        self,
        mode: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        is_editing = mode is not None
        self.setWindowTitle("모드 편집" if is_editing else "모드 추가")
        self.setMinimumWidth(scaled(400))
        self._data: dict[str, Any] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(METRICS.space_2)
        form = QFormLayout()
        form.setSpacing(METRICS.space_2)

        self._id = QLineEdit(str(mode["id"]) if mode else "")
        self._id.setPlaceholderText("예: dc-cup-2026-09")
        self._id.setEnabled(not is_editing)
        form.addRow("모드 id *", self._id)

        self._kind = QComboBox()
        for value, label in STANDING_KINDS:
            self._kind.addItem(label or value, value)
        kind_index = self._kind.findData(
            mode["standing_kind"] if mode else "event_points"
        )
        self._kind.setCurrentIndex(max(kind_index, 0))
        form.addRow("종류 *", self._kind)

        self._display_name = QLineEdit(str(mode["display_name"]) if mode else "")
        self._display_name.setPlaceholderText("예: 26.09 DC컵")
        form.addRow("표시명 *", self._display_name)

        self._context_id = QLineEdit(
            str(mode.get("play_context_id") or "") if mode else ""
        )
        self._context_id.setPlaceholderText("예: dc_cup_2026_09")
        form.addRow("문맥 id *", self._context_id)

        self._season_label = QLineEdit(
            str(mode.get("season_label") or "") if mode else ""
        )
        self._season_label.setPlaceholderText("예: 26.09")
        form.addRow("시즌 표기", self._season_label)

        self._sort_order = QLineEdit(str(mode.get("sort_order") or 0) if mode else "0")
        self._sort_order.setPlaceholderText("예: 2")
        form.addRow("정렬 순서", self._sort_order)

        self._active = QCheckBox("활성 (일반 앱에서 기록 추가 가능)")
        self._active.setChecked(bool(mode.get("is_active")) if mode else True)
        form.addRow("", self._active)
        layout.addLayout(form)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setAccessibleName("입력 오류")
        set_style_property(self._error, "tone", "danger")
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setText("서버에 저장")
        set_style_property(save_button, "role", "primary")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mode_data(self) -> dict[str, Any]:
        return self._data

    def _save(self) -> None:
        mode_id = self._id.text().strip()
        display_name = self._display_name.text().strip()
        context_id = self._context_id.text().strip()
        if not mode_id or not display_name or not context_id:
            self._show_error("모드 id, 표시명, 문맥 id는 필수입니다.")
            return
        try:
            sort_order = int(self._sort_order.text().strip() or "0")
        except ValueError:
            self._show_error("정렬 순서는 정수여야 합니다.")
            return
        self._data = {
            "id": mode_id,
            "standing_kind": self._kind.currentData(),
            "display_name": display_name,
            "play_context_id": context_id,
            "sort_order": sort_order,
            "is_active": self._active.isChecked(),
            "season_label": self._season_label.text().strip() or None,
        }
        self.accept()

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._id.setFocus()


class AdminWindow(QMainWindow):
    """서버 원본 모드/시즌을 관리하는 별도 관리자 창."""

    def __init__(self, client: ModesAdmin) -> None:
        super().__init__()
        self._client = client
        self.setWindowTitle("MDLogger 관리자 — 모드/시즌 관리")
        self.resize(scaled(850), scaled(560))

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(
            METRICS.space_4, METRICS.space_4, METRICS.space_4, METRICS.space_4
        )
        layout.setSpacing(METRICS.space_3)

        title = QLabel("모드/시즌 관리")
        title.setProperty("role", "heading")
        layout.addWidget(title)

        description = QLabel(
            "서버 game_modes 기준정보를 관리합니다. 저장한 변경은 일반 앱의 다음 동기화에서 반영됩니다."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        target = QLabel(f"연결 대상: {client.base_url}")
        target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        target.setToolTip(client.base_url)
        layout.addWidget(target)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["id", "종류", "표시명", "문맥 id", "시즌", "정렬", "상태"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        self._refresh_button = QPushButton("새로고침")
        self._add_button = QPushButton("모드 추가")
        self._edit_button = QPushButton("편집")
        self._toggle_button = QPushButton("활성/비활성 전환")
        self._delete_button = QPushButton("삭제")
        for button in (
            self._refresh_button,
            self._edit_button,
            self._toggle_button,
        ):
            set_style_property(button, "role", "secondary")
        set_style_property(self._add_button, "role", "primary")
        set_style_property(self._delete_button, "role", "danger")
        self._refresh_button.clicked.connect(self.refresh)
        self._add_button.clicked.connect(self._add)
        self._edit_button.clicked.connect(self._edit)
        self._toggle_button.clicked.connect(self._toggle_active)
        self._delete_button.clicked.connect(self._delete)
        for button in (
            self._refresh_button,
            self._add_button,
            self._edit_button,
            self._toggle_button,
            self._delete_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._status = QLabel("서버 기준정보를 불러오는 중입니다.")
        self._status.setWordWrap(True)
        self._status.setAccessibleName("작업 상태")
        layout.addWidget(self._status)
        self.setCentralWidget(central)
        self.refresh()

    def refresh(self) -> None:
        rows = self._run_request("모드 목록을 불러오는 중입니다.", self._client.fetch)
        if rows is None:
            return
        self._table.setRowCount(len(rows))
        for index, mode in enumerate(rows):
            values = (
                str(mode.get("id", "")),
                str(mode.get("standing_kind", "")),
                str(mode.get("display_name", "")),
                str(mode.get("play_context_id") or ""),
                str(mode.get("season_label") or ""),
                str(mode.get("sort_order", 0)),
                "활성" if mode.get("is_active") else "비활성",
            )
            for column, value in enumerate(values):
                self._table.setItem(index, column, _cell(value))
        self._status.setText(f"모드 {len(rows)}개를 서버에서 불러왔습니다.")

    def _selected_mode(self) -> dict[str, Any] | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        return {
            "id": self._table_text(row, 0),
            "standing_kind": self._table_text(row, 1),
            "display_name": self._table_text(row, 2),
            "play_context_id": self._table_text(row, 3),
            "season_label": self._table_text(row, 4) or None,
            "sort_order": int(self._table_text(row, 5) or 0),
            "is_active": self._table_text(row, 6) == "활성",
        }

    def _table_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return item.text() if item is not None else ""

    def _add(self) -> None:
        editor = _ModeEditor(parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._save(editor.mode_data(), "모드를 저장하는 중입니다.")

    def _edit(self) -> None:
        mode = self._require_selected("편집할 모드를 먼저 선택하세요.")
        if mode is None:
            return
        editor = _ModeEditor(mode, self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._save(editor.mode_data(), "모드를 저장하는 중입니다.")

    def _toggle_active(self) -> None:
        mode = self._require_selected("전환할 모드를 먼저 선택하세요.")
        if mode is None:
            return
        mode["is_active"] = not mode["is_active"]
        self._save(mode, "모드 상태를 저장하는 중입니다.")

    def _delete(self) -> None:
        mode = self._require_selected("삭제할 모드를 먼저 선택하세요.")
        if mode is None:
            return
        answer = QMessageBox.warning(
            self,
            "모드 삭제",
            f"서버에서 모드 '{mode['id']}'를 삭제할까요?\n\n기존 기록 보존을 위해 비활성화를 우선 권장합니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self._run_request(
            "모드를 삭제하는 중입니다.", lambda: self._client.delete(str(mode["id"]))
        )
        if result is not None:
            self.refresh()

    def _save(self, mode: Mapping[str, Any], message: str) -> None:
        result = self._run_request(message, lambda: self._client.upsert(mode))
        if result is not None:
            self.refresh()

    def _require_selected(self, message: str) -> dict[str, Any] | None:
        mode = self._selected_mode()
        if mode is None:
            QMessageBox.information(self, "모드 선택", message)
        return mode

    def _run_request(self, message: str, request: Callable[[], T]) -> T | None:
        self._set_actions_enabled(False)
        self._status.setText(message)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        QApplication.processEvents()
        try:
            return request()
        except AdminModesError as error:
            self._status.setText(str(error))
            QMessageBox.critical(self, "서버 요청 실패", str(error))
            return None
        finally:
            QApplication.restoreOverrideCursor()
            self._set_actions_enabled(True)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self._refresh_button,
            self._add_button,
            self._edit_button,
            self._toggle_button,
            self._delete_button,
        ):
            button.setEnabled(enabled)
