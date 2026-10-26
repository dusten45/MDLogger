"""decks 온라인 동기화 단위 테스트 (네트워크 없이 _fetch_remote 를 monkeypatch)."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from threading import Event, Thread, current_thread

import pytest

from mdlogger import local_reset, paths, profiles, sync
from mdlogger.decks import OTHER, load_decks
from mdlogger.profiles import ProfileManager

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


@pytest.fixture
def real_deck_worker(tmp_path, monkeypatch):
    """실제 디렉터리 준비와 작업자를 사용하고 외부 조회만 대체한다."""
    data_dir = tmp_path / "data"
    for name, value in {
        "DATA_DIR": data_dir,
        "BASE_DIR": tmp_path / "portable",
        "DB_PATH": data_dir / "games.db",
        "SETTINGS_PATH": data_dir / "settings.json",
        "DECKS_PATH": data_dir / "decks.json",
        "DECKS_SYNC_STATE_PATH": data_dir / "decks_sync.json",
    }.items():
        monkeypatch.setattr(paths, name, value)
    monkeypatch.setattr(profiles, "DATA_DIR", data_dir)
    url = "https://example.com/decks.json"
    monkeypatch.setattr(sync, "DECKS_REMOTE_URL", url)
    monkeypatch.setattr(
        sync.sync_decks,
        "__defaults__",
        (url, data_dir / "decks.json", data_dir / "decks_sync.json"),
    )
    fetched = Event()

    def fetch(url, etag):
        fetched.set()
        return ["원격 덱"], "new-etag"

    monkeypatch.setattr(sync, "_fetch_remote", fetch)
    workers = []

    def track_thread(*args, **kwargs):
        worker = Thread(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(sync.threading, "Thread", track_thread)
    yield data_dir, workers, fetched
    for worker in workers:
        worker.join(timeout=5)
        assert not worker.is_alive(), "덱 작업자가 종료되지 않았습니다."


class _ResetStopped(BaseException):
    pass


def _interrupt_reset(monkeypatch, data_dir: Path, phase: str):
    manager = ProfileManager(data_dir)
    guest = manager.guest()
    manager.prepare_database(guest)
    originals = {
        path: path.read_bytes() for path in (manager._state_path, guest.database_path)
    }
    write_journal = local_reset._write_journal

    def stop_write(staging, journal):
        if phase == "precommit" and journal["phase"] == "committed":
            raise _ResetStopped
        write_journal(staging, journal)
        if phase != "precommit" and journal["phase"] == phase:
            raise _ResetStopped

    with monkeypatch.context() as patch:
        patch.setattr(local_reset, "_write_journal", stop_write)
        with pytest.raises(_ResetStopped):
            manager.reset_local_data()
    staging = next(data_dir.glob(".mdlogger-reset-*"))
    assert local_reset._read_journal(staging)["phase"] == phase
    state_path = (
        staging / "old" / "global" / "profiles.json"
        if phase == "precommit"
        else staging / "new" / "global" / "profiles.json"
        if phase == "committed"
        else manager._state_path
    )
    expected_state = state_path.read_bytes()
    return originals, expected_state


def _observe_root_contention(monkeypatch, data_dir):
    """실제 잠금의 비차단 획득으로 경합을 관찰하고 원래 잠금을 그대로 반환한다."""
    contended = Event()
    get_lock = local_reset.data_root_lock

    def observe(directory):
        lock = get_lock(directory)
        if directory.resolve() == data_dir.resolve():
            if lock.acquire(blocking=False):
                lock.release()
            else:
                contended.set()
        return lock

    for module in (local_reset, paths, profiles, sync):
        monkeypatch.setattr(module, "data_root_lock", observe)
    return contended


@pytest.mark.parametrize("phase", ["precommit", "committed", "purge_pending"])
@pytest.mark.parametrize("first", ["profile", "deck"])
def test_profile_and_real_deck_worker_recover_one_journal_once(
    real_deck_worker, monkeypatch, capsys, phase, first
):
    data_dir, workers, fetched = real_deck_worker
    originals, expected_state = _interrupt_reset(monkeypatch, data_dir, phase)
    journal_read, release_read = Event(), Event()
    cleaning, release_cleanup = Event(), Event()
    contended = _observe_root_contention(monkeypatch, data_dir)
    reads, opened, errors = [], [], []
    read_journal = local_reset._read_journal
    discard_staging = local_reset._discard_staging

    def pause_after_read(staging):
        journal = read_journal(staging)
        reads.append(current_thread().name)
        journal_read.set()
        assert release_read.wait(timeout=5), "저널 읽기 후 대기가 풀리지 않았습니다."
        return journal

    def pause_before_cleanup(staging):
        cleaning.set()
        assert release_cleanup.wait(timeout=5), "정리 전 대기가 풀리지 않았습니다."
        discard_staging(staging)

    def open_profile():
        try:
            opened.append(ProfileManager(data_dir))
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(local_reset, "_read_journal", pause_after_read)
    monkeypatch.setattr(local_reset, "_discard_staging", pause_before_cleanup)
    foreground = Thread(target=open_profile, name="profile-startup", daemon=True)
    try:
        if first == "profile":
            foreground.start()
        else:
            sync.start_background_sync()
        assert journal_read.wait(timeout=5), "복구가 저널을 읽지 못했습니다."
        if first == "profile":
            sync.start_background_sync()
        else:
            foreground.start()
        assert contended.wait(timeout=5), "두 복구 호출이 같은 잠금을 기다려야 합니다."
        assert len(reads) == 1
        assert not fetched.is_set()
        release_read.set()
        assert cleaning.wait(timeout=5), "복구가 정리 단계에 도달하지 못했습니다."
        assert len(reads) == 1
        assert not opened
        assert not fetched.is_set()
    finally:
        release_read.set()
        release_cleanup.set()
        if foreground.ident is not None:
            foreground.join(timeout=5)
        for worker in workers:
            worker.join(timeout=5)

    assert not foreground.is_alive()
    assert all(not worker.is_alive() for worker in workers)
    assert not errors
    assert len(opened) == 1
    assert len(reads) == 1
    assert fetched.is_set()
    assert not list(data_dir.glob(".mdlogger-reset-*"))
    assert (data_dir / "global" / "profiles.json").read_bytes() == expected_state
    expected_id = json.loads(expected_state)["guest_profile_id"]
    assert opened[0].guest().local_profile_id == expected_id
    if phase == "precommit":
        assert all(path.read_bytes() == value for path, value in originals.items())
    else:
        assert not opened[0].guest().database_path.exists()
        assert expected_state != originals[data_dir / "global" / "profiles.json"]
    assert "원격 덱" in load_decks(data_dir / "decks.json")
    assert "동기화 건너뜀" not in capsys.readouterr().err


def test_explicit_reset_blocks_late_real_deck_worker(
    real_deck_worker, monkeypatch, capsys
):
    data_dir, workers, fetched = real_deck_worker
    manager = ProfileManager(data_dir)
    original_id = manager.guest().local_profile_id
    manager.prepare_database(manager.guest())
    original_bytes = manager.guest().database_path.read_bytes()
    prepared, release_prepare = Event(), Event()
    contended = _observe_root_contention(monkeypatch, data_dir)
    errors = []

    def pause_prepare(directory):
        manager._prepare_reset_state(directory)
        prepared.set()
        assert release_prepare.wait(timeout=5), (
            "새 프로필 준비 대기가 풀리지 않았습니다."
        )

    def reset():
        try:
            local_reset.reset_data(
                data_dir, manager._managed_reset_paths(), pause_prepare
            )
        except Exception as error:
            errors.append(error)

    sync.invalidate_background_sync()
    resetting = Thread(target=reset, daemon=True)
    resetting.start()
    try:
        assert prepared.wait(timeout=5), "초기화가 새 프로필을 준비하지 못했습니다."
        sync.start_background_sync()
        assert contended.wait(timeout=5), (
            "늦은 덱 작업자가 초기화 완료를 기다려야 합니다."
        )
        assert not fetched.is_set()
        staging = next(data_dir.glob(".mdlogger-reset-*"))
        assert (staging / "old" / "guest" / "games.db").read_bytes() == original_bytes
        assert not manager.guest().database_path.exists()
    finally:
        release_prepare.set()
        resetting.join(timeout=5)
        for worker in workers:
            worker.join(timeout=5)

    assert not resetting.is_alive()
    assert all(not worker.is_alive() for worker in workers)
    assert not errors
    assert fetched.is_set()
    assert ProfileManager(data_dir).guest().local_profile_id != original_id
    assert not manager.guest().database_path.exists()
    assert not list(data_dir.glob(".mdlogger-reset-*"))
    assert "원격 덱" in load_decks(data_dir / "decks.json")
    assert "동기화 건너뜀" not in capsys.readouterr().err


def test_explicit_reset_does_not_wait_for_deck_network(real_deck_worker, monkeypatch):
    data_dir, workers, fetched = real_deck_worker
    manager = ProfileManager(data_dir)
    original_id = manager.guest().local_profile_id
    release_fetch, reset_done = Event(), Event()
    errors = []

    def pause_fetch(url, etag):
        fetched.set()
        assert release_fetch.wait(timeout=5), "원격 조회 대기가 풀리지 않았습니다."
        return ["초기화 전 덱"], "old-etag"

    def reset():
        try:
            sync.invalidate_background_sync()
            manager.reset_local_data()
        except Exception as error:
            errors.append(error)
        finally:
            reset_done.set()

    monkeypatch.setattr(sync, "_fetch_remote", pause_fetch)
    resetting = Thread(target=reset, daemon=True)
    sync.start_background_sync()
    try:
        assert fetched.wait(timeout=5), "덱 작업자가 원격 조회를 시작하지 못했습니다."
        resetting.start()
        assert reset_done.wait(timeout=5), "초기화가 원격 조회 때문에 지연되었습니다."
        assert not errors
        assert manager.guest().local_profile_id != original_id
    finally:
        release_fetch.set()
        if resetting.ident is not None:
            resetting.join(timeout=5)
        for worker in workers:
            worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert not (data_dir / "decks.json").exists()
    assert not (data_dir / "decks_sync.json").exists()
    assert not list(data_dir.glob(".mdlogger-reset-*"))


def test_explicit_reset_waits_for_real_deck_cache_publication(
    real_deck_worker, monkeypatch, capsys
):
    data_dir, workers, _ = real_deck_worker
    manager = ProfileManager(data_dir)
    original_state = manager._state_path.read_bytes()
    decks_path = data_dir / "decks.json"
    sync.save_decks(["이전 덱", OTHER], decks_path)
    publishing, release_publish = Event(), Event()
    contended = _observe_root_contention(monkeypatch, data_dir)
    save_decks = sync.save_decks
    errors = []

    def pause_publication(decks, path):
        publishing.set()
        assert release_publish.wait(timeout=5), "덱 파일 게시 대기가 풀리지 않았습니다."
        save_decks(decks, path)

    def reset():
        try:
            local_reset.reset_data(
                data_dir, manager._managed_reset_paths(), manager._prepare_reset_state
            )
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(sync, "save_decks", pause_publication)
    sync.invalidate_background_sync()
    sync.start_background_sync()
    resetting = Thread(target=reset, daemon=True)
    try:
        assert publishing.wait(timeout=5), (
            "덱 작업자가 파일 게시를 시작하지 못했습니다."
        )
        resetting.start()
        assert contended.wait(timeout=5), (
            "초기화가 진행 중인 파일 게시를 기다려야 합니다."
        )
        assert manager._state_path.read_bytes() == original_state
        assert not list(data_dir.glob(".mdlogger-reset-*"))
    finally:
        release_publish.set()
        if resetting.ident is not None:
            resetting.join(timeout=5)
        for worker in workers:
            worker.join(timeout=5)

    assert not resetting.is_alive()
    assert all(not worker.is_alive() for worker in workers)
    assert not errors
    assert not decks_path.exists()
    assert not (data_dir / "decks_sync.json").exists()
    assert not list(data_dir.glob(".mdlogger-reset-*"))
    assert manager._state_path.read_bytes() != original_state
    assert "동기화 건너뜀" not in capsys.readouterr().err


@pytest.mark.parametrize("phase", ["precommit", "committed", "purge_pending"])
def test_actual_app_startup_recovers_profiles_before_starting_deck_worker(
    real_deck_worker, monkeypatch, capsys, phase
):
    from PySide6.QtWidgets import QApplication

    from mdlogger import app as app_module
    from mdlogger.app_settings import SettingsRepository

    data_dir, workers, fetched = real_deck_worker
    originals, expected_state = _interrupt_reset(monkeypatch, data_dir, phase)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, "QApplication", lambda argv: application)
    monkeypatch.setattr(app_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(app_module, "acquire_application_mutex", lambda: True)
    monkeypatch.setattr(
        app_module,
        "SettingsRepository",
        lambda: SettingsRepository(data_dir / "settings.json"),
    )
    events = []
    start_worker = sync.start_background_sync

    def open_profiles():
        manager = ProfileManager(data_dir)
        events.append("profiles-ready")
        assert manager._state_path.read_bytes() == expected_state
        assert not list(data_dir.glob(".mdlogger-reset-*"))
        return manager

    def start_decks():
        events.append("deck-worker")
        start_worker()

    def stop_before_remote_config():
        raise _ResetStopped

    monkeypatch.setattr(app_module, "ProfileManager", open_profiles)
    monkeypatch.setattr(sync, "start_background_sync", start_decks)
    monkeypatch.setattr(app_module, "get_remote_config", stop_before_remote_config)
    with pytest.raises(_ResetStopped):
        app_module.main()
    for worker in workers:
        worker.join(timeout=5)

    assert events == ["profiles-ready", "deck-worker"]
    assert len(workers) == 1
    assert not workers[0].is_alive()
    assert fetched.is_set()
    if phase == "precommit":
        assert all(path.read_bytes() == value for path, value in originals.items())
    assert "동기화 건너뜀" not in capsys.readouterr().err
