"""통합 설정 창 테스트 (계획 2, spec §8.4)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from mdlogger.app_settings import AppSettings, MemorySettingsStore, ReduceMotion
from mdlogger.game_service import GameService
from mdlogger.ui.settings_window import SettingsWindow
from mdlogger.ui.theme import ThemeController, ThemeMode, current_font_scale


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture(autouse=True)
def _reset_app_properties(qapp):
    yield
    qapp.setProperty("accentColor", None)
    qapp.setProperty("themeMode", None)


def _find_button(parent, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"버튼을 찾지 못함: {text!r}")


def _window(store, theme=None, games=None, registered=False) -> SettingsWindow:
    return SettingsWindow(
        store,
        theme,
        games,
        profile_name="user@example.com" if registered else "게스트",
        status_text="로그인됨" if registered else "게스트 · 로컬 저장",
        registered=registered,
    )


def test_category_navigation(qapp) -> None:
    win = _window(MemorySettingsStore())
    assert win._nav.count() == 4
    win._nav.setCurrentRow(1)
    assert win._stack.currentIndex() == 1
    win._nav.setCurrentRow(3)
    assert win._stack.currentIndex() == 3


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


def test_font_scale_applies_immediately(qapp) -> None:
    store = MemorySettingsStore()
    win = _window(store)
    win._on_font_changed("1.25")
    assert store.load().font_scale == 1.25
    assert current_font_scale() == 1.25


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
