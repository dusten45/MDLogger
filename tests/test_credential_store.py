"""자격 증명 저장소 테스트: 토큰이 평문 파일·로그로 새지 않아야 한다."""

from __future__ import annotations

import keyring.errors
import pytest

from mdlogger.auth.credential_store import (
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


def test_keyring_store_round_trip():
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend)

    assert store.load_refresh_token(ACCOUNT) is None
    store.save_refresh_token(ACCOUNT, "refresh-1")
    assert store.load_refresh_token(ACCOUNT) == "refresh-1"

    store.delete_refresh_token(ACCOUNT)
    assert store.load_refresh_token(ACCOUNT) is None


def test_keyring_store_isolates_accounts():
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend)
    other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    store.save_refresh_token(ACCOUNT, "refresh-a")
    store.save_refresh_token(other, "refresh-b")
    store.delete_refresh_token(ACCOUNT)

    assert store.load_refresh_token(ACCOUNT) is None
    assert store.load_refresh_token(other) == "refresh-b"


def test_keyring_store_delete_is_idempotent():
    store = KeyringCredentialStore(FakeKeyring())
    store.delete_refresh_token(ACCOUNT)  # 존재하지 않아도 예외 없음


def test_keyring_store_rejects_empty_token():
    store = KeyringCredentialStore(FakeKeyring())
    with pytest.raises(ValueError):
        store.save_refresh_token(ACCOUNT, "")


def test_keyring_backend_failure_raises_store_error_without_plaintext_fallback():
    store = KeyringCredentialStore(BrokenKeyring())

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
