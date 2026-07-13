"""화면2(신규 입력)와 편집 다이얼로그가 공용으로 쓰는 입력 폼.

필드: 선/후공 · 상대 덱 · 소요 턴 · 종료 방식 · 점수(+델타) · 메모.
enum 은 전부 버튼/칩, 손 타이핑은 점수·메모뿐.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..enums import END_REASONS, TURN_ORDERS
from .widgets import SearchableDeckCombo, SingleSelect, Stepper


def _caption(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#555; font-size:12px; font-weight:600; margin-top:2px;")
    return lbl


class DetailForm(QWidget):
    def __init__(self, decks: list[str], parent=None):
        super().__init__(parent)
        self._decks = list(decks)
        self._score_base = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # 선 / 후공
        self._turn = SingleSelect(TURN_ORDERS)
        self._turn.setValue("first")
        root.addWidget(_caption("선 / 후공"))
        root.addWidget(self._turn)

        # 내 덱
        self._my_deck = SearchableDeckCombo()
        self._my_deck.set_decks(self._decks)
        root.addWidget(_caption("내 덱"))
        root.addWidget(self._my_deck)

        # 상대 덱
        self._deck = SearchableDeckCombo()
        self._deck.set_decks(self._decks)
        root.addWidget(_caption("상대 덱"))
        root.addWidget(self._deck)

        # 소요 턴
        self._turns = Stepper(minimum=1, maximum=99, value=1)
        root.addWidget(_caption("소요 턴"))
        root.addWidget(self._turns)

        # 종료 방식 (2x2 칩)
        self._reason = SingleSelect(END_REASONS, columns=2)
        self._reason.setValue("regular")
        root.addWidget(_caption("종료 방식"))
        root.addWidget(self._reason)

        # 점수 (+ 델타)
        self._score = QLineEdit()
        self._score.setValidator(QIntValidator(0, 9_999_999, self))
        self._score.setMinimumHeight(32)
        self._score.setPlaceholderText("2nd STAGE 누적 점수")
        self._delta = QLabel("")
        self._delta.setMinimumWidth(84)
        self._delta.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        score_row = QHBoxLayout()
        score_row.setContentsMargins(0, 0, 0, 0)
        score_row.setSpacing(8)
        score_row.addWidget(self._score, 1)
        score_row.addWidget(self._delta)
        score_wrap = QWidget()
        score_wrap.setLayout(score_row)
        root.addWidget(_caption("점수 (누적)"))
        root.addWidget(score_wrap)
        self._score.textChanged.connect(self._update_delta)

        # 메모
        self._note = QLineEdit()
        self._note.setMinimumHeight(32)
        self._note.setPlaceholderText("메모 (선택)")
        root.addWidget(_caption("메모"))
        root.addWidget(self._note)

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
            self._delta.setStyleSheet("")
        else:
            color = "#2e7d32" if delta > 0 else "#c62828"
            self._delta.setText(f"{delta:+,}")
            self._delta.setStyleSheet(f"color:{color}; font-weight:700;")

    # ----- 덱 목록 -----
    def set_decks(self, decks: list[str]) -> None:
        self._decks = list(decks)
        self._my_deck.set_decks(self._decks)
        self._deck.set_decks(self._decks)

    def focus_deck(self) -> None:
        # 내 덱은 보통 프리필되므로, 입력 포커스는 상대 덱에 둔다
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
