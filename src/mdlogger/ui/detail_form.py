"""화면2(신규 입력)와 편집 다이얼로그가 공용으로 쓰는 입력 폼.

필드: 선/후공 · 상대 덱 · 소요 턴 · 종료 방식 · 점수(+델타) · 메모.
enum 은 전부 버튼/칩, 손 타이핑은 점수·메모뿐.

§9.2 읽기/Tab 순서: 진행 정보 → 덱 → 종료 방식 → 점수 → 메모.
색상·간격·폰트는 `theme.py` 토큰과 역할 기반 스타일을 사용한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..enums import END_REASONS, TURN_ORDERS
from .theme import METRICS, FontRole, font_for_role, set_style_property
from .widgets import SearchableDeckCombo, SingleSelect, Stepper


def _caption(text: str) -> QLabel:
    """필드 레이블: muted tone + caption 폰트 (placeholder 대체 명시 레이블)."""
    lbl = QLabel(text)
    set_style_property(lbl, "tone", "muted")
    lbl.setWordWrap(True)
    lbl.setFont(font_for_role(lbl.font(), FontRole.LABEL))
    return lbl


def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
    """섹션 표면: surface="section" QFrame + 섹션 제목 + 필드 열."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.NoFrame)
    set_style_property(frame, "surface", "section")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(
        METRICS.space_2, METRICS.space_2, METRICS.space_2, METRICS.space_2
    )
    layout.setSpacing(METRICS.space_2)
    heading = QLabel(title)
    set_style_property(heading, "role", "section")
    heading.setFont(font_for_role(heading.font(), FontRole.SECTION))
    layout.addWidget(heading)
    return frame, layout


def _field_row(label: str, widget: QWidget) -> QHBoxLayout:
    """레이블을 입력 옆에 두는 세로 공간 절약형 행 (덱 이름은 입력이 확장 담당)."""
    row = QHBoxLayout()
    row.setSpacing(METRICS.space_2)
    caption = _caption(label)
    caption.setWordWrap(False)
    caption.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
    row.addWidget(caption)
    row.addWidget(widget, 1)
    return row


class DetailForm(QWidget):
    def __init__(self, decks: list[str], parent=None):
        super().__init__(parent)
        self._decks = list(decks)
        self._score_base = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(METRICS.space_2)

        # 진행 정보: 선/후공 + 소요 턴 (폭이 허용되면 같은 행)
        progress, progress_col = _section("진행 정보")
        self._turn = SingleSelect(TURN_ORDERS)
        self._turn.setValue("first")
        self._turns = Stepper(minimum=1, maximum=99, value=1)
        row = QHBoxLayout()
        row.setSpacing(METRICS.space_3)
        row.addWidget(self._turn, 1)
        row.addWidget(self._turns)
        progress_col.addLayout(row)
        root.addWidget(progress)

        # 덱 (레이블 옆에 콤보를 두어 세로 공간 절약)
        decks_frame, decks_col = _section("덱")
        self._my_deck = SearchableDeckCombo()
        self._my_deck.set_decks(self._decks)
        decks_col.addLayout(_field_row("내 덱 (검색/선택)", self._my_deck))
        self._deck = SearchableDeckCombo()
        self._deck.set_decks(self._decks)
        decks_col.addLayout(_field_row("상대 덱 (검색/선택)", self._deck))
        root.addWidget(decks_frame)

        # 종료 방식 (2x2 칩)
        reason_frame, reason_col = _section("종료 방식")
        self._reason = SingleSelect(END_REASONS, columns=2)
        self._reason.setValue("regular")
        reason_col.addWidget(self._reason)
        root.addWidget(reason_frame)

        # 점수 (+ 델타)
        score_frame, score_col = _section("점수")
        self._score = QLineEdit()
        self._score.setValidator(QIntValidator(0, 9_999_999, self))
        self._score.setPlaceholderText("2nd STAGE 누적 점수")
        self._delta = QLabel("")
        self._delta.setMinimumWidth(84)
        self._delta.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        score_row = QHBoxLayout()
        score_row.setContentsMargins(0, 0, 0, 0)
        score_row.setSpacing(METRICS.space_2)
        score_row.addWidget(self._score, 1)
        score_row.addWidget(self._delta)
        score_col.addLayout(score_row)
        root.addWidget(score_frame)
        self._score.textChanged.connect(self._update_delta)

        # 메모
        note_frame, note_col = _section("메모")
        self._note = QLineEdit()
        self._note.setPlaceholderText("메모 (선택)")
        note_col.addWidget(self._note)
        root.addWidget(note_frame)

    # ----- 점수/델타 -----
    def score_value(self) -> int:
        t = self._score.text().strip()
        return int(t) if t else 0

    def set_score_base(self, base: int) -> None:
        """직전 점수로 프리필하고 델타 기준값 설정."""
        self._score_base = int(base)
        self._score.blockSignals(True)
        self._score.setText(str(self._score_base))
        self._score.blockSignals(False)
        self._update_delta()

    def _update_delta(self) -> None:
        delta = self.score_value() - self._score_base
        if delta == 0:
            self._delta.setText("")
            set_style_property(self._delta, "tone", None)
        else:
            # 부호(+,−)와 텍스트로 색상 없이도 의미를 전달한다 (§9.2)
            set_style_property(
                self._delta, "tone", "success" if delta > 0 else "danger"
            )
            self._delta.setText(f"{delta:+,}")

    # ----- 덱 목록 -----
    def set_decks(self, decks: list[str]) -> None:
        self._decks = list(decks)
        self._my_deck.set_decks(self._decks)
        self._deck.set_decks(self._decks)

    def focus_deck(self) -> None:
        # 내 덱은 보통 프리필되므로, 입력 포커스는 상대 덱에 둔다
        self._deck.setFocus()

    def focus_first_invalid(self) -> None:
        """저장 오류 후 첫 번째(시각적으로 위에 있는) 검증 실패 필드로 포커스를 옮긴다."""
        if self._my_deck.resolve() is None:
            self._my_deck.setFocus()
        else:
            self._deck.setFocus()

    # ----- 값 입출력 -----
    def values(self) -> dict | None:
        """검증된 입력값 dict. 내 덱/상대 덱이 모호하면 None(+빨간 테두리)."""
        my_deck = self._my_deck.resolve()
        opp_deck = self._deck.resolve()

        for combo, resolved in ((self._my_deck, my_deck), (self._deck, opp_deck)):
            if resolved is None:
                combo.mark_invalid()
            else:
                combo.clear_invalid()
        if my_deck is None or opp_deck is None:
            return None

        return {
            "turn_order": self._turn.value(),
            "my_deck": my_deck,
            "opp_deck": opp_deck,
            "turns": self._turns.value(),
            "end_reason": self._reason.value(),
            "score_after": self.score_value(),
            "note": self._note.text().strip(),
        }

    def set_values(self, row) -> None:
        """편집용: 기존 레코드로 폼 채우기."""
        self._turn.setValue(row["turn_order"])
        self._reason.setValue(row["end_reason"])
        self._turns.set_value(int(row["turns"]) if row["turns"] else 1)
        self._my_deck.clear_invalid()
        self._my_deck.setEditText(row["my_deck"] or "")
        self._deck.clear_invalid()
        self._deck.setEditText(row["opp_deck"] or "")
        self._note.setText(row["note"] or "")
        base = int(row["score_after"]) if row["score_after"] is not None else 0
        self.set_score_base(base)

    def reset(self, score_base: int = 0, my_deck: str = "") -> None:
        """저장 후 신규 입력용 기본값으로 초기화. 내 덱은 직전값으로 프리필."""
        self._turn.setValue("first")
        self._reason.setValue("regular")
        self._turns.set_value(1)
        self._my_deck.clear_invalid()
        self._my_deck.setEditText(my_deck or "")
        self._deck.clear_invalid()
        self._deck.setEditText("")
        self._note.clear()
        self.set_score_base(score_base)
