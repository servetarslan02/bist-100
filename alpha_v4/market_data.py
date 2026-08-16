"""Immutable raw market-data store with bitemporal correction handling."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from .contracts import RawBar
from .data_quality import masked_log_returns


class RawBarStore:
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
                CREATE TABLE IF NOT EXISTS raw_bars (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    source_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    is_tradable INTEGER NOT NULL,
                    UNIQUE(ticker, timestamp, source_id, observed_at)
                );
                CREATE INDEX IF NOT EXISTS idx_raw_bars_asof
                    ON raw_bars(ticker, timestamp, observed_at);
                """
            )

    def append(self, bar: RawBar) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO raw_bars (
                    ticker, timestamp, open, high, low, close, volume,
                    source_id, observed_at, is_tradable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bar.ticker,
                    bar.timestamp.isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.source_id,
                    bar.observed_at.isoformat(),
                    1 if bar.is_tradable else 0,
                ),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RawBar:
        return RawBar(
            ticker=row["ticker"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            source_id=row["source_id"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            is_tradable=bool(row["is_tradable"]),
        )

    def bars_as_of(self, ticker: str, decision_time: datetime) -> Tuple[RawBar, ...]:
        """Return latest known correction for every timestamp as of decision_time."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM raw_bars
                WHERE ticker = ? AND observed_at <= ? AND timestamp <= ?
                ORDER BY timestamp ASC, observed_at ASC
                """,
                (ticker, decision_time.isoformat(), decision_time.isoformat()),
            ).fetchall()

        latest_by_timestamp: dict[str, RawBar] = {}
        for row in rows:
            bar = self._from_row(row)
            key = bar.timestamp.isoformat()
            current = latest_by_timestamp.get(key)
            if current is None or bar.observed_at >= current.observed_at:
                latest_by_timestamp[key] = bar
        return tuple(sorted(latest_by_timestamp.values(), key=lambda item: item.timestamp))

    def masked_returns_as_of(
        self,
        ticker: str,
        decision_time: datetime,
        *,
        freshness_limit: timedelta,
    ) -> list[Optional[float]]:
        return masked_log_returns(
            self.bars_as_of(ticker, decision_time),
            decision_time=decision_time,
            freshness_limit=freshness_limit,
        )
