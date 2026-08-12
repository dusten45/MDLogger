"""개발용 위젯 gallery / 수동 harness.

제품 메뉴에는 노출하지 않는 개발 전용 창. 테마 토큰과 역할 기반 QSS가
라이트·다크에서 각 위젯·상태 조합을 어떻게 보여주는지 한 화면에서 눈으로 확인한다
(`docs/post-step5-work-spec.md` 항목 1).

진입점:
- ``python -m mdlogger.ui.widget_gallery``
- ``run_gallery()`` 함수 호출

hover/pressed 상태는 버튼을 직접 조작해 확인하고, disabled는 별도 버튼으로
Light/Dark 두 모드에서 구분되는지 본다. 픽셀 스크린샷 비교는 하지 않는다(스펙 §16).
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import (
    METRICS,
    FontRole,
    ThemeController,
    ThemeMode,
    apply_theme,
    font_for_role,
    set_style_property,
)
from .widgets import Card, SearchableDeckCombo, SingleSelect, Stepper

# SearchableDeckCombo 데모용 덱 목록
_GALLERY_DECKS = ["서브테러", "테라나이트", "신유희왕"]


def _group(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    """제목을 가진 수직 QGroupBox와 그 레이아웃을 만든다."""
    box = QGroupBox(title)
    layout = QVBoxLayout()
    layout.setSpacing(METRICS.space_2)
    box.setLayout(layout)
    return box, layout


def _role_buttons(role: str, text: str) -> QWidget:
    """역할이 같은 버튼을 enabled/disabled 한 쌍으로 만든다."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(METRICS.space_2)

    enabled = QPushButton(text)
    enabled.setCursor(Qt.CursorShape.PointingHandCursor)
    set_style_property(enabled, "role", role)

    disabled = QPushButton(text)
    set_style_property(disabled, "role", role)
    disabled.setEnabled(False)

    layout.addWidget(enabled)
    layout.addWidget(disabled)
    return container


class WidgetGallery(QDialog):
    """라이트·다크에서 위젯·상태 조합을 한 화면에 보여주는 개발용 창."""

    def __init__(
        self,
        controller: ThemeController | None = None,
        parent: QWidget | None = None,
    ) -> None:
        # QDialog를 만들기 전에 QApplication이 반드시 있어야 한다.
        # 컨트롤러가 주입되지 않았다면 이곳에서 보장한다.
        app = None
        if controller is None:
            instance = QApplication.instance()
            if isinstance(instance, QApplication):
                app = instance
            else:
                app = QApplication(sys.argv)

        super().__init__(parent)
        self.setWindowTitle("위젯 갤러리 (개발용)")
        self.resize(760, 680)

        self._controller = controller
        if self._controller is None:
            assert app is not None
            self._controller = apply_theme(app, ThemeMode.LIGHT)

        root = QVBoxLayout(self)
        root.setSpacing(METRICS.space_3)

        # 라이트/다크 즉시 전환 토글
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(METRICS.space_2)
        toggle_label = QLabel("테마")
        toggle_label.setFont(font_for_role(toggle_label.font(), FontRole.LABEL))
        self._theme_combo = QComboBox()
        self._theme_combo.addItem("라이트", ThemeMode.LIGHT)
        self._theme_combo.addItem("다크", ThemeMode.DARK)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        toggle_row.addWidget(toggle_label)
        toggle_row.addWidget(self._theme_combo)
        toggle_row.addStretch(1)
        root.addLayout(toggle_row)

        # 콤보를 컨트롤러의 현재 모드와 동기화한다 (기본은 라이트)
        current_mode = (
            self._controller.mode if self._controller is not None else ThemeMode.LIGHT
        )
        self.set_theme_mode(current_mode)

        # 스크롤 영역 안에 모든 상태 조합
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(METRICS.space_4)

        content_layout.addWidget(self._build_button_roles())
        content_layout.addWidget(self._build_segment())
        content_layout.addWidget(self._build_text_inputs())
        content_layout.addWidget(self._build_choice_widgets())
        content_layout.addWidget(self._build_common_widgets())
        content_layout.addWidget(self._build_result_buttons())
        content_layout.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def keyPressEvent(self, event) -> None:
        # 개발용 창이므로 ESC로 대화상자가 닫히지 않게 한다 (실수로 꺼지지 않도록).
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)

    @property
    def theme_controller(self) -> ThemeController | None:
        return self._controller

    def set_theme_mode(self, mode: ThemeMode) -> None:
        """라이트/다크를 즉시 전환하고 토글 콤보 표시도 동기화한다.

        프로그램적으로 호출해도 콤보가 실제 모드를 반영하도록 한다. 재귀를
        막기 위해 콤보 갱신 시 시그널을 잠시 차단한다.
        """
        if self._controller is not None:
            self._controller.set_mode(mode)
        index = self._theme_combo.findData(mode)
        if index >= 0 and self._theme_combo.currentIndex() != index:
            self._theme_combo.blockSignals(True)
            self._theme_combo.setCurrentIndex(index)
            self._theme_combo.blockSignals(False)

    def _on_theme_changed(self, index: int) -> None:
        # itemData는 StrEnum 멤버를 문자열 값으로 돌려주므로 다시 ThemeMode로 변환한다.
        value = self._theme_combo.itemData(index)
        if isinstance(value, str):
            try:
                mode = ThemeMode(value)
            except ValueError:
                return
            self.set_theme_mode(mode)

    def _build_button_roles(self) -> QGroupBox:
        box, layout = _group(
            "버튼 역할 (enabled / disabled — hover·pressed는 조작으로 확인)"
        )
        form = QFormLayout()
        form.setSpacing(METRICS.space_2)
        for role, text in (
            ("primary", "기본"),
            ("secondary", "보조"),
            ("ghost", "고스트"),
            ("danger", "위험"),
        ):
            form.addRow(role, _role_buttons(role, text))
        layout.addLayout(form)
        return box

    def _build_segment(self) -> QGroupBox:
        box, layout = _group("세그먼트 (SingleSelect — 선택됨/선택 안 됨)")
        segment = SingleSelect([("a", "첫 번째"), ("b", "두 번째"), ("c", "세 번째")])
        segment.setValue("b")  # 하나 선택 → 나머지는 선택 안 됨 상태를 함께 보여준다
        layout.addWidget(segment)
        return box

    def _build_text_inputs(self) -> QGroupBox:
        box, layout = _group("텍스트 입력 (일반 / focus / invalid / disabled)")
        form = QFormLayout()
        form.setSpacing(METRICS.space_2)

        normal = QLineEdit("일반 입력")
        form.addRow("일반", normal)

        focus = QLineEdit("포커스 상태")
        focus.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        form.addRow("focus", focus)

        invalid = QLineEdit("잘못된 값")
        set_style_property(invalid, "invalid", True)
        form.addRow("invalid", invalid)

        disabled = QLineEdit("비활성 입력")
        disabled.setEnabled(False)
        form.addRow("disabled", disabled)

        combo = QComboBox()
        combo.addItems(["옵션 A", "옵션 B", "옵션 C"])
        form.addRow("QComboBox", combo)
        layout.addLayout(form)
        return box

    def _build_choice_widgets(self) -> QGroupBox:
        box, layout = _group("선택 위젯 (checked / unchecked / disabled)")
        form = QFormLayout()
        form.setSpacing(METRICS.space_2)

        check_row = QWidget()
        check_layout = QHBoxLayout(check_row)
        check_layout.setContentsMargins(0, 0, 0, 0)
        check_layout.setSpacing(METRICS.space_3)
        check_layout.addWidget(QCheckBox("미선택"))
        checked = QCheckBox("선택됨")
        checked.setChecked(True)
        check_layout.addWidget(checked)
        disabled_check = QCheckBox("비활성")
        disabled_check.setChecked(True)
        disabled_check.setEnabled(False)
        check_layout.addWidget(disabled_check)
        form.addRow("QCheckBox", check_row)

        radio_row = QWidget()
        radio_layout = QHBoxLayout(radio_row)
        radio_layout.setContentsMargins(0, 0, 0, 0)
        radio_layout.setSpacing(METRICS.space_3)
        # 같은 부모를 공유하면 QRadioButton이 자동으로 상호 배타 그룹이 되어
        # 하나를 누르면 나머지가 풀린다. 갤러리에서는 각 상태를 독립적으로
        # 보여주고 싶으므로 비배타 그룹으로 묶어 독립 선택되게 한다.
        radio_group = QButtonGroup(self)
        radio_group.setExclusive(False)
        unchecked_radio = QRadioButton("미선택")
        checked_radio = QRadioButton("선택됨")
        checked_radio.setChecked(True)
        disabled_radio = QRadioButton("비활성")
        disabled_radio.setChecked(True)
        disabled_radio.setEnabled(False)
        for btn in (unchecked_radio, checked_radio, disabled_radio):
            radio_group.addButton(btn)
            radio_layout.addWidget(btn)
        form.addRow("QRadioButton", radio_row)

        disabled_combo = QComboBox()
        disabled_combo.addItems(["비활성 콤보"])
        disabled_combo.setEnabled(False)
        form.addRow("QComboBox(disabled)", disabled_combo)

        layout.addLayout(form)
        return box

    def _build_common_widgets(self) -> QGroupBox:
        box, layout = _group("공통 위젯")
        form = QFormLayout()
        form.setSpacing(METRICS.space_2)

        stepper = Stepper(minimum=1, maximum=10, value=3)
        stepper.setFixedWidth(200)
        form.addRow("Stepper", stepper)

        card = Card("승률", "66%")
        card.setFixedWidth(200)
        form.addRow("Card", card)

        # 빈 상태로 시작해 한 글자씩 입력할 때마다 실시간 필터링이 되는지
        # 바로 확인할 수 있게 한다. (미리 채워두면 그 위에 타이핑되어
        # 매칭이 생기지 않아 테스트가 막히는 문제가 있었다)
        valid_combo = SearchableDeckCombo()
        valid_combo.set_decks(_GALLERY_DECKS)
        valid_combo.setPlaceholderText("예: '테라' 입력 → 필터링 목록")
        form.addRow("SearchableDeckCombo(유효)", valid_combo)

        # 무효 상태(빨간 테두리)는 별도로 보여준다.
        invalid_combo = SearchableDeckCombo()
        invalid_combo.set_decks(_GALLERY_DECKS)
        invalid_combo.setEditText("존재하지 않는 덱")
        invalid_combo.mark_invalid()
        form.addRow("SearchableDeckCombo(무효)", invalid_combo)

        layout.addLayout(form)
        return box

    def _build_result_buttons(self) -> QGroupBox:
        box, layout = _group("결과 승/패 버튼 (normal / hover / pressed)")
        win = QPushButton("승")
        set_style_property(win, "role", "result-win")
        win.setMinimumHeight(METRICS.result_height)
        lose = QPushButton("패")
        set_style_property(lose, "role", "result-loss")
        lose.setMinimumHeight(METRICS.result_height)

        row = QHBoxLayout()
        row.setSpacing(METRICS.space_3)
        row.addWidget(win, 1)
        row.addWidget(lose, 1)
        layout.addLayout(row)
        return box


def run_gallery() -> int:
    """QApplication을 만들고 위젯 gallery를 표시한다 (개발용 진입점)."""
    app = QApplication(sys.argv)
    app.setApplicationName("MD WCQ 로거 — 위젯 갤러리")
    gallery = WidgetGallery()
    gallery.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gallery())
