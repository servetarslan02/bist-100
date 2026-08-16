"""Evidence based event impact analysis primitives.

This intentionally does not convert news into buy/sell decisions.
It creates structured impact hypotheses for later research.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EventImpactAssessment:
    materiality: str
    revenue_relevance: str
    cashflow_relevance: str
    novelty: str
    uncertainty: str
    horizon: str


class EventImpactEngine:
    def assess(self, *, materiality: str, revenue_relevance: str,
               cashflow_relevance: str, novelty: str,
               uncertainty: str, horizon: str) -> EventImpactAssessment:
        return EventImpactAssessment(
            materiality=materiality,
            revenue_relevance=revenue_relevance,
            cashflow_relevance=cashflow_relevance,
            novelty=novelty,
            uncertainty=uncertainty,
            horizon=horizon,
        )
