"""메인 창: 화면1/화면2 전환(QStackedWidget) + 오늘 전적 + 되돌리기 + 통계 열기."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from ..app_settings import ScoreInputMode
from ..decks import load_decks
from ..enums import RESULT_LABELS
from ..game_service import GameService
from ..game_sync.coordinator import SyncCoordinator
from ..game_sync.models import SyncPhase, SyncStatus
from ..models import GameMode, RankStanding, StandingKind
from ..profiles import ProfileContext, ProfileKind
from .detail_view import DetailView
from .focus import restrict_focus_to_pointer
from .result_view import ResultView
from .theme import ThemeController


class MainWindow(QMainWindow):
    settings_requested = Signal()

    def __init__(
        self,
        games: GameService,
        decks: list[str],
        profile: ProfileContext | None = None,
        theme: ThemeController | None = None,
    ):
        super().__init__()
        self._games = games
        self._profile = profile
        self._decks = list(decks)
        self._theme = theme
        self._stats = None  # 지연 생성되는 통계 창
        self._sync: SyncCoordinator | None = None
        self._sync_status: SyncStatus | None = None
        self._memo_enabled = True
        self._score_input_mode = ScoreInputMode.DELTA
        self._modes: list = []
        self._mode_by_id: dict[str, GameMode] = {}
        self._current_mode_id: str | None = None

        self.setWindowTitle("MDLogger")
        self.resize(420, 680)
        self.setMinimumWidth(380)

        self._stack = QStackedWidget()
        self._result_view = ResultView()
        self._detail_view = DetailView(self._decks)
        self._stack.addWidget(self._result_view)
        self._stack.addWidget(self._detail_view)
        self.setCentralWidget(self._stack)

        # 화면1 시그널
        self._result_view.record_requested.connect(self.show_detail)
        self._result_view.undo_requested.connect(self.on_undo)
        self._result_view.stats_requested.connect(self.open_stats)
        self._result_view.mode_changed.connect(self.on_mode_changed)
        self._result_view.settings_requested.connect(self.settings_requested)
        # 화면2 시그널
        self._detail_view.back_requested.connect(self.show_result)
        self._detail_view.confirmed.connect(self.on_confirm)

        self._load_modes()
        self.refresh_header()
        self.show_result()
        restrict_focus_to_pointer(self)

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
        # 동기화 주기가 끝나면(모드 기준정보는 run_once 끝에 갱신된다) 캐시가
        # 바뀌었는지 확인해 목록을 갱신한다. SYNCING은 주기 시작 전 상태다.
        if status.phase is not SyncPhase.SYNCING:
            self._reload_modes_if_changed()
        self.refresh_header()

    def request_sync(self, *, retry_failed: bool = False) -> None:
        if self._sync is not None:
            self._sync.request_sync(retry_failed=retry_failed)

    # ----- 화면 전환 -----
    def show_result(self) -> None:
        self._stack.setCurrentWidget(self._result_view)

    def _load_modes(self) -> None:
        """활성 모드 목록을 로드하고 기본/마지막 모드를 결정한다 (spec §6.1)."""
        self._modes = self._games.get_active_play_modes()
        self._mode_by_id = {
            str(m["id"]): GameMode(
                id=str(m["id"]),
                standing_kind=StandingKind(str(m["standing_kind"])),
                display_name=str(m["display_name"]),
                play_context_id=m["play_context_id"],
                sort_order=int(m["sort_order"] or 0),
                is_active=bool(m["is_active"]),
                season_label=m["season_label"],
            )
            for m in self._modes
        }
        self._result_view.set_modes(self._modes)
        self._current_mode_id = self._games.resolve_default_mode_id()
        if self._current_mode_id is not None:
            self._result_view.set_mode(self._current_mode_id)
        # 활성 모드가 없으면 전적 입력을 비활성화해 무모드 저장을 막는다(spec §2.5-7).
        self._result_view.set_record_button_enabled(self._current_mode_id is not None)

    @staticmethod
    def _mode_signature(mode) -> tuple:
        """모드 행의 비교용 시그니처 (id·종류·표시명·문맥·정렬·활성·시즌)."""
        return (
            str(mode["id"]),
            str(mode["standing_kind"]),
            str(mode["display_name"]),
            mode["play_context_id"],
            int(mode["sort_order"] or 0),
            bool(mode["is_active"]),
            mode["season_label"],
        )

    def _reload_modes_if_changed(self) -> None:
        """동기화로 로컬 play_modes 캐시가 바뀌었으면 모드 목록을 갱신한다.

        현재 선택을 보존하고, 선택한 모드가 사라졌으면 기본 모드로 되돌린다.
        """
        fresh = self._games.get_active_play_modes()
        if [self._mode_signature(m) for m in fresh] == [
            self._mode_signature(m) for m in self._modes
        ]:
            return
        previous = self._current_mode_id
        self._load_modes()
        if previous is not None and previous in self._mode_by_id:
            self._current_mode_id = previous
            self._result_view.set_mode(previous)

    def _current_mode(self) -> GameMode | None:
        if self._current_mode_id is None:
            return None
        return self._mode_by_id.get(self._current_mode_id)

    def on_mode_changed(self, mode_id: str) -> None:
        self._current_mode_id = mode_id

    def show_detail(self) -> None:
        # decks.json 편집 사항을 매 입력마다 반영
        self._decks = load_decks()
        self._detail_view.form.set_decks(self._decks)
        mode = self._current_mode()
        self._detail_view.set_mode(mode)
        self._detail_view.reset_result()
        self._detail_view.form.reset(
            score_base=0, my_deck=self._games.get_last_my_deck()
        )
        if mode is not None:
            kind = mode.standing_kind.value
            if kind == StandingKind.EVENT_POINTS.value:
                self._detail_view.form.set_score_base(
                    self._games.get_last_score(mode.id)
                )
            elif kind == StandingKind.RANK.value:
                standing = self._games.get_last_standing(mode.id)
                if standing is not None:
                    self._detail_view.form.set_rank_before(*standing)
            elif kind == StandingKind.RATING.value:
                rating = self._games.get_last_rating(mode.id)
                if rating is not None:
                    self._detail_view.form.set_rating_before(rating)
        self._stack.setCurrentWidget(self._detail_view)

    # ----- 동작 -----
    def on_confirm(self, values: dict) -> None:
        mode = self._current_mode()
        record = dict(values)
        if mode is not None:
            record["standing_kind"] = mode.standing_kind.value
            record["play_context_id"] = mode.play_context_id
        self._games.insert_game(record)
        if mode is not None:
            self._games.set_last_used_mode(mode.id)
        self.request_sync()
        self.refresh_header()
        self._refresh_stats()
        self.show_result()

    def on_undo(self) -> None:
        last = self._games.get_last_game()
        if last is None:
            return
        summary = self._record_summary(last)
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

    @staticmethod
    def _record_summary(row) -> str:
        """모드별 확인 요약 (spec §6.3: 점수전=점수, 랭크전=골드 3 → 골드 2, 레이팅=rating)."""
        kind = row["standing_kind"]
        result = RESULT_LABELS.get(row["result"], row["result"])
        if kind == StandingKind.RANK.value:
            before = (
                RankStanding(row["rank_tier_before"], int(row["rank_division_before"]))
                if row["rank_tier_before"] and row["rank_division_before"] is not None
                else None
            )
            after = (
                RankStanding(row["rank_tier_after"], int(row["rank_division_after"]))
                if row["rank_tier_after"] and row["rank_division_after"] is not None
                else None
            )
            if before is not None and after is not None:
                if before == after:
                    standing = f"{after.label} 유지"
                else:
                    standing = f"{before.label} → {after.label}"
            else:
                standing = "랭크"
            return f"{result} · {row['opp_deck']} · {standing}"
        if kind == StandingKind.RATING.value:
            rating = row["rating_after"] if row["rating_after"] is not None else "—"
            return f"{result} · {row['opp_deck']} · 레이팅 {rating}"
        score = (
            row["event_points_after"] if row["event_points_after"] is not None else 0
        )
        return f"{result} · {row['opp_deck']} · {score}점"

    def open_stats(self) -> None:
        from .stats_window import StatsWindow

        if self._stats is None:
            self._stats = StatsWindow(
                self._games, self._decks, theme=self._theme, profile=self._profile
            )
            self._stats.set_memo_enabled(self._memo_enabled)
            self._stats.data_changed.connect(self.refresh_header)
            # 휴대용 아카이브 가져오기 성공 시 즉시 동기화를 요청한다.
            self._stats.records_imported.connect(self.request_sync)
        self._stats.refresh()
        self._stats.show()
        self._stats.raise_()
        self._stats.activateWindow()

    def set_memo_enabled(self, enabled: bool) -> None:
        """메모 표시 여부를 상세 폼과 통계 표에 적용한다 (P8, spec §5.4)."""
        self._memo_enabled = enabled
        self._detail_view.form.set_memo_enabled(enabled)
        if self._stats is not None:
            self._stats.set_memo_enabled(enabled)

    def set_score_input_mode(self, mode: ScoreInputMode) -> None:
        """점수/레이팅 입력 방식을 상세 폼에 적용한다 (spec §4.6)."""
        self._score_input_mode = mode
        self._detail_view.form.set_score_input_mode(mode)

    def close_profile_windows(self) -> None:
        """프로필 전환 전에 이 범위의 보조 창과 메인 창을 닫고 삭제를 예약한다.

        deleteLater로 예약해 프로필 전환마다 닫힌 창이 GameService 참조를 들고
        누적되지 않게 한다(P1-10).
        """
        if self._stats is not None:
            self._stats.close()
            self._stats.deleteLater()
            self._stats = None
        self.close()
        self.deleteLater()

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
        self._result_view.set_mode_status(self._mode_status_text())

    def _mode_status_text(self) -> str:
        """활성 모드별 현재 상태 한 줄 (A5)."""
        parts = []
        for mode in self._modes:
            kind = str(mode["standing_kind"])
            name = str(mode["display_name"])
            if kind == StandingKind.RANK.value:
                standing = self._games.get_last_standing(str(mode["id"]))
                if standing is not None:
                    tier, division = standing
                    parts.append(f"{name} {RankStanding(tier, division).label}")
            elif kind == StandingKind.RATING.value:
                rating = self._games.get_last_rating(str(mode["id"]))
                if rating is not None:
                    parts.append(f"{name} {rating}")
            else:
                score = self._games.get_last_score(str(mode["id"]))
                parts.append(f"{name} {score}")
        return "  ·  ".join(parts)

    def _refresh_stats(self) -> None:
        if self._stats is not None and self._stats.isVisible():
            self._stats.refresh()
