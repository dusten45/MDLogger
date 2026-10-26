"""로컬 초기화의 이동·확정·삭제를 저널로 복구한다. 호출자는 쓰기를 중지해야 한다."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Lock, RLock
from weakref import WeakValueDictionary

PROFILE_DIRECTORIES = ("global", "guest", "accounts")
MANAGED_RESET_FILES = (
    "games.db",
    "games.db-wal",
    "games.db-shm",
    "games.db-journal",
    "settings.json",
    "decks.json",
    "decks.json.tmp",
    "decks_sync.json",
    "decks_sync.json.tmp",
    "environment_version_cache.json",
    "environment_version_cache.json.tmp",
    "release_policy_cache.json",
    "release_policy_cache.json.tmp",
)
_JOURNAL = "journal.json"
_DATA_ROOT_LOCKS: WeakValueDictionary[Path, RLock] = WeakValueDictionary()
_DATA_ROOT_LOCKS_GUARD = Lock()


def data_root_lock(data_dir: Path) -> RLock:
    """같은 루트의 복구와 파일 준비를 직렬화하는 재진입 잠금을 반환한다.

    덱 동기화 잠금이 필요하면 먼저 획득한다. 이 잠금 안에서는 네트워크나
    작업자 종료를 기다리지 않는다. 새 프로필 준비는 비공개 하위 루트만
    중첩하므로 다른 스레드가 부모 잠금을 역순으로 획득하지 않는다.
    """
    root = data_dir.resolve()
    # 대기 중인 호출도 강한 참조를 보유한다. 사용이 끝난 임시 루트는 남기지 않는다.
    with _DATA_ROOT_LOCKS_GUARD:
        lock = _DATA_ROOT_LOCKS.get(root)
        if lock is None:
            lock = RLock()
            _DATA_ROOT_LOCKS[root] = lock
        return lock


class ResetRecoveryError(OSError):
    """복구 자료를 보존한 채 초기화 또는 삭제를 중단한다."""

    def __init__(self, message: str, *, committed: bool = False):
        super().__init__(message)
        self.committed = committed


def sync_directory(path: Path) -> None:
    """POSIX에서 이름 변경도 동기화한다. Windows 디렉터리 fsync는 지원하지 않는다."""
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _identity(path: Path) -> list[int] | None:
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return None
    return [stat.st_dev, stat.st_ino]


def _managed_name(name: object) -> bool:
    return isinstance(name, str) and (
        name in (*PROFILE_DIRECTORIES, *MANAGED_RESET_FILES)
        or re.fullmatch(r"\.settings\.json\.[\w-]+\.tmp", name) is not None
        or re.fullmatch(r"games\.db\.pre-migration-v\d+\.bak[\w.-]*", name) is not None
    )


def _write_journal(staging: Path, journal: dict) -> None:
    temporary = staging / "journal.tmp"
    with temporary.open("w", encoding="utf-8") as file:
        if os.name != "nt":
            temporary.chmod(0o600)
        json.dump(journal, file, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, staging / _JOURNAL)
    sync_directory(staging)


def _read_journal(staging: Path) -> dict:
    journal_path = staging / _JOURNAL
    if staging.is_symlink() or journal_path.is_symlink() or not journal_path.is_file():
        raise ResetRecoveryError("초기화 복구 저널이 없거나 경로가 안전하지 않습니다.")
    try:
        if journal_path.stat().st_size > 1_000_000:
            raise ValueError
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if (
            not isinstance(journal, dict)
            or type(journal.get("version")) is not int
            or journal.get("version") != 1
            or journal.get("phase") not in ("precommit", "committed", "purge_pending")
            or not isinstance(journal.get("originals"), dict)
            or not isinstance(journal.get("replacements"), dict)
        ):
            raise ValueError
        for name, identity in journal["originals"].items():
            if not _managed_name(name) or not _valid_identity(identity):
                raise ValueError
        replacements = journal["replacements"]
        if journal["phase"] != "precommit" and set(replacements) != set(
            PROFILE_DIRECTORIES
        ):
            raise ValueError
        if any(
            name not in PROFILE_DIRECTORIES or not _valid_identity(identity)
            for name, identity in replacements.items()
        ):
            raise ValueError
        if {path.name for path in staging.iterdir()} - {
            _JOURNAL,
            "journal.tmp",
            "old",
            "new",
        }:
            raise ValueError
        temporary = staging / "journal.tmp"
        if temporary.is_symlink() or (temporary.exists() and not temporary.is_file()):
            raise ValueError
        for folder, names in (
            ("old", journal["originals"]),
            ("new", PROFILE_DIRECTORIES),
        ):
            path = staging / folder
            if path.is_symlink() or (
                path.exists()
                and (
                    not path.is_dir()
                    or {entry.name for entry in path.iterdir()} - set(names)
                )
            ):
                raise ValueError
        return journal
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        raise ResetRecoveryError(
            f"초기화 복구 자료를 확인할 수 없습니다: {staging}"
        ) from error


def _valid_identity(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(type(part) is int for part in value)
    )


def _move(source: Path, destination: Path) -> None:
    os.replace(source, destination)
    sync_directory(source.parent)
    sync_directory(destination.parent)


def _discard_staging(staging: Path) -> None:
    # 저널을 마지막에 제거해야 삭제 도중 종료돼도 남은 원본의 처리를 재개할 수 있다.
    for name in ("old", "new"):
        path = staging / name
        if path.exists():
            shutil.rmtree(path)
    (staging / "journal.tmp").unlink(missing_ok=True)
    sync_directory(staging)
    (staging / _JOURNAL).unlink()
    staging.rmdir()
    sync_directory(staging.parent)


def _discard_unpublished_reset(staging: Path) -> bool:
    """하위 데이터 디렉터리 생성 전의 빈 폴더 또는 초기 임시 저널만 제거한다."""
    if (
        re.fullmatch(r"\.mdlogger-reset-[0-9a-f]{32}", staging.name) is None
        or staging.is_symlink()
        or not staging.is_dir()
    ):
        return False
    entries = list(staging.iterdir())
    if entries:
        temporary = staging / "journal.tmp"
        if entries != [temporary] or temporary.is_symlink() or not temporary.is_file():
            return False
        with temporary.open("rb") as file:
            contents = file.read(1_000_001)
        # 첫 저널은 항상 이 순서로 쓴다. 다른 단계나 출처 불명 파일은 보존한다.
        prefix = b'{"version": 1, "phase": "precommit", "originals": '
        if len(contents) > 1_000_000 or not (
            prefix.startswith(contents) or contents.startswith(prefix)
        ):
            return False
        temporary.unlink()
    staging.rmdir()
    sync_directory(staging.parent)
    return True


def _recover(staging: Path, journal: dict) -> None:
    root = staging.parent
    if journal["phase"] == "precommit":
        for name, identity in journal["originals"].items():
            original, saved = root / name, staging / "old" / name
            original_id, saved_id = _identity(original), _identity(saved)
            if (original_id, saved_id) not in ((identity, None), (None, identity)):
                raise ResetRecoveryError(
                    f"원본과 복구본을 구분할 수 없어 보존합니다: {name}"
                )
        for name in reversed(journal["originals"]):
            saved = staging / "old" / name
            if _identity(saved) is not None:
                _move(saved, root / name)
    else:
        for name, identity in journal["replacements"].items():
            prepared, installed = staging / "new" / name, root / name
            prepared_id, installed_id = _identity(prepared), _identity(installed)
            if (prepared_id, installed_id) not in ((identity, None), (None, identity)):
                raise ResetRecoveryError(
                    f"새 프로필의 위치를 확인할 수 없습니다: {name}", committed=True
                )
        for name in journal["replacements"]:
            prepared = staging / "new" / name
            if _identity(prepared) is not None:
                _move(prepared, root / name)
        marker = root / ".legacy-data-migrated"
        if marker.is_symlink():
            raise ResetRecoveryError(
                "레거시 이관 표식에 링크가 있어 중단했습니다.", committed=True
            )
        with marker.open("a") as file:
            file.flush()
            os.fsync(file.fileno())
        if os.name != "nt":
            marker.chmod(0o600)
        sync_directory(root)
        journal["phase"] = "purge_pending"
        _write_journal(staging, journal)
    _discard_staging(staging)


def recover_pending_resets(data_dir: Path) -> None:
    """레거시 이관·프로필 생성 전에 미완료 초기화를 복구한다."""
    with data_root_lock(data_dir):
        staging_dirs = sorted(data_dir.glob(".mdlogger-reset-*"))
        if len(staging_dirs) > 1:
            raise ResetRecoveryError(
                "여러 초기화 복구 폴더가 있어 자동 처리를 중단했습니다."
            )
        for staging in staging_dirs:
            if _discard_unpublished_reset(staging):
                continue
            journal = _read_journal(staging)
            try:
                _recover(staging, journal)
            except OSError as error:
                raise ResetRecoveryError(
                    f"초기화 복구 또는 이전 데이터 삭제를 완료하지 못했습니다: {staging}",
                    committed=journal["phase"] != "precommit",
                ) from error


def reset_data(
    data_dir: Path, paths: Sequence[Path], prepare: Callable[[Path], None]
) -> None:
    """호출자가 닫은 데이터만 이동하고 새 프로필 준비 후 삭제를 확정한다."""
    with data_root_lock(data_dir):
        recover_pending_resets(data_dir)
        originals = {}
        for path in paths:
            if path.parent != data_dir or not _managed_name(path.name):
                raise ResetRecoveryError("앱 관리 경로가 아닌 초기화 대상입니다.")
            if (identity := _identity(path)) is not None:
                originals[path.name] = identity
        staging = data_dir / f".mdlogger-reset-{uuid.uuid4().hex}"
        journal = {
            "version": 1,
            "phase": "precommit",
            "originals": originals,
            "replacements": {},
        }
        try:
            staging.mkdir(mode=0o700)
            _write_journal(staging, journal)
            sync_directory(data_dir)
            (staging / "old").mkdir(mode=0o700)
            (staging / "new").mkdir(mode=0o700)
            sync_directory(staging)
            for name, identity in originals.items():
                if _identity(data_dir / name) != identity:
                    raise ResetRecoveryError("초기화 중 원본 경로가 변경되었습니다.")
                _move(data_dir / name, staging / "old" / name)
            prepare(staging / "new")
            journal["replacements"] = {
                name: _identity(staging / "new" / name) for name in PROFILE_DIRECTORIES
            }
            if not all(
                _valid_identity(value) for value in journal["replacements"].values()
            ):
                raise ResetRecoveryError("새 프로필을 준비하지 못했습니다.")
        except Exception as error:
            try:
                if _identity(staging) is not None and not _discard_unpublished_reset(
                    staging
                ):
                    _recover(staging, _read_journal(staging))
            except OSError as recovery_error:
                raise ResetRecoveryError(
                    f"이전 데이터를 자동 복원하지 못했습니다: {staging}"
                ) from recovery_error
            raise ResetRecoveryError("앱 데이터를 초기화할 수 없습니다.") from error
        journal["phase"] = "committed"
        try:
            _write_journal(staging, journal)
            _recover(staging, journal)
        except OSError as error:
            # 확정 기록이 교체된 직후 fsync가 실패했을 수도 있어 메모리 값으로 복원하지 않는다.
            if not staging.exists():
                raise ResetRecoveryError(
                    "초기화 완료 상태를 디스크에 확인하지 못했습니다.", committed=True
                ) from error
            persisted = _read_journal(staging)
            if persisted["phase"] == "precommit":
                _recover(staging, persisted)
            raise ResetRecoveryError(
                "초기화 전 앱 데이터를 완전히 제거할 수 없습니다.",
                committed=persisted["phase"] != "precommit",
            ) from error
