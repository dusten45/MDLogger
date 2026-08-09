"""상대 덱 후보 목록 로드.

후보는 외부 JSON 파일(프로젝트 루트의 decks.json)에서 읽으며 사용자가 직접 편집한다.
파일이 없으면 기본 시드를 한 번 써준다. 항상 "기타"가 포함되도록 보장한다.
"""

from __future__ import annotations

import importlib.resources
import json
import os
from pathlib import Path

from .paths import DECKS_PATH, secure_data_file

OTHER = "기타"

# 최초 시드: "기타" 하나만. 실제 덱은 사용자가 decks.json 을 직접 채운다.
DEFAULT_DECKS = [OTHER]

# 배포 빌드에 번들된 기본 덱 목록(하드닝 N-4). 사용자 decks.json이 없을 때
# 첫 실행 시드로 사용해 목록이 ["기타"] 하나로 남지 않게 한다.
_BUNDLED_CATALOG_RESOURCE = ("mdlogger", "data", "decks.json")


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


def bundled_catalog() -> list[str] | None:
    """번들된 기본 덱 목록을 읽는다. 없거나 손상됐으면 None."""
    try:
        ref = importlib.resources.files(_BUNDLED_CATALOG_RESOURCE[0])
        for part in _BUNDLED_CATALOG_RESOURCE[1:]:
            ref = ref.joinpath(part)
        data = json.loads(ref.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError, ModuleNotFoundError):
        return None
    return [str(item).strip() for item in data if str(item).strip()]


def load_decks(path: Path = DECKS_PATH) -> list[str]:
    """덱 후보 목록 반환. 파일이 없으면 번들 카탈로그 → 시드로 쓰고 반환."""
    if not path.exists():
        catalog = bundled_catalog()
        items = list(catalog) if catalog is not None else list(DEFAULT_DECKS)
        if OTHER not in items:
            items.append(OTHER)
        items = _dedup(items)
        save_decks(items, path)
        return items
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        decks = [str(d).strip() for d in data if str(d).strip()]
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        decks = [OTHER]
    if OTHER not in decks:
        decks.append(OTHER)
    return _dedup(decks)
