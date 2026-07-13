"""재사용 UI 컴포넌트.

- SingleSelect : 상호배타 버튼/칩 단일 선택 (enum 입력 — 오타 차단)
- SearchableDeckCombo : 타이핑 필터링되는 덱 검색 콤보박스
- Stepper : −/＋ 버튼만으로 조작하는 정수 스테퍼 (키 입력 불가)
- Card : 통계 요약 카드
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

ACCENT = "#1565c0"


def _seg_style(checked_bg: str) -> str:
    return f"""
        QPushButton {{
            padding: 7px 10px;
            border: 1px solid #c4c4c4;
            border-radius: 6px;
            background: #f3f3f3;
            color: #222;
        }}
        QPushButton:hover {{ background: #e9e9e9; }}
        QPushButton:checked {{
            background: {checked_bg};
            color: white;
            border-color: {checked_bg};
            font-weight: 600;
        }}
    """


class SingleSelect(QWidget):
    """(value, label) 옵션 중 하나만 선택하는 버튼 그룹."""

    changed = Signal(str)

    def __init__(self, options, *, columns: int = 0, color_map=None, parent=None):
        super().__init__(parent)
        color_map = color_map or {}
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        if columns and columns > 0:
            layout = QGridLayout(self)
        else:
            layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        for i, (value, text) in enumerate(options):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(38)
            btn.setStyleSheet(_seg_style(color_map.get(value, ACCENT)))
            self._group.addButton(btn)
            self._buttons[value] = btn
            if columns and columns > 0:
                layout.addWidget(btn, i // columns, i % columns)
            else:
                layout.addWidget(btn)

        self._group.buttonClicked.connect(self._on_clicked)

    def _on_clicked(self, btn: QPushButton) -> None:
        for value, b in self._buttons.items():
            if b is btn:
                self.changed.emit(value)
                return

    def value(self) -> str | None:
        for value, b in self._buttons.items():
            if b.isChecked():
                return value
        return None

    def setValue(self, value: str | None) -> None:
        """프로그램적 선택 (changed 시그널은 발생하지 않음)."""
        btn = self._buttons.get(value)
        if btn is not None:
            btn.setChecked(True)
        else:
            checked = self._group.checkedButton()
            if checked is not None:
                self._group.setExclusive(False)
                checked.setChecked(False)
                self._group.setExclusive(True)


class SearchableDeckCombo(QComboBox):
    """타이핑하면 부분일치로 필터링되는 덱 콤보박스.

    타이핑은 '검색' 용도이며 최종값은 후보(또는 '기타') 중 하나로 확정된다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._decks: list[str] = []
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(12)
        self.setMinimumHeight(34)

        completer = self.completer()
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)

    def set_decks(self, decks: list[str]) -> None:
        self._decks = list(decks)
        self.blockSignals(True)
        self.clear()
        self.addItems(self._decks)
        self.setEditText("")
        self.blockSignals(False)

    def current_deck(self) -> str:
        return self.currentText().strip()

    def is_valid(self) -> bool:
        return self.resolve() is not None

    def resolve(self) -> str | None:
        """입력 텍스트를 후보 중 하나로 해석. 모호하면 None."""
        text = self.current_deck()
        if not text:
            return None
        for d in self._decks:  # 정확 일치(대소문자 무시) 우선
            if d.lower() == text.lower():
                return d
        matches = [d for d in self._decks if text.lower() in d.lower()]
        if len(matches) == 1:  # 부분일치 단일 후보면 확정
            return matches[0]
        return None

    def mark_invalid(self) -> None:
        self.setStyleSheet("QComboBox { border: 1px solid #c62828; }")

    def clear_invalid(self) -> None:
        self.setStyleSheet("")


class Stepper(QWidget):
    """−/＋ 버튼만으로 조작하는 정수 스테퍼 (키 입력 없음)."""

    changed = Signal(int)

    def __init__(self, minimum: int = 1, maximum: int = 99, value: int = 1, parent=None):
        super().__init__(parent)
        self._min = minimum
        self._max = maximum
        self._value = max(minimum, min(maximum, value))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._minus = QPushButton("−")
        self._plus = QPushButton("＋")
        for b in (self._minus, self._plus):
            b.setFixedSize(40, 36)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton { border:1px solid #c4c4c4; border-radius:6px;"
                " background:#f3f3f3; font-size:16px; }"
                " QPushButton:hover { background:#e9e9e9; }"
            )

        self._label = QLabel(str(self._value))
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMinimumWidth(48)
        self._label.setStyleSheet("font-size:15px; font-weight:600;")

        self._minus.clicked.connect(lambda: self.set_value(self._value - 1))
        self._plus.clicked.connect(lambda: self.set_value(self._value + 1))

        layout.addWidget(self._minus)
        layout.addWidget(self._label)
        layout.addWidget(self._plus)
        layout.addStretch(1)

    def value(self) -> int:
        return self._value

    def set_value(self, v: int) -> None:
        v = max(self._min, min(self._max, v))
        self._label.setText(str(v))
        if v != self._value:
            self._value = v
            self.changed.emit(v)


class Card(QFrame):
    """통계 요약 카드: 제목 + 큰 값."""

    def __init__(self, title: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "#card { background:#fafafa; border:1px solid #e0e0e0; border-radius:8px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setStyleSheet("color:#666; font-size:11px;")
        self._value = QLabel(value)
        self._value.setStyleSheet("font-size:18px; font-weight:700; color:#1a1a1a;")

        layout.addWidget(self._title)
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)
