"""Persistent source definitions and measured reliability history."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

from .source_registry import SourceKind, SourceRecord


class PersistentSourceRegistry:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_definitions (
                    source_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    access_method TEXT NOT NULL,
                    timezone_name TEXT NOT NULL,
                    freshness_seconds REAL NOT NULL,
                    enabled INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_observations (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    detail TEXT,
                    FOREIGN KEY(source_id) REFERENCES source_definitions(source_id)
                );
                CREATE INDEX IF NOT EXISTS idx_source_obs
                    ON source_observations(source_id, sequence);
                """
            )

    def register(self, record: SourceRecord) -> None:
        if any(
            value != 0
            for value in (
                record.successful_observations,
                record.failed_observations,
                record.contradictions,
            )
        ):
            raise ValueError("persistent registration requires zero initial counters")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO source_definitions (
                    source_id, kind, owner, access_method, timezone_name,
                    freshness_seconds, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source_id,
                    record.kind.value,
                    record.owner,
                    record.access_method,
                    record.timezone_name,
                    record.freshness_limit.total_seconds(),
                    1 if record.enabled else 0,
                ),
            )

    def record_observation(
        self,
        source_id: str,
        outcome: str,
        *,
        observed_at: datetime,
        detail: str | None = None,
    ) -> None:
        normalized = outcome.upper()
        if normalized not in {"SUCCESS", "FAILURE", "CONTRADICTION"}:
            raise ValueError("outcome must be SUCCESS, FAILURE or CONTRADICTION")
        # Explicit existence check gives a clearer error than a DB-specific FK setting.
        self.get(source_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO source_observations (source_id, observed_at, outcome, detail)
                VALUES (?, ?, ?, ?)
                """,
                (source_id, observed_at.isoformat(), normalized, detail),
            )

    def get(self, source_id: str) -> SourceRecord:
        with self._connect() as connection:
            definition = connection.execute(
                "SELECT * FROM source_definitions WHERE source_id = ?", (source_id,)
            ).fetchone()
            if definition is None:
                raise KeyError(f"unknown source: {source_id}")
            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN outcome = 'SUCCESS' THEN 1 ELSE 0 END) AS successes,
                    SUM(CASE WHEN outcome = 'FAILURE' THEN 1 ELSE 0 END) AS failures,
                    SUM(CASE WHEN outcome = 'CONTRADICTION' THEN 1 ELSE 0 END) AS contradictions
                FROM source_observations
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()

        return SourceRecord(
            source_id=definition["source_id"],
            kind=SourceKind(definition["kind"]),
            owner=definition["owner"],
            access_method=definition["access_method"],
            timezone_name=definition["timezone_name"],
            freshness_limit=timedelta(seconds=float(definition["freshness_seconds"])),
            enabled=bool(definition["enabled"]),
            successful_observations=int(counts["successes"] or 0),
            failed_observations=int(counts["failures"] or 0),
            contradictions=int(counts["contradictions"] or 0),
        )

    def enabled_sources(self) -> Tuple[SourceRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT source_id FROM source_definitions WHERE enabled = 1 ORDER BY source_id"
            ).fetchall()
        return tuple(self.get(row["source_id"]) for row in rows)
