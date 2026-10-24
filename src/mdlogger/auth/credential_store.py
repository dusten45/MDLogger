"""OS 보안 자격 증명 저장소 adapter.

refresh token만 저장한다. 비밀번호와 access token은 저장하지 않는다
(로드맵 5.3). OS 저장소를 사용할 수 없을 때 평문 파일로 대체하지 않고
오류를 그대로 전달한다(로드맵 16장).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from hashlib import sha256
from pathlib import Path
from threading import Lock, RLock
from typing import Protocol

import keyring
import keyring.errors
from PySide6.QtCore import QLockFile, QStandardPaths

_SERVICE_NAME = "mdlogger"


class CredentialStoreError(RuntimeError):
    """자격 증명 저장소를 사용할 수 없을 때 발생한다."""


class CredentialStoreBusy(CredentialStoreError):
    """다른 실행이 같은 계정의 자격 증명을 갱신하고 있다."""


class KeyringBackend(Protocol):
    """``keyring`` 모듈과 같은 표면의 주입 가능한 backend."""

    def get_password(self, service_name: str, username: str, /) -> str | None: ...

    def set_password(
        self, service_name: str, username: str, password: str, /
    ) -> None: ...

    def delete_password(self, service_name: str, username: str, /) -> None: ...


class CredentialStore(Protocol):
    """계정별 refresh token 보관 경계."""

    def load_refresh_token(self, account_id: str) -> str | None: ...

    def save_refresh_token(self, account_id: str, refresh_token: str) -> None: ...

    def delete_refresh_token(self, account_id: str) -> None: ...

    def transaction(self, account_id: str) -> AbstractContextManager[None]: ...

    def refresh_lock(self, account_id: str) -> AbstractContextManager[None]: ...


def _entry_name(account_id: str) -> str:
    return f"refresh-token:{account_id}"


class KeyringCredentialStore:
    """``keyring`` 기반 OS 자격 증명 저장소 구현.

    Windows Credential Manager, macOS Keychain, Linux Secret Service를
    자동으로 사용한다. 테스트를 위해 keyring 호환 모듈을 주입할 수 있다.
    """

    def __init__(
        self,
        backend: KeyringBackend | None = None,
        *,
        lock_directory: Path | None = None,
    ) -> None:
        self._backend: KeyringBackend = backend if backend is not None else keyring
        # 키링은 데이터 디렉터리와 무관하게 공유되므로 잠금도 OS 사용자 범위다.
        self._lock_directory = lock_directory or (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.GenericDataLocation
                )
            )
            / "MDLogger"
            / "credential-locks"
        )
        self._transaction_lock = RLock()
        self._locked_accounts: set[str] = set()

    @contextmanager
    def _file_lock(
        self, account_id: str, suffix: str, timeout_ms: int
    ) -> Generator[None]:
        try:
            self._lock_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as error:
            raise CredentialStoreError(
                "자격 증명 잠금 디렉터리를 사용할 수 없습니다."
            ) from error
        key = sha256(f"{_SERVICE_NAME}:{_entry_name(account_id)}".encode()).hexdigest()
        lock = QLockFile(str(self._lock_directory / f"{key}.{suffix}.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(timeout_ms):
            if lock.error() == QLockFile.LockError.LockFailedError:
                raise CredentialStoreBusy(
                    "다른 창에서 이 계정의 자격 증명을 갱신 중입니다."
                )
            raise CredentialStoreError("자격 증명 잠금을 만들 수 없습니다.")
        try:
            yield
        finally:
            lock.unlock()

    @contextmanager
    def transaction(self, account_id: str) -> Generator[None]:
        """키링 읽기·비교·쓰기를 다른 프로세스와 짧게 직렬화한다."""
        with self._transaction_lock:
            if account_id in self._locked_accounts:
                yield
                return
            with self._file_lock(account_id, "store", 1000):
                self._locked_accounts.add(account_id)
                try:
                    yield
                finally:
                    self._locked_accounts.remove(account_id)

    def refresh_lock(self, account_id: str) -> AbstractContextManager[None]:
        """네트워크 갱신은 한 실행만 하되 로그아웃의 짧은 쓰기는 막지 않는다."""
        return self._file_lock(account_id, "refresh", 0)

    def load_refresh_token(self, account_id: str) -> str | None:
        with self.transaction(account_id):
            return self._load_refresh_token(account_id)

    def _load_refresh_token(self, account_id: str) -> str | None:
        try:
            token = self._backend.get_password(_SERVICE_NAME, _entry_name(account_id))
        except keyring.errors.KeyringError as error:
            raise CredentialStoreError(
                "OS 자격 증명 저장소를 읽을 수 없습니다."
            ) from error
        return token or None

    def save_refresh_token(self, account_id: str, refresh_token: str) -> None:
        with self.transaction(account_id):
            self._save_refresh_token(account_id, refresh_token)

    def _save_refresh_token(self, account_id: str, refresh_token: str) -> None:
        if not refresh_token:
            raise ValueError("빈 refresh token은 저장할 수 없습니다.")
        try:
            self._backend.set_password(
                _SERVICE_NAME, _entry_name(account_id), refresh_token
            )
        except keyring.errors.KeyringError as error:
            raise CredentialStoreError(
                "OS 자격 증명 저장소에 저장할 수 없습니다."
            ) from error

    def delete_refresh_token(self, account_id: str) -> None:
        with self.transaction(account_id):
            self._delete_refresh_token(account_id)

    def _delete_refresh_token(self, account_id: str) -> None:
        entry = _entry_name(account_id)
        try:
            if self._backend.get_password(_SERVICE_NAME, entry) is None:
                return
            self._backend.delete_password(_SERVICE_NAME, entry)
        except keyring.errors.PasswordDeleteError:
            return
        except keyring.errors.KeyringError as error:
            raise CredentialStoreError(
                "OS 자격 증명 저장소에서 삭제할 수 없습니다."
            ) from error


class InMemoryCredentialStore:
    """테스트용 메모리 저장소. 실제 앱 흐름에서는 사용하지 않는다."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}
        self._lock = RLock()
        self._refresh_locks: dict[str, Lock] = {}

    @contextmanager
    def transaction(self, account_id: str) -> Generator[None]:
        with self._lock:
            yield

    @contextmanager
    def refresh_lock(self, account_id: str) -> Generator[None]:
        with self._lock:
            lock = self._refresh_locks.setdefault(account_id, Lock())
        if not lock.acquire(blocking=False):
            raise CredentialStoreBusy(
                "다른 창에서 이 계정의 자격 증명을 갱신 중입니다."
            )
        try:
            yield
        finally:
            lock.release()

    def load_refresh_token(self, account_id: str) -> str | None:
        with self._lock:
            return self._tokens.get(_entry_name(account_id))

    def save_refresh_token(self, account_id: str, refresh_token: str) -> None:
        if not refresh_token:
            raise ValueError("빈 refresh token은 저장할 수 없습니다.")
        with self._lock:
            self._tokens[_entry_name(account_id)] = refresh_token

    def delete_refresh_token(self, account_id: str) -> None:
        with self._lock:
            self._tokens.pop(_entry_name(account_id), None)
