"""
ALPHA BIST — Cross-Source Reconciliation v1.0

Farklı kaynaklardan gelen verileri karşılaştırır.
Tutarsızlık tespit eder, güvenilirlik skoru atar.

Kullanım:
- Aynı hisse için Google Trends + Ekşi + Investing.com sentiment'leri karşılaştır
- Kaynaklar arası sapma > threshold → uyarı
- Güvenilirlik skoru: kaynak sayısı + tutarlılık
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class ReconciliationReport:
    """Uzlaştırma raporu."""

    ticker: str
    consensus_direction: str  # LONG, SHORT, NEUTRAL
    consensus_score: float  # -1 ile +1
    confidence: float  # 0-1
    source_count: int
    agreeing_sources: int
    disagreeing_sources: int
    reliability_score: float  # 0-1
    discrepancies: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Otomatik eklendi."""
        return {
            "ticker": self.ticker,
            "consensus_direction": self.consensus_direction,
            "consensus_score": round(self.consensus_score, 4),
            "confidence": round(self.confidence, 4),
            "source_count": self.source_count,
            "agreeing_sources": self.agreeing_sources,
            "disagreeing_sources": self.disagreeing_sources,
            "reliability_score": round(self.reliability_score, 4),
            "discrepancies": self.discrepancies,
            "warnings": self.warnings,
        }


class CrossSourceReconciler:
    """Kaynaklar arası veri uzlaştırma.

    Kurallar:
    - Sentiment skorları karşılaştır
    - Sapma > 0.5 → tutarsızlık uyarısı
    - Kaynak sayısı arttıkça güvenilirlik artar
    - Tüm kaynaklar aynı yönde → yüksek güvenilirlik
    """

    # Sentiment feature'ları
    SENTIMENT_FEATURES = [
        "google_trends_zscore",
        "eksi_sentiment",
        "investing_sentiment",
        "llm_kap_sentiment",
        "llm_news_sentiment",
        "social_sentiment",
    ]

    # Büyüme feature'ları
    GROWTH_FEATURES = [
        "google_trends_momentum_30d",
        "job_posting_growth",
        "cc_spend_growth",
    ]

    # Tutarsızlık eşiği
    DISCREPANCY_THRESHOLD = 0.5

    def reconcile(
        self,
        ticker: str,
        features: dict[str, float],
    ) -> ReconciliationReport:
        """Feature'ları uzlaştır.

        Args:
            ticker: Hisse kodu
            features: Tüm feature'lar

        Returns:
            ReconciliationReport
        """
        warnings = []
        discrepancies = []

        # 1. Sentiment skorlarını topla
        sentiment_scores = {}
        for feat in self.SENTIMENT_FEATURES:
            if feat in features and features[feat] != 0:
                sentiment_scores[feat] = features[feat]

        # 2. Büyüme skorlarını topla
        growth_scores = {}
        for feat in self.GROWTH_FEATURES:
            if feat in features and features[feat] != 0:
                growth_scores[feat] = features[feat]

        # 3. Sentiment consensus
        self._compute_consensus(sentiment_scores, "sentiment")

        # 4. Büyüme consensus
        self._compute_consensus(growth_scores, "growth")

        # 5. Genel consensus
        all_scores = {**sentiment_scores, **growth_scores}
        overall_consensus = self._compute_consensus(all_scores, "overall")

        # 6. Tutarsızlık tespiti
        for category, scores in [("sentiment", sentiment_scores), ("growth", growth_scores)]:
            if len(scores) >= 2:
                values = list(scores.values())
                max_diff = max(values) - min(values)
                if max_diff > self.DISCREPANCY_THRESHOLD:
                    discrepancies.append(
                        {
                            "category": category,
                            "max_difference": round(max_diff, 4),
                            "sources": {k: round(v, 4) for k, v in scores.items()},
                        }
                    )
                    warnings.append(f"{category}: Kaynaklar arası büyük fark ({max_diff:.2f})")

        # 7. Güvenilirlik skoru
        source_count = len(all_scores)
        reliability = self._compute_reliability(source_count, len(discrepancies))

        # 8. Yön belirle
        consensus_score = overall_consensus["mean"]
        if consensus_score > 0.15:
            direction = "LONG"
        elif consensus_score < -0.15:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        return ReconciliationReport(
            ticker=ticker,
            consensus_direction=direction,
            consensus_score=consensus_score,
            confidence=overall_consensus["confidence"],
            source_count=source_count,
            agreeing_sources=overall_consensus["agreeing"],
            disagreeing_sources=overall_consensus["disagreeing"],
            reliability_score=reliability,
            discrepancies=discrepancies,
            warnings=warnings,
        )

    def _compute_consensus(self, scores: dict[str, float], category: str) -> dict[str, Any]:
        """Consensus hesapla."""
        if not scores:
            return {"mean": 0, "confidence": 0, "agreeing": 0, "disagreeing": 0}

        values = list(scores.values())
        mean_val = np.mean(values)

        # Aynı yönde olan kaynaklar
        agreeing = sum(
            1 for v in values if (v > 0 and mean_val > 0) or (v < 0 and mean_val < 0) or (v == 0 and mean_val == 0)
        )
        disagreeing = len(values) - agreeing

        # Confidence: kaynak sayısı + tutarlılık
        source_factor = min(1.0, len(values) / 3)  # 3+ kaynak = tam güven
        agreement_factor = agreeing / len(values) if values else 0
        confidence = source_factor * agreement_factor

        return {
            "mean": float(mean_val),
            "confidence": round(confidence, 4),
            "agreeing": agreeing,
            "disagreeing": disagreeing,
        }

    def _compute_reliability(self, source_count: int, discrepancy_count: int) -> float:
        """Güvenilirlik skoru hesapla."""
        if source_count == 0:
            return 0.0

        # Kaynak sayısı bonusu (0-0.5)
        source_score = min(0.5, source_count * 0.15)

        # Tutarlılık bonusu (0-0.5)
        if discrepancy_count == 0:
            consistency_score = 0.5
        elif discrepancy_count == 1:
            consistency_score = 0.3
        else:
            consistency_score = 0.1

        return round(source_score + consistency_score, 4)


# Singleton
reconciler = CrossSourceReconciler()
