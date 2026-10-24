"""자격 증명 저장소 테스트: 토큰이 평문 파일·로그로 새지 않아야 한다."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import keyring.errors
import pytest

from mdlogger.auth.credential_store import (
    CredentialStoreBusy,
    CredentialStoreError,
    InMemoryCredentialStore,
    KeyringCredentialStore,
)

ACCOUNT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class FakeKeyring:
    """keyring 모듈과 같은 표면을 가진 메모리 backend."""

    def __init__(self):
        self.storage: dict[tuple[str, str], str] = {}

    def get_password(self, service, name):
        return self.storage.get((service, name))

    def set_password(self, service, name, value):
        self.storage[(service, name)] = value

    def delete_password(self, service, name):
        if (service, name) not in self.storage:
            raise keyring.errors.PasswordDeleteError(name)
        del self.storage[(service, name)]


class BrokenKeyring:
    def get_password(self, service, name):
        raise keyring.errors.KeyringError("backend unavailable")

    def set_password(self, service, name, value):
        raise keyring.errors.KeyringError("backend unavailable")

    def delete_password(self, service, name):
        raise keyring.errors.KeyringError("backend unavailable")


def test_keyring_store_round_trip(tmp_path: Path):
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend, lock_directory=tmp_path)

    assert store.load_refresh_token(ACCOUNT) is None
    store.save_refresh_token(ACCOUNT, "refresh-1")
    assert store.load_refresh_token(ACCOUNT) == "refresh-1"

    store.delete_refresh_token(ACCOUNT)
    assert store.load_refresh_token(ACCOUNT) is None


def test_keyring_store_isolates_accounts(tmp_path: Path):
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend, lock_directory=tmp_path)
    other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    store.save_refresh_token(ACCOUNT, "refresh-a")
    store.save_refresh_token(other, "refresh-b")
    store.delete_refresh_token(ACCOUNT)

    assert store.load_refresh_token(ACCOUNT) is None
    assert store.load_refresh_token(other) == "refresh-b"


def test_keyring_store_delete_is_idempotent(tmp_path: Path):
    store = KeyringCredentialStore(FakeKeyring(), lock_directory=tmp_path)
    store.delete_refresh_token(ACCOUNT)  # 존재하지 않아도 예외 없음


def test_keyring_store_rejects_empty_token(tmp_path: Path):
    store = KeyringCredentialStore(FakeKeyring(), lock_directory=tmp_path)
    with pytest.raises(ValueError):
        store.save_refresh_token(ACCOUNT, "")


def test_keyring_backend_failure_raises_store_error_without_plaintext_fallback(
    tmp_path: Path,
):
    store = KeyringCredentialStore(BrokenKeyring(), lock_directory=tmp_path)

    with pytest.raises(CredentialStoreError):
        store.save_refresh_token(ACCOUNT, "refresh-1")
    with pytest.raises(CredentialStoreError):
        store.load_refresh_token(ACCOUNT)


def test_in_memory_store_round_trip():
    store = InMemoryCredentialStore()
    store.save_refresh_token(ACCOUNT, "refresh-1")
    assert store.load_refresh_token(ACCOUNT) == "refresh-1"
    store.delete_refresh_token(ACCOUNT)
    assert store.load_refresh_token(ACCOUNT) is None


def _hold_refresh_lock(directory, entered, release):
    store = KeyringCredentialStore(FakeKeyring(), lock_directory=Path(directory))
    with store.refresh_lock(ACCOUNT):
        entered.set()
        assert release.wait(10)


def test_refresh_lock_coordinates_processes_but_does_not_block_logout(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    entered, release = context.Event(), context.Event()
    process = context.Process(
        target=_hold_refresh_lock, args=(str(tmp_path), entered, release)
    )
    process.start()
    store = KeyringCredentialStore(FakeKeyring(), lock_directory=tmp_path)
    try:
        assert entered.wait(10), "별도 프로세스가 계정 잠금을 얻지 못했습니다."
        with pytest.raises(CredentialStoreBusy), store.refresh_lock(ACCOUNT):
            pass
        # 네트워크 잠금은 키링의 짧은 로그아웃 트랜잭션을 막지 않는다.
        store.save_refresh_token(ACCOUNT, "비밀 토큰")
        store.delete_refresh_token(ACCOUNT)
        assert store.load_refresh_token(ACCOUNT) is None
        with store.refresh_lock("다른 계정"):
            pass
    finally:
        release.set()
        process.join(10)
    assert process.exitcode == 0
    assert list(tmp_path.iterdir()) == []


def test_lock_namespace_does_not_follow_data_directory(tmp_path: Path, monkeypatch):
    from mdlogger.auth import credential_store

    monkeypatch.setattr(
        credential_store.QStandardPaths, "writableLocation", lambda _: str(tmp_path)
    )
    monkeypatch.setenv("MDLOGGER_DATA_DIR", str(tmp_path / "첫 데이터"))
    first = KeyringCredentialStore(FakeKeyring())
    monkeypatch.setenv("MDLOGGER_DATA_DIR", str(tmp_path / "다른 데이터"))
    second = KeyringCredentialStore(FakeKeyring())
    with first.refresh_lock(ACCOUNT):
        with pytest.raises(CredentialStoreBusy), second.refresh_lock(ACCOUNT):
            pass
