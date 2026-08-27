"""
ALPHA BIST — Cross-Source Reconciliation v1.0

Kaynaklar arası fiyat uzlaştırma:
Yahoo ↔ Matriks ↔ BIST resmi ↔ KAP

Ağırlıklı canonical price hesaplama.
Conflict detection ve quality scoring.

Kullanım:
    reconciler = SourceReconciler()
    result = await reconciler.reconcile_price("THYAO", {
        "yfinance": 308.50,
        "matriks": 308.50,
        "bist_official": 308.50,
    })
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ReconciliationResult:
    """Uzlaştırma sonucu."""

    ticker: str
    canonical_price: float
    source: str  # "reconciled" veya tek kaynak adı
    conflict: bool  # Kaynaklar arası çakışma var mı
    quality_score: float  # 0-1
    max_deviation_pct: float  # Maksimum sapma %
    sources: dict[str, float] = field(default_factory=dict)  # source → price
    deviations: dict[str, float] = field(default_factory=dict)  # source → deviation %
    warnings: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class SourceReconciler:
    """
    Kaynaklar arası fiyat uzlaştırma.

    Kaynak güvenilirlik ağırlıkları:
    - bist_official: 1.00 (en güvenilir)
    - matriks: 0.90
    - yfinance: 0.85
    - investing: 0.70
    - social: 0.30
    """

    # Kaynak güvenilirlik ağırlıkları
    SOURCE_WEIGHTS = {
        "bist_official": 1.00,
        "kap": 0.95,
        "matriks": 0.90,
        "yfinance": 0.85,
        "investing": 0.70,
        "google": 0.60,
        "news": 0.50,
        "social": 0.30,
    }

    # Maksimum kabul edilebilir sapma (%)
    DEFAULT_MAX_DEVIATION_PCT = 0.5

    async def reconcile_price(
        self,
        ticker: str,
        prices: dict[str, float],
        max_deviation_pct: float | None = None,
    ) -> ReconciliationResult:
        """
        Çoklu kaynaktan fiyatı uzlaştır.

        Args:
            ticker: Hisse kodu
            prices: {source_name: price} sözlüğü
            max_deviation_pct: Maksimum kabul edilebilir sapma %

        Returns:
            ReconciliationResult
        """
        if not prices:
            return ReconciliationResult(
                ticker=ticker,
                canonical_price=0.0,
                source="none",
                conflict=False,
                quality_score=0.0,
                max_deviation_pct=0.0,
                warnings=["No price data from any source"],
            )

        max_dev = max_deviation_pct or self.DEFAULT_MAX_DEVIATION_PCT

        # Tek kaynak
        if len(prices) == 1:
            source, price = list(prices.items())[0]
            return ReconciliationResult(
                ticker=ticker,
                canonical_price=round(price, 2),
                source=source,
                conflict=False,
                quality_score=0.6,  # Tek kaynak = düşük güven
                max_deviation_pct=0.0,
                sources=prices,
                warnings=["Single source — no cross-validation"],
            )

        # Ağırlıklı canonical price
        canonical = self._compute_canonical_price(prices)

        # Sapmaları hesapla
        deviations = {}
        for source, price in prices.items():
            if price > 0 and canonical > 0:
                deviation = abs(price - canonical) / canonical * 100
                deviations[source] = round(deviation, 4)

        max_deviation = max(deviations.values()) if deviations else 0
        conflict = max_deviation > max_dev

        # Kalite skoru
        quality = self._compute_quality_score(prices, deviations, conflict)

        # Uyarılar
        warnings = []
        if conflict:
            for source, dev in deviations.items():
                if dev > max_dev:
                    warnings.append(f"{source}: {dev:.2f}% deviation from canonical")

        return ReconciliationResult(
            ticker=ticker,
            canonical_price=round(canonical, 2),
            source="reconciled",
            conflict=conflict,
            quality_score=round(quality, 3),
            max_deviation_pct=round(max_deviation, 3),
            sources={k: round(v, 2) for k, v in prices.items()},
            deviations=deviations,
            warnings=warnings,
        )

    async def reconcile_batch(
        self,
        data: dict[str, dict[str, float]],
    ) -> dict[str, ReconciliationResult]:
        """
        Toplu uzlaştırma.

        Args:
            data: {ticker: {source: price}} sözlüğü

        Returns:
            {ticker: ReconciliationResult} sözlüğü
        """
        results = {}
        for ticker, prices in data.items():
            results[ticker] = await self.reconcile_price(ticker, prices)
        return results

    def _compute_canonical_price(self, prices: dict[str, float]) -> float:
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
        self,
        prices: dict[str, float],
        deviations: dict[str, float],
        conflict: bool,
    ) -> float:
        """Kalite skoru (0-1)."""
        score = 1.0

        # Kaynak sayısına göre
        source_count = len(prices)
        if source_count == 1:
            score *= 0.6
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

        # Çakışma varsa
        if conflict:
            score *= 0.6

        return score

    def get_quality_report(
        self,
        results: dict[str, ReconciliationResult],
    ) -> dict[str, Any]:
        """Kalite raporu."""
        total = len(results)
        consistent = sum(1 for r in results.values() if not r.conflict)
        avg_quality = sum(r.quality_score for r in results.values()) / total if total > 0 else 0

        all_warnings = []
        for r in results.values():
            all_warnings.extend(r.warnings)

        return {
            "total_tickers": total,
            "consistent": consistent,
            "conflicts": total - consistent,
            "consistency_rate": round(consistent / max(total, 1) * 100, 1),
            "avg_quality_score": round(avg_quality, 3),
            "warnings": all_warnings[:20],
        }


# Singleton
source_reconciler = SourceReconciler()
