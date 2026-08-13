"""
ALPHA BIST - Data Validator v1.0

Kaynaklar arası cross-validation:
Yahoo ↔ Matriks ↔ BIST resmi

Farklılık varsa → DATA QUALITY WARNING
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class ValidationResult:
    """Doğrulama sonucu."""
    ticker: str
    canonical_price: float
    sources: Dict[str, float]  # source -> price
    is_consistent: bool
    max_deviation_pct: float
    quality_score: float  # 0-1
    warnings: List[str] = field(default_factory=list)


class DataValidator:
    """
    Kaynaklar arası cross-validation.
    Yahoo ↔ Matriks ↔ BIST resmi karşılaştırması.
    """

    # Kaynak güvenilirlik ağırlıkları
    SOURCE_WEIGHTS = {
        "bist_official": 1.00,
        "matriks": 0.90,
        "yfinance": 0.85,
        "investing": 0.70,
        "google_news": 0.50,
        "social": 0.30,
    }

    # Maksimum kabul edilebilir sapma (%)
    MAX_DEVIATION_PCT = 0.5  # %0.5

    def validate_price(
        self,
        ticker: str,
        prices: Dict[str, float],  # source -> price
    ) -> ValidationResult:
        """
        Fiyat doğrulama — kaynaklar arası karşılaştırma.

        prices: {"yfinance": 308.50, "matriks": 308.50, "bist_official": 308.50}
        """
        if not prices:
            return ValidationResult(
                ticker=ticker, canonical_price=0, sources=prices,
                is_consistent=False, max_deviation_pct=100, quality_score=0,
                warnings=["No price data from any source"],
            )

        # Ağırlıklı ortalama → canonical price
        canonical = self._compute_canonical_price(prices)

        # Sapmaları hesapla
        deviations = {}
        for source, price in prices.items():
            if price > 0:
                deviation = abs(price - canonical) / canonical * 100
                deviations[source] = deviation

        max_deviation = max(deviations.values()) if deviations else 0
        is_consistent = max_deviation <= self.MAX_DEVIATION_PCT

        # Kalite skoru
        quality = self._compute_quality_score(prices, deviations)

        # Uyarılar
        warnings = []
        if not is_consistent:
            for source, dev in deviations.items():
                if dev > self.MAX_DEVIATION_PCT:
                    warnings.append(
                        f"{source}: {dev:.2f}% deviation from canonical"
                    )

        if len(prices) < 2:
            warnings.append("Only single source available — no cross-validation")

        return ValidationResult(
            ticker=ticker,
            canonical_price=round(canonical, 2),
            sources={k: round(v, 2) for k, v in prices.items()},
            is_consistent=is_consistent,
            max_deviation_pct=round(max_deviation, 3),
            quality_score=round(quality, 3),
            warnings=warnings,
        )

    def _compute_canonical_price(self, prices: Dict[str, float]) -> float:
        """Ağırlıklı ortalama ile canonical price hesapla."""
        total_weight = 0
        weighted_sum = 0

        for source, price in prices.items():
            if price > 0:
                weight = self.SOURCE_WEIGHTS.get(source, 0.5)
                weighted_sum += price * weight
                total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0

    def _compute_quality_score(
        self, prices: Dict[str, float], deviations: Dict[str, float]
    ) -> float:
        """Kalite skoru (0-1)."""
        score = 1.0

        # Kaynak sayısına göre
        source_count = len(prices)
        if source_count == 1:
            score *= 0.6  # Tek kaynak = düşük güven
        elif source_count == 2:
            score *= 0.8
        # 3+ kaynak = tam güven

        # Sapmaya göre
        max_dev = max(deviations.values()) if deviations else 0
        if max_dev > 1.0:
            score *= 0.5
        elif max_dev > 0.5:
            score *= 0.7
        elif max_dev > 0.1:
            score *= 0.9

        return score

    def validate_batch(
        self, data: Dict[str, Dict[str, float]]
    ) -> Dict[str, ValidationResult]:
        """
        Toplu doğrulama.

        data: {
            "THYAO": {"yfinance": 308.50, "matriks": 308.50},
            "ASELS": {"yfinance": 381.00, "matriks": 381.00},
        }
        """
        results = {}
        for ticker, prices in data.items():
            results[ticker] = self.validate_price(ticker, prices)
        return results

    def get_quality_report(
        self, results: Dict[str, ValidationResult]
    ) -> Dict[str, Any]:
        """Kalite raporu."""
        total = len(results)
        consistent = sum(1 for r in results.values() if r.is_consistent)
        avg_quality = (
            sum(r.quality_score for r in results.values()) / total
            if total > 0 else 0
        )
        warnings = []
        for r in results.values():
            warnings.extend(r.warnings)

        return {
            "total_tickers": total,
            "consistent": consistent,
            "inconsistent": total - consistent,
            "consistency_rate": round(consistent / total * 100, 1) if total > 0 else 0,
            "avg_quality_score": round(avg_quality, 3),
            "warnings": warnings[:20],  # İlk 20 uyarı
        }


# Singleton
data_validator = DataValidator()
