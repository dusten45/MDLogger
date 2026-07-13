"""메인 창: 화면1/화면2 전환(QStackedWidget) + 오늘 전적 + 되돌리기 + 통계 열기."""
from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from .. import db
from ..decks import load_decks
from ..enums import RESULT_LABELS
from .detail_view import DetailView
from .result_view import ResultView


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection, decks: list[str]):
        super().__init__()
        self._conn = conn
        self._decks = list(decks)
        self._current_result: str | None = None
        self._stats = None  # 지연 생성되는 통계 창

        self.setWindowTitle("MD WCQ 로거")
        self.resize(360, 540)
        self.setMinimumWidth(340)

        self._stack = QStackedWidget()
        self._result_view = ResultView()
        self._detail_view = DetailView(self._decks)
        self._stack.addWidget(self._result_view)
        self._stack.addWidget(self._detail_view)
        self.setCentralWidget(self._stack)

        # 화면1 시그널
        self._result_view.result_chosen.connect(self.show_detail)
        self._result_view.undo_requested.connect(self.on_undo)
        self._result_view.stats_requested.connect(self.open_stats)
        # 화면2 시그널
        self._detail_view.back_requested.connect(self.show_result)
        self._detail_view.confirmed.connect(self.on_confirm)

        self.refresh_header()
        self.show_result()

    # ----- 화면 전환 -----
    def show_result(self) -> None:
        self._current_result = None
        self._stack.setCurrentWidget(self._result_view)

    def show_detail(self, result: str) -> None:
        self._current_result = result
        # decks.json 편집 사항을 매 입력마다 반영
        self._decks = load_decks()
        self._detail_view.form.set_decks(self._decks)
        self._detail_view.set_result(result)
        self._detail_view.form.reset(
            score_base=db.get_last_score(self._conn),
            my_deck=db.get_last_my_deck(self._conn),
        )
        self._detail_view.form.focus_deck()
        self._stack.setCurrentWidget(self._detail_view)

    # ----- 동작 -----
    def on_confirm(self, values: dict) -> None:
        if self._current_result is None:
            return
        record = {**values, "result": self._current_result}
        db.insert_game(self._conn, record)
        self.refresh_header()
        self._refresh_stats()
        self.show_result()

    def on_undo(self) -> None:
        last = db.get_last_game(self._conn)
        if last is None:
            return
        summary = (
            f"{RESULT_LABELS.get(last['result'], last['result'])} · "
            f"{last['opp_deck']} · {last['score_after']}점"
        )
        reply = QMessageBox.question(
            self,
            "마지막 기록 취소",
            f"가장 최근 기록을 삭제할까요?\n\n{summary}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            db.delete_game(self._conn, last["id"])
            self.refresh_header()
            self._refresh_stats()

    def open_stats(self) -> None:
        from .stats_window import StatsWindow

        if self._stats is None:
            self._stats = StatsWindow(self._conn, self._decks)
            self._stats.data_changed.connect(self.refresh_header)
        self._stats.refresh()
        self._stats.show()
        self._stats.raise_()
        self._stats.activateWindow()

    # ----- 헤더/통계 갱신 -----
    def refresh_header(self) -> None:
        wins, losses = db.get_today_record(self._conn)
        self._result_view.set_today_record(wins, losses)
        self._result_view.set_undo_enabled(db.count_games(self._conn) > 0)

    def _refresh_stats(self) -> None:
        if self._stats is not None and self._stats.isVisible():
            self._stats.refresh()
