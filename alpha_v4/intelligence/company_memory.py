"""Point-in-time company intelligence memory.

This module intentionally stores facts with evidence and effective dates.
Future facts cannot be used for historical state reconstruction.
"""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class CompanyFact:
    company_id: str
    key: str
    value: str
    effective_at: datetime
    observed_at: datetime
    evidence_id: str

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("timestamps must be timezone aware")
        if not self.evidence_id:
            raise ValueError("company facts require evidence")


class CompanyMemory:
    """Small deterministic store used as the base for the graph layer."""

    def __init__(self) -> None:
        self._facts: list[CompanyFact] = []

    def add_fact(self, fact: CompanyFact) -> None:
        if fact not in self._facts:
            self._facts.append(fact)

    def facts_at(self, company_id: str, as_of: datetime) -> list[CompanyFact]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone aware")
        return [
            fact
            for fact in self._facts
            if fact.company_id == company_id
            and fact.effective_at <= as_of
        ]

    def all_facts(self) -> tuple[CompanyFact, ...]:
        return tuple(self._facts)


UTC = UTC
