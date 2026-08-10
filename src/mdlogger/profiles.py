"""계정별 로컬 프로필 경로와 SQLite 소유권을 관리한다."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from . import db
from .paths import (
    DATA_DIR,
    copy_database_via_backup,
    ensure_data_dir,
    secure_data_file,
    secure_sidecars,
)

_PROFILE_STATE_VERSION = 1
_PRIVATE_DIR_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


class _ProfileState(TypedDict):
    version: int
    installation_id: str
    guest_profile_id: str
    consent_version: NotRequired[str]
    last_profile_kind: NotRequired[str]
    last_registered_user_id: NotRequired[str]
    last_registered_display_name: NotRequired[str]


class ProfileKind(StrEnum):
    """로컬에서 지원하는 프로필 종류."""

    GUEST = "guest"
    REGISTERED = "registered"


class ProfileError(RuntimeError):
    """프로필 상태 또는 데이터베이스가 안전하게 열릴 수 없을 때 발생한다."""


class ProfileOwnershipError(ProfileError):
    """DB의 기록된 소유자가 요청한 프로필과 다를 때 발생한다."""


@dataclass(frozen=True, slots=True)
class ProfileContext:
    """하나의 계정 범위 서비스를 구성하는 불변 로컬 프로필 정보."""

    local_profile_id: str
    kind: ProfileKind
    remote_user_id: str | None
    installation_id: str
    display_name: str
    database_path: Path
    session_state: str = "local"
    consent_version: str | None = None

    @property
    def owner_id(self) -> str:
        return self.remote_user_id or self.local_profile_id


class ProfileManager:
    """지속형 게스트와 등록 계정별 DB 경로 및 소유권을 관리한다."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.global_dir = data_dir / "global"
        self.guest_dir = data_dir / "guest"
        self.accounts_dir = data_dir / "accounts"
        self._state_path = self.global_dir / "profiles.json"
        self._legacy_db_path = data_dir / "games.db"

        if data_dir == DATA_DIR:
            ensure_data_dir()
        self._ensure_directories()
        self._state = self._load_or_create_state()

    def guest(self) -> ProfileContext:
        return ProfileContext(
            local_profile_id=self._state["guest_profile_id"],
            kind=ProfileKind.GUEST,
            remote_user_id=None,
            installation_id=self._state["installation_id"],
            display_name="게스트",
            database_path=self.guest_dir / "games.db",
            consent_version=self._state.get("consent_version"),
        )

    def registered(
        self,
        remote_user_id: str,
        display_name: str,
        *,
        session_state: str = "authenticated",
    ) -> ProfileContext:
        canonical_user_id = self._canonical_uuid(remote_user_id, "remote user ID")
        account_key = hashlib.sha256(canonical_user_id.encode()).hexdigest()
        return ProfileContext(
            local_profile_id=f"registered:{canonical_user_id}",
            kind=ProfileKind.REGISTERED,
            remote_user_id=canonical_user_id,
            installation_id=self._state["installation_id"],
            display_name=display_name,
            database_path=self.accounts_dir / account_key / "games.db",
            session_state=session_state,
            consent_version=self._state.get("consent_version"),
        )

    def last_profile(self) -> ProfileContext | None:
        """마지막 사용 프로필을 비민감 로컬 상태에서 복원한다."""
        kind = self._state.get("last_profile_kind")
        if kind == ProfileKind.GUEST.value:
            return self.guest()
        if kind != ProfileKind.REGISTERED.value:
            return None
        user_id = self._state.get("last_registered_user_id")
        display_name = self._state.get("last_registered_display_name")
        if not user_id or not display_name:
            return None
        return self.registered(user_id, display_name)

    def remember_profile(self, profile: ProfileContext) -> None:
        """다음 시작 라우팅에 필요한 최소 프로필 정보만 저장한다."""
        updated = cast(_ProfileState, dict(self._state))
        updated["last_profile_kind"] = profile.kind.value
        if profile.kind is ProfileKind.REGISTERED:
            if profile.remote_user_id is None:
                raise ProfileError("등록 프로필에는 remote user ID가 필요합니다.")
            updated["last_registered_user_id"] = profile.remote_user_id
            updated["last_registered_display_name"] = profile.display_name
        self._write_state(updated)
        self._state = updated

    def accept_data_consent(self, consent_version: str) -> None:
        """필수 듀얼 데이터 사용 고지에 동의한 문서 버전을 기록한다."""
        consent_version = consent_version.strip()
        if not consent_version:
            raise ValueError("동의 버전은 비어 있을 수 없습니다.")
        updated = cast(_ProfileState, dict(self._state))
        updated["consent_version"] = consent_version
        self._write_state(updated)
        self._state = updated

    def has_data_consent(self, consent_version: str) -> bool:
        return self._state.get("consent_version") == consent_version

    def prepare_database(self, profile: ProfileContext) -> None:
        """프로필 DB를 준비하고 기록된 소유권이 일치하는지 검증한다."""
        self._validate_context_path(profile)
        if profile.kind is ProfileKind.GUEST:
            self._copy_legacy_guest_database(profile.database_path)

        self._ensure_private_directory(profile.database_path.parent)
        connection = db.connect(profile.database_path)
        try:
            db.init_db(connection)
            self._claim_or_validate_owner(connection, profile)
        finally:
            connection.close()
        secure_data_file(profile.database_path)
        # 프로필 DB도 WAL 모드이므로 -wal/-shm 사이드카에 최신 기록이 쓰일 수 있다.
        # 기본 DB_PATH 외 프로필 DB의 사이드카도 소유자 전용 권한으로 맞춘다(P2-4).
        secure_sidecars(profile.database_path)

    def _ensure_directories(self) -> None:
        self._ensure_private_directory(self.data_dir)
        for path in (self.global_dir, self.guest_dir, self.accounts_dir):
            self._ensure_private_directory(path)

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        path.mkdir(mode=_PRIVATE_DIR_MODE, parents=True, exist_ok=True)
        if os.name != "nt":
            path.chmod(_PRIVATE_DIR_MODE)

    def _load_or_create_state(self) -> _ProfileState:
        if self._state_path.exists():
            try:
                state = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ProfileError("프로필 상태 파일을 읽을 수 없습니다.") from error
            self._validate_state(state)
            return cast(_ProfileState, state)

        state: _ProfileState = {
            "version": _PROFILE_STATE_VERSION,
            "installation_id": str(uuid.uuid4()),
            "guest_profile_id": str(uuid.uuid4()),
        }
        self._write_state(state)
        return state

    def _validate_state(self, state: object) -> None:
        if (
            not isinstance(state, dict)
            or state.get("version") != _PROFILE_STATE_VERSION
        ):
            raise ProfileError("지원하지 않는 프로필 상태 파일입니다.")
        self._canonical_uuid(state.get("installation_id"), "installation ID")
        self._canonical_uuid(state.get("guest_profile_id"), "guest profile ID")

        consent_version = state.get("consent_version")
        if consent_version is not None and not isinstance(consent_version, str):
            raise ProfileError("게스트 동의 버전이 올바르지 않습니다.")

        last_kind = state.get("last_profile_kind")
        if last_kind not in (
            None,
            ProfileKind.GUEST.value,
            ProfileKind.REGISTERED.value,
        ):
            raise ProfileError("마지막 프로필 종류가 올바르지 않습니다.")
        if last_kind == ProfileKind.REGISTERED.value:
            self._canonical_uuid(
                state.get("last_registered_user_id"), "last registered user ID"
            )
            display_name = state.get("last_registered_display_name")
            if not isinstance(display_name, str) or not display_name.strip():
                raise ProfileError("마지막 등록 계정 표시 이름이 올바르지 않습니다.")

    def _write_state(self, state: _ProfileState) -> None:
        temporary_path = self._state_path.with_suffix(".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            temporary_path.replace(self._state_path)
            secure_data_file(self._state_path)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise ProfileError("프로필 상태 파일을 저장할 수 없습니다.") from error

    @staticmethod
    def _canonical_uuid(value: object, label: str) -> str:
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ProfileError(f"올바르지 않은 {label}입니다.") from error

    def _validate_context_path(self, profile: ProfileContext) -> None:
        if profile.kind is ProfileKind.GUEST:
            expected_path = self.guest_dir / "games.db"
        elif profile.remote_user_id is not None:
            account_key = hashlib.sha256(profile.remote_user_id.encode()).hexdigest()
            expected_path = self.accounts_dir / account_key / "games.db"
        else:
            raise ProfileError("등록 프로필에는 remote user ID가 필요합니다.")

        if profile.database_path != expected_path:
            raise ProfileError("프로필 데이터베이스 경로가 예상 경로와 다릅니다.")

    def _copy_legacy_guest_database(self, destination: Path) -> None:
        if destination.exists() or not self._legacy_db_path.is_file():
            return
        self._ensure_private_directory(destination.parent)
        try:
            # WAL 체크포인트되지 않은 legacy DB의 -wal까지 포함해 복사한다(P0-5).
            copy_database_via_backup(self._legacy_db_path, destination)
            secure_data_file(destination)
        except (OSError, sqlite3.Error) as error:
            raise ProfileError(
                "기존 게임 DB를 게스트 프로필로 복사하지 못했습니다."
            ) from error

    @staticmethod
    def _claim_or_validate_owner(
        connection: sqlite3.Connection, profile: ProfileContext
    ) -> None:
        opened_at = datetime.now().isoformat(timespec="seconds")
        connection.execute("BEGIN IMMEDIATE")
        try:
            metadata = connection.execute(
                "SELECT owner_id, profile_kind FROM database_metadata WHERE id=1"
            ).fetchone()
            if metadata is None:
                raise ProfileOwnershipError("DB 소유권 메타데이터가 없습니다.")

            owner_id = metadata["owner_id"]
            profile_kind = metadata["profile_kind"]
            if owner_id is None and profile_kind is None:
                connection.execute(
                    """
                    UPDATE database_metadata
                    SET owner_id=?, profile_kind=?, last_opened_at=?
                    WHERE id=1
                    """,
                    (profile.owner_id, profile.kind.value, opened_at),
                )
            elif owner_id != profile.owner_id or profile_kind != profile.kind.value:
                raise ProfileOwnershipError(
                    "다른 프로필이 소유한 게임 DB는 열 수 없습니다."
                )
            else:
                connection.execute(
                    "UPDATE database_metadata SET last_opened_at=? WHERE id=1",
                    (opened_at,),
                )

            sync_state = connection.execute(
                "SELECT remote_user_id FROM sync_state WHERE id=1"
            ).fetchone()
            expected_remote_id = profile.remote_user_id
            if sync_state is None:
                raise ProfileOwnershipError("DB 동기화 상태 메타데이터가 없습니다.")
            if sync_state["remote_user_id"] not in (None, expected_remote_id):
                raise ProfileOwnershipError(
                    "다른 등록 계정의 동기화 상태가 저장된 DB입니다."
                )
            connection.execute(
                "UPDATE sync_state SET remote_user_id=? WHERE id=1",
                (expected_remote_id,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
