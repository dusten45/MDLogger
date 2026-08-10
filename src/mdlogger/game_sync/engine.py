"""outbox push, change-version pull 및 conflict 조정 엔진."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .. import __version__
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
from .models import OutboxEntry, SyncConflict, SyncPhase, SyncStatus
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
        token_provider: TokenProvider | None = None,
        token_refresher: TokenRefresher | None = None,
        repository_factory: Callable[[Path], SyncRepository] = SyncRepository.open,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._profile = profile
        self._registered_client = registered_client
        self._guest_client = guest_client
        self._token_provider = token_provider
        self._token_refresher = token_refresher
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
    ) -> None:
        repository = self._repository_factory(self._profile.database_path)
        try:
            repository.resolve_conflict(
                conflict_id,
                resolution,
                merged_payload,
                expected_remote_version=expected_remote_version,
            )
        finally:
            repository.close()

    def run_once(self) -> SyncStatus:
        repository = self._repository_factory(self._profile.database_path)
        try:
            entries = repository.fetch_due(limit=BATCH_SIZE, now=self._now())
            if self._profile.kind is ProfileKind.GUEST:
                if not entries:
                    return repository.status()
                return self._push_guest(repository, entries)
            return self._sync_registered(repository, entries)
        finally:
            repository.close()

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
        if client is None or self._token_provider is None:
            return repository.status(phase=SyncPhase.OFFLINE)
        token = self._token_provider()
        if not token:
            return repository.status(phase=SyncPhase.REAUTH_REQUIRED)
        try:
            self._registered_cycle(repository, entries, token)
        except RegisteredGamesError as error:
            if (
                error.kind is RegisteredGamesErrorKind.AUTH_REQUIRED
                and self._token_refresher is not None
            ):
                refreshed = self._token_refresher()
                if refreshed:
                    try:
                        self._registered_cycle(repository, entries, refreshed)
                    except RegisteredGamesError as retry_error:
                        return self._record_registered_failure(
                            repository, entries, retry_error
                        )
                else:
                    return repository.status(phase=SyncPhase.REAUTH_REQUIRED)
            else:
                return self._record_registered_failure(repository, entries, error)
        return repository.status(require_initial_sync=True)

    def _registered_cycle(
        self,
        repository: SyncRepository,
        entries: list[OutboxEntry],
        access_token: str,
    ) -> None:
        client = self._registered_client
        if client is None:
            return
        client.register_device(
            installation_id=self._profile.installation_id,
            display_name=self._profile.display_name,
            client_version=__version__,
            access_token=access_token,
        )
        if entries:
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
        if entries:
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
