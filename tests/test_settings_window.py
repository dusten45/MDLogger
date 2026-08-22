"""통합 설정 창 테스트 (계획 2, spec §8.4)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
)

from mdlogger.app_settings import (
    AppSettings,
    MemorySettingsStore,
    ReduceMotion,
    ScoreInputMode,
)
from mdlogger.game_service import GameService
from mdlogger.models import GameMode, StandingKind
from mdlogger.ui.main_window import MainWindow
from mdlogger.ui.settings_window import SettingsWindow
from mdlogger.ui.stats_window import StatsWindow
from mdlogger.ui.theme import (
    ThemeController,
    ThemeMode,
    apply_ui_scale,
    current_ui_scale,
    scaled,
)


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


class _Screen:
    def __init__(self, height: int) -> None:
        self._height = height

    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1920, self._height)


@pytest.fixture(autouse=True)
def _reset_app_properties(qapp):
    original_font = qapp.font()
    original_palette = qapp.palette()
    original_style_sheet = qapp.styleSheet()
    apply_ui_scale(1.0, qapp)
    yield
    qapp.closeAllWindows()
    qapp.processEvents()
    qapp.setProperty("accentColor", None)
    qapp.setProperty("themeMode", None)
    qapp.setStyleSheet(original_style_sheet)
    qapp.setFont(original_font)
    qapp.setPalette(original_palette)


def _find_button(parent, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"버튼을 찾지 못함: {text!r}")


def _window(
    store,
    theme=None,
    games=None,
    registered=False,
    parent=None,
) -> SettingsWindow:
    return SettingsWindow(
        store,
        theme,
        games,
        profile_name="user@example.com" if registered else "게스트",
        status_text="로그인됨" if registered else "게스트 · 로컬 저장",
        registered=registered,
        parent=parent,
    )


def test_category_navigation(qapp) -> None:
    win = _window(MemorySettingsStore())
    win.show()
    qapp.processEvents()

    assert win.focusWidget() is None
    assert win._nav.count() == 4
    win._nav.setCurrentRow(1)
    assert win._stack.currentIndex() == 1
    win._nav.setCurrentRow(3)
    assert win._stack.currentIndex() == 3


def test_settings_pages_scroll_without_overlapping_the_footer(qapp) -> None:
    win = _window(MemorySettingsStore(), registered=True)

    assert win.size().width() >= 680
    assert win.size().height() >= 620
    assert isinstance(win._page_scroll, QScrollArea)
    assert win._page_scroll.widgetResizable()
    assert win._page_scroll.widget() is win._stack

    win.resize(win.minimumSize())
    win.show()
    qapp.processEvents()
    win._nav.setCurrentRow(3)
    qapp.processEvents()

    assert win._page_scroll.verticalScrollBar().maximum() > 0
    win.close()


def test_registered_account_has_prominent_danger_zone_heading(qapp) -> None:
    win = _window(MemorySettingsStore(), registered=True)
    headings = [
        label for label in win.findChildren(QLabel) if label.text() == "위험 구역"
    ]
    dividers = [
        frame
        for frame in win.findChildren(QFrame)
        if frame.property("role") == "danger-divider"
    ]

    assert len(headings) == 1
    assert headings[0].property("tone") == "danger"
    assert headings[0].font().weight() == QFont.Weight.DemiBold
    assert len(dividers) == 2


def test_theme_and_accent_apply_immediately(qapp) -> None:
    store = MemorySettingsStore()
    theme = ThemeController(qapp)
    win = _window(store, theme=theme)

    win._on_theme_changed("dark")
    assert store.load().theme_mode is ThemeMode.DARK
    assert theme.mode is ThemeMode.DARK

    win._on_accent_changed("teal")
    assert store.load().accent_color == "teal"
    assert theme.accent == "teal"


def test_ui_scale_is_saved_for_the_next_restart(qapp) -> None:
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        settings = _window(MemorySettingsStore(), parent=main)
        main.show()
        settings.show()
        qapp.processEvents()

        original_size = main.size()
        original_font_size = main._result_view._today.font().pointSizeF()
        settings._on_ui_scale_changed("0.75")
        qapp.processEvents()

        assert settings._store.load().ui_scale == 0.75
        assert current_ui_scale() == 1.0
        assert main.size() == original_size
        assert main._result_view._today.font().pointSizeF() == original_font_size
    finally:
        settings.close()
        main.close()
        games.close()


def test_ui_scale_applies_to_windows_created_on_next_start(qapp) -> None:
    apply_ui_scale(0.75, qapp)
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        settings = _window(MemorySettingsStore(AppSettings(ui_scale=0.75)), parent=main)
        result_layout = main._result_view.layout()
        appearance_page = settings._pages[0][1]
        appearance_layout = appearance_page.layout()

        assert result_layout is not None
        assert appearance_layout is not None
        assert main.size() == QSize(315, 641)
        assert settings.size() == QSize(510, 465)
        assert settings.minimumSize() == QSize(465, 390)
        assert settings._nav.width() == 120
        assert main._result_view._undo.iconSize() == QSize(15, 15)
        assert result_layout.contentsMargins().left() == 9
        assert appearance_layout.contentsMargins().left() == 7
        assert "min-height: 26px" in qapp.styleSheet()
    finally:
        settings.close()
        main.close()
        games.close()


def test_result_view_does_not_inherit_detail_scroll_range(qapp) -> None:
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        main.show()
        qapp.processEvents()

        assert main._stack.currentWidget() is main._result_view
        assert not main._detail_scroll.isVisible()
    finally:
        main.close()
        games.close()


def test_stats_layout_and_table_constraints_scale_on_next_start(qapp) -> None:
    games = GameService.open(":memory:")
    full_size = None
    scaled_stats = None
    try:
        full_size = StatsWindow(games, ["테스트 덱"])
        assert full_size.size() == QSize(760, 600)
        full_size.show()
        qapp.processEvents()
        full_size_columns = full_size._card_cols
        full_size.close()
        qapp.processEvents()

        apply_ui_scale(0.75, qapp)
        scaled_stats = StatsWindow(games, ["테스트 덱"])
        assert scaled_stats.size() == QSize(570, 450)
        scaled_stats.show()
        qapp.processEvents()

        assert scaled_stats._card_cols == full_size_columns
        assert scaled_stats._rtable.horizontalHeader().maximumSectionSize() == 210
    finally:
        if full_size is not None:
            full_size.close()
        if scaled_stats is not None:
            scaled_stats.close()
        games.close()


def test_main_window_uses_stable_detail_height_when_screen_allows(
    qapp, monkeypatch
) -> None:
    apply_ui_scale(1.0, qapp)
    monkeypatch.setattr(MainWindow, "screen", lambda _: _Screen(1440))
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        expected_size = QSize(
            420, main._detail_view.minimumSizeHint().height() + scaled(1)
        )
        assert main.size() == expected_size

        main.show()
        qapp.processEvents()
        assert main.size() == expected_size

        main.show_detail()
        qapp.processEvents()
        assert main.size() == expected_size
        assert main._detail_scroll.verticalScrollBar().maximum() == 0

        main.show_result()
        qapp.processEvents()
        assert main.size() == expected_size
    finally:
        main.close()
        games.close()


def test_detail_view_allows_scrolling_to_confirm_on_small_main_window(
    qapp, monkeypatch
) -> None:
    apply_ui_scale(0.75, qapp)
    monkeypatch.setattr(MainWindow, "screen", lambda _: _Screen(510))
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        expected_size = QSize(315, 510)
        assert main.size() == expected_size

        main.show()
        qapp.processEvents()
        shown_size = main.size()

        main.show_detail()
        qapp.processEvents()

        scroll = main._detail_scroll
        assert main.size() == shown_size
        assert main._stack.currentWidget() is scroll
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.ensureWidgetVisible(main._detail_view._confirm)
        qapp.processEvents()
        confirm_bottom = main._detail_view._confirm.mapTo(
            scroll.viewport(), QPoint(0, main._detail_view._confirm.height())
        ).y()
        assert confirm_bottom <= scroll.viewport().height()

        main.show_result()
        qapp.processEvents()
        assert main.size() == shown_size
    finally:
        main.close()
        games.close()


def test_detail_scroll_resets_when_reopened(qapp, monkeypatch) -> None:
    apply_ui_scale(1.0, qapp)
    monkeypatch.setattr(MainWindow, "screen", lambda _: _Screen(510))
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        main.show()
        main.show_detail()
        qapp.processEvents()

        scroll = main._detail_scroll
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        assert scroll.verticalScrollBar().value() > 0

        main.show_result()
        main.show_detail()
        qapp.processEvents()
        assert scroll.verticalScrollBar().value() == 0
    finally:
        main.close()
        games.close()


@pytest.mark.parametrize("ui_scale", (0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5))
def test_detail_form_variants_fit_the_stable_large_screen_height(
    qapp, monkeypatch, ui_scale: float
) -> None:
    apply_ui_scale(ui_scale, qapp)
    monkeypatch.setattr(MainWindow, "screen", lambda _: _Screen(1800))
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        expected_size = main.size()
        main.show()
        main.show_detail()
        qapp.processEvents()

        modes = (
            GameMode("event", StandingKind.EVENT_POINTS, "event", None),
            GameMode("rank", StandingKind.RANK, "rank", None),
            GameMode("rating", StandingKind.RATING, "rating", None),
        )
        for mode in modes:
            for input_mode in (ScoreInputMode.DELTA, ScoreInputMode.DIRECT):
                for memo_enabled in (True, False):
                    main._detail_view.set_mode(mode)
                    main.set_score_input_mode(input_mode)
                    main.set_memo_enabled(memo_enabled)
                    qapp.processEvents()

                    assert main.size() == expected_size
                    assert main._detail_scroll.verticalScrollBar().maximum() == 0
    finally:
        main.close()
        games.close()


def test_detail_validation_messages_do_not_add_a_scrollbar(qapp, monkeypatch) -> None:
    apply_ui_scale(1.0, qapp)
    monkeypatch.setattr(MainWindow, "screen", lambda _: _Screen(1440))
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        main.show()
        main.show_detail()
        qapp.processEvents()

        messages = (
            "승/패를 선택하세요",
            "내 덱 / 상대 덱을 후보에서 정확히 선택하세요",
            "경기 전/후 레이팅을 입력하세요",
            "경기 전 레이팅을 입력하세요",
            "레이팅 변동폭을 입력하세요",
        )
        for message in messages:
            main._detail_view._status.setText(message)
            qapp.processEvents()
            assert main._detail_scroll.verticalScrollBar().maximum() == 0
    finally:
        main.close()
        games.close()


def test_main_window_rechecks_available_height_after_show(qapp, monkeypatch) -> None:
    apply_ui_scale(1.0, qapp)
    monkeypatch.setattr(MainWindow, "screen", lambda _: _Screen(764))
    monkeypatch.setattr(
        MainWindow,
        "frameGeometry",
        lambda window: QRect(
            0,
            0,
            window.width(),
            window.height() + (4 if window.isVisible() else 0),
        ),
    )
    games = GameService.open(":memory:")
    try:
        main = MainWindow(games, ["테스트 덱"])
        assert main.height() == 764

        main.show()
        qapp.processEvents()
        assert main.height() == 760

        main.show_detail()
        qapp.processEvents()
        assert main._detail_scroll.verticalScrollBar().maximum() > 0
    finally:
        main.close()
        games.close()


def test_memo_toggle_emits_signal_and_persists(qapp) -> None:
    store = MemorySettingsStore()
    win = _window(store)
    emitted: list[bool] = []
    win.memo_enabled_changed.connect(emitted.append)

    win._on_memo_changed(False)
    assert emitted == [False]
    assert store.load().memo_enabled is False


def test_reset_settings_restores_defaults_without_touching_games(qapp) -> None:
    store = MemorySettingsStore(
        AppSettings(theme_mode=ThemeMode.DARK, accent_color="teal", memo_enabled=False)
    )
    games = GameService.open(":memory:")
    try:
        win = _window(store, games=games)
        win._reset_settings()
        assert store.load() == AppSettings()
        assert store.load().memo_enabled is True
    finally:
        games.close()


def test_application_reset_requires_confirmation(qapp, monkeypatch) -> None:
    store = MemorySettingsStore(AppSettings(memo_enabled=False))
    win = _window(store)
    emitted: list[None] = []
    win.app_reset_requested.connect(lambda: emitted.append(None))
    button = _find_button(win, "앱 초기화")

    assert button.property("role") == "danger"
    assert button.accessibleName() == "설정과 이 기기에 저장된 모든 앱 데이터 삭제하기"

    confirmation: list[tuple] = []

    def reject(*args):
        confirmation.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "warning", reject)
    button.click()
    assert emitted == []
    assert store.load().memo_enabled is False
    assert "서버에 저장된 계정과 데이터" in confirmation[0][2]
    assert confirmation[0][3] == (
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    assert confirmation[0][4] == QMessageBox.StandardButton.No

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    button.click()
    assert emitted == [None]
    # 전체 초기화의 실제 저장소 변경은 ProfileRouter가 성공한 뒤 처리한다.
    assert store.load().memo_enabled is False


def test_low_spec_preserves_reduce_motion_individual_value(qapp) -> None:
    store = MemorySettingsStore(AppSettings(reduce_motion=ReduceMotion.OFF))
    win = _window(store)
    win._on_low_spec_changed(True)
    assert store.load().low_spec_mode is True
    # 개별 reduce_motion 값은 보존된다.
    assert store.load().reduce_motion is ReduceMotion.OFF


def test_registered_account_actions_emit_signals(qapp) -> None:
    win = _window(MemorySettingsStore(), registered=True)
    emitted: list[str] = []
    win.logout_requested.connect(lambda: emitted.append("logout"))
    win.sign_out_all_requested.connect(lambda: emitted.append("sign_out_all"))
    win.delete_account_requested.connect(lambda: emitted.append("delete"))

    _find_button(win, "로그아웃").click()
    _find_button(win, "모든 기기에서 로그아웃").click()
    _find_button(win, "계정 삭제").click()

    assert emitted == ["logout", "sign_out_all", "delete"]


def test_guest_settings_sync_buttons_disabled(qapp) -> None:
    win = _window(MemorySettingsStore(), registered=False)
    assert not win._settings_upload_btn.isEnabled()
    assert not win._settings_download_btn.isEnabled()


def test_last_used_mode_option_does_not_duplicate_after_reopen(qapp, tmp_path) -> None:
    database_path = tmp_path / "games.db"
    games = GameService.open(database_path)
    try:
        games.insert_play_mode(
            {
                "id": "last-used-cache",
                "standing_kind": "rank",
                "display_name": "이전 모드 기억",
                "play_context_id": "last_used_cache",
                "sort_order": 99,
                "is_active": True,
                "season_label": None,
            }
        )
        first_window = _window(MemorySettingsStore(), games=games)
        first_window._on_default_mode_changed("last_used")
        first_window.close()
    finally:
        games.close()

    reopened_games = GameService.open(database_path)
    try:
        reopened_window = _window(MemorySettingsStore(), games=reopened_games)
        labels = [
            button.text()
            for button in reopened_window._default_mode.findChildren(QPushButton)
        ]

        assert labels.count("이전 모드 기억") == 1
        assert reopened_window._default_mode.value() == "last_used"
    finally:
        reopened_games.close()


def test_settings_window_has_legal_policy_links(qapp) -> None:
    win = _window(MemorySettingsStore())
    privacy_btn = win.findChild(QPushButton, "settingsPrivacyLink")
    terms_btn = win.findChild(QPushButton, "settingsTermsLink")

    assert privacy_btn is not None
    assert privacy_btn.text() == "개인정보 처리방침"
    assert terms_btn is not None
    assert terms_btn.text() == "서비스 이용약관"
    win.close()
