"""Point-in-time company context memory for event interpretation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class CompanySnapshot:
    company_id: str
    effective_at: datetime
    known_at: datetime
    values: Dict[str, Any]
    source_event_ids: Tuple[str, ...]
    version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.company_id.strip():
            raise ValueError("company_id must not be empty")
        if not self.source_event_ids:
            raise ValueError("company snapshot requires source_event_ids")


class CompanyMemory:
    """Append-only snapshot collection with point-in-time retrieval semantics."""

    def __init__(self, snapshots: Iterable[CompanySnapshot] = ()):
        self._snapshots: list[CompanySnapshot] = []
        for snapshot in snapshots:
            self.append(snapshot)

    def append(self, snapshot: CompanySnapshot) -> None:
        self._snapshots.append(snapshot)

    def as_of(self, company_id: str, decision_time: datetime) -> Optional[CompanySnapshot]:
        eligible = [
            snapshot
            for snapshot in self._snapshots
            if snapshot.company_id == company_id and snapshot.known_at <= decision_time
        ]
        if not eligible:
            return None
        # Knowledge time controls availability; effective time helps order revisions that
        # became known simultaneously.
        return max(eligible, key=lambda item: (item.known_at, item.effective_at))

    def history(self, company_id: str) -> tuple[CompanySnapshot, ...]:
        return tuple(
            sorted(
                (s for s in self._snapshots if s.company_id == company_id),
                key=lambda item: (item.known_at, item.effective_at),
            )
        )
