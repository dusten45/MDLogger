"""outbox push, change-version pull 및 conflict 조정 엔진."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .. import __version__
from ..auth.session_manager import SessionManager, SessionState
from ..profiles import ProfileContext, ProfileKind
from ..remote.games import (
    RegisteredGamesClient,
    RegisteredGamesError,
    RegisteredGamesErrorKind,
    build_game_change,
)
from ..remote.guest_ingest import (
    GuestIngestClient,
    GuestIngestError,
    GuestIngestErrorKind,
    build_observation,
    build_withdrawal,
)
from .models import OutboxEntry, StaleConflictError, SyncConflict, SyncPhase, SyncStatus
from .modes import GameModesClient, GameModesError
from .repository import SyncRepository

BATCH_SIZE = 100
TokenProvider = Callable[[], str | None]
TokenRefresher = Callable[[], str | None]


class SyncEngine:
    """프로필 종류에 따라 guest push 또는 registered 양방향 sync를 실행한다."""

    def __init__(
        self,
        profile: ProfileContext,
        *,
        registered_client: RegisteredGamesClient | None = None,
        guest_client: GuestIngestClient | None = None,
        modes_client: GameModesClient | None = None,
        token_provider: TokenProvider | None = None,
        token_refresher: TokenRefresher | None = None,
        session_manager: SessionManager | None = None,
        can_sync: Callable[[], bool] | None = None,
        repository_factory: Callable[[Path], SyncRepository] = SyncRepository.open,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._profile = profile
        self._registered_client = registered_client
        self._guest_client = guest_client
        self._modes_client = modes_client
        self._token_provider = token_provider
        self._token_refresher = token_refresher
        self._session_manager = session_manager
        self._can_sync = can_sync or (lambda: True)
        self._repository_factory = repository_factory
        self._now = now

    def status(self, *, phase: SyncPhase | None = None) -> SyncStatus:
        repository = self._repository_factory(self._profile.database_path)
        try:
            return repository.status(
                phase=phase,
                require_initial_sync=self._profile.kind is ProfileKind.REGISTERED,
            )
        finally:
            repository.close()

    def retry_failed(self) -> None:
        repository = self._repository_factory(self._profile.database_path)
        try:
            repository.retry_failed()
        finally:
            repository.close()

    def list_conflicts(self) -> list[SyncConflict]:
        repository = self._repository_factory(self._profile.database_path)
        try:
            return repository.list_conflicts()
        finally:
            repository.close()

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: dict | None = None,
        *,
        expected_remote_version: int | None = None,
        expected_local_revision: str,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        repository = self._repository_factory(self._profile.database_path)
        try:
            self._require_online()
            client = self._registered_client
            if client is None:
                raise RegisteredGamesError(
                    RegisteredGamesErrorKind.NETWORK,
                    "서버를 확인할 수 없어 충돌 해결을 보류했습니다.",
                )
            conflict = next(
                (
                    item
                    for item in repository.list_conflicts()
                    if item.id == conflict_id
                ),
                None,
            )
            if conflict is None or conflict.local_revision != expected_local_revision:
                raise StaleConflictError(
                    "충돌 내용이 변경되었습니다. 최신 내용을 확인해 주세요."
                )
            token = self._access_token()
            if not token:
                raise self._missing_session_error()
            try:
                remote = client.fetch_game(conflict.game_sync_id, access_token=token)
            except RegisteredGamesError as error:
                if error.kind is not RegisteredGamesErrorKind.AUTH_REQUIRED:
                    raise
                token = self._access_token(rejected_access_token=token)
                if not token:
                    raise self._missing_session_error() from error
                remote = client.fetch_game(conflict.game_sync_id, access_token=token)
            self._require_online()
            if is_cancelled is not None and is_cancelled():
                raise RegisteredGamesError(
                    RegisteredGamesErrorKind.NETWORK,
                    "프로필을 닫아 충돌 해결을 취소했습니다.",
                )
            repository.resolve_conflict(
                conflict_id,
                resolution,
                merged_payload,
                expected_remote_version=expected_remote_version,
                expected_local_revision=expected_local_revision,
                fresh_remote=remote,
            )
        finally:
            repository.close()

    def run_once(self) -> SyncStatus:
        repository = self._repository_factory(self._profile.database_path)
        try:
            if not self._can_sync():
                return repository.status(phase=SyncPhase.OFFLINE)
            entries = repository.fetch_due(limit=BATCH_SIZE, now=self._now())
            if self._profile.kind is ProfileKind.GUEST:
                if not entries:
                    self._sync_modes(repository)
                    return repository.status()
                result = self._push_guest(repository, entries)
            else:
                result = self._sync_registered(repository, entries)
            self._sync_modes(repository)
            return result
        finally:
            repository.close()

    def _sync_modes(self, repository: SyncRepository) -> None:
        """서버 game_modes 기준정보로 로컬 play_modes 캐시를 맞춘다 (B2).

        실패(오프라인)면 기존 캐시로 동작한다(비차단 폴백, §10-2).
        """
        client = self._modes_client
        if client is None:
            return
        try:
            remote = client.fetch()
        except GameModesError:
            return
        try:
            repository.sync_modes(remote)
        except Exception:  # noqa: BLE001 - 캐시 갱신 실패는 동기화를 막지 않는다
            return

    def _push_guest(
        self, repository: SyncRepository, entries: list[OutboxEntry]
    ) -> SyncStatus:
        client = self._guest_client
        if client is None:
            return repository.status(phase=SyncPhase.OFFLINE)
        observations = []
        for entry in entries:
            if entry.operation == "delete":
                observation = build_withdrawal(entry.game_sync_id)
            else:
                observation = build_observation(
                    entry.payload,
                    timezone_offset_minutes=entry.payload.get(
                        "timezone_offset_minutes"
                    ),
                )
                observation["op"] = "upsert"
            observations.append(observation)
        batch_key = ",".join(f"{entry.id}:{entry.game_sync_id}" for entry in entries)
        batch_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"mdlogger:{self._profile.local_profile_id}:{batch_key}",
            )
        )
        try:
            result = client.upload_batch(observations, batch_id=batch_id)
        except GuestIngestError as error:
            retryable = error.kind in (
                GuestIngestErrorKind.NETWORK,
                GuestIngestErrorKind.RATE_LIMITED,
                GuestIngestErrorKind.SERVER,
            )
            repository.record_failure(
                entries,
                code=error.code or error.kind.value,
                detail=str(error),
                retryable=retryable,
                failed_at=self._now(),
                retry_after_seconds=error.retry_after_seconds,
            )
            phase = SyncPhase.OFFLINE if retryable else SyncPhase.FAILED
            return repository.status(phase=phase)
        if result.rejected:
            repository.record_failure(
                entries,
                code="guest_batch_rejected",
                detail=f"게스트 batch에서 {result.rejected}건이 거부되었습니다.",
                retryable=False,
                failed_at=self._now(),
            )
            return repository.status(phase=SyncPhase.FAILED)
        repository.acknowledge(entries, completed_at=self._now())
        return repository.status()

    def _sync_registered(
        self, repository: SyncRepository, entries: list[OutboxEntry]
    ) -> SyncStatus:
        client = self._registered_client
        if client is None or (
            self._token_provider is None and self._session_manager is None
        ):
            return repository.status(phase=SyncPhase.OFFLINE)
        token = self._access_token()
        if not token:
            return repository.status(phase=self._authentication_phase())
        try:
            self._registered_cycle(repository, entries, token)
        except RegisteredGamesError as error:
            if error.kind is RegisteredGamesErrorKind.AUTH_REQUIRED and (
                self._token_refresher is not None or self._session_manager is not None
            ):
                refreshed = self._access_token(rejected_access_token=token)
                if refreshed:
                    try:
                        remaining = repository.fetch_due(
                            limit=BATCH_SIZE, now=self._now()
                        )
                        self._registered_cycle(repository, remaining, refreshed)
                    except RegisteredGamesError as retry_error:
                        return self._record_registered_failure(
                            repository, entries, retry_error
                        )
                else:
                    return repository.status(phase=self._authentication_phase())
            else:
                return self._record_registered_failure(repository, entries, error)
        return repository.status(require_initial_sync=True)

    def _access_token(self, *, rejected_access_token: str | None = None) -> str | None:
        self._require_online()
        if self._session_manager is not None:
            account_id = self._profile.remote_user_id
            if account_id is None:
                return None
            snapshot = self._session_manager.session_for_sync(
                account_id, rejected_access_token=rejected_access_token
            )
            if (
                snapshot.state is SessionState.AUTHENTICATED
                and snapshot.session is not None
            ):
                return snapshot.session.tokens.access_token
            return None
        token = self._token_provider() if self._token_provider is not None else None
        if (
            not token or rejected_access_token is not None
        ) and self._token_refresher is not None:
            return self._token_refresher()
        return token

    def _authentication_phase(self) -> SyncPhase:
        if (
            self._session_manager is not None
            and self._session_manager.state is SessionState.OFFLINE
        ):
            return SyncPhase.OFFLINE
        return SyncPhase.REAUTH_REQUIRED

    def _missing_session_error(self) -> RegisteredGamesError:
        if self._authentication_phase() is SyncPhase.OFFLINE:
            return RegisteredGamesError(
                RegisteredGamesErrorKind.NETWORK,
                "세션을 확인할 수 없어 충돌 해결을 보류했습니다.",
            )
        return RegisteredGamesError(
            RegisteredGamesErrorKind.AUTH_REQUIRED,
            "다시 로그인한 뒤 충돌을 해결해 주세요.",
        )

    def _require_online(self) -> None:
        if not self._can_sync():
            raise RegisteredGamesError(
                RegisteredGamesErrorKind.NETWORK,
                "현재 프로필에서는 온라인 동기화를 사용할 수 없습니다.",
                code="online_disabled",
            )

    def _registered_cycle(
        self,
        repository: SyncRepository,
        entries: list[OutboxEntry],
        access_token: str,
    ) -> None:
        client = self._registered_client
        if client is None:
            return
        self._require_online()
        client.register_device(
            installation_id=self._profile.installation_id,
            display_name=self._profile.display_name,
            client_version=__version__,
            access_token=access_token,
        )
        if entries:
            self._require_online()
            changes = [
                build_game_change(
                    entry.payload,
                    sync_id=entry.game_sync_id,
                    operation=entry.operation,
                    remote_version=(
                        int(entry.payload["remote_version"])
                        if entry.payload.get("remote_version") is not None
                        else None
                    ),
                )
                for entry in entries
            ]
            result = client.apply_changes(changes, access_token=access_token)
            repository.apply_push_results(
                entries, result.results, completed_at=self._now()
            )

        cursor = repository.pull_cursor()
        self._require_online()
        pull = client.pull_changes(
            after_version=cursor,
            limit=BATCH_SIZE,
            access_token=access_token,
        )
        new_cursor = repository.apply_pull_batch(
            pull.games,
            completed_at=self._now(),
            initial_sync_completed=len(pull.games) < BATCH_SIZE,
        )
        self._require_online()
        client.acknowledge_device_version(
            installation_id=self._profile.installation_id,
            acknowledged_version=new_cursor,
            access_token=access_token,
        )

    def _record_registered_failure(
        self,
        repository: SyncRepository,
        entries: list[OutboxEntry],
        error: RegisteredGamesError,
    ) -> SyncStatus:
        retryable = error.kind in (
            RegisteredGamesErrorKind.NETWORK,
            RegisteredGamesErrorKind.RATE_LIMITED,
            RegisteredGamesErrorKind.SERVER,
        )
        if entries and error.kind is not RegisteredGamesErrorKind.AUTH_REQUIRED:
            repository.record_failure(
                entries,
                code=error.code or error.kind.value,
                detail=str(error),
                retryable=retryable,
                failed_at=self._now(),
                retry_after_seconds=error.retry_after_seconds,
            )
        if error.kind is RegisteredGamesErrorKind.AUTH_REQUIRED:
            phase = SyncPhase.REAUTH_REQUIRED
        elif retryable:
            phase = SyncPhase.OFFLINE
        else:
            phase = SyncPhase.FAILED
        return repository.status(phase=phase, require_initial_sync=True)
