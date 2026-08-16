"""Small, auditable persistence primitives for the V4 rebuild.

SQLite is used here as a deterministic bootstrap store for contract tests and local
operation. It is not a declaration that the final analytical architecture must use
SQLite. The invariant being established is append-only, restart-safe event history.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .contracts import CanonicalEvent, EvidenceRef


class DuplicateEventError(RuntimeError):
    pass


class AppendOnlyEventStore:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_events (
                    event_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_timestamp TEXT NOT NULL,
                    ingest_timestamp TEXT NOT NULL,
                    effective_timestamp TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_ingest ON canonical_events(ingest_timestamp)"
            )

    @staticmethod
    def _evidence_to_json(evidence: tuple[EvidenceRef, ...]) -> str:
        return json.dumps(
            [
                {
                    "source_id": item.source_id,
                    "source_timestamp": item.source_timestamp.isoformat(),
                    "ingest_timestamp": item.ingest_timestamp.isoformat(),
                    "locator": item.locator,
                    "evidence_text": item.evidence_text,
                }
                for item in evidence
            ],
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> CanonicalEvent:
        evidence = tuple(
            EvidenceRef(
                source_id=item["source_id"],
                source_timestamp=datetime.fromisoformat(item["source_timestamp"]),
                ingest_timestamp=datetime.fromisoformat(item["ingest_timestamp"]),
                locator=item["locator"],
                evidence_text=item.get("evidence_text"),
            )
            for item in json.loads(row["evidence_json"])
        )
        return CanonicalEvent(
            event_id=row["event_id"],
            schema_version=row["schema_version"],
            event_type=row["event_type"],
            source_id=row["source_id"],
            source_timestamp=datetime.fromisoformat(row["source_timestamp"]),
            ingest_timestamp=datetime.fromisoformat(row["ingest_timestamp"]),
            effective_timestamp=datetime.fromisoformat(row["effective_timestamp"]),
            entities=tuple(json.loads(row["entities_json"])),
            payload=json.loads(row["payload_json"]),
            evidence=evidence,
        )

    def append(self, event: CanonicalEvent) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO canonical_events (
                        event_id, schema_version, event_type, source_id,
                        source_timestamp, ingest_timestamp, effective_timestamp,
                        entities_json, payload_json, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.schema_version,
                        event.event_type,
                        event.source_id,
                        event.source_timestamp.isoformat(),
                        event.ingest_timestamp.isoformat(),
                        event.effective_timestamp.isoformat(),
                        json.dumps(
                            event.entities, sort_keys=True, separators=(",", ":")
                        ),
                        json.dumps(
                            event.payload, sort_keys=True, separators=(",", ":")
                        ),
                        self._evidence_to_json(event.evidence),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEventError(event.event_id) from exc

    def get(self, event_id: str) -> CanonicalEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM canonical_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return None if row is None else self._row_to_event(row)

    def list_known_at(self, decision_time: datetime) -> list[CanonicalEvent]:
        """Return only information that had actually been ingested by decision_time."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM canonical_events
                WHERE ingest_timestamp <= ?
                ORDER BY ingest_timestamp ASC, event_id ASC
                """,
                (decision_time.isoformat(),),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM canonical_events"
            ).fetchone()
        assert row is not None
        return int(row["count"])
