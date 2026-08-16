"""Tamper-evident append-only audit chain for ALPHA v4.

SQLite cannot by itself make an administrator incapable of editing bytes. The V4
bootstrap therefore adds cryptographic hash chaining so silent history rewrites are
detectable during verification/replay. Production storage can later add WORM/object
retention without changing this audit contract.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    sequence: int
    entry_id: str
    event_type: str
    created_at: datetime
    payload: Mapping[str, Any]
    previous_hash: str
    entry_hash: str


@dataclass(frozen=True)
class AuditVerification:
    valid: bool
    checked_entries: int
    first_invalid_sequence: int | None
    reason: str | None


class AuditLedger:
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
                CREATE TABLE IF NOT EXISTS audit_entries (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_audit_event_type
                    ON audit_entries(event_type, sequence);
                """
            )

    @staticmethod
    def _canonical_payload(payload: Mapping[str, Any]) -> str:
        try:
            return json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("audit payload must be JSON-serializable") from exc

    @staticmethod
    def _hash_entry(
        *,
        entry_id: str,
        event_type: str,
        created_at: datetime,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        material = "|".join(
            [
                entry_id,
                event_type,
                created_at.isoformat(),
                payload_json,
                previous_hash,
            ]
        )
        return sha256(material.encode("utf-8")).hexdigest()

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        created_at: datetime,
        entry_id: str | None = None,
    ) -> AuditEntry:
        if not event_type.strip():
            raise ValueError("event_type is required")
        entry_id = entry_id or uuid.uuid4().hex
        payload_json = self._canonical_payload(payload)

        with self._connect() as connection:
            previous = connection.execute(
                "SELECT entry_hash FROM audit_entries ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = (
                GENESIS_HASH if previous is None else str(previous["entry_hash"])
            )
            entry_hash = self._hash_entry(
                entry_id=entry_id,
                event_type=event_type,
                created_at=created_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            cursor = connection.execute(
                """
                INSERT INTO audit_entries (
                    entry_id, event_type, created_at, payload_json,
                    previous_hash, entry_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    event_type,
                    created_at.isoformat(),
                    payload_json,
                    previous_hash,
                    entry_hash,
                ),
            )
            sequence = int(cursor.lastrowid)

        return AuditEntry(
            sequence=sequence,
            entry_id=entry_id,
            event_type=event_type,
            created_at=created_at,
            payload=json.loads(payload_json),
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )

    def entries(self) -> tuple[AuditEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_entries ORDER BY sequence ASC"
            ).fetchall()
        return tuple(
            AuditEntry(
                sequence=int(row["sequence"]),
                entry_id=row["entry_id"],
                event_type=row["event_type"],
                created_at=datetime.fromisoformat(row["created_at"]),
                payload=json.loads(row["payload_json"]),
                previous_hash=row["previous_hash"],
                entry_hash=row["entry_hash"],
            )
            for row in rows
        )

    def verify_chain(self) -> AuditVerification:
        previous_hash = GENESIS_HASH
        entries = self.entries()
        for entry in entries:
            if entry.previous_hash != previous_hash:
                return AuditVerification(
                    valid=False,
                    checked_entries=entry.sequence - 1,
                    first_invalid_sequence=entry.sequence,
                    reason="previous_hash_mismatch",
                )
            payload_json = self._canonical_payload(entry.payload)
            expected = self._hash_entry(
                entry_id=entry.entry_id,
                event_type=entry.event_type,
                created_at=entry.created_at,
                payload_json=payload_json,
                previous_hash=entry.previous_hash,
            )
            if expected != entry.entry_hash:
                return AuditVerification(
                    valid=False,
                    checked_entries=entry.sequence - 1,
                    first_invalid_sequence=entry.sequence,
                    reason="entry_hash_mismatch",
                )
            previous_hash = entry.entry_hash
        return AuditVerification(
            valid=True,
            checked_entries=len(entries),
            first_invalid_sequence=None,
            reason=None,
        )
