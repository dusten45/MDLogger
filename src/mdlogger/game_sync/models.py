"""outbox push 동기화의 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SyncPhase(StrEnum):
    """UI에 노출하는 현재 push 동기화 상태."""

    SYNCED = "synced"
    SYNCING = "syncing"
    PENDING = "pending"
    FAILED = "failed"
    OFFLINE = "offline"
    REAUTH_REQUIRED = "reauth_required"


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """게임별 최신 전송 가능 outbox 항목."""

    id: int
    game_sync_id: str
    operation: str
    payload_version: int
    payload: dict[str, Any]
    attempt_count: int


@dataclass(frozen=True, slots=True)
class SyncStatus:
    """프로필별 push 상태 요약."""

    phase: SyncPhase
    pending_count: int
    failed_count: int
    last_error: str | None = None

    @property
    def display_text(self) -> str:
        if self.phase is SyncPhase.SYNCING:
            return f"동기화 중 · {self.pending_count}건 대기"
        if self.phase is SyncPhase.FAILED:
            return f"동기화 실패 · {self.failed_count}건 확인 필요"
        if self.phase is SyncPhase.OFFLINE:
            return f"오프라인 · {self.pending_count}건 업로드 대기"
        if self.phase is SyncPhase.REAUTH_REQUIRED:
            return f"재로그인 필요 · {self.pending_count}건 업로드 대기"
        if self.pending_count:
            return f"{self.pending_count}건 업로드 대기"
        return "동기화됨"
