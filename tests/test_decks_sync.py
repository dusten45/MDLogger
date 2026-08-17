"""decks 온라인 동기화 단위 테스트 (네트워크 없이 _fetch_remote 를 monkeypatch)."""

from __future__ import annotations

import json
import urllib.error
from threading import Event, Thread

import pytest

from mdlogger import sync
from mdlogger.decks import OTHER, load_decks

# ---------- merge_decks (순수 함수) ----------


def test_merge_union_preserves_local_and_remote():
    merged = sync.merge_decks(["A", "B", "C"], ["B", "X", OTHER])  # X 는 로컬 전용
    assert set(merged) == {"A", "B", "C", "X", OTHER}


def test_merge_remote_order_then_local_extras():
    merged = sync.merge_decks(["A", "B", "C"], ["X", "A", "Y"])
    assert merged[:3] == ["A", "B", "C"]  # 원격 순서 유지(먼저)
    assert merged.index("X") > merged.index("C")  # 로컬 전용은 뒤에
    assert merged.index("Y") > merged.index("C")


def test_merge_dedup_and_other_guaranteed():
    merged = sync.merge_decks(["A", "A", " B "], ["B", "A"])
    assert merged.count("A") == 1  # 중복 제거
    assert "B" in merged  # 양끝 공백 strip
    assert OTHER in merged  # 어느 쪽에도 없어도 보장


# ---------- _fetch_remote URL 보안 ----------


class _Response:
    def __init__(self, final_url: str, payload: bytes = b'["A"]'):
        self._final_url = final_url
        self._payload = payload
        self.headers = {"ETag": "etag"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self) -> str:
        return self._final_url

    def read(self) -> bytes:
        return self._payload


def test_fetch_rejects_non_https_before_open(monkeypatch):
    called = []
    monkeypatch.setattr(
        sync.urllib.request, "urlopen", lambda *args, **kwargs: called.append(args)
    )

    with pytest.raises(ValueError, match="HTTPS"):
        sync._fetch_remote("http://example.com/decks.json", None)

    assert not called


def test_fetch_rejects_redirect_to_non_https(monkeypatch):
    monkeypatch.setattr(
        sync.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response("http://example.com/decks.json"),
    )

    with pytest.raises(ValueError, match="HTTPS"):
        sync._fetch_remote("https://example.com/decks.json", None)


def test_fetch_accepts_https_response(monkeypatch):
    monkeypatch.setattr(
        sync.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response("https://example.com/decks.json"),
    )

    assert sync._fetch_remote("https://example.com/decks.json", None) == (["A"], "etag")


# ---------- sync_decks (_fetch_remote monkeypatch) ----------


def _no_real_data_dir(monkeypatch):
    """실제 data 디렉터리 생성을 막는다(tmp_path 는 이미 존재)."""
    monkeypatch.setattr(sync, "ensure_data_dir", lambda: None)


def test_sync_noop_when_url_empty(tmp_path, monkeypatch):
    _no_real_data_dir(monkeypatch)
    called = []
    monkeypatch.setattr(
        sync, "_fetch_remote", lambda *a: called.append(a) or (None, None)
    )
    decks_path = tmp_path / "decks.json"
    sync.sync_decks(url="", decks_path=decks_path, state_path=tmp_path / "state.json")
    assert not called  # fetch 호출조차 안 함
    assert not decks_path.exists()  # 아무 파일도 안 씀


def test_sync_304_leaves_file_untouched(tmp_path, monkeypatch):
    _no_real_data_dir(monkeypatch)
    decks_path = tmp_path / "decks.json"
    decks_path.write_text(json.dumps(["A", OTHER]), encoding="utf-8")
    before = decks_path.read_text(encoding="utf-8")
    monkeypatch.setattr(sync, "_fetch_remote", lambda url, etag: (None, etag))
    sync.sync_decks(
        url="http://x", decks_path=decks_path, state_path=tmp_path / "state.json"
    )
    assert decks_path.read_text(encoding="utf-8") == before


def test_sync_200_merges_and_preserves_local(tmp_path, monkeypatch):
    _no_real_data_dir(monkeypatch)
    decks_path = tmp_path / "decks.json"
    decks_path.write_text(
        json.dumps(["로컬전용", OTHER], ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        sync, "_fetch_remote", lambda url, etag: (["원격A", "원격B"], "etag1")
    )
    sync.sync_decks(
        url="http://x", decks_path=decks_path, state_path=tmp_path / "state.json"
    )
    result = load_decks(decks_path)
    assert "원격A" in result and "원격B" in result  # 원격 신규 반영
    assert "로컬전용" in result  # 로컬 전용 보존
    assert OTHER in result


def test_sync_writes_state_etag(tmp_path, monkeypatch):
    _no_real_data_dir(monkeypatch)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(sync, "_fetch_remote", lambda url, etag: (["A"], "etag-xyz"))
    sync.sync_decks(
        url="http://x", decks_path=tmp_path / "decks.json", state_path=state_path
    )
    assert json.loads(state_path.read_text(encoding="utf-8"))["etag"] == "etag-xyz"


def test_sync_passes_saved_etag_back(tmp_path, monkeypatch):
    """이전 실행이 저장한 ETag 가 다음 조건부 GET 에 전달되는지."""
    _no_real_data_dir(monkeypatch)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"etag": "prev"}), encoding="utf-8")
    seen = {}

    def _capture(url, etag):
        seen["etag"] = etag
        return None, etag  # 304

    monkeypatch.setattr(sync, "_fetch_remote", _capture)
    sync.sync_decks(
        url="http://x", decks_path=tmp_path / "decks.json", state_path=state_path
    )
    assert seen["etag"] == "prev"


def test_invalidated_background_sync_cannot_recreate_reset_cache(tmp_path, monkeypatch):
    _no_real_data_dir(monkeypatch)
    fetched = Event()
    release_fetch = Event()

    def blocked_fetch(url, etag):
        fetched.set()
        assert release_fetch.wait(timeout=2)
        return ["원격 덱"], "etag"

    monkeypatch.setattr(sync, "_fetch_remote", blocked_fetch)
    with sync._BACKGROUND_SYNC_LOCK:
        generation = sync._BACKGROUND_SYNC_GENERATION
    decks_path = tmp_path / "decks.json"
    state_path = tmp_path / "decks_sync.json"
    worker = Thread(
        target=sync.sync_decks,
        kwargs={
            "url": "https://example.com/decks.json",
            "decks_path": decks_path,
            "state_path": state_path,
            "generation": generation,
        },
    )
    worker.start()
    assert fetched.wait(timeout=2)

    sync.invalidate_background_sync()
    release_fetch.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert not decks_path.exists()
    assert not state_path.exists()


def test_sync_swallows_fetch_error(tmp_path, monkeypatch):
    _no_real_data_dir(monkeypatch)
    decks_path = tmp_path / "decks.json"
    decks_path.write_text(json.dumps(["A", OTHER]), encoding="utf-8")
    before = decks_path.read_text(encoding="utf-8")

    def _boom(url, etag):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(sync, "_fetch_remote", _boom)
    sync.sync_decks(
        url="http://x", decks_path=decks_path, state_path=tmp_path / "state.json"
    )
    assert decks_path.read_text(encoding="utf-8") == before  # 예외 전파 없음·로컬 보존
