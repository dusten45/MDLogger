"""통계 / 기록 창 (별도 창, 탭 2개).

- 통계 탭   : 요약 카드 · 점수 시계열(pyqtgraph) · 덱별 매치업(선/후공 필터) · CSV/XLSX 내보내기
- 기록 관리 : 전체 레코드 테이블 + 편집 / 삭제 / 새로고침
"""

from __future__ import annotations

from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..enums import (
    END_REASON_LABELS,
    RESULT_COLORS,
    RESULT_LABELS,
    TURN_ORDER_LABELS,
    label,
)
from ..game_service import GameService
from .edit_dialog import EditDialog
from .widgets import Card


def _cell(text: str, *, center: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


class StatsWindow(QWidget):
    data_changed = Signal()  # 편집/삭제로 데이터가 바뀜(메인 헤더 갱신용)

    def __init__(self, games: GameService, decks: list[str]):
        super().__init__()
        self._games = games
        self._decks = decks

        self.setWindowTitle("통계 / 기록")
        self.resize(760, 600)

        tabs = QTabWidget()
        tabs.addTab(self._build_stats_tab(), "통계")
        tabs.addTab(self._build_records_tab(), "기록 관리")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.addWidget(tabs)

        self.refresh()

    # ===== 통계 탭 =====
    def _build_stats_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

        # 요약 카드
        cards = QHBoxLayout()
        cards.setSpacing(8)
        self._card_total = Card("총 전적")
        self._card_overall = Card("전체 승률")
        self._card_first = Card("선공 승률")
        self._card_second = Card("후공 승률")
        self._card_turns = Card("평균 소요 턴")
        for c in (
            self._card_total,
            self._card_overall,
            self._card_first,
            self._card_second,
            self._card_turns,
        ):
            cards.addWidget(c)
        v.addLayout(cards)

        # 점수 시계열
        self._plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self._plot.setBackground("w")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("left", "누적 점수")
        self._plot.setMinimumHeight(220)
        v.addWidget(self._plot, 2)

        # 매치업 헤더 + 선/후공 필터
        mh = QHBoxLayout()
        title = QLabel("상대 덱별 매치업")
        title.setStyleSheet("font-weight:700;")
        mh.addWidget(title)
        mh.addStretch(1)
        self._f_all = QRadioButton("전체")
        self._f_first = QRadioButton("선공")
        self._f_second = QRadioButton("후공")
        self._f_all.setChecked(True)
        grp = QButtonGroup(self)
        for r in (self._f_all, self._f_first, self._f_second):
            grp.addButton(r)
            mh.addWidget(r)
        v.addLayout(mh)

        # 매치업 테이블
        self._mtable = QTableWidget(0, 5)
        self._mtable.setHorizontalHeaderLabels(["덱", "판수", "승", "패", "승률"])
        self._mtable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._mtable.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._mtable.verticalHeader().setVisible(False)
        mhead = self._mtable.horizontalHeader()
        mhead.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            mhead.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self._mtable, 1)

        # 내보내기
        ex = QHBoxLayout()
        ex.addStretch(1)
        csv_btn = QPushButton("CSV 내보내기")
        xlsx_btn = QPushButton("XLSX 내보내기")
        csv_btn.clicked.connect(self._export_csv)
        xlsx_btn.clicked.connect(self._export_xlsx)
        ex.addWidget(csv_btn)
        ex.addWidget(xlsx_btn)
        v.addLayout(ex)

        # 필터 변경 시 매치업만 갱신 (테이블 생성 후에 연결)
        for r in (self._f_all, self._f_first, self._f_second):
            r.toggled.connect(self._refresh_matchups)

        return w

    # ===== 기록 관리 탭 =====
    def _build_records_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)

        headers = [
            "ID",
            "시각",
            "결과",
            "선/후공",
            "내 덱",
            "상대 덱",
            "턴",
            "종료",
            "점수",
            "메모",
        ]
        self._rtable = QTableWidget(0, len(headers))
        self._rtable.setHorizontalHeaderLabels(headers)
        self._rtable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._rtable.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._rtable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._rtable.verticalHeader().setVisible(False)
        rhead = self._rtable.horizontalHeader()
        rhead.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        rhead.setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)  # 메모 늘림
        self._rtable.doubleClicked.connect(self._edit_selected)
        v.addWidget(self._rtable, 1)

        b = QHBoxLayout()
        edit_btn = QPushButton("편집")
        del_btn = QPushButton("삭제")
        refresh_btn = QPushButton("새로고침")
        edit_btn.clicked.connect(self._edit_selected)
        del_btn.clicked.connect(self._delete_selected)
        refresh_btn.clicked.connect(self.refresh)
        b.addWidget(edit_btn)
        b.addWidget(del_btn)
        b.addStretch(1)
        b.addWidget(refresh_btn)
        v.addLayout(b)

        return w

    # ===== 갱신 =====
    def refresh(self) -> None:
        self._refresh_cards()
        self._refresh_plot()
        self._refresh_matchups()
        self._refresh_records()

    def _refresh_cards(self) -> None:
        s = self._games.get_summary()
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
        series = self._games.get_score_series()
        self._plot.clear()
        if not series:
            return
        xs: list[float] = []
        ys: list[int] = []
        brushes = []
        for row in series:
            try:
                ts = datetime.fromisoformat(row["played_at"]).timestamp()
            except (TypeError, ValueError):
                continue
            xs.append(ts)
            ys.append(row["score_after"] or 0)
            brushes.append(pg.mkBrush(RESULT_COLORS.get(row["result"], "#888")))
        if not xs:
            return
        self._plot.plot(xs, ys, pen=pg.mkPen("#888", width=2))
        scatter = pg.ScatterPlotItem(
            x=xs, y=ys, brush=brushes, pen=pg.mkPen("#333"), size=11
        )
        self._plot.addItem(scatter)

    def _refresh_matchups(self, *_args) -> None:
        if self._f_first.isChecked():
            tf = "first"
        elif self._f_second.isChecked():
            tf = "second"
        else:
            tf = None
        data = self._games.get_deck_matchups(tf)
        self._mtable.setRowCount(len(data))
        for i, row in enumerate(data):
            self._mtable.setItem(i, 0, _cell(row["deck"]))
            self._mtable.setItem(i, 1, _cell(str(row["games"]), center=True))
            self._mtable.setItem(i, 2, _cell(str(row["wins"]), center=True))
            self._mtable.setItem(i, 3, _cell(str(row["losses"]), center=True))
            self._mtable.setItem(i, 4, _cell(f"{row['winrate']:.1f}%", center=True))

    def _refresh_records(self) -> None:
        games = self._games.get_all_games()
        self._rtable.setRowCount(len(games))
        for i, g in enumerate(games):
            id_item = _cell(str(g["id"]), center=True)
            id_item.setData(Qt.ItemDataRole.UserRole, int(g["id"]))
            self._rtable.setItem(i, 0, id_item)
            self._rtable.setItem(i, 1, _cell(g["played_at"] or ""))
            self._rtable.setItem(
                i, 2, _cell(label(RESULT_LABELS, g["result"]), center=True)
            )
            self._rtable.setItem(
                i, 3, _cell(label(TURN_ORDER_LABELS, g["turn_order"]), center=True)
            )
            self._rtable.setItem(i, 4, _cell(g["my_deck"] or ""))
            self._rtable.setItem(i, 5, _cell(g["opp_deck"] or ""))
            self._rtable.setItem(i, 6, _cell(str(g["turns"]), center=True))
            self._rtable.setItem(
                i, 7, _cell(label(END_REASON_LABELS, g["end_reason"]), center=True)
            )
            self._rtable.setItem(i, 8, _cell(str(g["score_after"]), center=True))
            self._rtable.setItem(i, 9, _cell(g["note"] or ""))

    # ===== 편집 / 삭제 =====
    def _selected_id(self) -> int | None:
        row = self._rtable.currentRow()
        if row < 0:
            return None
        item = self._rtable.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

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
        reply = QMessageBox.question(
            self,
            "삭제",
            "선택한 기록을 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
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
        export_fn(path)
        QMessageBox.information(self, "내보내기", f"{label} 저장 완료:\n{path}")

    def _export_csv(self) -> None:
        self._export("CSV", "games.csv", "CSV (*.csv)", self._games.export_csv)

    def _export_xlsx(self) -> None:
        self._export("XLSX", "games.xlsx", "Excel (*.xlsx)", self._games.export_xlsx)
