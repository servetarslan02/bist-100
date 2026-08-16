"""Bitemporal instrument/universe registry for ALPHA v4.

The registry separates instrument identity from ticker symbol and preserves what was
known at each decision time. This is a prerequisite for survivorship-safe research.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class InstrumentVersion:
    instrument_id: str
    company_id: str
    symbol: str
    effective_from: datetime
    known_at: datetime
    listed_at: datetime
    delisted_at: datetime | None
    sector: str | None
    source_event_id: str

    def __post_init__(self) -> None:
        for field_name in ("instrument_id", "company_id", "symbol", "source_event_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.delisted_at is not None and self.delisted_at < self.listed_at:
            raise ValueError("delisted_at cannot be before listed_at")


@dataclass(frozen=True)
class UniverseMembershipVersion:
    universe_name: str
    instrument_id: str
    effective_from: datetime
    effective_to: datetime | None
    known_at: datetime
    source_event_id: str

    def __post_init__(self) -> None:
        if not self.universe_name.strip() or not self.instrument_id.strip():
            raise ValueError("universe_name and instrument_id are required")
        if not self.source_event_id.strip():
            raise ValueError("source_event_id is required")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")


class UniverseStore:
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
                CREATE TABLE IF NOT EXISTS instrument_versions (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    known_at TEXT NOT NULL,
                    listed_at TEXT NOT NULL,
                    delisted_at TEXT,
                    sector TEXT,
                    source_event_id TEXT NOT NULL,
                    UNIQUE(instrument_id, effective_from, known_at, source_event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_instrument_known
                    ON instrument_versions(known_at, effective_from);
                CREATE INDEX IF NOT EXISTS idx_instrument_symbol
                    ON instrument_versions(symbol);

                CREATE TABLE IF NOT EXISTS universe_membership_versions (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    universe_name TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    effective_to TEXT,
                    known_at TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    UNIQUE(universe_name, instrument_id, effective_from, known_at, source_event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_membership_known
                    ON universe_membership_versions(universe_name, known_at, effective_from);
                """
            )

    def append_instrument(self, version: InstrumentVersion) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO instrument_versions (
                    instrument_id, company_id, symbol, effective_from, known_at,
                    listed_at, delisted_at, sector, source_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version.instrument_id,
                    version.company_id,
                    version.symbol,
                    version.effective_from.isoformat(),
                    version.known_at.isoformat(),
                    version.listed_at.isoformat(),
                    version.delisted_at.isoformat() if version.delisted_at else None,
                    version.sector,
                    version.source_event_id,
                ),
            )

    def append_membership(self, version: UniverseMembershipVersion) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO universe_membership_versions (
                    universe_name, instrument_id, effective_from, effective_to,
                    known_at, source_event_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    version.universe_name,
                    version.instrument_id,
                    version.effective_from.isoformat(),
                    version.effective_to.isoformat() if version.effective_to else None,
                    version.known_at.isoformat(),
                    version.source_event_id,
                ),
            )

    @staticmethod
    def _instrument_from_row(row: sqlite3.Row) -> InstrumentVersion:
        return InstrumentVersion(
            instrument_id=row["instrument_id"],
            company_id=row["company_id"],
            symbol=row["symbol"],
            effective_from=datetime.fromisoformat(row["effective_from"]),
            known_at=datetime.fromisoformat(row["known_at"]),
            listed_at=datetime.fromisoformat(row["listed_at"]),
            delisted_at=datetime.fromisoformat(row["delisted_at"])
            if row["delisted_at"]
            else None,
            sector=row["sector"],
            source_event_id=row["source_event_id"],
        )

    def instruments_as_of(
        self, decision_time: datetime
    ) -> tuple[InstrumentVersion, ...]:
        """Return every active instrument known at decision_time; no business cap."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM instrument_versions
                WHERE known_at <= ? AND effective_from <= ?
                ORDER BY instrument_id, effective_from, known_at
                """,
                (decision_time.isoformat(), decision_time.isoformat()),
            ).fetchall()

        latest: dict[str, InstrumentVersion] = {}
        for row in rows:
            version = self._instrument_from_row(row)
            current = latest.get(version.instrument_id)
            if current is None or (version.effective_from, version.known_at) >= (
                current.effective_from,
                current.known_at,
            ):
                latest[version.instrument_id] = version

        active = [
            version
            for version in latest.values()
            if version.listed_at <= decision_time
            and (version.delisted_at is None or decision_time < version.delisted_at)
        ]
        return tuple(sorted(active, key=lambda item: item.symbol))

    def members_as_of(
        self, universe_name: str, decision_time: datetime
    ) -> tuple[str, ...]:
        """Return point-in-time membership for an index/peer universe."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM universe_membership_versions
                WHERE universe_name = ? AND known_at <= ? AND effective_from <= ?
                ORDER BY instrument_id, effective_from, known_at
                """,
                (universe_name, decision_time.isoformat(), decision_time.isoformat()),
            ).fetchall()

        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            instrument_id = row["instrument_id"]
            current = latest.get(instrument_id)
            row_key = (row["effective_from"], row["known_at"])
            current_key = (
                None
                if current is None
                else (current["effective_from"], current["known_at"])
            )
            if current_key is None or row_key >= current_key:
                latest[instrument_id] = row

        members = []
        for instrument_id, row in latest.items():
            effective_to = (
                datetime.fromisoformat(row["effective_to"])
                if row["effective_to"]
                else None
            )
            if effective_to is None or decision_time < effective_to:
                members.append(instrument_id)
        return tuple(sorted(members))
