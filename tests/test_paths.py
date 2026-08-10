"""OS별 사용자 데이터 경로 및 기존 데이터 마이그레이션 테스트."""

import os
import shutil
import sqlite3
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


def test_copy_database_via_backup_preserves_wal_rows_where_byte_copy_loses_them(
    tmp_path: Path,
):
    """P0-5: WAL 체크포인트되지 않은 DB는 바이트 복사로 유실되지만 backup은 보존한다."""
    source = tmp_path / "legacy-games.db"
    conn = sqlite3.connect(source)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
    conn.execute("INSERT INTO games (note) VALUES ('WAL 유지 행')")
    conn.commit()

    # 쓰는 연결이 닫힐 때 최종 체크포인트가 일어나지 않도록 읽기 트랜잭션을 유지한다.
    reader = sqlite3.connect(source)
    reader.execute("BEGIN")
    reader.execute("SELECT name FROM sqlite_master LIMIT 1")
    conn.close()
    assert (tmp_path / "legacy-games.db-wal").exists()

    # 버그 재현: 메인 .db만 복사하면 WAL에 있던 스키마/행이 유실된다.
    stale_copy = tmp_path / "stale-games.db"
    shutil.copy2(source, stale_copy)
    stale = sqlite3.connect(stale_copy)
    try:
        stale_table = stale.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='games'"
        ).fetchone()[0]
    finally:
        stale.close()
    assert stale_table == 0

    # 수정: backup 복사는 WAL 내용을 포함한 일관 스냅숏을 만든다.
    good_copy = tmp_path / "good-games.db"
    paths.copy_database_via_backup(source, good_copy)
    good = sqlite3.connect(good_copy)
    try:
        rows = good.execute("SELECT note FROM games").fetchall()
    finally:
        good.close()
    reader.rollback()
    reader.close()
    assert rows == [("WAL 유지 행",)]


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX 파일 권한 테스트")
def test_secure_sidecars_applies_owner_only_permissions(tmp_path: Path):
    """P2-4: WAL/-shm/-journal 사이드카에 0600을 적용해 최신 기록 노출을 막는다."""
    db_path = tmp_path / "games.db"
    db_path.write_text("db")
    sidecar_names = ("-wal", "-shm", "-journal")
    for suffix in sidecar_names:
        (tmp_path / f"games.db{suffix}").write_text("sidecar")

    paths.secure_sidecars(db_path)

    for suffix in sidecar_names:
        sidecar = tmp_path / f"games.db{suffix}"
        assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600

    # 없는 사이드카는 무해하게 건너뛴다.
    paths.secure_sidecars(tmp_path / "missing.db")


@pytest.mark.skipif(os.name == "nt", reason="POSIX 파일 권한 테스트")
def test_ensure_data_dir_secures_existing_sidecars(monkeypatch, tmp_path):
    """기존 데이터에도 사이드카 권한이 적용된다."""
    data_dir = tmp_path / "private-data"
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path / "no-legacy")
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(paths, "DB_PATH", data_dir / "games.db")
    monkeypatch.setattr(paths, "DECKS_PATH", data_dir / "decks.json")
    monkeypatch.setattr(paths, "DECKS_SYNC_STATE_PATH", data_dir / "decks_sync.json")

    paths.ensure_data_dir()
    paths.DB_PATH.write_text("db")
    (data_dir / "games.db-wal").write_text("wal")
    paths.ensure_data_dir()

    assert stat.S_IMODE((data_dir / "games.db-wal").stat().st_mode) == 0o600
