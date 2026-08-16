"""Bitemporal entity relationships with evidence provenance."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class RelationVersion:
    source_entity: str
    relation: str
    target_entity: str
    effective_from: datetime
    known_at: datetime
    source_event_ids: Tuple[str, ...]
    effective_to: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.source_entity.strip() or not self.relation.strip() or not self.target_entity.strip():
            raise ValueError("source, relation and target are required")
        if not self.source_event_ids:
            raise ValueError("relation evidence is required")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")


class RelationStore:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        with sqlite3.connect(self.database_path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS relation_versions (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_entity TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_entity TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    effective_to TEXT,
                    known_at TEXT NOT NULL,
                    source_event_ids_json TEXT NOT NULL,
                    UNIQUE(source_entity, relation, target_entity, effective_from, known_at)
                );
                CREATE INDEX IF NOT EXISTS idx_relation_source
                    ON relation_versions(source_entity, known_at, effective_from);
                CREATE INDEX IF NOT EXISTS idx_relation_target
                    ON relation_versions(target_entity, known_at, effective_from);
                """
            )

    def append(self, item: RelationVersion) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO relation_versions (
                    source_entity, relation, target_entity, effective_from,
                    effective_to, known_at, source_event_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source_entity,
                    item.relation,
                    item.target_entity,
                    item.effective_from.isoformat(),
                    item.effective_to.isoformat() if item.effective_to else None,
                    item.known_at.isoformat(),
                    json.dumps(item.source_event_ids, separators=(",", ":")),
                ),
            )

    def outgoing_as_of(self, source_entity: str, decision_time: datetime) -> Tuple[RelationVersion, ...]:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT * FROM relation_versions
                WHERE source_entity = ? AND known_at <= ? AND effective_from <= ?
                ORDER BY relation, target_entity, effective_from, known_at
                """,
                (source_entity, decision_time.isoformat(), decision_time.isoformat()),
            ).fetchall()

        latest = {}
        for row in rows:
            item = RelationVersion(
                source_entity=row["source_entity"],
                relation=row["relation"],
                target_entity=row["target_entity"],
                effective_from=datetime.fromisoformat(row["effective_from"]),
                effective_to=datetime.fromisoformat(row["effective_to"]) if row["effective_to"] else None,
                known_at=datetime.fromisoformat(row["known_at"]),
                source_event_ids=tuple(json.loads(row["source_event_ids_json"])),
            )
            key = (item.relation, item.target_entity)
            current = latest.get(key)
            if current is None or (item.effective_from, item.known_at) >= (current.effective_from, current.known_at):
                latest[key] = item

        return tuple(
            item for item in latest.values()
            if item.effective_to is None or decision_time < item.effective_to
        )
