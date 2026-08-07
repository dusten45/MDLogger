"""상대 덱 후보 목록 로드.

후보는 외부 JSON 파일(프로젝트 루트의 decks.json)에서 읽으며 사용자가 직접 편집한다.
파일이 없으면 기본 시드를 한 번 써준다. 항상 "기타"가 포함되도록 보장한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .paths import DECKS_PATH, secure_data_file

OTHER = "기타"

# 최초 시드: "기타" 하나만. 실제 덱은 사용자가 decks.json 을 직접 채운다.
DEFAULT_DECKS = [OTHER]


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def save_decks(decks: list[str], path: Path = DECKS_PATH) -> None:
    """덱 목록을 원자적으로 쓴다(임시 파일 → ``os.replace``).

    백그라운드 동기화가 파일을 쓰는 동안 메인 스레드가 부분 파일을 읽지 않도록
    같은 디렉터리 내 원자적 교체를 사용한다.
    """
    text = json.dumps(decks, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    secure_data_file(tmp)
    os.replace(tmp, path)


def load_decks(path: Path = DECKS_PATH) -> list[str]:
    """덱 후보 목록 반환. 파일이 없으면 시드를 쓰고 반환. 항상 '기타' 포함."""
    if not path.exists():
        save_decks(DEFAULT_DECKS, path)
        return list(DEFAULT_DECKS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        decks = [str(d).strip() for d in data if str(d).strip()]
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        decks = [OTHER]
    if OTHER not in decks:
        decks.append(OTHER)
    return _dedup(decks)
