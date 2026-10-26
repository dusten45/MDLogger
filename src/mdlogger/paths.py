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
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from .local_reset import data_root_lock, recover_pending_resets, sync_directory


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


def project_license_path() -> Path | None:
    """현재 배포 형식에서 사용자가 열 수 있는 프로젝트 라이선스(GPL-3.0) 파일을 찾는다."""

    candidates = [
        BASE_DIR / "LICENSE",
        Path("/app/share/licenses/mdlogger/LICENSE"),
    ]
    return next((path for path in candidates if path.is_file()), None)


def third_party_notices_path() -> Path | None:
    """현재 배포 형식에서 사용자가 열 수 있는 제3자 고지 파일을 찾는다."""

    candidates = [
        BASE_DIR / "THIRD_PARTY_NOTICES.txt",
        Path("/app/share/doc/mdlogger/THIRD_PARTY_NOTICES.txt"),
    ]
    return next((path for path in candidates if path.is_file()), None)


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


def copy_database_via_backup(
    source: Path | sqlite3.Connection,
    destination: Path,
    *,
    timeout: float = 5.0,
) -> None:
    """SQLite DB를 WAL 포함 일관 스냅숏으로 안전하게 복사한다.

    WAL 모드 DB를 체크포인트 없이 ``shutil.copy2``로 복사하면 ``-wal``에 남은
    페이지가 복사본에서 유실되어 전체 데이터가 사라질 수 있다(P0-5).
    같은 파일시스템의 비공개 임시 DB를 검증한 뒤 새 경로에 게시한다. 기존 대상은
    덮어쓰지 않으며 운영 오류를 원시 파일 복사로 숨기지 않는다. 전달한 연결은
    호출자 소유이고, 경로로 연 읽기 전용 연결은 이 함수가 닫는다.
    """
    temporary_path = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.copy.tmp"
    )
    if timeout <= 0:
        raise ValueError("백업 제한 시간은 양수여야 합니다.")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    owns_connection = not isinstance(source, sqlite3.Connection)
    source_conn = (
        sqlite3.connect(
            f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=timeout
        )
        if isinstance(source, Path)
        else source
    )
    deadline = time.monotonic() + timeout

    def progress(status: int, remaining: int, total: int) -> None:
        if status != sqlite3.SQLITE_DONE and time.monotonic() >= deadline:
            raise sqlite3.OperationalError("SQLite 스냅숏의 제한 시간을 초과했습니다.")

    try:
        if source_conn.in_transaction:
            raise sqlite3.OperationalError(
                "진행 중인 트랜잭션의 연결은 백업할 수 없습니다."
            )
        try:
            with temporary_path.open("xb"):
                secure_data_file(temporary_path)
            backup_conn = sqlite3.connect(temporary_path)
            try:
                source_conn.backup(
                    backup_conn, pages=128, progress=progress, sleep=0.05
                )
                if backup_conn.execute("PRAGMA integrity_check").fetchall() != [
                    ("ok",)
                ]:
                    raise sqlite3.DatabaseError(
                        "SQLite 스냅숏의 무결성 검증에 실패했습니다."
                    )
                backup_conn.execute("PRAGMA journal_mode=DELETE")
            finally:
                backup_conn.close()
            with temporary_path.open("r+b") as file:
                os.fsync(file.fileno())
            # 하드 링크 게시로 동시에 만들어진 목적지도 덮어쓰지 않는다.
            os.link(temporary_path, destination)
            sync_directory(destination.parent)
        finally:
            temporary_path.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm", "-journal"):
                temporary_path.with_name(temporary_path.name + suffix).unlink(
                    missing_ok=True
                )
    finally:
        if owns_connection:
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
    with data_root_lock(DATA_DIR):
        DATA_DIR.mkdir(mode=_PRIVATE_DIR_MODE, parents=True, exist_ok=True)
        if os.name != "nt":
            DATA_DIR.chmod(_PRIVATE_DIR_MODE)
        recover_pending_resets(DATA_DIR)
        _migrate_legacy_data()
        _secure_data_permissions()
