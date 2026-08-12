"""휴대용 아카이브 UI 배선 테스트 (P1-13 / 하드닝 H-3).

코어 writer/reader/검증/중복방지/outbox 는 ``tests/test_portable.py`` 가 검증한다.
여기서는 그 코어를 통계 창(내보내기 버튼)과 가져오기 대화상자에 배선한 부분을
offscreen 에서 확인한다:

- 통계 창에 "휴대용 아카이브 내보내기"/"가져오기" 버튼이 존재하고
  ``GameService.export_portable_archive`` / ``portable.import_portable_archive``
  로 이어지는 호출 경로가 연결되어 있는지.
- 잘못된 경로·손상 아카이브를 선택했을 때 ``PortableArchiveError`` 가 안내로
  처리되어 크래시하지 않는지.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

from mdlogger import portable
from mdlogger.game_service import GameService
from mdlogger.game_sync.coordinator import SyncCoordinator
from mdlogger.profiles import ProfileContext, ProfileManager
from mdlogger.ui.main_window import MainWindow
from mdlogger.ui.portable_import_dialog import PortableImportDialog
from mdlogger.ui.stats_window import StatsWindow

DECKS = ["융합 덱", "싱크로 덱"]


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


def _find_button(parent, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"버튼을 찾지 못함: {text!r}")


def _make_archive(tmp_path: Path, count: int = 2) -> Path:
    """테스트용 휴대용 아카이브 디렉터리를 만든다."""
    profiles = ProfileManager(tmp_path / "profiles")
    profile = profiles.guest()
    profiles.prepare_database(profile)
    games = GameService.open(profile.database_path)
    for i in range(count):
        games.insert_game(
            {
                "result": "win",
                "turn_order": "first",
                "my_deck": "융합 덱",
                "opp_deck": "싱크로 덱",
                "turns": 3,
                "end_reason": "regular",
                "score_after": 1200 + i,
                "note": "",
            }
        )
    archive = tmp_path / "out.mdlogger-export"
    games.export_portable_archive(archive)
    games.close()
    return archive


def _open_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MainWindow, GameService, ProfileManager, ProfileContext]:
    monkeypatch.setattr("mdlogger.ui.main_window.load_decks", lambda: list(DECKS))
    profiles = ProfileManager(tmp_path)
    profile = profiles.guest()
    profiles.prepare_database(profile)
    games = GameService.open(profile.database_path)
    window = MainWindow(games, DECKS, profile)
    return window, games, profiles, profile


def test_stats_window_has_portable_export_button(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """통계 창에 휴대용 아카이브 내보내기/가져오기 버튼이 존재한다."""
    window, games, _, _ = _open_window(tmp_path, monkeypatch)
    window.refresh_header()
    window.show()
    qapp.processEvents()

    stats = window._stats
    assert stats is None
    # 통계 창을 직접 열어 버튼 존재를 확인한다.
    stats_window = StatsWindow(games, DECKS, profile=window.profile)
    stats_window.show()
    qapp.processEvents()

    export_btn = _find_button(stats_window, "휴대용 아카이브 내보내기")
    import_btn = _find_button(stats_window, "휴대용 아카이브 가져오기")
    assert export_btn is not None
    assert import_btn is not None
    # 기존 CSV/XLSX 내보내기 버튼도 유지된다.
    assert _find_button(stats_window, "CSV 내보내기") is not None
    assert _find_button(stats_window, "XLSX 내보내기") is not None

    stats_window.close()
    window.close_profile_windows()
    games.close()


def test_export_portable_archive_calls_game_service(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_export_portable_archive`가 대상 경로를 조합해 GameService 호출로 연결된다."""
    window, games, _, _ = _open_window(tmp_path, monkeypatch)
    window.refresh_header()
    stats = StatsWindow(games, DECKS, profile=window.profile)

    # 부모 폴더 선택 + 폴더 이름 입력을 고정 값으로 패치한다.
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: str(tmp_path)),
    )
    name_value = "my.mdlogger-export"
    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getText",
        staticmethod(lambda *a, **k: (name_value, True)),
    )
    # 성공 후 안내하는 모달 QMessageBox.information이 오프스크린에서 차단되지 않도록 패치한다.
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *a, **k: None),
    )

    captured: list[Path] = []

    def _fake_export(path, *, profile_kind=None):
        captured.append(Path(path))
        return Path(path)

    monkeypatch.setattr(games, "export_portable_archive", _fake_export)

    stats._export_portable_archive()
    assert captured == [tmp_path / name_value]

    stats.close()
    window.close_profile_windows()
    games.close()


def test_export_portable_archive_error_is_handled(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """내보내기 중 오류(PortableArchiveError 포함)가 안내로 처리되고 전파되지 않는다."""
    window, games, _, _ = _open_window(tmp_path, monkeypatch)
    window.refresh_header()
    stats = StatsWindow(games, DECKS, profile=window.profile)

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: str(tmp_path)),
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("dup.mdlogger-export", True)),
    )
    errors: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: errors.append(str(a[2]) if len(a) > 2 else "")),
    )

    def _boom(path, *, profile_kind=None):
        raise portable.PortableArchiveError(f"Archive already exists: {path}")

    monkeypatch.setattr(games, "export_portable_archive", _boom)

    stats._export_portable_archive()  # 예외가 전파되면 안 됨
    assert any("Archive already exists" in e for e in errors)

    stats.close()
    window.close_profile_windows()
    games.close()


def test_import_portable_calls_portable_import(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_import_portable`이 PortableImportDialog 경유로 portable.import 호출로 연결된다."""
    window, games, _, profile = _open_window(tmp_path, monkeypatch)
    window.refresh_header()
    stats = StatsWindow(games, DECKS, profile=profile)

    archive = _make_archive(tmp_path, count=2)
    called: list[tuple[Path, Path]] = []

    def _fake_import(archive_path, target_path):
        called.append((Path(archive_path), Path(target_path)))
        return portable.PortableImportResult(
            Path(archive_path),
            Path(target_path),
            archive_id="id",
            source_profile_kind=portable.ProfileKind.GUEST,
            imported_count=2,
            skipped_count=0,
            failed_count=0,
            already_imported=False,
        )

    monkeypatch.setattr(
        "mdlogger.ui.portable_import_dialog.import_portable_archive", _fake_import
    )
    # 성공 후 안내하는 모달 QMessageBox.information이 오프스크린에서 차단되지 않도록 패치한다.
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *a, **k: None),
    )

    dialog = PortableImportDialog(profile.database_path, stats)
    dialog._path_edit.setText(str(archive))
    dialog._import()

    assert called == [(archive, profile.database_path)]
    assert dialog.imported_count == 2
    assert dialog.already_imported is False

    stats.close()
    window.close_profile_windows()
    games.close()


def test_import_portable_wires_dialog_and_refreshes(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_import_portable`이 대상 DB 경로로 대화상자를 구성하고 성공 시 갱신한다."""
    from PySide6.QtWidgets import QDialog

    window, games, _, profile = _open_window(tmp_path, monkeypatch)
    window.refresh_header()
    stats = StatsWindow(games, DECKS, profile=profile)

    constructed: list[Path] = []

    class _FakeDialog:
        def __init__(self, target, parent):
            constructed.append(Path(target))
            self.imported_count = 2
            self.already_imported = False

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr("mdlogger.ui.stats_window.PortableImportDialog", _FakeDialog)
    refreshed: list[bool] = []
    monkeypatch.setattr(stats, "refresh", lambda: refreshed.append(True))
    imported_signals: list[bool] = []
    stats.records_imported.connect(lambda: imported_signals.append(True))

    stats._import_portable()

    assert constructed == [profile.database_path]
    assert refreshed == [True]
    assert imported_signals == [True]

    stats.close()
    window.close_profile_windows()
    games.close()


def test_main_window_wires_records_imported_to_request_sync(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """메인 창이 `records_imported`를 `request_sync`에 연결해 즉시 동기화를 요청한다."""
    window, games, _, _ = _open_window(tmp_path, monkeypatch)
    window.refresh_header()
    # 실제 통계 창 경로(open_stats)를 통해 생성해 연결이 맺어졌는지 확인한다.
    if window._stats is None:
        window.open_stats()
    stats = window._stats
    assert stats is not None

    class _FakeSync:
        def __init__(self) -> None:
            self.calls = 0

        def request_sync(self, *, retry_failed: bool = False) -> None:
            self.calls += 1

    fake_sync = _FakeSync()
    window._sync = cast(SyncCoordinator, fake_sync)

    stats.records_imported.emit()
    assert fake_sync.calls == 1

    stats.close()
    window.close_profile_windows()
    games.close()


def test_import_portable_error_is_handled_without_crash(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """손상·변조 아카이브 선택 시 PortableArchiveError가 안내로 처리되고 크래시하지 않는다."""
    window, games, _, profile = _open_window(tmp_path, monkeypatch)
    window.refresh_header()
    stats = StatsWindow(games, DECKS, profile=profile)

    bad_archive = tmp_path / "bad.mdlogger-export"
    bad_archive.mkdir()
    (bad_archive / portable.RECORDS_FILENAME).write_text(
        "{not-json}\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: None),
    )

    dialog = PortableImportDialog(profile.database_path, stats)
    dialog._path_edit.setText(str(bad_archive))
    dialog._import()  # 예외가 전파되면 안 됨
    assert dialog.result() != 1  # accept 되지 않음(대화상자 유지)

    stats.close()
    window.close_profile_windows()
    games.close()
