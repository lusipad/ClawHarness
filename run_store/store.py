from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Sequence

VALID_STATUSES = (
    "queued",
    "claimed",
    "planning",
    "coding",
    "opening_pr",
    "awaiting_ci",
    "awaiting_review",
    "awaiting_human",
    "completed",
    "failed",
    "cancelled",
)

TERMINAL_STATUSES = ("completed", "failed", "cancelled")
ACTIVE_STATUSES = tuple(status for status in VALID_STATUSES if status not in TERMINAL_STATUSES)

_ALLOWED_STATUS_TRANSITIONS = {
    "queued": {"claimed", "cancelled", "failed"},
    "claimed": {"planning", "cancelled", "failed"},
    "planning": {"coding", "awaiting_human", "cancelled", "failed"},
    "coding": {"opening_pr", "awaiting_ci", "awaiting_review", "awaiting_human", "cancelled", "failed"},
    "opening_pr": {"awaiting_ci", "awaiting_review", "awaiting_human", "cancelled", "failed"},
    "awaiting_ci": {"coding", "completed", "awaiting_human", "cancelled", "failed"},
    "awaiting_review": {"coding", "completed", "awaiting_human", "cancelled", "failed"},
    "awaiting_human": {"planning", "coding", "cancelled", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_timestamp(value: str | None) -> str:
    return value or utc_now()


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dump_payload(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class TaskRun:
    run_id: str
    provider_type: str
    task_id: str
    task_key: str
    session_id: str
    executor_type: str
    status: str = "claimed"
    repo_id: str | None = None
    branch_name: str | None = None
    workspace_path: str | None = None
    pr_id: str | None = None
    ci_run_id: str | None = None
    chat_thread_id: str | None = None
    retry_count: int = 0
    started_at: str | None = None
    updated_at: str | None = None
    last_error: str | None = None

    def normalized(self, *, timestamp: str | None = None) -> "TaskRun":
        stamp = _normalize_timestamp(timestamp)
        status = self.status
        if status not in VALID_STATUSES:
            raise ValueError(f"Unknown status: {status}")
        return replace(
            self,
            started_at=self.started_at or stamp,
            updated_at=self.updated_at or stamp,
        )


@dataclass(frozen=True)
class ClaimRequest:
    fingerprint: str
    source_type: str
    run: TaskRun
    owner: str
    source_id: str | None = None
    dedupe_ttl_seconds: int = 86400
    lock_ttl_seconds: int = 1800


@dataclass(frozen=True)
class ClaimOutcome:
    accepted: bool
    reason: str
    run: TaskRun | None = None
    existing_run: TaskRun | None = None


@dataclass(frozen=True)
class LockResult:
    acquired: bool
    lock_key: str
    run_id: str | None = None
    owner: str | None = None
    expires_at: str | None = None


class StatusTransitionError(ValueError):
    pass


class RunStore:
    def __init__(self, db_path: str | Path, *, schema_path: str | Path | None = None, busy_timeout_ms: int = 5000):
        self.db_path = Path(db_path)
        self.schema_path = Path(schema_path) if schema_path else Path(__file__).with_name("schema.sql")
        self.busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema = self.schema_path.read_text(encoding="utf-8")
        with self._connect() as connection:
            connection.executescript(schema)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def create_run(self, run: TaskRun, *, connection: sqlite3.Connection | None = None) -> TaskRun:
        normalized = run.normalized()
        owns_connection = connection is None
        if owns_connection:
            with self._transaction() as connection:
                return self.create_run(normalized, connection=connection)

        assert connection is not None
        connection.execute(
            """
            INSERT INTO task_runs (
              run_id, provider_type, task_id, task_key, repo_id, branch_name,
              workspace_path, pr_id, ci_run_id, chat_thread_id, session_id,
              executor_type, status, retry_count, started_at, updated_at, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized.run_id,
                normalized.provider_type,
                normalized.task_id,
                normalized.task_key,
                normalized.repo_id,
                normalized.branch_name,
                normalized.workspace_path,
                normalized.pr_id,
                normalized.ci_run_id,
                normalized.chat_thread_id,
                normalized.session_id,
                normalized.executor_type,
                normalized.status,
                normalized.retry_count,
                normalized.started_at,
                normalized.updated_at,
                normalized.last_error,
            ),
        )
        return normalized

    def get_run(self, run_id: str) -> TaskRun | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM task_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_run(row)

    def find_active_run_by_task_key(self, task_key: str) -> TaskRun | None:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM task_runs
                WHERE task_key = ? AND status IN ({placeholders})
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (task_key, *ACTIVE_STATUSES),
            ).fetchone()
        return self._row_to_run(row)

    def find_run_by_pr_id(self, pr_id: str) -> TaskRun | None:
        return self._find_run_by_field("pr_id", pr_id)

    def find_run_by_ci_run_id(self, ci_run_id: str) -> TaskRun | None:
        return self._find_run_by_field("ci_run_id", ci_run_id)

    def _find_run_by_field(self, field: str, value: str) -> TaskRun | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM task_runs WHERE {field} = ? ORDER BY started_at DESC LIMIT 1",
                (value,),
            ).fetchone()
        return self._row_to_run(row)

    def claim_run(self, request: ClaimRequest, *, now: str | None = None) -> ClaimOutcome:
        run = request.run.normalized(timestamp=now)
        current_time = _parse_timestamp(run.updated_at)
        dedupe_expires_at = (current_time + timedelta(seconds=request.dedupe_ttl_seconds)).isoformat().replace("+00:00", "Z")
        lock_expires_at = (current_time + timedelta(seconds=request.lock_ttl_seconds)).isoformat().replace("+00:00", "Z")

        with self._transaction() as connection:
            self._delete_expired_state(connection, now=run.updated_at)

            existing_run = self._find_active_run_by_task_key(connection, run.task_key)
            if existing_run is not None:
                return ClaimOutcome(
                    accepted=False,
                    reason="already_claimed",
                    existing_run=existing_run,
                )

            dedupe_created = self._record_event(
                connection,
                fingerprint=request.fingerprint,
                source_type=request.source_type,
                source_id=request.source_id,
                received_at=run.updated_at,
                expires_at=dedupe_expires_at,
            )
            if not dedupe_created:
                return ClaimOutcome(accepted=False, reason="duplicate_event")

            created_run = self.create_run(run, connection=connection)
            lock = self._acquire_lock(
                connection,
                lock_key=run.task_key,
                run_id=run.run_id,
                owner=request.owner,
                acquired_at=run.updated_at,
                expires_at=lock_expires_at,
            )
            if not lock.acquired:
                raise RuntimeError(f"Expected lock acquisition to succeed for task_key={run.task_key}")

            self.append_audit(
                run.run_id,
                "run_claimed",
                payload={
                    "task_key": run.task_key,
                    "owner": request.owner,
                    "source_type": request.source_type,
                },
                created_at=run.updated_at,
                connection=connection,
            )
            return ClaimOutcome(accepted=True, reason="claimed", run=created_run)

    def record_event(
        self,
        fingerprint: str,
        *,
        source_type: str,
        source_id: str | None = None,
        received_at: str | None = None,
        expires_at: str | None = None,
    ) -> bool:
        received = _normalize_timestamp(received_at)
        expiry = expires_at or (_parse_timestamp(received) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        with self._transaction() as connection:
            self._delete_expired_state(connection, now=received)
            return self._record_event(
                connection,
                fingerprint=fingerprint,
                source_type=source_type,
                source_id=source_id,
                received_at=received,
                expires_at=expiry,
            )

    def _record_event(
        self,
        connection: sqlite3.Connection,
        *,
        fingerprint: str,
        source_type: str,
        source_id: str | None,
        received_at: str,
        expires_at: str,
    ) -> bool:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO event_dedupe (
              fingerprint, source_type, source_id, received_at, expires_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (fingerprint, source_type, source_id, received_at, expires_at),
        )
        return cursor.rowcount == 1

    def acquire_lock(
        self,
        lock_key: str,
        *,
        run_id: str,
        owner: str,
        acquired_at: str | None = None,
        ttl_seconds: int = 1800,
    ) -> LockResult:
        claimed_at = _normalize_timestamp(acquired_at)
        expires_at = (_parse_timestamp(claimed_at) + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
        with self._transaction() as connection:
            self._delete_expired_state(connection, now=claimed_at)
            return self._acquire_lock(
                connection,
                lock_key=lock_key,
                run_id=run_id,
                owner=owner,
                acquired_at=claimed_at,
                expires_at=expires_at,
            )

    def _acquire_lock(
        self,
        connection: sqlite3.Connection,
        *,
        lock_key: str,
        run_id: str,
        owner: str,
        acquired_at: str,
        expires_at: str,
    ) -> LockResult:
        existing = connection.execute(
            "SELECT run_id, owner, expires_at FROM task_locks WHERE lock_key = ?",
            (lock_key,),
        ).fetchone()
        if existing is not None:
            return LockResult(
                acquired=False,
                lock_key=lock_key,
                run_id=existing["run_id"],
                owner=existing["owner"],
                expires_at=existing["expires_at"],
            )

        connection.execute(
            """
            INSERT INTO task_locks (lock_key, run_id, owner, acquired_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (lock_key, run_id, owner, acquired_at, expires_at),
        )
        return LockResult(
            acquired=True,
            lock_key=lock_key,
            run_id=run_id,
            owner=owner,
            expires_at=expires_at,
        )

    def release_lock(self, lock_key: str, *, owner: str | None = None) -> bool:
        query = "DELETE FROM task_locks WHERE lock_key = ?"
        params: list[str] = [lock_key]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)
        with self._transaction() as connection:
            cursor = connection.execute(query, tuple(params))
        return cursor.rowcount == 1

    def transition_status(
        self,
        run_id: str,
        *,
        to_status: str,
        expected_from: str | Sequence[str] | None = None,
        last_error: str | None = None,
        retry_increment: bool = False,
        released_lock: bool = False,
        updated_at: str | None = None,
    ) -> TaskRun:
        if to_status not in VALID_STATUSES:
            raise StatusTransitionError(f"Unknown status: {to_status}")

        stamp = _normalize_timestamp(updated_at)
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM task_runs WHERE run_id = ?", (run_id,)).fetchone()
            current = self._row_to_run(row)
            if current is None:
                raise KeyError(f"Run not found: {run_id}")

            allowed = _ALLOWED_STATUS_TRANSITIONS[current.status]
            if to_status not in allowed and to_status != current.status:
                raise StatusTransitionError(f"Invalid transition {current.status} -> {to_status}")

            if expected_from is not None:
                expected = {expected_from} if isinstance(expected_from, str) else set(expected_from)
                if current.status not in expected:
                    raise StatusTransitionError(
                        f"Run {run_id} is in status {current.status}, expected one of {sorted(expected)}"
                    )

            new_retry_count = current.retry_count + 1 if retry_increment else current.retry_count
            connection.execute(
                """
                UPDATE task_runs
                SET status = ?, retry_count = ?, last_error = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (to_status, new_retry_count, last_error, stamp, run_id),
            )

            if released_lock or to_status in TERMINAL_STATUSES:
                connection.execute("DELETE FROM task_locks WHERE run_id = ?", (run_id,))

            self.append_audit(
                run_id,
                "status_transition",
                payload={
                    "from": current.status,
                    "to": to_status,
                    "retry_increment": retry_increment,
                    "released_lock": released_lock or to_status in TERMINAL_STATUSES,
                },
                created_at=stamp,
                connection=connection,
            )
            updated = connection.execute("SELECT * FROM task_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_run(updated)

    def update_run_fields(
        self,
        run_id: str,
        *,
        repo_id: str | None = None,
        session_id: str | None = None,
        branch_name: str | None = None,
        workspace_path: str | None = None,
        pr_id: str | None = None,
        ci_run_id: str | None = None,
        chat_thread_id: str | None = None,
        updated_at: str | None = None,
    ) -> TaskRun:
        updates = {
            "repo_id": repo_id,
            "session_id": session_id,
            "branch_name": branch_name,
            "workspace_path": workspace_path,
            "pr_id": pr_id,
            "ci_run_id": ci_run_id,
            "chat_thread_id": chat_thread_id,
        }
        assignments = []
        params: list[Any] = []
        for field, value in updates.items():
            if value is not None:
                assignments.append(f"{field} = ?")
                params.append(value)

        if not assignments:
            run = self.get_run(run_id)
            if run is None:
                raise KeyError(f"Run not found: {run_id}")
            return run

        stamp = _normalize_timestamp(updated_at)
        assignments.append("updated_at = ?")
        params.append(stamp)
        params.append(run_id)
        query = f"UPDATE task_runs SET {', '.join(assignments)} WHERE run_id = ?"
        with self._transaction() as connection:
            cursor = connection.execute(query, tuple(params))
            if cursor.rowcount != 1:
                raise KeyError(f"Run not found: {run_id}")
            row = connection.execute("SELECT * FROM task_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_run(row)

    def append_audit(
        self,
        run_id: str,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        stamp = _normalize_timestamp(created_at)
        owns_connection = connection is None
        if owns_connection:
            with self._transaction() as connection:
                self.append_audit(run_id, event_type, payload=payload, created_at=stamp, connection=connection)
                return

        assert connection is not None
        connection.execute(
            """
            INSERT INTO run_audit (run_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, event_type, _dump_payload(payload), stamp),
        )

    def list_audit(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, run_id, event_type, payload_json, created_at
                FROM run_audit
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "event_type": row["event_type"],
                "payload_json": row["payload_json"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _delete_expired_state(self, connection: sqlite3.Connection, *, now: str) -> None:
        connection.execute("DELETE FROM task_locks WHERE expires_at <= ?", (now,))
        connection.execute("DELETE FROM event_dedupe WHERE expires_at <= ?", (now,))

    def _find_active_run_by_task_key(self, connection: sqlite3.Connection, task_key: str) -> TaskRun | None:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        row = connection.execute(
            f"""
            SELECT * FROM task_runs
            WHERE task_key = ? AND status IN ({placeholders})
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (task_key, *ACTIVE_STATUSES),
        ).fetchone()
        return self._row_to_run(row)

    def _row_to_run(self, row: sqlite3.Row | None) -> TaskRun | None:
        if row is None:
            return None
        return TaskRun(
            run_id=row["run_id"],
            provider_type=row["provider_type"],
            task_id=row["task_id"],
            task_key=row["task_key"],
            repo_id=row["repo_id"],
            branch_name=row["branch_name"],
            workspace_path=row["workspace_path"],
            pr_id=row["pr_id"],
            ci_run_id=row["ci_run_id"],
            chat_thread_id=row["chat_thread_id"],
            session_id=row["session_id"],
            executor_type=row["executor_type"],
            status=row["status"],
            retry_count=row["retry_count"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            last_error=row["last_error"],
        )
