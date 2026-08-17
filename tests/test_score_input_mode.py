"""점수 입력 방식(변동폭/직접 입력) 폼 테스트 (spec §6.2)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mdlogger.app_settings import ScoreInputMode
from mdlogger.models import GameMode, StandingKind
from mdlogger.ui.detail_form import DetailForm


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def _score_mode() -> GameMode:
    return GameMode(
        id="dc-cup-2026-08",
        standing_kind=StandingKind.EVENT_POINTS,
        display_name="DC컵",
        play_context_id="dc_cup_2026_08",
    )


def _rating_mode() -> GameMode:
    return GameMode(
        id="rating-2026-08",
        standing_kind=StandingKind.RATING,
        display_name="레이팅",
        play_context_id="rating_2026_08",
    )


def _fill_decks(form: DetailForm) -> None:
    form._my_deck.setEditText("융합 덱")
    form._deck.setEditText("융합 덱")


def test_delta_mode_computes_after_for_win(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form.set_score_base(1000)
    form.set_result("win")
    _fill_decks(form)
    form._score_delta_input.setText("345")
    values = form.values()
    assert values is not None
    assert values["event_points_before"] == 1000
    assert values["event_points_after"] == 1345


def test_delta_mode_computes_after_for_lose(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form.set_score_base(1000)
    form.set_result("lose")
    _fill_decks(form)
    form._score_delta_input.setText("345")
    values = form.values()
    assert values is not None
    assert values["event_points_after"] == 655


def test_delta_mode_allows_zero(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form.set_score_base(1000)
    form.set_result("win")
    _fill_decks(form)
    form._score_delta_input.setText("0")
    values = form.values()
    assert values is not None
    assert values["event_points_after"] == 1000


def test_delta_mode_requires_result(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form.set_score_base(1000)
    _fill_decks(form)
    form._score_delta_input.setText("345")
    assert form.values() is None


def test_direct_mode_reads_after_input(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DIRECT)
    form.set_score_base(1000)
    _fill_decks(form)
    form._score_after.setText("1345")
    values = form.values()
    assert values is not None
    assert values["event_points_before"] == 1000
    assert values["event_points_after"] == 1345


def test_direct_mode_before_label_readonly_and_after_empty(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DIRECT)
    form.set_score_base(1000)
    # 경기 전은 읽기 전용 레이블로 표시, 경기 후 입력창은 비어 있다.
    assert form._score_before_label.text() == "1000"
    assert form._score_after.text() == ""


def test_rating_delta_mode_computes_after(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_rating_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form.set_rating_before(1500)
    form.set_result("win")
    _fill_decks(form)
    form._rating_delta_input.setText("50")
    values = form.values()
    assert values is not None
    assert values["rating_before"] == 1500
    assert values["rating_after"] == 1550


def test_rating_direct_mode_reads_after_input(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_rating_mode())
    form.set_score_input_mode(ScoreInputMode.DIRECT)
    form.set_rating_before(1500)
    _fill_decks(form)
    form._rating_after.setText("1490")
    values = form.values()
    assert values is not None
    assert values["rating_before"] == 1500
    assert values["rating_after"] == 1490


def test_rating_first_game_before_is_editable(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_rating_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    # 첫 경기(직전 레이팅 없음): "경기 전 레이팅"은 편집 가능
    assert form._rating_before.isHidden() is False
    assert form._rating_before_label.isHidden() is True
    # 직전 레이팅이 있으면 읽기 전용
    form.set_rating_before(1500)
    assert form._rating_before.isHidden() is True
    assert form._rating_before_label.isHidden() is False


def test_rating_delta_mode_first_game_computes_after(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_rating_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form._rating_before.setText("1000")  # 첫 경기: 사용자가 직접 입력
    form.set_result("win")
    _fill_decks(form)
    form._rating_delta_input.setText("50")
    values = form.values()
    assert values is not None
    assert values["rating_before"] == 1000
    assert values["rating_after"] == 1050


def test_delta_mode_negative_after_shows_warning(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form.set_score_base(100)
    form.set_result("lose")
    _fill_decks(form)
    form._score_delta_input.setText("200")
    # after = 100 - 200 = -100 → 경고 테두리 표시, 저장은 음수 허용
    assert form._score_delta_input.property("warning") is True
    values = form.values()
    assert values is not None
    assert values["event_points_after"] == -100


def test_delta_mode_nonnegative_after_clears_warning(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form.set_score_base(100)
    form.set_result("lose")
    _fill_decks(form)
    form._score_delta_input.setText("50")
    assert form._score_delta_input.property("warning") is not True


def test_validation_error_messages(qapp) -> None:
    form = DetailForm(["융합 덱"])
    form.set_mode(_score_mode())
    form.set_score_input_mode(ScoreInputMode.DELTA)
    form.set_score_base(100)
    form.set_result("win")
    # 덱 미선택
    assert form.values() is None
    assert form.validation_error() == "내 덱 / 상대 덱을 후보에서 정확히 선택하세요"
    # 덱 선택, 변동폭 미입력
    _fill_decks(form)
    assert form.values() is None
    assert form.validation_error() == "점수 변동폭을 입력하세요"
