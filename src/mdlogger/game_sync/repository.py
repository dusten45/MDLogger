"""worker 전용 SQLite outbox/pull/conflict 저장소."""

from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .. import db
from ..remote.games import PRIVATE_GAME_FIELDS, MutationResult, private_game_payload
from .models import OutboxEntry, SyncConflict, SyncPhase, SyncStatus

_MAX_RETRY_SECONDS = 300
_REMOTE_COMPARE_FIELDS = (*PRIVATE_GAME_FIELDS, "deleted_at")


class SyncRepository:
    """UI 연결과 분리된 worker 전용 SQLite 연결을 소유한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, database_path: Path) -> SyncRepository:
        return cls(db.connect(database_path))

    def close(self) -> None:
        self._connection.close()

    def fetch_due(self, *, limit: int, now: datetime) -> list[OutboxEntry]:
        """충돌 없는 게임별 최신 변경 중 재시도 시각이 된 항목만 가져온다."""
        rows = self._connection.execute(
            """
            SELECT current.*
            FROM sync_outbox AS current
            JOIN games ON games.sync_id = current.game_sync_id
            WHERE games.sync_status <> 'conflict'
              AND current.id = (
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
                self._acknowledge_entry(entry, versions.get(entry.game_sync_id))
            self._mark_success(completed_at)

    def apply_push_results(
        self,
        entries: list[OutboxEntry],
        results: tuple[MutationResult, ...],
        *,
        completed_at: datetime,
    ) -> None:
        """부분 성공과 CAS conflict를 한 로컬 transaction으로 반영한다."""
        by_id = {entry.game_sync_id: entry for entry in entries}
        if set(by_id) != {result.game_id for result in results}:
            raise ValueError("서버 mutation 결과가 outbox batch와 일치하지 않습니다.")
        with self._connection:
            for result in results:
                entry = by_id[result.game_id]
                if result.status == "applied":
                    self._acknowledge_entry(entry, result.change_version)
                elif result.remote is not None:
                    self._reconcile_remote(result.remote, outbox_entry=entry)
                else:
                    self._store_conflict(
                        entry.game_sync_id,
                        entry.payload,
                        {"id": entry.game_sync_id, "missing": True},
                        entry.payload.get("remote_version"),
                    )
            self._mark_success(completed_at)

    def pull_cursor(self) -> int:
        row = self._connection.execute(
            "SELECT last_pulled_version FROM sync_state WHERE id=1"
        ).fetchone()
        return int(row[0])

    def apply_pull_batch(
        self,
        remote_games: Iterable[Mapping[str, Any]],
        *,
        completed_at: datetime,
        initial_sync_completed: bool,
    ) -> int:
        """remote batch와 cursor를 원자적으로 반영하고 새 cursor를 반환한다."""
        rows = [dict(game) for game in remote_games]
        cursor = self.pull_cursor()
        previous = cursor
        with self._connection:
            for remote in rows:
                version = int(remote["change_version"])
                if version <= previous:
                    raise ValueError(
                        "pull batch의 change_version 순서가 올바르지 않습니다."
                    )
                self._reconcile_remote(remote)
                previous = version
            # initial sync는 한 번 완료되면 batch가 정확히 BATCH_SIZE에 걸려도
            # 다시 0으로 되돌리지 않는다(P1-4). 이미 완료됐으면 유지한다.
            state_row = self._connection.execute(
                "SELECT initial_sync_completed FROM sync_state WHERE id=1"
            ).fetchone()
            already_completed = bool(state_row["initial_sync_completed"])
            self._connection.execute(
                """
                UPDATE sync_state
                SET last_pulled_version=?, initial_sync_completed=?,
                    last_server_schema_version=1, last_successful_sync_at=?
                WHERE id=1
                """,
                (
                    previous,
                    int(already_completed or initial_sync_completed),
                    completed_at.isoformat(timespec="seconds"),
                ),
            )
        return previous

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
                    # 재시도 시각을 흩뿌려 재시도 충돌/스탬핑을 완화하는 backoff
                    # jitter 전용이다. 인증 토큰·nonce·암호 키가 아니므로
                    # 암호학적 난수(secrets)가 필요하지 않다 (Semgrep B311 감사 명시).
                    random_jitter = (
                        random.uniform(0, min(delay * 0.25, 15))
                        if jitter is None
                        else jitter
                    )
                    retry_at = failed_at + timedelta(seconds=delay + random_jitter)
                    next_retry_at = retry_at.isoformat(timespec="seconds")
                else:
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
                    UPDATE games SET sync_status=?, last_sync_error=? WHERE sync_id=?
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
                UPDATE games SET sync_status='pending', last_sync_error=NULL
                WHERE sync_status='failed'
                """
            )

    def sync_modes(self, remote_modes: Iterable[Mapping[str, Any]]) -> int:
        """서버 game_modes 목록으로 로컬 play_modes 캐시를 맞춘다 (spec §4.8)."""
        from .modes import sync_play_modes

        return sync_play_modes(self._connection, list(remote_modes))

    def list_conflicts(self) -> list[SyncConflict]:
        rows = self._connection.execute(
            """
            SELECT * FROM sync_conflicts
            WHERE resolved_at IS NULL
            ORDER BY detected_at, id
            """
        ).fetchall()
        return [
            SyncConflict(
                id=int(row["id"]),
                game_sync_id=str(row["game_sync_id"]),
                local_payload=self._json_object(row["local_payload"]),
                remote_payload=self._json_object(row["remote_payload"]),
                base_remote_version=(
                    int(row["base_remote_version"])
                    if row["base_remote_version"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def resolve_conflict(
        self,
        conflict_id: int,
        resolution: str,
        merged_payload: Mapping[str, Any] | None = None,
        *,
        expected_remote_version: int | None = None,
    ) -> None:
        resolved_at = datetime.now().isoformat(timespec="seconds")
        with self._connection:
            row = self._connection.execute(
                "SELECT * FROM sync_conflicts WHERE id=? AND resolved_at IS NULL",
                (conflict_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Conflict {conflict_id} does not exist")
            local = self._json_object(row["local_payload"])
            remote = self._json_object(row["remote_payload"])
            sync_id = str(row["game_sync_id"])
            remote_version = remote.get("change_version")
            if remote_version is None:
                raise ValueError("충돌의 서버 version이 없습니다.")
            if (
                expected_remote_version is not None
                and int(remote_version) != expected_remote_version
            ):
                raise ValueError(
                    "충돌을 확인하는 동안 서버 기록이 다시 변경되었습니다."
                )

            if resolution == "remote":
                self._apply_remote_row(remote, sync_status="synced")
                self._connection.execute(
                    "DELETE FROM sync_outbox WHERE game_sync_id=?", (sync_id,)
                )
            elif resolution in ("local", "merged"):
                selected = (
                    local if resolution == "local" else dict(merged_payload or {})
                )
                selected["sync_id"] = sync_id
                self._apply_selected_resolution(selected, remote)
            else:
                raise ValueError("지원하지 않는 충돌 해결 방식입니다.")
            self._connection.execute(
                """
                UPDATE sync_conflicts SET resolution=?, resolved_at=? WHERE id=?
                """,
                (resolution, resolved_at, conflict_id),
            )

    def status(
        self,
        *,
        phase: SyncPhase | None = None,
        require_initial_sync: bool = False,
    ) -> SyncStatus:
        row = self._connection.execute(
            """
            SELECT COUNT(DISTINCT CASE WHEN games.sync_status <> 'conflict'
                                       THEN sync_outbox.game_sync_id END)
                       AS pending_count,
                   COUNT(DISTINCT CASE
                       WHEN games.sync_status <> 'conflict'
                            AND sync_outbox.last_error_code IS NOT NULL
                       THEN sync_outbox.game_sync_id END) AS failed_count,
                   MAX(CASE WHEN games.sync_status <> 'conflict'
                            THEN sync_outbox.last_error_detail END) AS last_error
            FROM sync_outbox
            JOIN games ON games.sync_id = sync_outbox.game_sync_id
            """
        ).fetchone()
        state = self._connection.execute(
            """
            SELECT last_pulled_version, initial_sync_completed FROM sync_state WHERE id=1
            """
        ).fetchone()
        conflict_count = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE resolved_at IS NULL"
            ).fetchone()[0]
        )
        pending_count = int(row["pending_count"])
        failed_count = int(row["failed_count"])
        initial_completed = bool(state["initial_sync_completed"])
        if phase is None:
            if failed_count:
                phase = SyncPhase.FAILED
            elif pending_count or (require_initial_sync and not initial_completed):
                phase = SyncPhase.PENDING
            else:
                phase = SyncPhase.SYNCED
        return SyncStatus(
            phase=phase,
            pending_count=pending_count,
            failed_count=failed_count,
            last_error=str(row["last_error"]) if row["last_error"] else None,
            conflict_count=conflict_count,
            initial_sync_completed=initial_completed,
            last_pulled_version=int(state["last_pulled_version"]),
        )

    def _acknowledge_entry(
        self, entry: OutboxEntry, remote_version: int | None
    ) -> None:
        self._connection.execute(
            "DELETE FROM sync_outbox WHERE game_sync_id=? AND id<=?",
            (entry.game_sync_id, entry.id),
        )
        remaining = self._connection.execute(
            "SELECT 1 FROM sync_outbox WHERE game_sync_id=? LIMIT 1",
            (entry.game_sync_id,),
        ).fetchone()
        base_payload = json.dumps(
            self._comparable_payload(entry.payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._connection.execute(
            """
            UPDATE games
            SET sync_status=?, remote_version=COALESCE(?, remote_version),
                base_remote_payload=?, last_sync_error=NULL
            WHERE sync_id=?
            """,
            (
                "pending" if remaining is not None else "synced",
                remote_version,
                base_payload,
                entry.game_sync_id,
            ),
        )

    def _reconcile_remote(
        self,
        remote: Mapping[str, Any],
        *,
        outbox_entry: OutboxEntry | None = None,
    ) -> None:
        sync_id = str(remote["id"])
        remote_version = int(remote["change_version"])
        local_row = self._connection.execute(
            "SELECT * FROM games WHERE sync_id=?", (sync_id,)
        ).fetchone()
        if local_row is None:
            self._insert_remote_row(remote)
            return
        local = dict(local_row)
        has_pending = (
            outbox_entry is not None
            or self._connection.execute(
                "SELECT 1 FROM sync_outbox WHERE game_sync_id=? LIMIT 1", (sync_id,)
            ).fetchone()
            is not None
        )
        if not has_pending:
            self._apply_remote_row(remote, sync_status="synced")
            return

        base_raw = local.get("base_remote_payload")
        base = self._json_object(base_raw) if base_raw else None
        local_payload = self._comparable_payload(local)
        remote_payload = self._comparable_payload(remote)
        if base is None:
            if all(
                self._equivalent(field, local_payload[field], remote_payload[field])
                for field in _REMOTE_COMPARE_FIELDS
            ):
                self._apply_remote_row(remote, sync_status="synced")
                if outbox_entry is not None:
                    self._connection.execute(
                        "DELETE FROM sync_outbox WHERE game_sync_id=? AND id<=?",
                        (sync_id, outbox_entry.id),
                    )
                return
            self._store_conflict(sync_id, local, remote, local.get("remote_version"))
            return
        base_payload = self._comparable_payload(base)
        local_changes = self._changed_fields(base_payload, local_payload)
        remote_changes = self._changed_fields(base_payload, remote_payload)
        conflicting = {
            field
            for field in local_changes & remote_changes
            if not self._equivalent(field, local_payload[field], remote_payload[field])
        }
        delete_edit_conflict = (
            "deleted_at" in remote_changes and bool(local_changes - {"deleted_at"})
        ) or ("deleted_at" in local_changes and bool(remote_changes - {"deleted_at"}))
        if conflicting or delete_edit_conflict:
            self._store_conflict(sync_id, local, remote, local.get("remote_version"))
            return

        merged = dict(remote_payload)
        for field in local_changes:
            merged[field] = local_payload[field]
        if not local_changes or all(
            self._equivalent(field, merged[field], remote_payload[field])
            for field in _REMOTE_COMPARE_FIELDS
        ):
            self._apply_remote_row(remote, sync_status="synced")
            if outbox_entry is not None:
                self._connection.execute(
                    "DELETE FROM sync_outbox WHERE game_sync_id=? AND id<=?",
                    (sync_id, outbox_entry.id),
                )
            return

        merged["sync_id"] = sync_id
        merged["remote_version"] = remote_version
        self._update_local_payload(
            sync_id,
            merged,
            remote_version=remote_version,
            base_remote=remote_payload,
            sync_status="pending",
        )
        operation = self._resolution_operation(local_payload, remote_payload)
        self._replace_outbox(sync_id, operation)

    def _store_conflict(
        self,
        sync_id: str,
        local: Mapping[str, Any],
        remote: Mapping[str, Any],
        base_version: Any,
    ) -> None:
        detected_at = datetime.now().isoformat(timespec="seconds")
        existing = self._connection.execute(
            """
            SELECT id FROM sync_conflicts
            WHERE game_sync_id=? AND resolved_at IS NULL
            """,
            (sync_id,),
        ).fetchone()
        values = (
            json.dumps(dict(local), ensure_ascii=False, separators=(",", ":")),
            json.dumps(dict(remote), ensure_ascii=False, separators=(",", ":")),
            int(base_version) if base_version is not None else None,
            detected_at,
        )
        if existing is None:
            self._connection.execute(
                """
                INSERT INTO sync_conflicts
                    (game_sync_id, local_payload, remote_payload,
                     base_remote_version, detected_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sync_id, *values),
            )
        else:
            self._connection.execute(
                """
                UPDATE sync_conflicts
                SET local_payload=?, remote_payload=?, base_remote_version=?, detected_at=?
                WHERE id=?
                """,
                (*values, existing["id"]),
            )
        self._connection.execute(
            """
            UPDATE games SET sync_status='conflict', last_sync_error=? WHERE sync_id=?
            """,
            ("다른 장치의 변경과 충돌했습니다.", sync_id),
        )

    def _insert_remote_row(self, remote: Mapping[str, Any]) -> None:
        payload = self._comparable_payload(remote)
        columns = ", ".join(("sync_id", *_REMOTE_COMPARE_FIELDS))
        placeholders = ", ".join("?" for _ in range(len(_REMOTE_COMPARE_FIELDS) + 1))
        self._connection.execute(
            f"INSERT INTO games ({columns}, remote_version, sync_status, "
            "base_remote_payload, local_updated_at) "
            f"VALUES ({placeholders}, ?, 'synced', ?, ?)",
            (
                str(remote["id"]),
                *(payload[field] for field in _REMOTE_COMPARE_FIELDS),
                int(remote["change_version"]),
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                str(
                    remote.get("updated_at")
                    or datetime.now().isoformat(timespec="seconds")
                ),
            ),
        )

    def _apply_remote_row(self, remote: Mapping[str, Any], *, sync_status: str) -> None:
        payload = self._comparable_payload(remote)
        self._update_local_payload(
            str(remote["id"]),
            payload,
            remote_version=int(remote["change_version"]),
            base_remote=payload,
            sync_status=sync_status,
        )

    def _update_local_payload(
        self,
        sync_id: str,
        payload: Mapping[str, Any],
        *,
        remote_version: int,
        base_remote: Mapping[str, Any],
        sync_status: str,
    ) -> None:
        assignments = ", ".join(f"{field}=?" for field in _REMOTE_COMPARE_FIELDS)
        self._connection.execute(
            f"UPDATE games SET {assignments}, remote_version=?, sync_status=?, "
            "base_remote_payload=?, last_sync_error=NULL WHERE sync_id=?",
            (
                *(payload.get(field) for field in _REMOTE_COMPARE_FIELDS),
                remote_version,
                sync_status,
                json.dumps(
                    dict(base_remote), ensure_ascii=False, separators=(",", ":")
                ),
                sync_id,
            ),
        )

    def _apply_selected_resolution(
        self, selected: Mapping[str, Any], remote: Mapping[str, Any]
    ) -> None:
        sync_id = str(selected["sync_id"])
        remote_payload = self._comparable_payload(remote)
        selected_payload = self._comparable_payload(selected)
        self._update_local_payload(
            sync_id,
            selected_payload,
            remote_version=int(remote["change_version"]),
            base_remote=remote_payload,
            sync_status="pending",
        )
        self._connection.execute(
            "DELETE FROM sync_outbox WHERE game_sync_id=?", (sync_id,)
        )
        self._replace_outbox(
            sync_id, self._resolution_operation(selected_payload, remote_payload)
        )

    def _replace_outbox(self, sync_id: str, operation: str) -> None:
        row = self._connection.execute(
            "SELECT * FROM games WHERE sync_id=?", (sync_id,)
        ).fetchone()
        if row is None:
            raise KeyError(sync_id)
        self._connection.execute(
            "DELETE FROM sync_outbox WHERE game_sync_id=?", (sync_id,)
        )
        self._connection.execute(
            """
            INSERT INTO sync_outbox
                (game_sync_id, operation, payload_version, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                sync_id,
                operation,
                db.PAYLOAD_VERSION,
                json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def _mark_success(self, completed_at: datetime) -> None:
        self._connection.execute(
            "UPDATE sync_state SET last_successful_sync_at=? WHERE id=1",
            (completed_at.isoformat(timespec="seconds"),),
        )

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        parsed = json.loads(str(value))
        if not isinstance(parsed, dict):
            raise ValueError("저장된 sync payload는 JSON object여야 합니다.")
        return parsed

    @staticmethod
    def _comparable_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        private = private_game_payload(payload)
        return {
            field: private.get(field) if field != "deleted_at" else payload.get(field)
            for field in _REMOTE_COMPARE_FIELDS
        }

    @staticmethod
    def _equivalent(field: str, left: Any, right: Any) -> bool:
        if field == "deleted_at":
            return (left is None) == (right is None)
        return left == right

    @classmethod
    def _changed_fields(
        cls, base: Mapping[str, Any], current: Mapping[str, Any]
    ) -> set[str]:
        return {
            field
            for field in _REMOTE_COMPARE_FIELDS
            if not cls._equivalent(field, base.get(field), current.get(field))
        }

    @staticmethod
    def _resolution_operation(
        selected: Mapping[str, Any], remote: Mapping[str, Any]
    ) -> str:
        if selected.get("deleted_at") is not None:
            return "delete"
        if remote.get("deleted_at") is not None:
            return "restore"
        return "upsert"
