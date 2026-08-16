"""Versioned, point-in-time feature primitives for ALPHA v4."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from .market_data import RawBarStore


@dataclass(frozen=True)
class FeatureRecord:
    instrument_id: str
    feature_id: str
    value: Optional[float]
    effective_at: datetime
    known_at: datetime
    source_ids: Tuple[str, ...]
    input_timestamps: Tuple[datetime, ...]
    status: str

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or not self.feature_id.strip():
            raise ValueError("instrument_id and feature_id are required")
        if not self.source_ids:
            raise ValueError("feature provenance source_ids are required")
        if not self.input_timestamps:
            raise ValueError("input_timestamps are required")
        if self.status not in {"VALID", "MASKED", "INSUFFICIENT_DATA"}:
            raise ValueError("invalid feature status")
        if self.status == "VALID" and self.value is None:
            raise ValueError("VALID feature requires a value")


class FeatureStore:
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
                CREATE TABLE IF NOT EXISTS feature_records (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id TEXT NOT NULL,
                    feature_id TEXT NOT NULL,
                    value REAL,
                    effective_at TEXT NOT NULL,
                    known_at TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    input_timestamps_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    UNIQUE(instrument_id, feature_id, effective_at, known_at)
                );
                CREATE INDEX IF NOT EXISTS idx_feature_asof
                    ON feature_records(instrument_id, feature_id, known_at, effective_at);
                """
            )

    def append(self, record: FeatureRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO feature_records (
                    instrument_id, feature_id, value, effective_at, known_at,
                    source_ids_json, input_timestamps_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.instrument_id,
                    record.feature_id,
                    record.value,
                    record.effective_at.isoformat(),
                    record.known_at.isoformat(),
                    json.dumps(record.source_ids, separators=(",", ":")),
                    json.dumps([ts.isoformat() for ts in record.input_timestamps], separators=(",", ":")),
                    record.status,
                ),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> FeatureRecord:
        return FeatureRecord(
            instrument_id=row["instrument_id"],
            feature_id=row["feature_id"],
            value=row["value"],
            effective_at=datetime.fromisoformat(row["effective_at"]),
            known_at=datetime.fromisoformat(row["known_at"]),
            source_ids=tuple(json.loads(row["source_ids_json"])),
            input_timestamps=tuple(datetime.fromisoformat(x) for x in json.loads(row["input_timestamps_json"])),
            status=row["status"],
        )

    def as_of(
        self,
        instrument_id: str,
        feature_id: str,
        decision_time: datetime,
    ) -> Optional[FeatureRecord]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM feature_records
                WHERE instrument_id = ? AND feature_id = ?
                  AND known_at <= ? AND effective_at <= ?
                ORDER BY effective_at DESC, known_at DESC
                LIMIT 1
                """,
                (instrument_id, feature_id, decision_time.isoformat(), decision_time.isoformat()),
            ).fetchone()
        return None if row is None else self._from_row(row)


def compute_log_return_feature(
    market_store: RawBarStore,
    *,
    ticker: str,
    instrument_id: str,
    decision_time: datetime,
    lookback_bars: int,
    feature_version: str = "1.0",
) -> FeatureRecord:
    """Compute a point-in-time log return from valid historical endpoints.

    Intermediate invalid observations intentionally cause the feature to be MASKED
    rather than silently bridging across an untradable/corrupt period.
    """
    if lookback_bars <= 0:
        raise ValueError("lookback_bars must be positive")

    bars = list(market_store.bars_as_of(ticker, decision_time))
    feature_id = f"log_return_{lookback_bars}b@{feature_version}"
    if len(bars) < lookback_bars + 1:
        available = tuple(bar.timestamp for bar in bars) or (decision_time,)
        sources = tuple(sorted({bar.source_id for bar in bars})) or ("no-source",)
        return FeatureRecord(
            instrument_id=instrument_id,
            feature_id=feature_id,
            value=None,
            effective_at=decision_time,
            known_at=decision_time,
            source_ids=sources,
            input_timestamps=available,
            status="INSUFFICIENT_DATA",
        )

    window = bars[-(lookback_bars + 1):]
    from .data_quality import masked_log_returns

    returns = masked_log_returns(
        window,
        decision_time=decision_time,
        freshness_limit=timedelta(days=36500),
    )
    if any(value is None for value in returns[1:]):
        return FeatureRecord(
            instrument_id=instrument_id,
            feature_id=feature_id,
            value=None,
            effective_at=window[-1].timestamp,
            known_at=max(bar.observed_at for bar in window),
            source_ids=tuple(sorted({bar.source_id for bar in window})),
            input_timestamps=tuple(bar.timestamp for bar in window),
            status="MASKED",
        )

    value = sum(value for value in returns[1:] if value is not None)
    if not math.isfinite(value):
        raise ValueError("feature value must be finite")

    return FeatureRecord(
        instrument_id=instrument_id,
        feature_id=feature_id,
        value=value,
        effective_at=window[-1].timestamp,
        known_at=max(bar.observed_at for bar in window),
        source_ids=tuple(sorted({bar.source_id for bar in window})),
        input_timestamps=tuple(bar.timestamp for bar in window),
        status="VALID",
    )
