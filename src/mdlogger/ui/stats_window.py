"""통계 / 기록 창 (별도 창, 탭 2개).

- 통계 탭   : 요약 카드 · 점수 시계열(pyqtgraph, 앱 테마 동기화) · 덱별 매치업(선/후공 필터) · CSV/XLSX 내보내기
- 기록 관리 : 전체 레코드 테이블 + 편집 / 삭제 / 새로고침

단계 3(§9.3·§9.4) 반영:
- 요약 카드는 폭에 따라 3+2 / 2+2+1 / 1열 grid로 재배치한다.
- pyqtgraph 배경·축·격자·선 색상을 라이트/다크 테마 토큰과 동기화한다.
- 시계열은 기록이 4개 미만이면 추세 선 대신 현재 값 안내, 0개면 빈 상태 안내를 보인다.
- 선/후공 필터는 `SingleSelect`(segment 역할)로, 기록/매치업 테이블은 그리드를 줄이고
  행 높이·선택 상태를 개선한다. 편집/삭제는 선택이 없으면 disabled + tooltip이다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..enums import (
    END_REASON_LABELS,
    RANK_TIER_INDEX,
    RANK_TIER_LABELS,
    RANK_TIERS,
    RESULT_LABELS,
    TURN_ORDER_LABELS,
    label,
)
from ..game_service import GameService
from ..models import StandingKind
from ..paths import DB_PATH
from ..profiles import ProfileContext, ProfileKind
from .edit_dialog import EditDialog
from .portable_import_dialog import PortableImportDialog
from .theme import (
    LIGHT_COLORS,
    METRICS,
    FontRole,
    ThemeController,
    current_colors,
    font_for_role,
    set_style_property,
)
from .widgets import Card, FlowLayout, SingleSelect

# 통계 창 카드 배치 breakpoint (logical px). §9.3: 넓은 3+2 / 중간 2+2+1 / 좁은 1열.
_CARD_WIDE = 720
_CARD_MEDIUM = 520
# 시계열이 이보다 적으면 추세를 과장하는 선 그래프 대신 현재 값 안내 (§9.3).
_PLOT_MIN_POINTS = 4


def _cell(text: str, *, center: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setToolTip(text)
    return item


def _make_table(headers: list[str]) -> QTableWidget:
    """공통 테이블: 행 선택, 그리드 없음, 교차 배경, 충분한 행 높이(§9.4)."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setDefaultSectionSize(METRICS.control_height_small)
    return table


def _install_elide(table: QTableWidget) -> None:
    """긴 셀은 `…`로 elide하고 전체 값은 tooltip으로 제공한다 (§9.4)."""
    table.setItemDelegate(_ElideDelegate(table))


class _ElideDelegate(QStyledItemDelegate):
    """셀 텍스트를 열 너비에 맞게 elide해 그리드 없이도 긴 덱/메모가 잘리지 않게 한다."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(
        self,
        painter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not index.isValid():
            return
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text is None:
            super().paint(painter, option, index)
            return
        text = str(text)
        metrics = painter.fontMetrics()
        rect = option.rect
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        # 표시 텍스트만 elide하고, 편집/선택 상태는 기본 구현을 유지한다
        option_clone = QStyleOptionViewItem(option)
        option_clone.text = elided
        super().paint(painter, option_clone, index)


class StatsWindow(QWidget):
    data_changed = Signal()  # 편집/삭제로 데이터가 바뀜(메인 헤더 갱신용)
    records_imported = Signal()  # 휴대용 아카이브 가져오기 완료(즉시 동기화 트리거용)

    def __init__(
        self,
        games: GameService,
        decks: list[str],
        theme: ThemeController | None = None,
        profile: ProfileContext | None = None,
    ):
        super().__init__()
        self._games = games
        self._decks = decks
        self._theme = theme
        self._profile = profile
        self._colors = LIGHT_COLORS
        self._card_cols = 0

        app = QApplication.instance()
        self._app: QApplication | None = app if isinstance(app, QApplication) else None

        self.setWindowTitle("통계 / 기록")
        self.resize(760, 600)
        self.setMinimumWidth(360)

        self._modes = self._games.get_play_modes()
        self._mode_id: str | None = None  # None = 전체
        self._mode_name_by_ctx = {
            str(m["play_context_id"]): str(m["display_name"]) for m in self._modes
        }

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            METRICS.space_2, METRICS.space_2, METRICS.space_2, METRICS.space_2
        )

        # 상단 모드 필터: 전체 / 각 활성 모드 (spec §6.5, A1)
        filter_row = QHBoxLayout()
        filter_caption = QLabel("모드")
        set_style_property(filter_caption, "tone", "muted")
        filter_caption.setFont(font_for_role(filter_caption.font(), FontRole.LABEL))
        filter_row.addWidget(filter_caption)
        self._mode_filter = SingleSelect(self._mode_options())
        self._mode_filter.setValue("all")
        self._mode_filter.changed.connect(self._on_mode_filter)
        filter_row.addWidget(self._mode_filter, 1)
        outer.addLayout(filter_row)

        self._tabs = QTabWidget()
        self._stats_tab = self._build_stats_tab()
        self._records_tab = self._build_records_tab()
        self._tabs.addTab(self._stats_tab, "통계")
        self._tabs.addTab(self._records_tab, "기록 관리")
        outer.addWidget(self._tabs)

        # 시스템 테마가 바뀌면 pyqtgraph도 함께 갱신한다.
        if self._app is not None:
            self._app.styleHints().colorSchemeChanged.connect(self._apply_theme)
        # 앱 내부에서 테마 모드를 직접 바꿔도(ThemeController.set_mode) 그래프에 반영한다.
        if self._theme is not None:
            self._theme.theme_changed.connect(self._apply_theme)

        self._apply_theme()
        self._relayout_cards(self._stats_tab.width())
        self.refresh()

    # ===== 통계 탭 =====
    def _build_stats_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(METRICS.space_3)

        # 요약 카드 (폭에 따라 3+2 / 2+2+1 / 1열 grid)
        self._cards_grid = QGridLayout()
        self._cards_grid.setSpacing(METRICS.space_2)
        self._card_total = Card("총 전적")
        self._card_overall = Card("전체 승률")
        self._card_first = Card("선공 승률")
        self._card_second = Card("후공 승률")
        self._card_turns = Card("평균 소요 턴")
        self._cards = [
            self._card_total,
            self._card_overall,
            self._card_first,
            self._card_second,
            self._card_turns,
        ]
        v.addLayout(self._cards_grid)

        # 점수 시계열 (제목이 있는 표면 안, §9.3)
        v.addWidget(self._build_chart_panel(), 2)

        # 매치업 헤더 + 선/후공 필터 (segment 역할)
        mh = QHBoxLayout()
        title = QLabel("상대 덱별 매치업")
        set_style_property(title, "role", "section")
        title.setFont(font_for_role(title.font(), FontRole.SECTION))
        mh.addWidget(title)
        mh.addStretch(1)
        self._filter = SingleSelect(
            [("all", "전체"), ("first", "선공"), ("second", "후공")]
        )
        self._filter.setValue("all")
        self._filter.changed.connect(self._refresh_matchups)
        mh.addWidget(self._filter)
        v.addLayout(mh)

        # 매치업 테이블
        self._mtable = _make_table(["덱", "판수", "승", "패", "승률"])
        self._mtable.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        mhead = self._mtable.horizontalHeader()
        mhead.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            mhead.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        _install_elide(self._mtable)

        self._matchup_empty = QLabel("이 조건에 해당하는 기록이 없습니다.")
        self._matchup_empty.setWordWrap(True)
        self._matchup_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_style_property(self._matchup_empty, "tone", "muted")

        self._matchup_stack = QStackedWidget()
        self._matchup_stack.addWidget(self._mtable)
        self._matchup_stack.addWidget(self._matchup_empty)
        v.addWidget(self._matchup_stack, 1)

        # 내보내기 / 가져오기
        # 버튼 4개를 FlowLayout에 두어 좁은 폭(380px)이나 글자 확대 시에도
        # 줄바꿈되어 가로 넘침이 생기지 않게 한다(spec §7.3).
        ex = FlowLayout(spacing=METRICS.space_2)
        csv_btn = QPushButton("CSV 내보내기")
        xlsx_btn = QPushButton("XLSX 내보내기")
        portable_export_btn = QPushButton("휴대용 아카이브 내보내기")
        portable_import_btn = QPushButton("휴대용 아카이브 가져오기")
        for btn in (csv_btn, xlsx_btn, portable_export_btn, portable_import_btn):
            set_style_property(btn, "role", "secondary")
        csv_btn.clicked.connect(self._export_csv)
        xlsx_btn.clicked.connect(self._export_xlsx)
        portable_export_btn.clicked.connect(self._export_portable_archive)
        portable_import_btn.clicked.connect(self._import_portable)
        for btn in (csv_btn, xlsx_btn, portable_export_btn, portable_import_btn):
            ex.addWidget(btn)
        v.addLayout(ex)

        return w

    def _build_chart_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.NoFrame)
        set_style_property(panel, "surface", "card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            METRICS.space_3, METRICS.space_3, METRICS.space_3, METRICS.space_3
        )
        layout.setSpacing(METRICS.space_2)

        self._chart_title = QLabel("점수 시계열")
        set_style_property(self._chart_title, "role", "section")
        self._chart_title.setFont(
            font_for_role(self._chart_title.font(), FontRole.SECTION)
        )
        layout.addWidget(self._chart_title)

        # 0: 그래프 / 1: 데이터 적음 안내 / 2: 빈 상태
        self._plot_stack = QStackedWidget()
        self._plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self._plot.setMinimumHeight(200)
        self._plot_stack.addWidget(self._plot)

        self._sparse_label = QLabel("")
        self._sparse_label.setWordWrap(True)
        self._sparse_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_style_property(self._sparse_label, "tone", "muted")
        self._plot_stack.addWidget(self._sparse_label)

        self._empty_label = QLabel(
            "아직 기록이 없습니다.\n메인 화면에서 첫 듀얼 결과를 저장하면 추세가 표시됩니다."
        )
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_style_property(self._empty_label, "tone", "muted")
        self._plot_stack.addWidget(self._empty_label)

        layout.addWidget(self._plot_stack, 1)
        return panel

    # ===== 기록 관리 탭 =====
    def _build_records_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(METRICS.space_2)

        headers = [
            "ID",
            "시각",
            "결과",
            "모드",
            "선/후공",
            "내 덱",
            "상대 덱",
            "턴",
            "종료",
            "상태",
            "메모",
        ]
        self._rtable = _make_table(headers)
        # 기록 테이블은 선택된 행의 current-cell 경계를 뚜렷하게 보여준다(§9.4).
        self._rtable.setProperty("statsTable", True)
        self._rtable.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._rtable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        rhead = self._rtable.horizontalHeader()
        rhead.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        rhead.setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)  # 메모 늘림
        # 긴 덱 이름은 열을 무한히 넓히지 않고 최대 폭에서 elide + tooltip으로 처리(§9.4)
        rhead.setMaximumSectionSize(280)
        self._rtable.doubleClicked.connect(self._edit_selected)
        self._rtable.itemSelectionChanged.connect(self._update_record_actions)
        _install_elide(self._rtable)

        self._records_empty = QLabel(
            "기록이 없습니다.\n메인 화면에서 첫 듀얼 결과를 저장하면 여기에 표시됩니다."
        )
        self._records_empty.setWordWrap(True)
        self._records_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_style_property(self._records_empty, "tone", "muted")

        self._records_stack = QStackedWidget()
        self._records_stack.addWidget(self._rtable)
        self._records_stack.addWidget(self._records_empty)
        v.addWidget(self._records_stack, 1)

        b = QHBoxLayout()
        self._edit_btn = QPushButton("편집")
        self._del_btn = QPushButton("삭제")
        self._refresh_btn = QPushButton("새로고침")
        set_style_property(self._edit_btn, "role", "secondary")
        set_style_property(self._del_btn, "role", "danger")
        set_style_property(self._refresh_btn, "role", "ghost")
        self._edit_btn.clicked.connect(self._edit_selected)
        self._del_btn.clicked.connect(self._delete_selected)
        self._refresh_btn.clicked.connect(self.refresh)
        self._edit_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        self._edit_btn.setToolTip("편집할 기록을 먼저 선택하세요")
        self._del_btn.setToolTip("삭제할 기록을 먼저 선택하세요")
        b.addWidget(self._edit_btn)
        b.addWidget(self._del_btn)
        b.addStretch(1)
        b.addWidget(self._refresh_btn)
        v.addLayout(b)

        return w

    # ===== 테마 동기화 =====
    def _apply_theme(self) -> None:
        """pyqtgraph 배경·축·격자 색상을 현재 테마 토큰으로 맞춘다 (§9.3).

        `DateAxisItem`에는 `axis.setGrid()`를 쓰면 재배치 시 크래시가 나므로
        `showGrid` + 축 펜 색으로 격자를 그림한다.
        """
        self._colors = current_colors(self._app)
        self._plot.setBackground(self._colors.surface)
        plot_item = self._plot.getPlotItem()
        for name in ("left", "bottom"):
            axis = plot_item.getAxis(name)
            axis.setPen(pg.mkPen(self._colors.chart_grid))
            axis.setTextPen(pg.mkPen(self._colors.chart_axis))
        self._plot.setLabel("left", "누적 점수", color=self._colors.chart_axis)
        self._plot.showGrid(x=True, y=True, alpha=0.5)
        self._refresh_plot()

    # ===== 갱신 =====
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._relayout_cards(self._stats_tab.width())

    def _relayout_cards(self, width: int) -> None:
        if width >= _CARD_WIDE:
            cols = 3
        elif width >= _CARD_MEDIUM:
            cols = 2
        else:
            cols = 1
        if cols == self._card_cols:
            return
        self._card_cols = cols
        for i, card in enumerate(self._cards):
            self._cards_grid.addWidget(card, i // cols, i % cols)

    def refresh(self) -> None:
        self._refresh_cards()
        self._refresh_plot()
        self._refresh_matchups()
        self._refresh_records()

    def set_memo_enabled(self, enabled: bool) -> None:
        """기록 표의 메모 열 표시 여부 (P8, spec §5.4).

        비활성화하면 메모 열을 숨긴다. 기존 메모 데이터는 삭제하지 않는다.
        """
        self._rtable.setColumnHidden(10, not enabled)

    def _mode_options(self) -> list[tuple[str, str]]:
        return [("all", "전체")] + [
            (str(m["id"]), str(m["display_name"])) for m in self._modes
        ]

    def _on_mode_filter(self, value: str) -> None:
        self._mode_id = None if value == "all" else value
        self.refresh()

    def _selected_mode(self):
        if self._mode_id is None:
            return None
        for mode in self._modes:
            if mode["id"] == self._mode_id:
                return mode
        return None

    def _refresh_cards(self) -> None:
        s = self._games.get_summary(self._mode_id)
        self._card_total.set_value(f"{s['total']}판 {s['wins']}승 {s['losses']}패")
        self._card_overall.set_value(f"{s['winrate']:.1f}%")
        self._card_first.set_value(
            f"{s['first_winrate']:.1f}%  ({s['first_wins']}/{s['first_games']})"
        )
        self._card_second.set_value(
            f"{s['second_winrate']:.1f}%  ({s['second_wins']}/{s['second_games']})"
        )
        self._card_turns.set_value(f"{s['avg_turns']:.1f}")

    def _refresh_plot(self) -> None:
        colors = self._colors
        self._plot.clear()
        mode = self._selected_mode()
        if mode is None:
            # A1: 전체에서는 그래프를 그리지 않는다 (숫자 통계만)
            self._chart_title.setText("추세")
            self._sparse_label.setText(
                "전체에서는 그래프를 표시하지 않습니다.\n모드를 선택하면 추세가 표시됩니다."
            )
            self._plot_stack.setCurrentWidget(self._sparse_label)
            return
        kind = mode["standing_kind"]
        if kind == "rank":
            self._chart_title.setText("랭크 진행")
            self._plot.setLabel("left", "랭크", color=colors.chart_axis)
            self._set_rank_axis_ticks()
            self._render_series(self._games.get_rank_series(self._mode_id), "rank")
        elif kind == "rating":
            self._chart_title.setText("레이팅 추이")
            self._plot.setLabel("left", "레이팅", color=colors.chart_axis)
            self._render_series(self._games.get_rating_series(self._mode_id), "rating")
        else:
            self._chart_title.setText("누적 점수")
            self._plot.setLabel("left", "누적 점수", color=colors.chart_axis)
            self._render_series(self._games.get_score_series(self._mode_id), "score")

    def _set_rank_axis_ticks(self) -> None:
        """랭크 그래프 Y축 tick을 사람이 읽는 티어 이름으로 설정한다(spec §5.5)."""
        axis = self._plot.getAxis("left")
        ticks = [(index * 10, label) for index, (_, label) in enumerate(RANK_TIERS)]
        axis.setTicks([ticks])

    def _render_series(self, rows, kind: str) -> None:
        """모드별 시계열을 그린다. 승/패는 색상 외 marker 모양으로 구분한다(§9.3)."""
        colors = self._colors
        xs: list[float] = []
        ys: list[float] = []
        brushes = []
        symbols = []
        tips: list[tuple[str, str]] = []
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["played_at"]).timestamp()
            except (TypeError, ValueError):
                continue
            if kind == "rank":
                tier = row["rank_tier_after"]
                division = row["rank_division_after"]
                if tier is None or division is None:
                    continue
                y = RANK_TIER_INDEX[tier] * 10 - int(division)
                value_text = f"{RANK_TIER_LABELS.get(tier, tier)} {division}"
            elif kind == "rating":
                y = row["rating_after"] or 0
                value_text = f"레이팅 {y:,}"
            else:
                y = row["event_points_after"] or 0
                value_text = f"점수 {y:,}"
            xs.append(ts)
            ys.append(float(y))
            is_win = row["result"] == "win"
            brushes.append(pg.mkBrush(colors.success if is_win else colors.danger))
            symbols.append("o" if is_win else "x")
            tips.append((row["played_at"] or "", value_text))

        if not xs:
            self._plot_stack.setCurrentWidget(self._empty_label)
            return

        if len(xs) < _PLOT_MIN_POINTS:
            self._sparse_label.setText(
                f"기록이 {len(xs)}개뿐이라 추세를 표시하지 않습니다.\n최근 {tips[-1][1]}"
            )
            self._plot_stack.setCurrentWidget(self._sparse_label)
            return

        def _tip(x: float, y: float, data: tuple[str, str] | None) -> str:
            # hover 시 정확한 값/시각을 tooltip으로 제공한다 (§9.3)
            if data is None:
                return ""
            when, value = data
            return f"{when}\n{value}" if when else value

        self._plot_stack.setCurrentWidget(self._plot)
        self._plot.plot(xs, ys, pen=pg.mkPen(colors.chart_primary, width=2))
        scatter = pg.ScatterPlotItem(
            x=xs,
            y=ys,
            brush=brushes,
            symbol=symbols,
            pen=pg.mkPen(colors.surface),
            size=11,
            hoverable=True,
            tip=_tip,
            data=tips,
        )
        self._plot.addItem(scatter)

    def _refresh_matchups(self, *_args) -> None:
        tf = self._filter.value()
        if tf == "all":
            tf = None
        data = self._games.get_deck_matchups(tf, self._mode_id)
        self._mtable.setRowCount(len(data))
        for i, row in enumerate(data):
            self._mtable.setItem(i, 0, _cell(row["deck"]))
            self._mtable.setItem(i, 1, _cell(str(row["games"]), center=True))
            self._mtable.setItem(i, 2, _cell(str(row["wins"]), center=True))
            self._mtable.setItem(i, 3, _cell(str(row["losses"]), center=True))
            self._mtable.setItem(i, 4, _cell(f"{row['winrate']:.1f}%", center=True))
        self._matchup_stack.setCurrentIndex(1 if not data else 0)

    def _mode_badge(self, row) -> str:
        """기록 행의 모드 배지 (spec §6.5)."""
        kind = row["standing_kind"]
        if kind == StandingKind.RANK.value:
            return "랭크"
        if kind == StandingKind.RATING.value:
            return "레이팅"
        ctx = row["play_context_id"]
        return self._mode_name_by_ctx.get(ctx, "점수")

    def _record_state(self, row) -> str:
        """기록 행의 상태 변화 표시 (spec §6.5)."""
        kind = row["standing_kind"]
        if kind == StandingKind.RANK.value:
            before_tier = row["rank_tier_before"]
            before_div = row["rank_division_before"]
            after_tier = row["rank_tier_after"]
            after_div = row["rank_division_after"]
            if (
                before_tier
                and before_div is not None
                and after_tier
                and after_div is not None
            ):
                b = f"{RANK_TIER_LABELS.get(before_tier, before_tier)} {before_div}"
                a = f"{RANK_TIER_LABELS.get(after_tier, after_tier)} {after_div}"
                return f"{b} → {a}" if b != a else f"{a} 유지"
            return "랭크"
        if kind == StandingKind.RATING.value:
            after = row["rating_after"]
            return f"레이팅 {after}" if after is not None else "레이팅"
        after = row["event_points_after"]
        before = row["event_points_before"]
        if after is None:
            return "점수"
        if before is not None:
            return f"{after} ({after - before:+,})"
        return str(after)

    def _refresh_records(self) -> None:
        games = self._games.get_all_games()
        mode = self._selected_mode()
        if mode is not None:
            ctx = mode["play_context_id"]
            games = [g for g in games if g["play_context_id"] == ctx]
        self._rtable.setRowCount(len(games))
        for i, g in enumerate(games):
            id_item = _cell(str(g["id"]), center=True)
            id_item.setData(Qt.ItemDataRole.UserRole, int(g["id"]))
            self._rtable.setItem(i, 0, id_item)
            self._rtable.setItem(i, 1, _cell(g["played_at"] or ""))
            self._rtable.setItem(
                i, 2, _cell(label(RESULT_LABELS, g["result"]), center=True)
            )
            self._rtable.setItem(i, 3, _cell(self._mode_badge(g), center=True))
            self._rtable.setItem(
                i, 4, _cell(label(TURN_ORDER_LABELS, g["turn_order"]), center=True)
            )
            self._rtable.setItem(i, 5, _cell(g["my_deck"] or ""))
            self._rtable.setItem(i, 6, _cell(g["opp_deck"] or ""))
            self._rtable.setItem(i, 7, _cell(str(g["turns"]), center=True))
            self._rtable.setItem(
                i, 8, _cell(label(END_REASON_LABELS, g["end_reason"]), center=True)
            )
            self._rtable.setItem(i, 9, _cell(self._record_state(g), center=True))
            self._rtable.setItem(i, 10, _cell(g["note"] or ""))

        self._records_stack.setCurrentIndex(1 if not games else 0)
        self._update_record_actions()

    # ===== 편집 / 삭제 =====
    def _selected_id(self) -> int | None:
        row = self._rtable.currentRow()
        if row < 0:
            return None
        item = self._rtable.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _update_record_actions(self) -> None:
        has_selection = self._selected_id() is not None
        self._edit_btn.setEnabled(has_selection)
        self._del_btn.setEnabled(has_selection)

    def _edit_selected(self, *_args) -> None:
        gid = self._selected_id()
        if gid is None:
            QMessageBox.information(self, "편집", "편집할 행을 먼저 선택하세요.")
            return
        row = self._games.get_game(gid)
        if row is None:
            return
        dlg = EditDialog(self._games, self._decks, row, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.data_changed.emit()

    def _delete_selected(self) -> None:
        gid = self._selected_id()
        if gid is None:
            QMessageBox.information(self, "삭제", "삭제할 행을 먼저 선택하세요.")
            return
        row = self._games.get_game(gid)
        if row is None:
            return
        summary = (
            f"{RESULT_LABELS.get(row['result'], row['result'])} · "
            f"{row['opp_deck']} · {row['played_at']}"
        )
        reply = QMessageBox.question(
            self,
            "기록 삭제",
            f"다음 기록을 삭제할까요?\n\n{summary}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,  # 기본 포커스가 삭제(Yes)에 놓이지 않게
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._games.delete_game(gid)
            self.refresh()
            self.data_changed.emit()

    # ===== 내보내기 =====
    def _export(self, label: str, filename: str, filter_: str, export_fn) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, f"{label}로 내보내기", filename, filter_
        )
        if not path:
            return
        try:
            export_fn(path)
        except Exception as exc:  # noqa: BLE001 - 내보내기 실패를 사용자에게 안내
            QMessageBox.critical(
                self,
                f"{label} 내보내기 실패",
                f"파일을 저장하지 못했습니다.\n\n{exc}",
                QMessageBox.StandardButton.Ok,
            )
            return
        QMessageBox.information(self, "내보내기", f"{label} 저장 완료:\n{path}")

    def _export_csv(self) -> None:
        self._export("CSV", "games.csv", "CSV (*.csv)", self._games.export_csv)

    def _export_xlsx(self) -> None:
        self._export("XLSX", "games.xlsx", "Excel (*.xlsx)", self._games.export_xlsx)

    def _export_portable_archive(self) -> None:
        """휴대용 아카이브(.mdlogger-export) 디렉터리를 선택 대상에 생성한다.

        대상은 파일이 아니라 디렉터리이므로 부모 폴더를 고르고 폴더 이름을
        입력받아 조합한다. `export_portable_archive`는 이미 존재하면 오류를
        던지므로, 그 오류를 포함한 실패는 안내로 처리하고 예외를 전파하지 않는다.
        """
        parent_dir = QFileDialog.getExistingDirectory(
            self, "휴대용 아카이브를 저장할 폴더 선택"
        )
        if not parent_dir:
            return
        default_name = f"MDLogger-export-{datetime.now():%Y%m%d-%H%M%S}"
        name, ok = QInputDialog.getText(
            self,
            "휴대용 아카이브 내보내기",
            "아카이브 폴더 이름",
            text=default_name,
        )
        if not ok or not name.strip():
            return
        target = Path(parent_dir) / name.strip()
        try:
            self._games.export_portable_archive(
                target,
                profile_kind=self._profile.kind if self._profile else ProfileKind.GUEST,
            )
        except Exception as exc:  # noqa: BLE001 - 내보내기 실패를 사용자에게 안내
            QMessageBox.critical(
                self,
                "휴대용 아카이브 내보내기 실패",
                f"아카이브를 만들지 못했습니다.\n\n{exc}",
                QMessageBox.StandardButton.Ok,
            )
            return
        QMessageBox.information(
            self,
            "내보내기",
            f"휴대용 아카이브 저장 완료:\n{target}",
            QMessageBox.StandardButton.Ok,
        )

    def _import_portable(self) -> None:
        """휴대용 아카이브를 선택해 현재 프로필 DB로 가져온다.

        대상 DB 경로는 현재 프로필의 DB를, 없으면 기본 DB 경로를 쓴다. 실제
        가져오기와 결과/오류 안내는 `PortableImportDialog`가 담당하고, 성공 시
        통계/기록을 갱신하고 가져온 기록이 동기화되도록 즉시 동기화를 요청한다.
        """
        target = self._profile.database_path if self._profile else DB_PATH
        dialog = PortableImportDialog(target, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.data_changed.emit()
        self.records_imported.emit()
        self.refresh()
