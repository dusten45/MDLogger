"""단계 6 계정 UI의 키보드·상태 표시·긴 텍스트 회귀 테스트."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from mdlogger.game_service import GameService
from mdlogger.game_sync.models import SyncPhase, SyncStatus
from mdlogger.profiles import ProfileManager
from mdlogger.ui.account_views import AuthWindow, GuestNoticeDialog
from mdlogger.ui.main_window import MainWindow
from mdlogger.ui.theme import DARK_COLORS, build_palette

USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def test_login_form_has_visible_labels_password_toggle_and_enter_submit(
    qapp: QApplication,
):
    window = AuthWindow()
    submitted: list[tuple[str, str]] = []
    window.sign_in_requested.connect(
        lambda email, password: submitted.append((email, password))
    )
    window.show()
    qapp.processEvents()

    window._email.setText("a@test.local")
    window._password.setText("password")
    assert window._email.accessibleName() == "이메일"
    assert window._password.accessibleName() == "비밀번호"
    assert window._password.echoMode() is QLineEdit.EchoMode.Password

    window._show_password.setChecked(True)
    assert window._password.echoMode() is QLineEdit.EchoMode.Normal
    window._password.returnPressed.emit()
    assert submitted == [("a@test.local", "password")]
    window.close()


def test_form_validation_is_next_to_the_field_and_focus_order_matches_layout(
    qapp: QApplication,
):
    window = AuthWindow()
    window.show()
    qapp.processEvents()

    window._email.setText("invalid")
    window._password.setText("short")
    window._submit.click()

    assert window._email_error.isVisible()
    assert window._password_error.isVisible()
    assert window._email.property("invalid") is True
    window._email.setFocus()
    QTest.keyClick(window._email, Qt.Key.Key_Tab)
    assert window.focusWidget() is window._password
    window.close()


def test_guest_notice_wraps_long_korean_copy_and_names_included_excluded_data(
    qapp: QApplication,
):
    dialog = GuestNoticeDialog()
    text = " ".join(label.text() for label in dialog.findChildren(QLabel))

    assert "전송:" in text
    assert "전송하지 않음:" in text
    assert "자유 입력 메모" in text
    assert dialog.minimumWidth() >= 380
    dialog.close()


def test_result_header_uses_dark_theme_palette_instead_of_fixed_light_text(
    qapp: QApplication, tmp_path: Path
):
    original_palette = qapp.palette()
    qapp.setPalette(build_palette(DARK_COLORS))
    profiles = ProfileManager(tmp_path)
    profile = profiles.guest()
    profiles.prepare_database(profile)
    games = GameService.open(profile.database_path)
    window = MainWindow(games, ["테스트 덱"], profile)

    assert "color:" not in window._result_view._today.styleSheet()
    assert (
        window._result_view._today.palette().windowText().color().name().upper()
        == DARK_COLORS.text_primary
    )

    window.close_profile_windows()
    games.close()
    qapp.setPalette(original_palette)


def test_main_window_shows_profile_and_local_status_without_changing_result_flow(
    qapp: QApplication, tmp_path: Path
):
    profiles = ProfileManager(tmp_path)
    profile = profiles.registered(
        USER_ID, "very-long-account-name@example.com", session_state="offline"
    )
    profiles.prepare_database(profile)
    games = GameService.open(profile.database_path)
    window = MainWindow(games, ["테스트 덱"], profile)

    assert (
        "very-long-account-name@example.com"
        in window._result_view._account_status.text()
    )
    assert "오프라인" in window._result_view._account_status.text()
    window.set_sync_status(
        SyncStatus(SyncPhase.FAILED, pending_count=3, failed_count=2)
    )
    assert "동기화 실패" in window._result_view._account_status.text()
    assert "2건" in window._result_view._account_status.text()
    assert window._stack.currentWidget() is window._result_view

    window.close_profile_windows()
    games.close()
