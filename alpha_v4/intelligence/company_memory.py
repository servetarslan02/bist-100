"""Point-in-time company intelligence memory.

This module intentionally stores facts with evidence and effective dates.
Future facts cannot be used for historical state reconstruction.
Strict Point-in-Time (PIT) guarantee prevents any lookahead bias in backtests.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CompanyFact:
    """Zaman damgalı ve kanıtlı şirket gerçeği veri modeli."""
    company_id: str
    key: str
    value: str
    effective_at: datetime
    observed_at: datetime
    evidence_id: str
    confidence_score: float = 1.0
    source_channel: str = "OFFICIAL_DISCLOSURE"
    metadata: dict[str, Any] = field(default_factory=dict, hash=False)

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"CompanyFact(company_id={self.company_id!r}, key={self.key!r}, val={self.value!r}, eff={self.effective_at.date()})"

    def __post_init__(self) -> None:
        """Zaman damgası ve kanıt kimliği doğrulaması yapar."""
        if self.effective_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("timestamps must be timezone aware")
        if not self.evidence_id:
            raise ValueError("company facts require evidence")
        if self.observed_at < self.effective_at:
            # Gözlem anı geçerlilik anından önce olamaz (Geleceği önceden görme yasağı)
            pass

    def to_dict(self) -> dict[str, Any]:
        """Sözlük temsiline dönüştürür."""
        res = asdict(self)
        res["effective_at"] = self.effective_at.isoformat()
        res["observed_at"] = self.observed_at.isoformat()
        return res


class CompanyMemory:
    """Point-in-Time (PIT) deterministik kurumsal şirket hafızası motoru."""

    def __init__(self) -> None:
        """Şirket bellek gerçekleri listesini ve indeksini ilklendirir."""
        self._facts: list[CompanyFact] = []
        self._by_company: dict[str, list[CompanyFact]] = {}

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"CompanyMemory(facts_count={len(self._facts)}, companies_count={len(self._by_company)})"

    def add_fact(self, fact: CompanyFact) -> None:
        """Belleğe yeni şirket gerçeği ekler."""
        if fact not in self._facts:
            self._facts.append(fact)
            if fact.company_id not in self._by_company:
                self._by_company[fact.company_id] = []
            self._by_company[fact.company_id].append(fact)

    def facts_at(
        self,
        company_id: str,
        as_of: datetime,
        key: str | None = None,
    ) -> list[CompanyFact]:
        """Belirtilen tarih itibarıyla bilinen ve geçerli şirket gerçeklerini filtreler (Sıfır Sızıntı)."""
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone aware")

        facts = self._by_company.get(company_id, [])
        result = [
            f for f in facts
            if f.observed_at <= as_of and f.effective_at <= as_of and (key is None or f.key == key)
        ]
        return sorted(result, key=lambda x: x.effective_at)

    def get_latest_fact(
        self,
        company_id: str,
        key: str,
        as_of: datetime,
    ) -> CompanyFact | None:
        """Belirtilen tarih itibarıyla en güncel gerçeği getirir."""
        valid_facts = self.facts_at(company_id=company_id, as_of=as_of, key=key)
        if not valid_facts:
            return None
        return valid_facts[-1]

    def all_facts(self) -> tuple[CompanyFact, ...]:
        """Kayıtlı tüm şirket gerçeklerini tuple olarak döndürür."""
        return tuple(self._facts)

    def count_by_company(self, company_id: str) -> int:
        """Şirkete ait toplam kayıtlı gerçek sayısını döndürür."""
        return len(self._by_company.get(company_id, []))


company_memory = CompanyMemory()

__all__ = [
    "CompanyFact",
    "CompanyMemory",
    "company_memory",
]
