"""전역 설정 적용 테스트 (계획 2, spec §5.3~§5.4, §8.4)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from mdlogger.app_settings import AppSettings, ReduceMotion, effective_reduce_motion
from mdlogger.game_service import GameService
from mdlogger.profiles import ProfileManager
from mdlogger.ui import result_view
from mdlogger.ui.detail_form import DetailForm
from mdlogger.ui.stats_window import StatsWindow


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


# --- effective_reduce_motion (저사양 모드 → 애니메이션 강제 off, 개별값 보존) ---


def test_effective_reduce_motion_off_by_default() -> None:
    assert effective_reduce_motion(AppSettings()) is False


def test_effective_reduce_motion_on_when_explicit() -> None:
    assert effective_reduce_motion(AppSettings(reduce_motion=ReduceMotion.ON)) is True


def test_low_spec_forces_reduce_motion_but_preserves_individual_value() -> None:
    settings = AppSettings(reduce_motion=ReduceMotion.OFF, low_spec_mode=True)
    assert effective_reduce_motion(settings) is True
    # 개별값은 보존되어 저사양 모드를 끄면 복원된다.
    assert settings.reduce_motion is ReduceMotion.OFF


# --- 메모 입력 숨김 (P8) ---


def test_detail_form_hides_memo_when_disabled(qapp) -> None:
    form = DetailForm(["융합 덱"])
    assert form._note_frame.isHidden() is False
    form.set_memo_enabled(False)
    assert form._note_frame.isHidden() is True
    form.set_memo_enabled(True)
    assert form._note_frame.isHidden() is False


def test_detail_form_records_empty_note_when_disabled(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_memo_enabled(False)
    form._my_deck.setEditText("융합 덱")
    form._deck.setEditText("융합 덱")
    form._note.setText("숨겨진 메모")
    values = form.values()
    assert values is not None
    assert values["note"] == ""


# --- 기록 표 메모 열 숨김 (P8) ---


def test_stats_window_hides_memo_column_when_disabled(qapp, tmp_path) -> None:
    profiles = ProfileManager(tmp_path)
    profile = profiles.guest()
    profiles.prepare_database(profile)
    games = GameService.open(profile.database_path)
    try:
        stats = StatsWindow(games, ["융합 덱"])
        assert stats._rtable.isColumnHidden(10) is False
        stats.set_memo_enabled(False)
        assert stats._rtable.isColumnHidden(10) is True
        stats.set_memo_enabled(True)
        assert stats._rtable.isColumnHidden(10) is False
    finally:
        games.close()


# --- 승/패 버튼 hover 애니메이션 비활성화 (저사양/애니메이션 감소) ---


def test_result_motion_flag_toggles(qapp) -> None:
    result_view.set_result_motion_enabled(False)
    assert result_view._motion_enabled is False
    result_view.set_result_motion_enabled(True)
    assert result_view._motion_enabled is True


def test_result_button_applies_scale_immediately_when_motion_disabled(qapp) -> None:
    result_view.set_result_motion_enabled(False)
    buttons = result_view._RecordButton()
    btn = buttons._button
    btn.set_base_size(QSize(100, 75))
    btn._animate(1.05)
    assert btn.growScale == pytest.approx(1.05)
    result_view.set_result_motion_enabled(True)
