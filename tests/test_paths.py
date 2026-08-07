"""OS별 사용자 데이터 경로 및 기존 데이터 마이그레이션 테스트."""

import os
import stat
from pathlib import Path

import pytest

from mdlogger import paths


def test_mdlogger_data_dir_override_is_preserved(monkeypatch, tmp_path):
    override = tmp_path / "custom-data"
    monkeypatch.setenv("MDLOGGER_DATA_DIR", str(override))

    assert paths._resolve_data_dir() == override.resolve()


def test_linux_uses_xdg_data_home():
    result = paths._default_data_dir(
        "linux", {"XDG_DATA_HOME": "/tmp/xdg-data"}, Path("/home/user")
    )
    assert result == Path("/tmp/xdg-data/mdlogger")


def test_linux_falls_back_to_local_share():
    result = paths._default_data_dir("linux", {}, Path("/home/user"))
    assert result == Path("/home/user/.local/share/mdlogger")


def test_windows_uses_local_app_data():
    result = paths._default_data_dir(
        "win32", {"LOCALAPPDATA": "C:/Users/user/AppData/Local"}, Path("C:/Users/user")
    )
    assert result == Path("C:/Users/user/AppData/Local/MDLogger")


def test_macos_uses_application_support():
    result = paths._default_data_dir("darwin", {}, Path("/Users/user"))
    assert result == Path("/Users/user/Library/Application Support/MDLogger")


def test_migrates_legacy_files_without_overwriting(monkeypatch, tmp_path):
    base_dir = tmp_path / "portable"
    legacy_data_dir = base_dir / "data"
    new_data_dir = tmp_path / "standard"
    legacy_data_dir.mkdir(parents=True)
    (legacy_data_dir / "games.db").write_text("legacy-db")
    (legacy_data_dir / "decks_sync.json").write_text("legacy-state")
    (base_dir / "decks.json").write_text("legacy-decks")
    new_data_dir.mkdir()
    (new_data_dir / "decks.json").write_text("current-decks")

    monkeypatch.setattr(paths, "BASE_DIR", base_dir)
    monkeypatch.setattr(paths, "DATA_DIR", new_data_dir)
    monkeypatch.setattr(paths, "DB_PATH", new_data_dir / "games.db")
    monkeypatch.setattr(paths, "DECKS_PATH", new_data_dir / "decks.json")
    monkeypatch.setattr(
        paths, "DECKS_SYNC_STATE_PATH", new_data_dir / "decks_sync.json"
    )

    paths.ensure_data_dir()

    assert (new_data_dir / "games.db").read_text() == "legacy-db"
    assert (new_data_dir / "decks_sync.json").read_text() == "legacy-state"
    assert (new_data_dir / "decks.json").read_text() == "current-decks"
    assert (new_data_dir / ".legacy-data-migrated").exists()

    (new_data_dir / "games.db").unlink()
    (legacy_data_dir / "games.db").write_text("changed-legacy-db")
    paths.ensure_data_dir()
    assert not (new_data_dir / "games.db").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX 파일 권한 테스트")
def test_data_files_are_owner_only(monkeypatch, tmp_path):
    data_dir = tmp_path / "private-data"
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path / "no-legacy")
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(paths, "DB_PATH", data_dir / "games.db")
    monkeypatch.setattr(paths, "DECKS_PATH", data_dir / "decks.json")
    monkeypatch.setattr(paths, "DECKS_SYNC_STATE_PATH", data_dir / "decks_sync.json")

    paths.ensure_data_dir()
    paths.DB_PATH.write_text("db")
    paths.DECKS_PATH.write_text("[]")
    paths.DECKS_SYNC_STATE_PATH.write_text("{}")
    paths.ensure_data_dir()

    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    for path in (paths.DB_PATH, paths.DECKS_PATH, paths.DECKS_SYNC_STATE_PATH):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
