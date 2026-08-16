"""Versioned core contracts for ALPHA v4.

The goal here is not feature breadth; it is trustworthy primitives that every later
service can depend on without silently fabricating market state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping, Optional, Tuple


class ValidationStatus(str, Enum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_YET_KNOWN = "NOT_YET_KNOWN"
    UNTRADABLE = "UNTRADABLE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


@dataclass(frozen=True)
class EvidenceRef:
    source_id: str
    source_timestamp: datetime
    ingest_timestamp: datetime
    locator: str
    evidence_text: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if not self.locator.strip():
            raise ValueError("locator must not be empty")
        if self.ingest_timestamp < self.source_timestamp:
            raise ValueError("ingest_timestamp cannot be before source_timestamp")


@dataclass(frozen=True)
class RawBar:
    ticker: str
    timestamp: datetime
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    volume: Optional[float]
    source_id: str
    observed_at: datetime
    is_tradable: bool = True

    def __post_init__(self) -> None:
        if not self.ticker.strip():
            raise ValueError("ticker must not be empty")
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")


@dataclass(frozen=True)
class CanonicalEvent:
    event_type: str
    source_id: str
    source_timestamp: datetime
    ingest_timestamp: datetime
    effective_timestamp: datetime
    entities: Tuple[str, ...]
    payload: Mapping[str, Any]
    evidence: Tuple[EvidenceRef, ...]
    schema_version: str = "1.0"
    event_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.event_type.strip():
            raise ValueError("event_type must not be empty")
        if not self.entities:
            raise ValueError("at least one entity is required")
        if self.ingest_timestamp < self.source_timestamp:
            raise ValueError("ingest_timestamp cannot be before source_timestamp")
        if not self.evidence:
            raise ValueError("decision-relevant canonical events require evidence")

        try:
            canonical_payload = json.dumps(
                self.payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("canonical event payload must be JSON-serializable") from exc

        if not self.event_id:
            stable = "|".join(
                [
                    self.schema_version,
                    self.event_type,
                    self.source_id,
                    self.source_timestamp.astimezone(timezone.utc).isoformat(),
                    ",".join(sorted(self.entities)),
                    canonical_payload,
                ]
            )
            object.__setattr__(self, "event_id", sha256(stable.encode("utf-8")).hexdigest())

    def was_known_at(self, decision_time: datetime) -> bool:
        """Point-in-time availability gate.

        Information is usable only after it actually entered ALPHA, not merely because
        its source timestamp is earlier.
        """
        return self.ingest_timestamp <= decision_time
