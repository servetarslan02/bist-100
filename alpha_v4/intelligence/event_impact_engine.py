"""Evidence based event impact analysis primitives.

This intentionally does not convert news into buy/sell decisions.
It creates structured impact hypotheses for later research.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EventImpactAssessment:
    """Olayın şirket üzerindeki yapısal finansal etki hipotezi modeli."""
    materiality: str
    revenue_relevance: str
    cashflow_relevance: str
    novelty: str
    uncertainty: str
    horizon: str

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"EventImpactAssessment(materiality={self.materiality!r}, horizon={self.horizon!r})"


class EventImpactEngine:
    """Haber ve olayların finansal etki hipotezlerini üreten motor."""

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return "EventImpactEngine()"

    def assess(
        self,
        *,
        materiality: str,
        revenue_relevance: str,
        cashflow_relevance: str,
        novelty: str,
        uncertainty: str,
        horizon: str,
    ) -> EventImpactAssessment:
        """Belirtilen etki parametrelerine göre değerlendirme çıktısı oluşturur."""
        return EventImpactAssessment(
            materiality=materiality,
            revenue_relevance=revenue_relevance,
            cashflow_relevance=cashflow_relevance,
            novelty=novelty,
            uncertainty=uncertainty,
            horizon=horizon,
        )
