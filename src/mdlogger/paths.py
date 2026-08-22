"""OS 표준 사용자 데이터 경로와 애플리케이션 파일 경로를 해석한다.

기본 데이터 위치:
- Windows: ``%LOCALAPPDATA%/MDLogger``
- Linux: ``$XDG_DATA_HOME/mdlogger`` 또는 ``~/.local/share/mdlogger``
- macOS: ``~/Library/Application Support/MDLogger``

환경변수:
- ``MDLOGGER_DATA_DIR`` : 모든 사용자 데이터의 위치를 직접 지정
- ``MDLOGGER_DECKS_URL``: decks.json 원본(Gist raw) URL. 비면 동기화 끔
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path


def _base_dir() -> Path:
    """기존 포터블 데이터 탐색과 프로젝트 자원에 사용할 기준 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _default_data_dir(platform: str, environ: Mapping[str, str], home: Path) -> Path:
    if platform == "win32":
        root = environ.get("LOCALAPPDATA")
        return (Path(root) if root else home / "AppData" / "Local") / "MDLogger"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "MDLogger"

    root = environ.get("XDG_DATA_HOME")
    return (Path(root) if root else home / ".local" / "share") / "mdlogger"


def _resolve_data_dir() -> Path:
    override = os.environ.get("MDLOGGER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return _default_data_dir(sys.platform, os.environ, Path.home())


BASE_DIR = _base_dir()
DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "games.db"
DECKS_PATH = DATA_DIR / "decks.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

# 덱 목록 "원본"을 두는 온라인 위치(GitHub Gist 의 latest raw URL).
# 비어 있으면 동기화를 끈다. 환경변수 ``MDLOGGER_DECKS_URL`` 로 덮어쓸 수 있다.
# 주의: 커밋 SHA 가 박힌 raw URL 은 고정 리비전이라 갱신이 반영되지 않으므로,
#       SHA 없는 "latest raw" URL(.../raw/decks.json)을 써야 한다.
DECKS_REMOTE_URL = os.environ.get(
    "MDLOGGER_DECKS_URL",
    "https://gist.githubusercontent.com/dusten45/f7c427c57a0842f05cf8b2e3aeb011c3/raw/decks.json",
).strip()

DECKS_SYNC_STATE_PATH = DATA_DIR / "decks_sync.json"

# 웹 canonical 공개 법률 문서 URL. 환경변수로 재정의 가능.
PRIVACY_POLICY_URL = os.environ.get(
    "MDLOGGER_PRIVACY_URL",
    "https://mdlogger-web.dalimi4511-615.workers.dev/privacy",
).strip()
TERMS_OF_SERVICE_URL = os.environ.get(
    "MDLOGGER_TERMS_URL",
    "https://mdlogger-web.dalimi4511-615.workers.dev/terms",
).strip()

_PRIVATE_DIR_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


def secure_data_file(path: Path) -> None:
    """POSIX에서 사용자 데이터 파일을 현재 사용자만 읽고 쓰게 한다."""
    if os.name != "nt" and path.exists():
        path.chmod(_PRIVATE_FILE_MODE)


def secure_sidecars(db_path: Path) -> None:
    """POSIX에서 WAL 모드 DB의 사이드카 파일에도 0600을 적용한다.

    WAL 모드에서는 최신 기록이 ``-wal`` 사이드카에 먼저 쓰이므로 메인 DB만
    0600으로 두면 사이드카가 기본 권한(umask)으로 남아 다른 사용자에게 노출될
    수 있다. ``-wal``/``-shm``/``-journal``을 메인 DB와 같은 소유자 전용 권한으로
    맞춘다.
    """
    if os.name == "nt":
        return
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = db_path.with_name(f"{db_path.name}{suffix}")
        if sidecar.exists():
            sidecar.chmod(_PRIVATE_FILE_MODE)


def copy_database_via_backup(source: Path, destination: Path) -> None:
    """SQLite DB를 WAL 포함 일관 스냅숏으로 안전하게 복사한다.

    WAL 모드 DB를 체크포인트 없이 ``shutil.copy2``로 복사하면 ``-wal``에 남은
    페이지가 복사본에서 유실되어 전체 데이터가 사라질 수 있다(P0-5).
    ``sqlite3.Connection.backup()``은 원본을 읽기 잠금으로 잠그고 메인 DB+WAL을
    포함한 일관 스냅숏을 임시 파일에 만든 뒤 원자적으로 ``destination``으로 옮긴다.
    """
    temporary_path = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.copy.tmp"
    )
    source_conn = sqlite3.connect(source)
    try:
        try:
            backup_conn = sqlite3.connect(temporary_path)
            try:
                source_conn.backup(backup_conn)
            finally:
                backup_conn.close()
            if os.name != "nt":
                temporary_path.chmod(_PRIVATE_FILE_MODE)
            os.replace(temporary_path, destination)
        except sqlite3.DatabaseError:
            # 유효한 SQLite DB가 아닌(빈/손상) legacy 파일은 바이트 단위로 복사해
            # 기존 동작을 유지한다. 유효한 DB의 WAL 유실 문제는 위 backup 경로가 해결한다.
            temporary_path.unlink(missing_ok=True)
            shutil.copy2(source, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    finally:
        source_conn.close()


def _secure_data_permissions() -> None:
    """기존 데이터에도 현재 사용자 전용 권한을 적용한다."""
    if os.name == "nt":
        return
    DATA_DIR.chmod(_PRIVATE_DIR_MODE)
    for path in (DB_PATH, DECKS_PATH, DECKS_SYNC_STATE_PATH, SETTINGS_PATH):
        secure_data_file(path)
    secure_sidecars(DB_PATH)


def _migrate_legacy_data() -> None:
    """기존 실행 파일/프로젝트 인접 데이터를 새 경로로 한 번 복사한다."""
    marker = DATA_DIR / ".legacy-data-migrated"
    if marker.exists():
        return

    legacy_data_dir = BASE_DIR / "data"
    legacy_files = {
        legacy_data_dir / "games.db": DB_PATH,
        BASE_DIR / "decks.json": DECKS_PATH,
        legacy_data_dir / "decks_sync.json": DECKS_SYNC_STATE_PATH,
    }
    for source, destination in legacy_files.items():
        if source != destination and source.is_file() and not destination.exists():
            if destination == DB_PATH:
                # WAL 모드에서 종료된 legacy DB의 -wal을 체크포인트 없이는
                # shutil.copy2로 살릴 수 없다. 안전한 스냅숏 복사를 사용한다(P0-5).
                copy_database_via_backup(source, destination)
            else:
                shutil.copy2(source, destination)
    marker.touch(mode=_PRIVATE_FILE_MODE)


def ensure_data_dir() -> None:
    """사용자 데이터 디렉터리를 만들고 기존 데이터를 보존해 이전한다."""
    DATA_DIR.mkdir(mode=_PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    if os.name != "nt":
        DATA_DIR.chmod(_PRIVATE_DIR_MODE)
    _migrate_legacy_data()
    _secure_data_permissions()
