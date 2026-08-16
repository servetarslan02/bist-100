"""Versioned state snapshots for ALPHA v4."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class StateSnapshot:
    state_type: str
    entity_id: str
    effective_at: datetime
    known_at: datetime
    payload: Dict[str, Any]
    source_event_ids: tuple[str, ...]
    schema_version: str = "1.0"
    snapshot_id: str = ""

    def __post_init__(self) -> None:
        if not self.state_type.strip():
            raise ValueError("state_type is required")
        if not self.entity_id.strip():
            raise ValueError("entity_id is required")
        if not self.source_event_ids:
            raise ValueError("state snapshot requires source_event_ids")
        if not self.snapshot_id:
            stable = json.dumps(
                {
                    "schema_version": self.schema_version,
                    "state_type": self.state_type,
                    "entity_id": self.entity_id,
                    "effective_at": self.effective_at.isoformat(),
                    "known_at": self.known_at.isoformat(),
                    "payload": self.payload,
                    "source_event_ids": sorted(self.source_event_ids),
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            object.__setattr__(self, "snapshot_id", sha256(stable.encode("utf-8")).hexdigest())


class StateStore:
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
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    state_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    known_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_event_ids_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_state_asof
                    ON state_snapshots(state_type, entity_id, known_at, effective_at);
                """
            )

    def append(self, snapshot: StateSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO state_snapshots (
                    snapshot_id, schema_version, state_type, entity_id,
                    effective_at, known_at, payload_json, source_event_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.schema_version,
                    snapshot.state_type,
                    snapshot.entity_id,
                    snapshot.effective_at.isoformat(),
                    snapshot.known_at.isoformat(),
                    json.dumps(snapshot.payload, sort_keys=True, separators=(",", ":"), default=str),
                    json.dumps(snapshot.source_event_ids, sort_keys=True, separators=(",", ":")),
                ),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StateSnapshot:
        return StateSnapshot(
            snapshot_id=row["snapshot_id"],
            schema_version=row["schema_version"],
            state_type=row["state_type"],
            entity_id=row["entity_id"],
            effective_at=datetime.fromisoformat(row["effective_at"]),
            known_at=datetime.fromisoformat(row["known_at"]),
            payload=json.loads(row["payload_json"]),
            source_event_ids=tuple(json.loads(row["source_event_ids_json"])),
        )

    def as_of(self, state_type: str, entity_id: str, decision_time: datetime) -> Optional[StateSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM state_snapshots
                WHERE state_type = ? AND entity_id = ?
                  AND known_at <= ? AND effective_at <= ?
                ORDER BY effective_at DESC, known_at DESC
                """,
                (
                    state_type,
                    entity_id,
                    decision_time.isoformat(),
                    decision_time.isoformat(),
                ),
            ).fetchall()
        if not rows:
            return None
        return self._from_row(rows[0])
