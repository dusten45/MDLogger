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
    source = sqlite3.connect(legacy_data_dir / "games.db")
    source.execute("CREATE TABLE marker (value TEXT)")
    source.execute("INSERT INTO marker VALUES ('legacy-db')")
    source.commit()
    source.close()
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

    copied = sqlite3.connect(new_data_dir / "games.db")
    assert copied.execute("SELECT value FROM marker").fetchone()[0] == "legacy-db"
    copied.close()
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


def test_legal_urls_defined_and_overrideable(monkeypatch):
    assert (
        paths.PRIVACY_POLICY_URL
        == "https://mdlogger-web.dalimi4511-615.workers.dev/privacy"
    )
    assert (
        paths.TERMS_OF_SERVICE_URL
        == "https://mdlogger-web.dalimi4511-615.workers.dev/terms"
    )


def test_backup_full_never_falls_back_to_stale_main_file(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.db", tmp_path / "copy.db"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE games (note TEXT)")
    connection.execute("INSERT INTO games VALUES ('체크포인트 완료')")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.execute("INSERT INTO games VALUES (?)", ("기록" * 65536,))
    connection.commit()
    real_connect = sqlite3.connect

    def limited_connect(path, *args, **kwargs):
        opened = real_connect(path, *args, **kwargs)
        if str(path).endswith(".copy.tmp"):
            opened.execute("PRAGMA max_page_count=2")
        return opened

    monkeypatch.setattr(paths.sqlite3, "connect", limited_connect)
    try:
        with pytest.raises(sqlite3.OperationalError) as error:
            paths.copy_database_via_backup(source, destination)
        assert error.value.sqlite_errorcode == sqlite3.SQLITE_FULL
        assert not destination.exists()
        assert connection.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 2
        assert not list(tmp_path.glob(".*.copy.tmp*"))
    finally:
        connection.close()


def test_backup_rejects_corrupt_or_missing_source_without_publishing(tmp_path):
    source, destination = tmp_path / "broken.db", tmp_path / "copy.db"
    with pytest.raises(sqlite3.Error):
        paths.copy_database_via_backup(source, destination)
    assert not source.exists()
    source.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.Error):
        paths.copy_database_via_backup(source, destination)
    assert source.read_bytes() == b"not sqlite"
    assert not destination.exists()
    assert not list(tmp_path.glob(".*.copy.tmp*"))


def test_backup_does_not_overwrite_racing_destination(tmp_path, monkeypatch):
    source = sqlite3.connect(":memory:")
    source.execute("CREATE TABLE marker (value TEXT)")
    destination = tmp_path / "copy.db"
    real_link = paths.os.link

    def publish_after_other_writer(temporary, target):
        target.write_bytes(b"other data")
        real_link(temporary, target)

    monkeypatch.setattr(paths.os, "link", publish_after_other_writer)
    with pytest.raises(FileExistsError):
        paths.copy_database_via_backup(source, destination)
    assert destination.read_bytes() == b"other data"
    assert source.execute("SELECT COUNT(*) FROM marker").fetchone()[0] == 0
    source.close()


def test_backup_contention_is_bounded(tmp_path):
    source, destination = tmp_path / "locked.db", tmp_path / "copy.db"
    writer = sqlite3.connect(source)
    writer.execute("CREATE TABLE marker (value TEXT)")
    writer.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="제한 시간"):
            paths.copy_database_via_backup(source, destination, timeout=0.01)
        assert not destination.exists()
        assert not list(tmp_path.glob(".*.copy.tmp*"))
    finally:
        writer.rollback()
        writer.close()


def test_backup_rejects_uncommitted_owned_connection_without_rolling_it_back(tmp_path):
    source = sqlite3.connect(":memory:")
    source.execute("CREATE TABLE marker (value TEXT)")
    source.execute("INSERT INTO marker VALUES ('미커밋')")
    with pytest.raises(sqlite3.OperationalError, match="트랜잭션"):
        paths.copy_database_via_backup(source, tmp_path / "copy.db")
    assert source.in_transaction
    assert source.execute("SELECT COUNT(*) FROM marker").fetchone()[0] == 1
    source.close()


def test_reset_is_recovered_before_legacy_migration(tmp_path, monkeypatch):
    from mdlogger.profiles import ProfileManager

    class ProcessStopped(BaseException):
        pass

    data_dir, base_dir = tmp_path / "current", tmp_path / "portable"
    manager = ProfileManager(data_dir)
    guest_id = manager.guest().local_profile_id
    (data_dir / "games.db").write_bytes(b"current data")
    legacy = base_dir / "data"
    legacy.mkdir(parents=True)
    (legacy / "games.db").write_bytes(b"stale data")

    def stop_before_commit(directory):
        raise ProcessStopped

    monkeypatch.setattr(manager, "_prepare_reset_state", stop_before_commit)
    with pytest.raises(ProcessStopped):
        manager.reset_local_data()
    assert not (data_dir / "games.db").exists()
    for name, value in {
        "DATA_DIR": data_dir,
        "BASE_DIR": base_dir,
        "DB_PATH": data_dir / "games.db",
        "SETTINGS_PATH": data_dir / "settings.json",
        "DECKS_PATH": data_dir / "decks.json",
        "DECKS_SYNC_STATE_PATH": data_dir / "decks_sync.json",
    }.items():
        monkeypatch.setattr(paths, name, value)
    paths.ensure_data_dir()
    assert (data_dir / "games.db").read_bytes() == b"current data"
    assert ProfileManager(data_dir).guest().local_profile_id == guest_id
    assert not list(data_dir.glob(".mdlogger-reset-*"))


def test_backup_restarts_safely_when_another_connection_writes_and_checkpoints(
    tmp_path,
):
    source, destination = tmp_path / "source.db", tmp_path / "copy.db"
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE games (note TEXT)")
    writer.executemany("INSERT INTO games VALUES (?)", [("기록" * 4096,)] * 100)
    writer.commit()
    wrote_during_backup = False

    class ConcurrentConnection(sqlite3.Connection):
        def backup(self, target, *, progress=None, **kwargs):
            def concurrent_progress(status, remaining, total):
                nonlocal wrote_during_backup
                if remaining and not wrote_during_backup:
                    wrote_during_backup = True
                    writer.execute("INSERT INTO games VALUES ('복사 도중 커밋')")
                    writer.commit()
                    writer.execute("PRAGMA wal_checkpoint(PASSIVE)")
                if progress is not None:
                    progress(status, remaining, total)

            return super().backup(target, progress=concurrent_progress, **kwargs)

    reader = sqlite3.connect(source, factory=ConcurrentConnection)
    try:
        paths.copy_database_via_backup(reader, destination)
        copied = sqlite3.connect(destination)
        try:
            assert wrote_during_backup
            assert copied.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 101
            assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            copied.close()
    finally:
        reader.close()
        writer.close()
