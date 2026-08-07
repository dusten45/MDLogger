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
import sys
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

# 덱 목록 "원본"을 두는 온라인 위치(GitHub Gist 의 latest raw URL).
# 비어 있으면 동기화를 끈다. 환경변수 ``MDLOGGER_DECKS_URL`` 로 덮어쓸 수 있다.
# 주의: 커밋 SHA 가 박힌 raw URL 은 고정 리비전이라 갱신이 반영되지 않으므로,
#       SHA 없는 "latest raw" URL(.../raw/decks.json)을 써야 한다.
DECKS_REMOTE_URL = os.environ.get(
    "MDLOGGER_DECKS_URL",
    "https://gist.githubusercontent.com/dusten45/f7c427c57a0842f05cf8b2e3aeb011c3/raw/decks.json",
).strip()

DECKS_SYNC_STATE_PATH = DATA_DIR / "decks_sync.json"

_PRIVATE_DIR_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


def secure_data_file(path: Path) -> None:
    """POSIX에서 사용자 데이터 파일을 현재 사용자만 읽고 쓰게 한다."""
    if os.name != "nt" and path.exists():
        path.chmod(_PRIVATE_FILE_MODE)


def _secure_data_permissions() -> None:
    """기존 데이터에도 현재 사용자 전용 권한을 적용한다."""
    if os.name == "nt":
        return
    DATA_DIR.chmod(_PRIVATE_DIR_MODE)
    for path in (DB_PATH, DECKS_PATH, DECKS_SYNC_STATE_PATH):
        secure_data_file(path)


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
            shutil.copy2(source, destination)
    marker.touch(mode=_PRIVATE_FILE_MODE)


def ensure_data_dir() -> None:
    """사용자 데이터 디렉터리를 만들고 기존 데이터를 보존해 이전한다."""
    DATA_DIR.mkdir(mode=_PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    if os.name != "nt":
        DATA_DIR.chmod(_PRIVATE_DIR_MODE)
    _migrate_legacy_data()
    _secure_data_permissions()
