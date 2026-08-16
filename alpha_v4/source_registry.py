"""Versioned source-registry primitives for ALPHA v4."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import Enum
from typing import Dict, Iterable


class SourceKind(str, Enum):
    MARKET = "market"
    KAP = "kap"
    COMPANY_IR = "company_ir"
    OFFICIAL_MACRO = "official_macro"
    NEWS = "news"
    WEB = "web"
    LICENSED = "licensed"


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    kind: SourceKind
    owner: str
    access_method: str
    timezone_name: str
    freshness_limit: timedelta
    enabled: bool = True
    successful_observations: int = 0
    failed_observations: int = 0
    contradictions: int = 0

    @property
    def measured_reliability(self) -> float | None:
        total = self.successful_observations + self.failed_observations + self.contradictions
        if total == 0:
            return None
        return self.successful_observations / total


class SourceRegistry:
    def __init__(self, records: Iterable[SourceRecord] = ()):
        self._records: Dict[str, SourceRecord] = {}
        for record in records:
            self.register(record)

    def register(self, record: SourceRecord) -> None:
        if not record.source_id.strip():
            raise ValueError("source_id must not be empty")
        if record.source_id in self._records:
            raise ValueError(f"source already registered: {record.source_id}")
        self._records[record.source_id] = record

    def get(self, source_id: str) -> SourceRecord:
        try:
            return self._records[source_id]
        except KeyError as exc:
            raise KeyError(f"unknown source: {source_id}") from exc

    def record_success(self, source_id: str) -> SourceRecord:
        current = self.get(source_id)
        updated = replace(current, successful_observations=current.successful_observations + 1)
        self._records[source_id] = updated
        return updated

    def record_failure(self, source_id: str) -> SourceRecord:
        current = self.get(source_id)
        updated = replace(current, failed_observations=current.failed_observations + 1)
        self._records[source_id] = updated
        return updated

    def record_contradiction(self, source_id: str) -> SourceRecord:
        current = self.get(source_id)
        updated = replace(current, contradictions=current.contradictions + 1)
        self._records[source_id] = updated
        return updated

    def enabled_sources(self) -> tuple[SourceRecord, ...]:
        return tuple(record for record in self._records.values() if record.enabled)
