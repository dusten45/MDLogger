"""OS 보안 자격 증명 저장소 adapter.

refresh token만 저장한다. 비밀번호와 access token은 저장하지 않는다
(로드맵 5.3). OS 저장소를 사용할 수 없을 때 평문 파일로 대체하지 않고
오류를 그대로 전달한다(로드맵 16장).
"""

from __future__ import annotations

from typing import Protocol

import keyring
import keyring.errors

_SERVICE_NAME = "mdlogger"


class CredentialStoreError(RuntimeError):
    """자격 증명 저장소를 사용할 수 없을 때 발생한다."""


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


def _entry_name(account_id: str) -> str:
    return f"refresh-token:{account_id}"


class KeyringCredentialStore:
    """``keyring`` 기반 OS 자격 증명 저장소 구현.

    Windows Credential Manager, macOS Keychain, Linux Secret Service를
    자동으로 사용한다. 테스트를 위해 keyring 호환 모듈을 주입할 수 있다.
    """

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend: KeyringBackend = backend if backend is not None else keyring

    def load_refresh_token(self, account_id: str) -> str | None:
        try:
            token = self._backend.get_password(_SERVICE_NAME, _entry_name(account_id))
        except keyring.errors.KeyringError as error:
            raise CredentialStoreError(
                "OS 자격 증명 저장소를 읽을 수 없습니다."
            ) from error
        return token or None

    def save_refresh_token(self, account_id: str, refresh_token: str) -> None:
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

    def load_refresh_token(self, account_id: str) -> str | None:
        return self._tokens.get(_entry_name(account_id))

    def save_refresh_token(self, account_id: str, refresh_token: str) -> None:
        if not refresh_token:
            raise ValueError("빈 refresh token은 저장할 수 없습니다.")
        self._tokens[_entry_name(account_id)] = refresh_token

    def delete_refresh_token(self, account_id: str) -> None:
        self._tokens.pop(_entry_name(account_id), None)
