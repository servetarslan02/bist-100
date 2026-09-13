"""Evidence based event impact analysis primitives.

Haber ve kurumsal olayların (KAP bildirimleri, regülasyon, bilanço, temettü, dava vb.)
şirket finansalları ve hisse performansı üzerindeki yapısal hipotez motoru:
- Maddilik (Materiality), Gelir & Nakit Akışı İlgililiği (Cashflow Relevance)
- Olay Yenilik Derecesi (Novelty) & Piyasa Belirsizliği (Uncertainty)
- Zamansal Ufuk (Horizon: İntraday, 1 Hafta, 1 Çeyrek, Uzun Vade)
- Sayısal Şok Çarpanı (Quantitative Shock Multiplier) ve Güven Skoru
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class MaterialityLevel(StrEnum):
    """Maddilik seviyesi."""
    NEGLIGIBLE = "NEGLIGIBLE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    TRANSFORMATIVE = "TRANSFORMATIVE"


class EventHorizon(StrEnum):
    """Etki ufku."""
    IMMEDIATE_INTRADAY = "IMMEDIATE_INTRADAY"
    SHORT_TERM_1W = "SHORT_TERM_1W"
    MEDIUM_TERM_1Q = "MEDIUM_TERM_1Q"
    LONG_TERM_MULTI_YEAR = "LONG_TERM_MULTI_YEAR"


@dataclass(frozen=True)
class EventImpactAssessment:
    """Olayın şirket üzerindeki yapısal finansal etki hipotezi modeli."""
    materiality: str
    revenue_relevance: str
    cashflow_relevance: str
    novelty: str
    uncertainty: str
    horizon: str
    estimated_ebitda_impact_pct: float = 0.0
    sentiment_bias: float = 0.0  # -1.0 (aşırı negatif) ile +1.0 (aşırı pozitif)
    confidence_score: float = 0.85
    impact_narrative: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return (
            f"EventImpactAssessment(materiality={self.materiality!r}, horizon={self.horizon!r}, "
            f"bias={self.sentiment_bias:+.2f}, conf={self.confidence_score:.2f})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sözlük temsiline dönüştürür."""
        return asdict(self)


class EventImpactEngine:
    """Haber ve olayların finansal etki hipotezlerini üreten kurumsal analiz motoru."""

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return "EventImpactEngine(version='3.0-institutional')"

    def assess(
        self,
        *,
        materiality: str,
        revenue_relevance: str,
        cashflow_relevance: str,
        novelty: str,
        uncertainty: str,
        horizon: str,
        estimated_ebitda_impact_pct: float = 0.0,
        sentiment_bias: float = 0.0,
        confidence_score: float = 0.85,
        impact_narrative: str = "",
    ) -> EventImpactAssessment:
        """Belirtilen etki parametrelerine göre kurumsal değerlendirme çıktısı oluşturur."""
        # Maddilik katsayısı hesaplama
        mat_upper = str(materiality).upper()
        if "TRANSFORMATIVE" in mat_upper or "VERY_HIGH" in mat_upper:
            base_ebitda = estimated_ebitda_impact_pct or 15.0
        elif "HIGH" in mat_upper:
            base_ebitda = estimated_ebitda_impact_pct or 7.5
        elif "MEDIUM" in mat_upper:
            base_ebitda = estimated_ebitda_impact_pct or 2.5
        else:
            base_ebitda = estimated_ebitda_impact_pct or 0.5

        narrative = impact_narrative or (
            f"Event materiality rated {materiality} with {horizon} persistence. "
            f"Estimated operational cashflow sensitivity: %{base_ebitda:.1f}."
        )

        return EventImpactAssessment(
            materiality=materiality,
            revenue_relevance=revenue_relevance,
            cashflow_relevance=cashflow_relevance,
            novelty=novelty,
            uncertainty=uncertainty,
            horizon=horizon,
            estimated_ebitda_impact_pct=round(base_ebitda, 2),
            sentiment_bias=round(sentiment_bias, 2),
            confidence_score=round(confidence_score, 2),
            impact_narrative=narrative,
        )

    def evaluate_kap_announcement(
        self,
        title: str,
        disclosure_type: str,
        company_ticker: str,
        amount_tl: float | None = None,
        market_cap_tl: float | None = None,
    ) -> EventImpactAssessment:
        """KAP bildirim türüne ve tutarına göre otomatik etki hipotezi üretir."""
        dt_upper = disclosure_type.upper()
        ratio = (amount_tl / market_cap_tl) if amount_tl and market_cap_tl and market_cap_tl > 0 else None

        if "YATIRIM" in dt_upper or "SÖZLEŞME" in dt_upper or "YENİ İŞ" in dt_upper:
            mat = MaterialityLevel.HIGH.value if ratio and ratio > 0.10 else MaterialityLevel.MEDIUM.value
            return self.assess(
                materiality=mat,
                revenue_relevance="HIGH",
                cashflow_relevance="MEDIUM",
                novelty="HIGH",
                uncertainty="LOW",
                horizon=EventHorizon.MEDIUM_TERM_1Q.value,
                estimated_ebitda_impact_pct=10.0 if ratio and ratio > 0.10 else 4.0,
                sentiment_bias=0.75,
                confidence_score=0.90,
                impact_narrative=f"KAP: {company_ticker} yeni iş/yatırım bildirimi ({disclosure_type}).",
            )
        elif "DAVA" in dt_upper or "CEZA" in dt_upper or "VERGİ" in dt_upper:
            return self.assess(
                materiality=MaterialityLevel.HIGH.value if ratio and ratio > 0.05 else MaterialityLevel.MEDIUM.value,
                revenue_relevance="LOW",
                cashflow_relevance="HIGH",
                novelty="MEDIUM",
                uncertainty="HIGH",
                horizon=EventHorizon.SHORT_TERM_1W.value,
                estimated_ebitda_impact_pct=-5.0,
                sentiment_bias=-0.70,
                confidence_score=0.85,
                impact_narrative=f"KAP: {company_ticker} aleyhine hukuki/mali süreç bildirimi.",
            )
        else:
            return self.assess(
                materiality=MaterialityLevel.LOW.value,
                revenue_relevance="LOW",
                cashflow_relevance="LOW",
                novelty="LOW",
                uncertainty="LOW",
                horizon=EventHorizon.IMMEDIATE_INTRADAY.value,
                estimated_ebitda_impact_pct=0.0,
                sentiment_bias=0.0,
                confidence_score=0.95,
                impact_narrative=f"KAP: {company_ticker} rutin bildirim ({title[:50]}).",
            )


event_impact_engine = EventImpactEngine()

__all__ = [
    "EventHorizon",
    "EventImpactAssessment",
    "EventImpactEngine",
    "MaterialityLevel",
    "event_impact_engine",
]
