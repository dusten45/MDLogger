"""profile 종류별 outbox push 동기화 엔진."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..profiles import ProfileContext, ProfileKind
from ..remote.games import (
    RegisteredGamesClient,
    RegisteredGamesError,
    RegisteredGamesErrorKind,
    build_registered_game,
)
from ..remote.guest_ingest import (
    GuestIngestClient,
    GuestIngestError,
    GuestIngestErrorKind,
    build_observation,
    build_withdrawal,
)
from .models import OutboxEntry, SyncPhase, SyncStatus
from .repository import SyncRepository

BATCH_SIZE = 100
TokenProvider = Callable[[], str | None]
TokenRefresher = Callable[[], str | None]


class SyncEngine:
    """한 번의 제한된 push batch를 실행하고 로컬 outbox를 반영한다."""

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
            return repository.status(phase=phase)
        finally:
            repository.close()

    def retry_failed(self) -> None:
        repository = self._repository_factory(self._profile.database_path)
        try:
            repository.retry_failed()
        finally:
            repository.close()

    def run_once(self) -> SyncStatus:
        repository = self._repository_factory(self._profile.database_path)
        try:
            entries = repository.fetch_due(limit=BATCH_SIZE, now=self._now())
            if not entries:
                return repository.status()
            if self._profile.kind is ProfileKind.GUEST:
                return self._push_guest(repository, entries)
            return self._push_registered(repository, entries)
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

    def _push_registered(
        self, repository: SyncRepository, entries: list[OutboxEntry]
    ) -> SyncStatus:
        client = self._registered_client
        user_id = self._profile.remote_user_id
        if client is None or user_id is None or self._token_provider is None:
            return repository.status(phase=SyncPhase.OFFLINE)
        access_token = self._token_provider()
        if not access_token:
            return repository.status(phase=SyncPhase.REAUTH_REQUIRED)
        games = [
            build_registered_game(
                entry.payload,
                sync_id=entry.game_sync_id,
                user_id=user_id,
                operation=entry.operation,
                payload_version=entry.payload_version,
            )
            for entry in entries
        ]
        try:
            result = client.upsert_batch(games, access_token=access_token)
        except RegisteredGamesError as error:
            if (
                error.kind is RegisteredGamesErrorKind.AUTH_REQUIRED
                and self._token_refresher is not None
            ):
                refreshed_token = self._token_refresher()
                if refreshed_token:
                    try:
                        result = client.upsert_batch(
                            games, access_token=refreshed_token
                        )
                    except RegisteredGamesError as retry_error:
                        return self._record_registered_failure(
                            repository, entries, retry_error
                        )
                else:
                    return repository.status(phase=SyncPhase.REAUTH_REQUIRED)
            else:
                return self._record_registered_failure(repository, entries, error)
        repository.acknowledge(
            entries,
            remote_versions=result.remote_versions,
            completed_at=self._now(),
        )
        return repository.status()

    def _record_registered_failure(
        self,
        repository: SyncRepository,
        entries: list[OutboxEntry],
        error: RegisteredGamesError,
    ) -> SyncStatus:
        retryable = error.kind in (
            RegisteredGamesErrorKind.NETWORK,
            RegisteredGamesErrorKind.SERVER,
        )
        repository.record_failure(
            entries,
            code=error.code or error.kind.value,
            detail=str(error),
            retryable=retryable,
            failed_at=self._now(),
        )
        if error.kind is RegisteredGamesErrorKind.AUTH_REQUIRED:
            phase = SyncPhase.REAUTH_REQUIRED
        elif retryable:
            phase = SyncPhase.OFFLINE
        else:
            phase = SyncPhase.FAILED
        return repository.status(phase=phase)
