"""화면1 (결과 선택): 계정/오늘 전적/안내문 + 승/패 버튼 + 되돌리기/통계.

승/패 버튼 레이아웃 규칙:
- 4:3 비율(세로:가로 = 4:3, 세로가 조금 더 길게), 가용 영역에 contain-fit.
- 버튼은 메인 창 하단(되돌리기/통계 줄) 바로 위에 붙고, 남는 공백은 버튼 위쪽
  (안내문과 버튼 사이)에 위치한다.
- hover 시 호버된 버튼만 가로·세로 같은 비율로 부드럽게 커진다.
- 성장 시 잘리지 않도록 컨테이너는 "성장 후 크기"로 두고, 휴지 버튼은 그 안에서
  성장 여유를 남긴다(버튼이 컨테이너를 벗어나 클리핑되지 않게).
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QEnterEvent, QResizeEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .icons import load_icon
from .theme import METRICS, FontRole, font_for_role, set_style_property
from .widgets import SingleSelect

_RESULT_ASPECT = 4 / 3  # 세로:가로 — 세로가 조금 더 길게
_RESULT_GAP = 12
_RESULT_GROW = 0.05  # hover 시 같은 비율로 5% 확대
_RESULT_MOTION_MS = 140
_RESULT_MARGIN = 4  # 성장 버튼이 컨테이너 상하 여백을 두고 맞도록
_RESULT_UP = 4  # 수직 중심에서 살짝 위로 (아래로 성장해도 하단 버튼을 침범하지 않게)

# 저사양 모드/애니메이션 감소 시 승/패 버튼 hover 확대 애니메이션을 끈다(spec §5.3).
_motion_enabled = True


def set_result_motion_enabled(enabled: bool) -> None:
    """승/패 버튼 hover 확대 애니메이션 활성화 여부를 설정한다."""
    global _motion_enabled
    _motion_enabled = enabled


class _ResultButton(QPushButton):
    """승/패 버튼. 호버 시 같은 비율로 배율(growScale)을 애니메이션한다."""

    def __init__(
        self, text: str, role: str, accessible_name: str, parent: QWidget | None = None
    ):
        super().__init__(text, parent)
        self.setAccessibleName(accessible_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(font_for_role(self.font(), FontRole.DISPLAY))
        # 키보드 전용 조작을 쓰지 않으므로 버튼에 포커스 링을 띄우지 않는다
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        set_style_property(self, "role", role)

        self._base_size = QSize(0, 0)
        self._grow_scale = 1.0
        self._anim = QPropertyAnimation(self, b"growScale", self)
        self._anim.setDuration(_RESULT_MOTION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def set_base_size(self, size: QSize) -> None:
        self._base_size = size
        self._apply()

    def _scaled_size(self) -> QSize:
        return QSize(
            int(round(self._base_size.width() * self._grow_scale)),
            int(round(self._base_size.height() * self._grow_scale)),
        )

    def _apply(self) -> None:
        parent = self.parentWidget()
        if isinstance(parent, _ResultButtons):
            parent.place(self, self._scaled_size())

    @Property(float)
    def growScale(self) -> float:
        return self._grow_scale

    @growScale.setter
    def growScale(self, value: float) -> None:
        self._grow_scale = value
        self._apply()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._animate(1.0 + _RESULT_GROW)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._animate(1.0)
        super().leaveEvent(event)

    def _animate(self, target: float) -> None:
        if not _motion_enabled:
            self._grow_scale = target
            self._apply()
            return
        self._anim.stop()
        self._anim.setStartValue(self._grow_scale)
        self._anim.setEndValue(target)
        self._anim.start()


class _ResultButtons(QWidget):
    """승/패 버튼을 4:3으로 배치하고, 각 버튼을 독립적으로 크기 조절한다.

    컨테이너 높이는 "성장 후(contain-fit)" 크기로 잡아, 휴지 버튼은 그 안에서
    5% 여유를 남기고 성장한다. 버튼이 컨테이너를 벗어나지 않아 잘리지 않는다.
    """

    result_chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._gap = _RESULT_GAP
        self._win = _ResultButton("승", "result-win", "승리 기록", self)
        self._lose = _ResultButton("패", "result-loss", "패배 기록", self)
        self._win.clicked.connect(lambda: self.result_chosen.emit("win"))
        self._lose.clicked.connect(lambda: self.result_chosen.emit("lose"))

    def set_enabled(self, enabled: bool) -> None:
        """승/패 버튼 활성화 상태. 활성 모드가 없으면 비활성화한다(spec §2.5-7)."""
        self._win.setEnabled(enabled)
        self._lose.setEnabled(enabled)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        per = max(0.0, (width - self._gap) / 2)
        return int(per * _RESULT_ASPECT) + 2 * _RESULT_MARGIN

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._layout_buttons()
        super().resizeEvent(event)

    def _layout_buttons(self) -> None:
        r = self.rect()
        per_w = (r.width() - self._gap) / 2
        # 성장 후(contain-fit) 크기: 세로/가로 중 먼저 닿는 쪽 기준 (상하 여백 제외)
        grown_w = min(
            max(0.0, per_w), (r.height() - 2 * _RESULT_MARGIN) / _RESULT_ASPECT
        )
        # 휴지 크기는 5% 여유를 남겨 성장 때 잘리지 않게 한다
        base_w = grown_w / (1.0 + _RESULT_GROW)
        base = QSize(int(base_w), int(base_w * _RESULT_ASPECT))
        self._win.set_base_size(base)
        self._lose.set_base_size(base)

    def place(self, btn: _ResultButton, size: QSize) -> None:
        r = self.rect()
        half_w = (r.width() - self._gap) / 2
        left = r.left() if btn is self._win else r.left() + half_w + self._gap
        # 중심을 기준으로 성장 → 위·아래·양옆 모두 커진다. 수직 중심은 살짝 위로.
        cx = left + half_w / 2
        cy = r.top() + r.height() / 2 - _RESULT_UP
        x = int(cx - size.width() / 2)
        y = int(cy - size.height() / 2)
        btn.setGeometry(x, y, int(size.width()), int(size.height()))


class ResultView(QWidget):
    result_chosen = Signal(str)  # 'win' | 'lose'
    mode_changed = Signal(str)  # play_modes.id
    undo_requested = Signal()
    stats_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        # 낮은 우선순위의 계정/동기화 상태 (맨 위 텍스트) + 톱니바퀴 설정 버튼
        account_row = QHBoxLayout()
        account_row.setSpacing(8)
        self._account_status = QLabel("게스트 · 로컬 저장")
        set_style_property(self._account_status, "tone", "muted")
        self._account_status.setWordWrap(True)
        settings_button = QPushButton("설정")
        settings_icon = load_icon("settings")
        if settings_icon is not None:
            settings_button.setIcon(settings_icon)
            settings_button.setIconSize(QSize(METRICS.icon_small, METRICS.icon_small))
        settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_button.setAccessibleName("설정")
        settings_button.setToolTip("설정")
        settings_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        set_style_property(settings_button, "role", "ghost")
        settings_button.clicked.connect(self.settings_requested)
        account_row.addWidget(self._account_status, 1)
        account_row.addWidget(settings_button)
        root.addLayout(account_row)

        # 오늘 전적: 맨 위 텍스트와 안내문 사이의 정확히 중앙에 배치
        root.addStretch(1)
        self._today = QLabel("오늘 전적  0승 0패")
        self._today.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_style_property(self._today, "role", "title")
        self._today.setFont(font_for_role(self._today.font(), FontRole.TITLE))
        root.addWidget(self._today)

        # 활성 모드별 현재 상태 한 줄 (A5)
        self._mode_status = QLabel("")
        self._mode_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_status.setWordWrap(True)
        set_style_property(self._mode_status, "tone", "muted")
        root.addWidget(self._mode_status)
        root.addStretch(1)

        # 안내문: 버튼 바로 위
        prompt = QLabel("이번 듀얼의 결과를 기록하세요")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_style_property(prompt, "tone", "muted")
        root.addWidget(prompt)

        # 모드 선택기 (승/패보다 낮은 시각적 우선순위, spec §6.1)
        self._mode_select = SingleSelect([])
        self._mode_select.setAccessibleName("기록할 경기 모드 선택")
        self._mode_select.changed.connect(self.mode_changed)
        self._mode_select_index = root.count()
        root.insertWidget(self._mode_select_index, self._mode_select)

        # 승/패 버튼 (하단 위, 안내문 아래)
        self._buttons = _ResultButtons()
        self._buttons.result_chosen.connect(self.result_chosen)
        root.addWidget(self._buttons)

        # 하단: 되돌리기 / 통계
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self._undo = QPushButton("마지막 기록 취소")
        undo_icon = load_icon("undo")
        if undo_icon is not None:
            self._undo.setIcon(undo_icon)
            self._undo.setIconSize(QSize(METRICS.icon_medium, METRICS.icon_medium))
        self._undo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._undo.setMinimumHeight(36)
        self._undo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._undo.setEnabled(False)
        self._undo.clicked.connect(self.undo_requested)
        stats_btn = QPushButton("통계 / 기록")
        stats_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stats_btn.setMinimumHeight(36)
        stats_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        stats_btn.clicked.connect(self.stats_requested)
        bottom.addWidget(self._undo)
        bottom.addWidget(stats_btn)
        root.addLayout(bottom)

    def set_account_status(self, text: str) -> None:
        self._account_status.setText(text)

    def set_modes(self, modes) -> None:
        """활성 모드 목록을 선택기로 설정한다 (spec §6.1, A3)."""
        options = [(mode["id"], mode["display_name"]) for mode in modes]
        old = self._mode_select
        self._mode_select = SingleSelect(options)
        self._mode_select.setAccessibleName("기록할 경기 모드 선택")
        self._mode_select.changed.connect(self.mode_changed)
        self._root_layout.replaceWidget(old, self._mode_select)
        old.deleteLater()
        self._mode_select.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_mode(self, mode_id: str) -> None:
        self._mode_select.setValue(mode_id)

    def mode(self) -> str | None:
        return self._mode_select.value()

    def set_today_record(self, wins: int, losses: int) -> None:
        total = wins + losses
        text = f"오늘  {wins}승 {losses}패"
        if total:
            text += f"  ·  {total}전  승률 {wins / total * 100:.0f}%"
        self._today.setText(text)

    def set_mode_status(self, text: str) -> None:
        """활성 모드별 현재 상태 한 줄 (A5)."""
        self._mode_status.setText(text)

    def set_undo_enabled(self, enabled: bool) -> None:
        self._undo.setEnabled(enabled)

    def set_result_buttons_enabled(self, enabled: bool) -> None:
        """승/패 버튼 활성화 상태. 활성 모드가 없으면 비활성화한다(spec §2.5-7)."""
        self._buttons.set_enabled(enabled)
