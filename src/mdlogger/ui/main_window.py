"""메인 창: 화면1/화면2 전환(QStackedWidget) + 오늘 전적 + 되돌리기 + 통계 열기."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from ..decks import load_decks
from ..enums import RESULT_LABELS
from ..game_service import GameService
from ..game_sync.coordinator import SyncCoordinator
from ..game_sync.models import SyncStatus
from ..profiles import ProfileContext, ProfileKind
from .detail_view import DetailView
from .result_view import ResultView


class MainWindow(QMainWindow):
    account_requested = Signal()

    def __init__(
        self,
        games: GameService,
        decks: list[str],
        profile: ProfileContext | None = None,
    ):
        super().__init__()
        self._games = games
        self._profile = profile
        self._decks = list(decks)
        self._current_result: str | None = None
        self._stats = None  # 지연 생성되는 통계 창
        self._sync: SyncCoordinator | None = None
        self._sync_status: SyncStatus | None = None

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
        self._result_view.account_requested.connect(self.account_requested)
        # 화면2 시그널
        self._detail_view.back_requested.connect(self.show_result)
        self._detail_view.confirmed.connect(self.on_confirm)

        self.refresh_header()
        self.show_result()

    @property
    def profile(self) -> ProfileContext | None:
        return self._profile

    def set_sync_coordinator(self, coordinator: SyncCoordinator) -> None:
        self._sync = coordinator
        self._sync_status = coordinator.status
        coordinator.status_changed.connect(self.set_sync_status)
        self.refresh_header()

    def set_sync_status(self, status: SyncStatus) -> None:
        self._sync_status = status
        self.refresh_header()

    def request_sync(self, *, retry_failed: bool = False) -> None:
        if self._sync is not None:
            self._sync.request_sync(retry_failed=retry_failed)

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
            score_base=self._games.get_last_score(),
            my_deck=self._games.get_last_my_deck(),
        )
        self._detail_view.form.focus_deck()
        self._stack.setCurrentWidget(self._detail_view)

    # ----- 동작 -----
    def on_confirm(self, values: dict) -> None:
        if self._current_result is None:
            return
        record = {**values, "result": self._current_result}
        self._games.insert_game(record)
        self.request_sync()
        self.refresh_header()
        self._refresh_stats()
        self.show_result()

    def on_undo(self) -> None:
        last = self._games.get_last_game()
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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._games.delete_game(last["id"])
            self.request_sync()
            self.refresh_header()
            self._refresh_stats()

    def open_stats(self) -> None:
        from .stats_window import StatsWindow

        if self._stats is None:
            self._stats = StatsWindow(self._games, self._decks)
            self._stats.data_changed.connect(self.refresh_header)
        self._stats.refresh()
        self._stats.show()
        self._stats.raise_()
        self._stats.activateWindow()

    def close_profile_windows(self) -> None:
        """프로필 전환 전에 이 범위의 보조 창과 메인 창을 닫는다."""
        if self._stats is not None:
            self._stats.close()
            self._stats = None
        self.close()

    # ----- 헤더/통계 갱신 -----
    def refresh_header(self) -> None:
        if self._profile is not None:
            if self._profile.kind is ProfileKind.GUEST:
                account_status = "게스트 · 로컬 저장"
            else:
                state_label = {
                    "authenticated": "인증됨",
                    "offline": "오프라인",
                    "reauth_required": "재로그인 필요",
                    "credential_unavailable": "보안 저장소 확인 필요",
                }.get(self._profile.session_state, "로컬 사용")
                account_status = (
                    f"{self._profile.display_name} · {state_label} · 로컬 저장"
                )
            if self._sync_status is not None:
                account_status = (
                    f"{account_status.removesuffix(' · 로컬 저장')} · "
                    f"{self._sync_status.display_text}"
                )
            self._result_view.set_account_status(account_status)
        wins, losses = self._games.get_today_record()
        self._result_view.set_today_record(wins, losses)
        self._result_view.set_undo_enabled(self._games.count_games() > 0)

    def _refresh_stats(self) -> None:
        if self._stats is not None and self._stats.isVisible():
            self._stats.refresh()
