"""Durable idempotent job leases for ALPHA v4 workers and schedulers."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class JobRun:
    run_id: str
    job_name: str
    owner_id: str
    idempotency_key: str
    started_at: datetime
    finished_at: datetime | None
    status: str


class JobCoordinator:
    """Serialize logical jobs across processes with durable SQLite leases."""

    FINAL_STATUSES: ClassVar[frozenset[str]] = frozenset(
        {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"}
    )

    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_leases (
                    job_name TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    lease_until TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_runs (
                    run_id TEXT PRIMARY KEY,
                    job_name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    UNIQUE(job_name, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_job_runs_name_time
                    ON job_runs(job_name, started_at);
                """
            )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("job timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    def try_start(
        self,
        *,
        job_name: str,
        owner_id: str,
        idempotency_key: str,
        started_at: datetime,
        lease_for: timedelta,
    ) -> JobRun | None:
        """Acquire a job once; return None when already leased or already attempted."""
        if not job_name.strip() or not owner_id.strip() or not idempotency_key.strip():
            raise ValueError("job_name, owner_id and idempotency_key are required")
        if lease_for <= timedelta(0):
            raise ValueError("lease_for must be positive")

        started_at = self._utc(started_at)
        lease_until = started_at + lease_for
        run_id = uuid.uuid4().hex

        connection = self._connect()
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")

            prior = connection.execute(
                """
                SELECT run_id FROM job_runs
                WHERE job_name = ? AND idempotency_key = ?
                """,
                (job_name, idempotency_key),
            ).fetchone()
            if prior is not None:
                connection.execute("ROLLBACK")
                return None

            lease = connection.execute(
                """
                SELECT owner_id, run_id, lease_until
                FROM job_leases
                WHERE job_name = ?
                """,
                (job_name,),
            ).fetchone()
            if lease is not None:
                current_lease_until = datetime.fromisoformat(lease["lease_until"])
                if current_lease_until > started_at:
                    connection.execute("ROLLBACK")
                    return None
                connection.execute(
                    """
                    UPDATE job_runs
                    SET status = 'EXPIRED', finished_at = ?
                    WHERE run_id = ? AND status = 'RUNNING'
                    """,
                    (started_at.isoformat(), lease["run_id"]),
                )

            connection.execute(
                """
                INSERT INTO job_leases (
                    job_name, owner_id, run_id, acquired_at, lease_until
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_name) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    run_id = excluded.run_id,
                    acquired_at = excluded.acquired_at,
                    lease_until = excluded.lease_until
                """,
                (
                    job_name,
                    owner_id,
                    run_id,
                    started_at.isoformat(),
                    lease_until.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO job_runs (
                    run_id, job_name, owner_id, idempotency_key,
                    started_at, finished_at, status
                ) VALUES (?, ?, ?, ?, ?, NULL, 'RUNNING')
                """,
                (run_id, job_name, owner_id, idempotency_key, started_at.isoformat()),
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

        return JobRun(
            run_id=run_id,
            job_name=job_name,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            started_at=started_at,
            finished_at=None,
            status="RUNNING",
        )

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: datetime,
    ) -> JobRun:
        status = status.upper()
        if status not in self.FINAL_STATUSES:
            raise ValueError(f"invalid final job status: {status}")
        finished_at = self._utc(finished_at)

        connection = self._connect()
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM job_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise KeyError(run_id)
            if row["status"] != "RUNNING":
                connection.execute("ROLLBACK")
                raise ValueError("job run is already final")
            started_at = datetime.fromisoformat(row["started_at"])
            if finished_at < started_at:
                connection.execute("ROLLBACK")
                raise ValueError("finished_at cannot be before started_at")

            connection.execute(
                """
                UPDATE job_runs
                SET status = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (status, finished_at.isoformat(), run_id),
            )
            connection.execute(
                "DELETE FROM job_leases WHERE job_name = ? AND run_id = ?",
                (row["job_name"], run_id),
            )
            connection.execute("COMMIT")
        except (sqlite3.Error, ValueError, KeyError):
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

        return JobRun(
            run_id=run_id,
            job_name=row["job_name"],
            owner_id=row["owner_id"],
            idempotency_key=row["idempotency_key"],
            started_at=started_at,
            finished_at=finished_at,
            status=status,
        )

    def get(self, run_id: str) -> JobRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return JobRun(
            run_id=row["run_id"],
            job_name=row["job_name"],
            owner_id=row["owner_id"],
            idempotency_key=row["idempotency_key"],
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=(
                datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None
            ),
            status=row["status"],
        )
