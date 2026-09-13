"""Point-in-time company intelligence memory.

This module intentionally stores facts with evidence and effective dates.
Future facts cannot be used for historical state reconstruction.
"""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class CompanyFact:
    """Zaman damgalı ve kanıtlı şirket gerçeği veri modeli."""
    company_id: str
    key: str
    value: str
    effective_at: datetime
    observed_at: datetime
    evidence_id: str

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"CompanyFact(company_id={self.company_id!r}, key={self.key!r}, value={self.value!r})"

    def __post_init__(self) -> None:
        """Zaman damgası ve kanıt kimliği doğrulaması yapar."""
        if self.effective_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("timestamps must be timezone aware")
        if not self.evidence_id:
            raise ValueError("company facts require evidence")


class CompanyMemory:
    """Small deterministic store used as the base for the graph layer."""

    def __init__(self) -> None:
        """Şirket bellek gerçekleri listesini ilklendirir."""
        self._facts: list[CompanyFact] = []

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"CompanyMemory(facts_count={len(self._facts)})"

    def add_fact(self, fact: CompanyFact) -> None:
        """Belleğe yeni şirket gerçeği ekler."""
        if fact not in self._facts:
            self._facts.append(fact)

    def facts_at(self, company_id: str, as_of: datetime) -> list[CompanyFact]:
        """Belirtilen tarih itibarıyla geçerli şirket gerçeklerini filtreler."""
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone aware")
        return [fact for fact in self._facts if fact.company_id == company_id and fact.effective_at <= as_of]

    def all_facts(self) -> tuple[CompanyFact, ...]:
        """Kayıtlı tüm şirket gerçeklerini tuple olarak döndürür."""
        return tuple(self._facts)


UTC = UTC
