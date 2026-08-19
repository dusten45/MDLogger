"""단계 6 계정 UI의 키보드·상태 표시·긴 텍스트 회귀 테스트."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
)

from mdlogger.game_service import GameService
from mdlogger.game_sync.models import SyncConflict, SyncPhase, SyncStatus
from mdlogger.profiles import ProfileManager
from mdlogger.ui.account_views import (
    AccountDialog,
    AuthWindow,
    ConflictDialog,
    GuestNoticeDialog,
    GuestRecordChoice,
    GuestRecordChoiceDialog,
)
from mdlogger.ui.focus import install_pointer_focus_only
from mdlogger.ui.main_window import MainWindow
from mdlogger.ui.theme import DARK_COLORS, build_palette, scaled

USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        application = QApplication([])
    install_pointer_focus_only(application)
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


def test_login_window_size_is_independent_of_main_window_height(
    qapp: QApplication,
):
    window = AuthWindow()
    assert window.size() == QSize(scaled(420), scaled(560))
    assert window.minimumSize() == QSize(scaled(360), scaled(500))
    window.close()


def test_login_form_validation_is_next_to_the_field_and_tab_moves_focus(
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


def test_signup_form_tab_moves_from_email_to_password_confirmation(
    qapp: QApplication,
):
    window = AuthWindow()
    window.show_signup()
    window.show()
    qapp.processEvents()

    window._email.setFocus()
    QTest.keyClick(window._email, Qt.Key.Key_Tab)
    assert window.focusWidget() is window._password
    QTest.keyClick(window._password, Qt.Key.Key_Tab)
    assert window.focusWidget() is window._password_confirm
    window.close()


def test_verification_page_keeps_tab_focus_blocked(qapp: QApplication):
    window = AuthWindow()
    window.show_verification("a@test.local")
    window.show()
    qapp.processEvents()

    back = next(
        button
        for button in window._verification_page.findChildren(QPushButton)
        if button.text() == "로그인으로 돌아가기"
    )
    back.setFocus()
    QTest.keyClick(back, Qt.Key.Key_Tab)
    assert window.focusWidget() is back
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


def test_verification_back_button_returns_to_login_and_clears_status(
    qapp: QApplication,
):
    window = AuthWindow()
    window.set_status("이전 상태 메시지", error=True)
    window.show_verification("a@test.local")
    window.show()
    qapp.processEvents()

    back = next(
        button
        for button in window._verification_page.findChildren(QPushButton)
        if button.text() == "로그인으로 돌아가기"
    )
    back.click()

    # clicked(bool)의 checked 값이 상태 메시지로 전달되면 setText가 실패한다.
    assert window._stack.currentWidget() is window._form_page
    assert window._status.text() == ""
    window.close()


def test_guest_record_choice_dialog_never_clips_wrapped_copy(qapp: QApplication):
    dialog = GuestRecordChoiceDialog(1)
    dialog.show()
    qapp.processEvents()

    labels = dialog.findChildren(QLabel)
    assert labels
    assert "삭제되지 않습니다" in " ".join(label.text() for label in labels)
    for label in labels:
        assert label.height() >= label.heightForWidth(label.width())

    dialog.resize(dialog.minimumWidth(), 1)
    qapp.processEvents()
    for label in labels:
        assert label.height() >= label.heightForWidth(label.width())
    dialog.close()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("현재 계정으로 가져오기", GuestRecordChoice.IMPORT),
        ("게스트에 보관하고 계정으로 전환", GuestRecordChoice.KEEP),
        ("나중에 결정", GuestRecordChoice.LATER),
    ],
)
def test_guest_record_choice_dialog_describes_and_returns_each_option(
    qapp: QApplication, text: str, expected: GuestRecordChoice
):
    dialog = GuestRecordChoiceDialog(2)
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}

    assert buttons[text].accessibleDescription() != ""
    buttons[text].click()

    assert dialog.choice is expected
    assert dialog.result() == QDialog.DialogCode.Accepted
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


def test_conflict_dialog_compares_both_versions_and_supports_field_selection(
    qapp: QApplication,
):
    conflict = SyncConflict(
        id=1,
        game_sync_id="11111111-1111-4111-8111-111111111111",
        local_payload={"note": "이 장치 메모", "turns": 4, "deleted_at": None},
        remote_payload={
            "note": "서버 메모",
            "turns": 4,
            "deleted_at": None,
            "change_version": 7,
        },
        base_remote_version=6,
    )
    dialog = ConflictDialog(conflict)
    dialog.show()
    qapp.processEvents()

    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.columnCount() == 4
    assert table.accessibleName() == "충돌 필드 비교"
    choice = dialog.findChild(QComboBox)
    assert choice is not None
    choice.setCurrentIndex(1)
    apply_button = next(
        button
        for button in dialog.findChildren(QPushButton)
        if button.text() == "선택 내용 적용"
    )
    apply_button.click()

    assert dialog.resolution == "merged"
    assert dialog.merged_payload is not None
    assert dialog.merged_payload["note"] == "서버 메모"
    dialog.close()


def test_conflict_dialog_does_not_collapse_none_and_literal_display_text(
    qapp: QApplication,
):
    conflict = SyncConflict(
        id=2,
        game_sync_id="22222222-2222-4222-8222-222222222222",
        local_payload={"note": None},
        remote_payload={"note": "없음", "change_version": 8},
        base_remote_version=7,
    )
    dialog = ConflictDialog(conflict)
    table = dialog.findChild(QTableWidget)

    assert table is not None
    assert table.rowCount() == 1
    local_item = table.item(0, 1)
    remote_item = table.item(0, 2)
    assert local_item is not None
    assert remote_item is not None
    assert local_item.text() == "없음"
    assert remote_item.text() == "없음"
    dialog.close()


def test_account_dialog_exposes_color_independent_conflict_action(
    qapp: QApplication,
):
    dialog = AccountDialog(
        "user@example.com",
        "충돌 2건 · 확인 필요",
        registered=True,
        conflict_count=2,
    )
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}

    assert "동기화 충돌 2건 해결" in buttons
    assert "충돌 2건" in dialog.findChildren(QLabel)[1].text()
    assert "2건" in buttons["동기화 충돌 2건 해결"].accessibleName()
    dialog.close()


def test_account_dialog_reserves_height_for_wrapped_text(qapp: QApplication):
    dialog = AccountDialog(
        "게스트",
        "게스트 · 동기화됨",
        registered=False,
    )
    layout = dialog.layout()

    assert layout is not None
    assert dialog.width() == 420
    assert dialog.minimumHeight() >= layout.heightForWidth(dialog.minimumWidth())
    dialog.close()


def test_account_dialog_exposes_operation_buttons_only_for_registered(
    qapp: QApplication,
):
    registered = AccountDialog(
        "user@example.com",
        "로그인됨",
        registered=True,
    )
    registered_buttons = {
        button.text(): button for button in registered.findChildren(QPushButton)
    }
    assert "모든 기기에서 로그아웃" in registered_buttons
    assert "내 데이터 내보내기" in registered_buttons
    assert "계정 삭제" in registered_buttons
    assert registered_buttons["계정 삭제"].property("role") == "danger"
    registered.close()

    guest = AccountDialog(
        "게스트",
        "게스트 · 로컬 저장",
        registered=False,
    )
    guest_buttons = {
        button.text(): button for button in guest.findChildren(QPushButton)
    }
    assert "모든 기기에서 로그아웃" not in guest_buttons
    assert "내 데이터 내보내기" not in guest_buttons
    assert "계정 삭제" not in guest_buttons
    guest.close()


def test_account_dialog_emits_operation_signals(qapp: QApplication):
    dialog = AccountDialog(
        "user@example.com",
        "로그인됨",
        registered=True,
    )
    emitted: list[str] = []
    dialog.export_requested.connect(lambda: emitted.append("export"))
    dialog.sign_out_all_requested.connect(lambda: emitted.append("sign_out_all"))
    dialog.delete_account_requested.connect(lambda: emitted.append("delete"))
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}

    buttons["내 데이터 내보내기"].click()
    buttons["모든 기기에서 로그아웃"].click()
    buttons["계정 삭제"].click()

    assert emitted == ["export", "sign_out_all", "delete"]
    dialog.close()


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


def test_main_window_reloads_modes_when_sync_completes(
    qapp: QApplication, tmp_path: Path
):
    profiles = ProfileManager(tmp_path)
    profile = profiles.guest()
    profiles.prepare_database(profile)
    games = GameService.open(profile.database_path)
    window = MainWindow(games, ["테스트 덱"], profile)

    initial_ids = [str(m["id"]) for m in window._modes]
    assert "wcq-2026" in initial_ids

    # 동기화가 서버 기준정보로 로컬 캐시를 재구성한 상황을 재현한다.
    games.delete_play_mode("wcq-2026")
    games.insert_play_mode(
        {
            "id": "wcq-2027",
            "standing_kind": "event_points",
            "display_name": "2027 WCQ",
            "play_context_id": "wcq_2027",
            "sort_order": 3,
            "is_active": True,
            "season_label": "2027",
        }
    )

    # SYNCED 상태가 도착하기 전에는 아직 이전 목록을 유지한다.
    assert [str(m["id"]) for m in window._modes] == initial_ids

    window.set_sync_status(
        SyncStatus(SyncPhase.SYNCED, pending_count=0, failed_count=0)
    )

    updated_ids = [str(m["id"]) for m in window._modes]
    assert "wcq-2026" not in updated_ids
    assert "wcq-2027" in updated_ids

    window.close_profile_windows()
    games.close()
