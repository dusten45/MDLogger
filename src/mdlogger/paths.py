"""파일 경로 해석: 기준 폴더, 데이터 디렉터리, DB, decks.json.

데이터는 '기준 폴더(BASE_DIR)' 바로 아래에 둔다.
- 개발 모드(uv run)         : 프로젝트 루트
- 패키징된 실행 파일(frozen): .exe 가 있는 폴더

BASE_DIR 아래:
- decks.json            : 덱 후보 목록(온라인 동기화 + 사용자 편집)
- data/games.db         : SQLite 단일 파일
- data/decks_sync.json  : 덱 동기화 상태(ETag 등)

환경변수:
- ``MDLOGGER_DATA_DIR`` : DB(데이터) 디렉터리를 따로 지정
- ``MDLOGGER_DECKS_URL``: decks.json 원본(Gist raw) URL. 비면 동기화 끔
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller 등으로 묶인 실행 파일: .exe 가 있는 폴더(쓰기 가능·영속)
        return Path(sys.executable).resolve().parent
    # 개발 모드: src/mdlogger/paths.py -> parents[2] == 프로젝트 루트
    return Path(__file__).resolve().parents[2]


BASE_DIR = _base_dir()


def _resolve_data_dir() -> Path:
    override = os.environ.get("MDLOGGER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return BASE_DIR / "data"


DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "games.db"
DECKS_PATH = BASE_DIR / "decks.json"

# 덱 목록 "원본"을 두는 온라인 위치(GitHub Gist 의 latest raw URL).
# 비어 있으면 동기화를 끈다. 환경변수 ``MDLOGGER_DECKS_URL`` 로 덮어쓸 수 있다.
# 주의: 커밋 SHA 가 박힌 raw URL 은 고정 리비전이라 갱신이 반영되지 않으므로,
#       SHA 없는 "latest raw" URL(.../raw/decks.json)을 써야 한다.
DECKS_REMOTE_URL = os.environ.get(
    "MDLOGGER_DECKS_URL",
    "https://gist.githubusercontent.com/dusten45/f7c427c57a0842f05cf8b2e3aeb011c3/raw/decks.json",
).strip()

# 덱 동기화 상태(ETag, 마지막 확인 시각) 사이드카. DB 와 같은 data 디렉터리에 둔다.
DECKS_SYNC_STATE_PATH = DATA_DIR / "decks_sync.json"


def ensure_data_dir() -> None:
    """DB 디렉터리를 보장한다(없으면 생성)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
