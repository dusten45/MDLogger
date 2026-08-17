"""덱 카탈로그 전용 온라인 동기화(GitHub Gist).

게임 기록 동기화는 이 모듈의 책임이 아니며 향후 별도 계정 범위 구성요소로 둔다.

기존 ``decks.json`` 동기화 동작:

앱 시작 시 백그라운드 스레드로 원격 decks.json 을 ETag 조건부 GET 으로 확인하고,
바뀐 경우 로컬과 '병합'(합집합)하여 다시 쓴다. 사용자가 로컬에 추가한 덱은 보존된다.

설계 원칙:
- 네트워크/HTTP/파싱 오류는 모두 삼키고 로컬 파일을 그대로 둔다(앱은 절대 죽지 않음).
- 파일만 쓰고 Qt 객체는 건드리지 않는다(스레드 안전). 갱신 반영은 main_window 가
  상세 화면 진입 때마다 ``load_decks()`` 를 다시 부르는 기존 동작에 맡긴다.
- ``DECKS_REMOTE_URL`` 이 비어 있으면 동기화를 끈다.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .decks import OTHER, _dedup, load_decks, save_decks
from .paths import (
    DECKS_PATH,
    DECKS_REMOTE_URL,
    DECKS_SYNC_STATE_PATH,
    ensure_data_dir,
    secure_data_file,
)

# 시작이 네트워크에 오래 묶이지 않게 하는 요청 타임아웃(초).
_TIMEOUT = 4
# 일부 GitHub 엔드포인트는 User-Agent 누락 요청을 거부하므로 명시한다.
_USER_AGENT = "mdlogger-decks-sync"

# 초기화 중에는 진행 중인 동기화가 이전 덱 캐시를 다시 쓰지 못하게 세대를 올린다.
_BACKGROUND_SYNC_LOCK = threading.Lock()
_BACKGROUND_SYNC_GENERATION = 0


def _require_https(url: str) -> None:
    """원격 덱 목록과 리디렉션 대상은 유효한 HTTPS URL이어야 한다."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("decks URL must use HTTPS")


def merge_decks(remote: list[str], local: list[str]) -> list[str]:
    """원격 우선 순서 + 로컬 전용 항목의 합집합. 'OTHER' 보장, strip/dedup.

    ``load_decks`` 의 정규화 규칙(strip 후 빈 값 제거, OTHER 보장, dedup)과 동일하게
    맞춰, 동기화 결과와 일반 로드 결과가 어긋나지 않도록 한다. 원격의 큐레이션 순서를
    존중하기 위해 원격 항목을 먼저 두고 로컬 전용 항목을 뒤에 붙인다.
    """
    items = [str(x).strip() for x in remote if str(x).strip()]
    items += [str(x).strip() for x in local if str(x).strip()]
    if OTHER not in items:
        items.append(OTHER)
    return _dedup(items)


def _fetch_remote(url: str, etag: str | None) -> tuple[list[str] | None, str | None]:
    """조건부 GET. ``304`` -> ``(None, etag)``, ``200`` -> ``(list[str], 새 etag)``.

    네트워크/HTTP/JSON 오류는 호출자(``sync_decks``)가 처리하도록 그대로 raise 한다.
    원격이 JSON 배열이 아니면 ``ValueError`` 를 낸다.
    """
    _require_https(url)
    headers = {"User-Agent": _USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        # 최초 URL과 리디렉션 결과를 모두 HTTPS로 검사한다.
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310
            _require_https(resp.geturl())
            new_etag = resp.headers.get("ETag")
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 304:  # Not Modified: 로컬이 이미 최신
            return None, etag
        raise
    if not isinstance(data, list):
        raise ValueError("remote decks.json is not a JSON array")
    return [str(x) for x in data], new_etag


def _load_state(state_path: Path) -> dict:
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_state(state_path: Path, etag: str | None) -> None:
    state = {
        "etag": etag,
        "last_checked": datetime.now().isoformat(timespec="seconds"),
    }
    ensure_data_dir()
    text = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    secure_data_file(tmp)
    os.replace(tmp, state_path)


def sync_decks(
    url: str = DECKS_REMOTE_URL,
    decks_path: Path = DECKS_PATH,
    state_path: Path = DECKS_SYNC_STATE_PATH,
    *,
    generation: int | None = None,
) -> None:
    """원격을 확인해 필요 시 로컬 decks.json 을 병합·갱신한다.

    best-effort: 어떤 예외도 밖으로 내보내지 않는다(로컬 보존, 앱 안정성 우선).
    """
    if not url:
        return
    try:
        ensure_data_dir()
        etag = _load_state(state_path).get("etag")

        remote, new_etag = _fetch_remote(url, etag)
        if remote is None:  # 304 Not Modified
            return

        with _BACKGROUND_SYNC_LOCK:
            if generation is not None and generation != _BACKGROUND_SYNC_GENERATION:
                return
            local = load_decks(decks_path)
            merged = merge_decks(remote, local)
            if merged != local:
                save_decks(merged, decks_path)
            _save_state(state_path, new_etag)
    except Exception as e:  # noqa: BLE001 - 동기화는 best-effort, 절대 앱을 막지 않음
        print(f"[decks-sync] 동기화 건너뜀: {e}", file=sys.stderr)


def invalidate_background_sync() -> None:
    """진행 중인 동기화가 초기화 뒤 캐시를 다시 쓰지 못하게 한다."""
    global _BACKGROUND_SYNC_GENERATION
    with _BACKGROUND_SYNC_LOCK:
        _BACKGROUND_SYNC_GENERATION += 1


def start_background_sync() -> None:
    """동기화를 데몬 스레드로 시작한다(비차단). 실패해도 앱에 영향이 없다."""
    if not DECKS_REMOTE_URL:
        return
    with _BACKGROUND_SYNC_LOCK:
        generation = _BACKGROUND_SYNC_GENERATION
    threading.Thread(
        target=sync_decks,
        kwargs={"generation": generation},
        name="decks-sync",
        daemon=True,
    ).start()
