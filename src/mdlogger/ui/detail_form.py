"""화면2(신규 입력)와 편집 다이얼로그가 공용으로 쓰는 입력 폼.

공통 필드: 선/후공 · 내/상대 덱 · 소요 턴 · 종료 방식 · 메모.
모드별 상태 입력만 교체한다 (spec §6.2):
- 점수 모드: 경기 전/후 점수 + 변화량
- 랭크 모드: 경기 전 티어·단계(프리필) + 빠른 버튼(변동 없음/승급/강등) + 직접 선택
- 레이팅 모드: 경기 전/후 레이팅

enum 은 전부 버튼/칩, 손 타이핑은 점수·레이팅·메모뿐.
색상·간격·폰트는 `theme.py` 토큀과 역할 기반 스타일을 사용한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..enums import (
    END_REASONS,
    RANK_DIVISION_MAX,
    RANK_DIVISION_MIN,
    RANK_TIERS,
    TURN_ORDERS,
)
from ..models import GameMode, RankStanding, StandingKind
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


def _field_layout_row(label: str, inner: QHBoxLayout) -> QHBoxLayout:
    """레이블을 레이아웃 옆에 두는 행 (랭크 티어·단계 콤보 행)."""
    row = QHBoxLayout()
    row.setSpacing(METRICS.space_2)
    caption = _caption(label)
    caption.setWordWrap(False)
    caption.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
    row.addWidget(caption)
    row.addLayout(inner, 1)
    return row


def _int_line(placeholder: str) -> QLineEdit:
    line = QLineEdit()
    line.setValidator(QIntValidator(0, 9_999_999))
    line.setPlaceholderText(placeholder)
    return line


def _tier_combo() -> QComboBox:
    combo = QComboBox()
    for value, label in RANK_TIERS:
        combo.addItem(label, value)
    combo.setMinimumHeight(METRICS.control_height_small)
    return combo


def _division_combo() -> QComboBox:
    combo = QComboBox()
    for division in range(RANK_DIVISION_MIN, RANK_DIVISION_MAX + 1):
        combo.addItem(str(division), division)
    combo.setMinimumHeight(METRICS.control_height_small)
    return combo


class _RankPanel(QWidget):
    """랭크 모드 상태 입력: 경기 전 프리필 + 빠른 변동 + 직접 선택."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(METRICS.space_2)

        self._before_tier = _tier_combo()
        self._before_div = _division_combo()
        before_row = QHBoxLayout()
        before_row.setSpacing(METRICS.space_2)
        before_row.addWidget(self._before_tier, 1)
        before_row.addWidget(self._before_div)
        root.addLayout(_field_layout_row("경기 전", before_row))

        quick = QHBoxLayout()
        quick.setSpacing(METRICS.space_2)
        self._same = QPushButton("변동 없음")
        self._up = QPushButton("한 단계 승급")
        self._down = QPushButton("한 단계 강등")
        for btn in (self._same, self._up, self._down):
            btn.setCheckable(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(METRICS.control_height)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            set_style_property(btn, "role", "segment")
            btn.setFont(font_for_role(btn.font(), FontRole.LABEL))
            quick.addWidget(btn)
        root.addLayout(quick)

        self._after_tier = _tier_combo()
        self._after_div = _division_combo()
        after_row = QHBoxLayout()
        after_row.setSpacing(METRICS.space_2)
        after_row.addWidget(self._after_tier, 1)
        after_row.addWidget(self._after_div)
        root.addLayout(_field_layout_row("경기 후 (직접 선택)", after_row))

        self._same.clicked.connect(self._apply_quick)
        self._up.clicked.connect(self._apply_quick)
        self._down.clicked.connect(self._apply_quick)

    def set_before(self, tier: str | None, division: int | None) -> None:
        """경기 전 상태 프리필 (get_last_standing). 없으면 기본값 유지."""
        if tier is not None:
            index = self._before_tier.findData(tier)
            if index >= 0:
                self._before_tier.setCurrentIndex(index)
        if division is not None:
            index = self._before_div.findData(division)
            if index >= 0:
                self._before_div.setCurrentIndex(index)
        self._sync_after_from_before()

    def _before_standing(self) -> RankStanding | None:
        tier = self._before_tier.currentData()
        division = self._before_div.currentData()
        if tier is None or division is None:
            return None
        try:
            return RankStanding(str(tier), int(division))
        except ValueError:
            return None

    def _apply_quick(self) -> None:
        before = self._before_standing()
        if before is None:
            return
        sender = self.sender()
        if sender is self._up:
            after = before.promoted()
        elif sender is self._down:
            after = before.demoted()
        else:
            after = before
        self._set_after(after)

    def _set_after(self, standing: RankStanding) -> None:
        index = self._after_tier.findData(standing.tier)
        if index >= 0:
            self._after_tier.setCurrentIndex(index)
        div_index = self._after_div.findData(standing.division)
        if div_index >= 0:
            self._after_div.setCurrentIndex(div_index)

    def _sync_after_from_before(self) -> None:
        before = self._before_standing()
        if before is not None:
            self._set_after(before)

    def before_values(self) -> tuple[str, int] | None:
        tier = self._before_tier.currentData()
        division = self._before_div.currentData()
        if tier is None or division is None:
            return None
        return str(tier), int(division)

    def after_values(self) -> tuple[str, int] | None:
        tier = self._after_tier.currentData()
        division = self._after_div.currentData()
        if tier is None or division is None:
            return None
        return str(tier), int(division)

    def set_values(
        self, before: tuple[str, int] | None, after: tuple[str, int] | None
    ) -> None:
        if before is not None:
            self.set_before(*before)
        if after is not None:
            self._set_after(RankStanding(after[0], after[1]))

    def reset(self) -> None:
        """랭크 패널을 기본값(첫 티어·첫 단계)으로 초기화한다."""
        self._before_tier.setCurrentIndex(0)
        self._before_div.setCurrentIndex(0)
        self._after_tier.setCurrentIndex(0)
        self._after_div.setCurrentIndex(0)


class DetailForm(QWidget):
    def __init__(self, decks: list[str], parent=None):
        super().__init__(parent)
        self._decks = list(decks)
        self._mode: GameMode | None = None
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

        # 모드별 상태 입력 (점수/랭크/레이팅)
        standing_frame, standing_col = _section("모드 상태")
        self._standing_stack = QStackedWidget()
        self._score_panel = self._build_score_panel()
        self._rank_panel = _RankPanel()
        self._rating_panel = self._build_rating_panel()
        self._standing_stack.addWidget(self._score_panel)
        self._standing_stack.addWidget(self._rank_panel)
        self._standing_stack.addWidget(self._rating_panel)
        standing_col.addWidget(self._standing_stack)
        root.addWidget(standing_frame)

        # 메모
        note_frame, note_col = _section("메모")
        self._note = QLineEdit()
        self._note.setPlaceholderText("메모 (선택)")
        note_col.addWidget(self._note)
        root.addWidget(note_frame)

    # ----- 모드별 상태 패널 -----
    def _build_score_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_2)
        self._score_before = _int_line("경기 전 점수")
        layout.addLayout(_field_row("경기 전 점수", self._score_before))
        score_row = QHBoxLayout()
        score_row.setContentsMargins(0, 0, 0, 0)
        score_row.setSpacing(METRICS.space_2)
        self._score_after = _int_line("경기 후 점수")
        self._delta = QLabel("")
        self._delta.setMinimumWidth(84)
        self._delta.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        score_row.addWidget(self._score_after, 1)
        score_row.addWidget(self._delta)
        layout.addLayout(_field_layout_row("경기 후 점수", score_row))
        self._score_after.textChanged.connect(self._update_delta)
        self._score_before.textChanged.connect(self._update_delta)
        return panel

    def _build_rating_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_2)
        self._rating_before = _int_line("경기 전 레이팅")
        layout.addLayout(_field_row("경기 전 레이팅", self._rating_before))
        self._rating_after = _int_line("경기 후 레이팅")
        layout.addLayout(_field_row("경기 후 레이팅", self._rating_after))
        return panel

    def set_mode(self, mode) -> None:
        """선택된 GameMode에 따라 모드별 상태 입력을 전환한다."""
        self._mode = mode
        kind = mode.standing_kind.value if mode is not None else None
        if kind == StandingKind.RANK.value:
            self._standing_stack.setCurrentWidget(self._rank_panel)
        elif kind == StandingKind.RATING.value:
            self._standing_stack.setCurrentWidget(self._rating_panel)
        else:
            self._standing_stack.setCurrentWidget(self._score_panel)

    def mode(self):
        return self._mode

    # ----- 점수/델타 -----
    def score_before(self) -> int:
        t = self._score_before.text().strip()
        return int(t) if t else 0

    def score_after(self) -> int:
        t = self._score_after.text().strip()
        return int(t) if t else 0

    def set_score_base(self, base: int) -> None:
        """직전 점수로 경기 전을 프리필하고 델타 기준값 설정."""
        self._score_base = int(base)
        self._score_before.blockSignals(True)
        self._score_before.setText(str(self._score_base))
        self._score_before.blockSignals(False)
        self._score_after.blockSignals(True)
        self._score_after.setText(str(self._score_base))
        self._score_after.blockSignals(False)
        self._update_delta()

    def set_rank_before(self, tier: str, division: int) -> None:
        """랭크 모드 경기 전 상태 프리필 (get_last_standing, spec §5.2)."""
        self._rank_panel.set_before(tier, division)

    def set_rating_before(self, rating: int) -> None:
        """레이팅 모드 경기 전 프리필 (get_last_rating, spec §5.3)."""
        self._rating_before.setText(str(rating))

    def _update_delta(self) -> None:
        # 변화량은 현재 입력된 경기 전/후 점수 차이다. 사용자가 경기 전 점수를
        # 수정해도 프리필 기준값(_score_base)이 아니라 실제 입력값을 따른다.
        delta = self.score_after() - self.score_before()
        if delta == 0:
            self._delta.setText("")
            set_style_property(self._delta, "tone", None)
        else:
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
        self._deck.setFocus()

    def focus_first_invalid(self) -> None:
        """저장 오류 후 첫 번째(시각적으로 위에 있는) 검증 실패 필드로 포커스를 옮긴다."""
        if self._my_deck.resolve() is None:
            self._my_deck.setFocus()
        elif self._deck.resolve() is None:
            self._deck.setFocus()
        elif (
            self._mode is not None
            and self._mode.standing_kind.value == StandingKind.RANK.value
        ):
            self._rank_panel._after_tier.setFocus()
        elif (
            self._mode is not None
            and self._mode.standing_kind.value == StandingKind.RATING.value
        ):
            self._rating_after.setFocus()
        else:
            self._score_after.setFocus()

    # ----- 값 입출력 -----
    def values(self) -> dict | None:
        """검증된 입력값 dict. 내 덱/상대 덱이 모호하거나 모드 필수값이 없으면 None."""
        my_deck = self._my_deck.resolve()
        opp_deck = self._deck.resolve()

        for combo, resolved in ((self._my_deck, my_deck), (self._deck, opp_deck)):
            if resolved is None:
                combo.mark_invalid()
            else:
                combo.clear_invalid()
        if my_deck is None or opp_deck is None:
            return None

        values = {
            "turn_order": self._turn.value(),
            "my_deck": my_deck,
            "opp_deck": opp_deck,
            "turns": self._turns.value(),
            "end_reason": self._reason.value(),
            "note": self._note.text().strip(),
            "standing_kind": (
                self._mode.standing_kind.value if self._mode is not None else None
            ),
            "play_context_id": (
                self._mode.play_context_id if self._mode is not None else None
            ),
        }
        if self._mode is None:
            return values

        kind = self._mode.standing_kind.value
        if kind == StandingKind.EVENT_POINTS.value:
            before = self._score_before.text().strip()
            after = self._score_after.text().strip()
            if not before or not after:
                return None
            values["event_points_before"] = int(before)
            values["event_points_after"] = int(after)
        elif kind == StandingKind.RANK.value:
            before = self._rank_panel.before_values()
            after = self._rank_panel.after_values()
            if before is None or after is None:
                return None
            values["rank_tier_before"], values["rank_division_before"] = before
            values["rank_tier_after"], values["rank_division_after"] = after
        elif kind == StandingKind.RATING.value:
            before = self._rating_before.text().strip()
            after = self._rating_after.text().strip()
            if not before or not after:
                return None
            values["rating_before"] = int(before)
            values["rating_after"] = int(after)
        return values

    def set_values(self, row) -> None:
        """편집용: 기존 레코드로 폼 채우기 (모드별 상태 포함)."""
        self._turn.setValue(row["turn_order"])
        self._reason.setValue(row["end_reason"])
        self._turns.set_value(int(row["turns"]) if row["turns"] else 1)
        self._my_deck.clear_invalid()
        self._my_deck.setEditText(row["my_deck"] or "")
        self._deck.clear_invalid()
        self._deck.setEditText(row["opp_deck"] or "")
        self._note.setText(row["note"] or "")

        kind = row["standing_kind"]
        if kind == StandingKind.RANK.value:
            before = (
                (row["rank_tier_before"], int(row["rank_division_before"]))
                if row["rank_tier_before"] and row["rank_division_before"] is not None
                else None
            )
            after = (
                (row["rank_tier_after"], int(row["rank_division_after"]))
                if row["rank_tier_after"] and row["rank_division_after"] is not None
                else None
            )
            self._rank_panel.set_values(before, after)
        elif kind == StandingKind.RATING.value:
            self._rating_before.setText(
                str(row["rating_before"]) if row["rating_before"] is not None else ""
            )
            self._rating_after.setText(
                str(row["rating_after"]) if row["rating_after"] is not None else ""
            )
        else:
            base = (
                int(row["event_points_before"])
                if row["event_points_before"] is not None
                else 0
            )
            self.set_score_base(base)
            if row["event_points_after"] is not None:
                self._score_after.setText(str(row["event_points_after"]))
                self._update_delta()

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
        self._rating_before.clear()
        self._rating_after.clear()
        self._rank_panel.reset()
