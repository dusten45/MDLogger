"""worker 전용 SQLite outbox 저장소."""

from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path

from .. import db
from .models import OutboxEntry, SyncPhase, SyncStatus

_MAX_RETRY_SECONDS = 300


class SyncRepository:
    """UI 연결과 분리된 worker 전용 SQLite 연결을 소유한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, database_path: Path) -> SyncRepository:
        connection = db.connect(database_path)
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def fetch_due(self, *, limit: int, now: datetime) -> list[OutboxEntry]:
        """게임별 최신 변경 중 재시도 시각이 된 항목만 가져온다."""
        rows = self._connection.execute(
            """
            SELECT current.*
            FROM sync_outbox AS current
            WHERE current.id = (
                SELECT MAX(candidate.id)
                FROM sync_outbox AS candidate
                WHERE candidate.game_sync_id = current.game_sync_id
            )
              AND (current.next_retry_at IS NULL OR current.next_retry_at <= ?)
            ORDER BY current.id
            LIMIT ?
            """,
            (now.isoformat(timespec="seconds"), limit),
        ).fetchall()
        entries: list[OutboxEntry] = []
        for row in rows:
            payload = json.loads(row["payload"])
            if not isinstance(payload, dict):
                raise ValueError("outbox payload는 JSON object여야 합니다.")
            entries.append(
                OutboxEntry(
                    id=int(row["id"]),
                    game_sync_id=str(row["game_sync_id"]),
                    operation=str(row["operation"]),
                    payload_version=int(row["payload_version"]),
                    payload=payload,
                    attempt_count=int(row["attempt_count"]),
                )
            )
        return entries

    def acknowledge(
        self,
        entries: Iterable[OutboxEntry],
        *,
        remote_versions: Mapping[str, int] | None = None,
        completed_at: datetime,
    ) -> None:
        """응답 대상까지만 지워 요청 중 생긴 새 변경을 보존한다."""
        versions = remote_versions or {}
        with self._connection:
            for entry in entries:
                self._connection.execute(
                    "DELETE FROM sync_outbox WHERE game_sync_id=? AND id<=?",
                    (entry.game_sync_id, entry.id),
                )
                remaining = self._connection.execute(
                    "SELECT 1 FROM sync_outbox WHERE game_sync_id=? LIMIT 1",
                    (entry.game_sync_id,),
                ).fetchone()
                self._connection.execute(
                    """
                    UPDATE games
                    SET sync_status=?, remote_version=COALESCE(?, remote_version),
                        last_sync_error=NULL
                    WHERE sync_id=?
                    """,
                    (
                        "pending" if remaining is not None else "synced",
                        versions.get(entry.game_sync_id),
                        entry.game_sync_id,
                    ),
                )
            self._connection.execute(
                "UPDATE sync_state SET last_successful_sync_at=? WHERE id=1",
                (completed_at.isoformat(timespec="seconds"),),
            )

    def record_failure(
        self,
        entries: Iterable[OutboxEntry],
        *,
        code: str,
        detail: str,
        retryable: bool,
        failed_at: datetime,
        retry_after_seconds: int | None = None,
        jitter: float | None = None,
    ) -> None:
        """실패를 기록하고 일시 오류만 제한된 backoff로 재시도한다."""
        safe_detail = detail[:500]
        with self._connection:
            for entry in entries:
                attempt_count = entry.attempt_count + 1
                if retryable:
                    base_delay = min(2 ** min(attempt_count, 8), _MAX_RETRY_SECONDS)
                    delay = max(base_delay, retry_after_seconds or 0)
                    random_jitter = (
                        random.uniform(0, min(delay * 0.25, 15))
                        if jitter is None
                        else jitter
                    )
                    retry_at = failed_at + timedelta(seconds=delay + random_jitter)
                    next_retry_at = retry_at.isoformat(timespec="seconds")
                else:
                    # 영구 오류는 자동 선택 대상에서 제외하고 수동 재시도만 허용한다.
                    next_retry_at = "9999-12-31T23:59:59"
                self._connection.execute(
                    """
                    UPDATE sync_outbox
                    SET attempt_count=?, next_retry_at=?, last_error_code=?,
                        last_error_detail=?
                    WHERE id=?
                    """,
                    (attempt_count, next_retry_at, code, safe_detail, entry.id),
                )
                self._connection.execute(
                    """
                    UPDATE games
                    SET sync_status=?, last_sync_error=?
                    WHERE sync_id=?
                    """,
                    (
                        "pending" if retryable else "failed",
                        safe_detail,
                        entry.game_sync_id,
                    ),
                )

    def retry_failed(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE sync_outbox
                SET next_retry_at=NULL, last_error_code=NULL, last_error_detail=NULL
                WHERE last_error_code IS NOT NULL
                """
            )
            self._connection.execute(
                """
                UPDATE games
                SET sync_status='pending', last_sync_error=NULL
                WHERE sync_status='failed'
                """
            )

    def status(self, *, phase: SyncPhase | None = None) -> SyncStatus:
        row = self._connection.execute(
            """
            SELECT COUNT(DISTINCT game_sync_id) AS pending_count,
                   COUNT(DISTINCT CASE
                       WHEN last_error_code IS NOT NULL THEN game_sync_id
                   END) AS failed_count,
                   MAX(last_error_detail) AS last_error
            FROM sync_outbox
            """
        ).fetchone()
        pending_count = int(row["pending_count"])
        failed_count = int(row["failed_count"])
        if phase is None:
            if failed_count:
                phase = SyncPhase.FAILED
            elif pending_count:
                phase = SyncPhase.PENDING
            else:
                phase = SyncPhase.SYNCED
        return SyncStatus(
            phase=phase,
            pending_count=pending_count,
            failed_count=failed_count,
            last_error=str(row["last_error"]) if row["last_error"] else None,
        )
