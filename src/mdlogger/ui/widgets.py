"""재사용 UI 컴포넌트.

- SingleSelect : 상호배타 버튼/칩 단일 선택 (enum 입력 — 오타 차단)
- SearchableDeckCombo : 타이핑 필터링되는 덱 검색 콤보박스
- Stepper : −/＋ 버튼만으로 조작하는 정수 스테퍼 (키 입력 불가)
- Card : 통계 요약 카드
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .icons import load_icon
from .theme import METRICS, FontRole, font_for_role, scaled, set_style_property


class FlowLayout(QLayout):
    """폭을 넘으면 다음 줄로 감싸는 flow 레이아웃 (칩/버튼 그룹용).

    ``QHBoxLayout``과 달리 가용 폭을 넘는 항목을 자동으로 다음 줄로 내려
    380px 최소 폭이나 글자 확대 시에도 가로 넘침이 생기지 않게 한다(spec §7.3).
    """

    def __init__(self, parent: QWidget | None = None, *, spacing: int = -1):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class SingleSelect(QWidget):
    """(value, label) 옵션 중 하나만 선택하는 버튼 그룹.

    색상은 `theme.py`의 `role="segment"` 역할 기반 QSS로 채택한다.
    `color_map`은 하위 호환을 위해 받아들이지만 더 이상 인라인 색으로 적용하지 않는다.
    """

    changed = Signal(str)

    def __init__(self, options, *, columns: int = 0, color_map=None, parent=None):
        super().__init__(parent)
        color_map = color_map or {}
        self._buttons: dict[str, QPushButton] = {}
        self._values: dict[QPushButton, str] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        if columns > 0:
            layout: QLayout = QGridLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(METRICS.space_2)
        else:
            layout = FlowLayout(self, spacing=METRICS.space_2)

        for i, (value, text) in enumerate(options):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(METRICS.control_height)
            btn.setAccessibleName(text)
            # 키보드/스크린 리더 접근성을 위해 포커스를 허용한다(spec §6.1)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            set_style_property(btn, "role", "segment")
            btn.setFont(font_for_role(btn.font(), FontRole.LABEL))
            self._group.addButton(btn)
            self._buttons[value] = btn
            self._values[btn] = value
            if isinstance(layout, QGridLayout):
                layout.addWidget(btn, i // columns, i % columns)
            else:
                layout.addWidget(btn)

        self._group.buttonClicked.connect(self._on_clicked)

    def _on_clicked(self, btn: QPushButton) -> None:
        self.changed.emit(self._values[btn])

    def value(self) -> str | None:
        checked = self._group.checkedButton()
        return self._values.get(checked) if checked is not None else None

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


class ResultSelect(QWidget):
    """승/패 선택 (초록/빨강 legacy 유지, `result-win`/`result-loss` 역할).

    `SingleSelect`는 `segment` 역할을 강제하므로 쓰지 않고, 초록(승)/빨강(패)
    색상을 유지하는 소형 전용 위젯이다(spec §3.2). 라벨("승"/"패")이 항상
    표시되어 색상만으로 구분하지 않는다.
    """

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAccessibleName("이번 듀얼의 결과 선택")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._values: dict[QPushButton, str] = {}
        self._labels: dict[str, str] = {}
        for value, text, role in (
            ("win", "승", "result-win"),
            ("lose", "패", "result-loss"),
        ):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(METRICS.control_height)
            btn.setAccessibleName(text)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            set_style_property(btn, "role", role)
            set_style_property(btn, "compact", True)
            btn.setFont(font_for_role(btn.font(), FontRole.LABEL))
            self._group.addButton(btn)
            self._buttons[value] = btn
            self._values[btn] = value
            self._labels[value] = text
            btn.toggled.connect(self._on_toggled)
            # 두 버튼이 항상 같은 폭을 유지해 체크 표시가 레이아웃을 밀지 않게 한다.
            layout.addWidget(btn, 1)

        self._group.buttonClicked.connect(self._on_clicked)

    def _on_clicked(self, btn: QPushButton) -> None:
        self.changed.emit(self._values[btn])

    def _on_toggled(self, checked: bool) -> None:
        """선택 상태를 색상만으로 전달하지 않도록 체크 표시(✓)를 덧붙인다."""
        btn = self.sender()
        if not isinstance(btn, QPushButton):
            return
        label = self._labels[self._values[btn]]
        btn.setText(f"✓ {label}" if checked else label)

    def value(self) -> str | None:
        checked = self._group.checkedButton()
        return self._values.get(checked) if checked is not None else None

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
    한글 등 IME 입력이 `textEdited`를 거치지 않고 텍스트만 바꾸는 commit 경로와
    조합(preedit) 단계 양쪽에서도 completer가 실시간으로 필터링되도록
    `textChanged` 연결 + InputMethod 이벤트 필터를 사용한다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._decks: list[str] = []
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(12)
        self.setMinimumHeight(METRICS.control_height_small)

        completer = self.completer()
        if completer is not None:
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        # 실시간 필터링을 두 경로로 보장한다.
        # 1) textChanged: 키보드뿐 아니라 실제 Linux IBus처럼 `textEdited`를
        #    발화하지 않고 텍스트만 바꾸는 IME commit 경로까지 커버한다.
        # 2) InputMethod 이벤트 필터: 조합(preedit) 단계에서도 반영한다.
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.textChanged.connect(self._refresh_completer)
            line_edit.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        # 한글 등 IME 조합(preedit) 단계에서도 completer가 실시간으로 갱신되도록
        # 조합 중인 문자열까지 포함한 현재 텍스트로 completer를 갱신한다.
        if obj is self.lineEdit() and event.type() == QEvent.Type.InputMethod:
            preedit = event.preeditString()
            if preedit:
                text = obj.text()
                pos = obj.cursorPosition()
                effective = text[:pos] + preedit + text[pos:]
                self._refresh_completer(effective)
        return super().eventFilter(obj, event)

    def _refresh_completer(self, text: str) -> None:
        """현재 입력(조합 포함)을 prefix로 completer를 갱신하고 팝업을 띄운다."""
        completer = self.completer()
        if completer is None:
            return
        completer.setCompletionPrefix(text)
        popup = completer.popup()
        if popup is None:
            return
        if text and completer.completionCount() > 0:
            completer.complete()
        else:
            popup.hide()

    def _hide_completer_popup(self) -> None:
        completer = self.completer()
        if completer is not None and (popup := completer.popup()) is not None:
            popup.hide()

    def setEditText(self, text: str) -> None:
        """프로그램이 넣는 기본값에서는 자동완성 팝업을 열지 않는다."""
        line_edit = self.lineEdit()
        if line_edit is None:
            super().setEditText(text)
        else:
            signals_blocked = line_edit.blockSignals(True)
            try:
                super().setEditText(text)
            finally:
                line_edit.blockSignals(signals_blocked)
        self._hide_completer_popup()

    def set_decks(self, decks: list[str]) -> None:
        self._decks = list(decks)
        line_edit = self.lineEdit()
        combo_signals_blocked = self.blockSignals(True)
        line_signals_blocked = (
            line_edit.blockSignals(True) if line_edit is not None else False
        )
        try:
            self.clear()
            self.addItems(self._decks)
            self.setEditText("")
        finally:
            self.blockSignals(combo_signals_blocked)
            if line_edit is not None:
                line_edit.blockSignals(line_signals_blocked)
        self._hide_completer_popup()

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
        """theme QSS의 `[invalid="true"]` 상태를 켜 빨간 테두리로 표시한다."""
        set_style_property(self, "invalid", True)

    def clear_invalid(self) -> None:
        set_style_property(self, "invalid", None)


class Stepper(QWidget):
    """−/＋ 또는 아이콘 버튼만으로 조작하는 정수 스테퍼 (키 입력 없음)."""

    changed = Signal(int)

    def __init__(
        self, minimum: int = 1, maximum: int = 99, value: int = 1, parent=None
    ):
        super().__init__(parent)
        self._min = minimum
        self._max = maximum
        self._value = max(minimum, min(maximum, value))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_2)

        self._minus = self._step_button("−", "minus", "소요 턴 감소")
        self._plus = self._step_button("＋", "plus", "소요 턴 증가")

        self._label = QLabel(str(self._value))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumWidth(scaled(48))
        self._label.setFont(font_for_role(self._label.font(), FontRole.SECTION))

        self._minus.clicked.connect(lambda: self.set_value(self._value - 1))
        self._plus.clicked.connect(lambda: self.set_value(self._value + 1))

        layout.addWidget(self._minus)
        layout.addWidget(self._label)
        layout.addWidget(self._plus)
        layout.addStretch(1)

    def _step_button(
        self, text: str, icon_name: str, accessible_name: str
    ) -> QPushButton:
        btn = QPushButton(text)
        # 진행 정보 행에서 세그먼트 버튼과 높이를 맞춘다
        btn.setFixedSize(scaled(40), METRICS.control_height)
        # 키보드 접근성을 위해 포커스를 허용한다(spec §6.1)
        btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setAccessibleName(accessible_name)
        btn.setToolTip(accessible_name)
        # 아이콘을 기본으로, SVG가 없으면 텍스트로 동작을 설명한다(§10).
        icon = load_icon(icon_name)
        if icon is not None:
            btn.setIcon(icon)
            btn.setIconSize(QSize(METRICS.icon_small, METRICS.icon_small))
            btn.setText("")
        return btn

    def value(self) -> int:
        return self._value

    def set_value(self, v: int) -> None:
        v = max(self._min, min(self._max, v))
        self._label.setText(str(v))
        if v != self._value:
            self._value = v
            self.changed.emit(v)


class Card(QFrame):
    """통계 요약 카드: 제목 + 큰 값.

    표면은 `theme.py`의 `surface="summary-card"` 역할 기반 QSS로 채택한다.
    """

    def __init__(self, title: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        set_style_property(self, "surface", "summary-card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_3, METRICS.space_2, METRICS.space_3, METRICS.space_2
        )
        layout.setSpacing(0)

        self._title = QLabel(title)
        set_style_property(self._title, "tone", "muted")
        self._title.setFont(font_for_role(self._title.font(), FontRole.CAPTION))
        self._value = QLabel(value)
        self._value.setFont(font_for_role(self._value.font(), FontRole.NUMERIC))

        layout.addWidget(self._title)
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)
