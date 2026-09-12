"""
ALPHA BIST — Cross-Source Reconciliation v1.0

Kaynaklar arası fiyat uzlaştırma:
Yahoo ↔ Matriks ↔ BIST resmi ↔ KAP

Ağırlıklı canonical price hesaplama.
Conflict detection ve quality scoring.

Kullanım:
    reconciler = SourceReconciler()
    result = reconciler.reconcile_price("THYAO", {
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

# Kalite skoru çarpanları
DEFAULT_QUALITY_SINGLE_SOURCE: float = 0.6
DEFAULT_QUALITY_TWO_SOURCES: float = 0.8
DEFAULT_QUALITY_DEV_HIGH: float = 0.5
DEFAULT_QUALITY_DEV_MED: float = 0.7
DEFAULT_QUALITY_DEV_LOW: float = 0.9
DEFAULT_QUALITY_CONFLICT_PENALTY: float = 0.6


@dataclass
class ReconciliationResult:
    """Uzlaştırma sonucu.

    Attributes:
        ticker: Hisse sembolü.
        canonical_price: Uzlaştırılmış fiyat.
        source: "reconciled" veya tek kaynak adı.
        conflict: Kaynaklar arası çakışma var mı.
        quality_score: Kalite puanı (0.0-1.0).
        max_deviation_pct: Maksimum sapma yüzdesi.
        sources: {kaynak: fiyat} sözlüğü.
        deviations: {kaynak: sapma_%} sözlüğü.
        warnings: Uyarı mesajları.
        timestamp: Sonuç zaman damgası.
    """

    ticker: str
    canonical_price: float
    source: str
    conflict: bool
    quality_score: float
    max_deviation_pct: float
    sources: dict[str, float] = field(default_factory=dict)
    deviations: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"ReconciliationResult(ticker={self.ticker!r}, "
            f"price={self.canonical_price}, conflict={self.conflict}, "
            f"quality={self.quality_score:.2f})"
        )


class SourceReconciler:
    """Kaynaklar arası fiyat uzlaştırıcı.

    Çoklu kaynaktan gelen fiyatları ağırlıklı ortalama ile
    birleştirir, çakışma tespiti yapar ve kalite skoru hesaplar.

    Kaynak güvenilirlik ağırlıkları:
    - bist_official: 1.00 (en güvenilir)
    - kap: 0.95
    - matriks: 0.90
    - yfinance: 0.85
    - investing: 0.70
    - social: 0.30
    """

    SOURCE_WEIGHTS: dict[str, float] = {
        "bist_official": 1.00,
        "kap": 0.95,
        "matriks": 0.90,
        "yfinance": 0.85,
        "investing": 0.70,
        "google": 0.60,
        "news": 0.50,
        "social": 0.30,
    }
    """Kaynak güvenilirlik ağırlıkları (0.0-1.0)."""

    DEFAULT_MAX_DEVIATION_PCT: float = 0.5
    """Varsayılan maksimum kabul edilebilir sapma (%)."""

    def reconcile_price(
        self,
        ticker: str,
        prices: dict[str, float],
        max_deviation_pct: float | None = None,
    ) -> ReconciliationResult:
        """Çoklu kaynaktan fiyatı uzlaştırır.

        Args:
            ticker: Hisse kodu.
            prices: {kaynak_adı: fiyat} sözlüğü.
            max_deviation_pct: Maksimum kabul edilebilir sapma %.

        Returns:
            ReconciliationResult: Uzlaştırma sonucu.
        """
        if not prices:
            return ReconciliationResult(
                ticker=ticker,
                canonical_price=0.0,
                source="none",
                conflict=False,
                quality_score=0.0,
                max_deviation_pct=0.0,
                warnings=["Hiçbir kaynaktan fiyat verisi yok"],
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
                quality_score=DEFAULT_QUALITY_SINGLE_SOURCE,
                max_deviation_pct=0.0,
                sources=prices,
                warnings=["Tek kaynak — çapraz doğrulama yok"],
            )

        # Ağırlıklı canonical price
        canonical = self._compute_canonical_price(prices)

        # Sapmaları hesapla
        deviations: dict[str, float] = {}
        for source, price in prices.items():
            if price > 0 and canonical > 0:
                deviation = abs(price - canonical) / canonical * 100
                deviations[source] = round(deviation, 4)

        max_deviation = max(deviations.values()) if deviations else 0
        conflict = max_deviation > max_dev

        # Kalite skoru
        quality = self._compute_quality_score(prices, deviations, conflict)

        # Uyarılar
        warnings: list[str] = []
        if conflict:
            for source, dev in deviations.items():
                if dev > max_dev:
                    warnings.append(f"{source}: %{dev:.2f} sapma (canonical'dan)")

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

    def reconcile_batch(
        self,
        data: dict[str, dict[str, float]],
    ) -> dict[str, ReconciliationResult]:
        """Toplu uzlaştırma yapar.

        Args:
            data: {ticker: {kaynak: fiyat}} sözlüğü.

        Returns:
            {ticker: ReconciliationResult} sözlüğü.
        """
        results: dict[str, ReconciliationResult] = {}
        for ticker, prices in data.items():
            results[ticker] = self.reconcile_price(ticker, prices)
        return results

    def _compute_canonical_price(self, prices: dict[str, float]) -> float:
        """Ağırlıklı ortalama ile canonical price hesaplar.

        Args:
            prices: {kaynak: fiyat} sözlüğü.

        Returns:
            Ağırlıklı canonical fiyat.
        """
        total_weight = 0.0
        weighted_sum = 0.0

        for source, price in prices.items():
            if price > 0:
                weight = self.SOURCE_WEIGHTS.get(source, 0.5)
                weighted_sum += price * weight
                total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _compute_quality_score(
        self,
        prices: dict[str, float],
        deviations: dict[str, float],
        conflict: bool,
    ) -> float:
        """Kalite skoru hesaplar (0-1).

        Args:
            prices: {kaynak: fiyat} sözlüğü.
            deviations: {kaynak: sapma_%} sözlüğü.
            conflict: Kaynaklar arası çakışma var mı.

        Returns:
            Kalite skoru (0.0-1.0).
        """
        score = 1.0

        # Kaynak sayısına göre
        source_count = len(prices)
        if source_count == 1:
            score *= DEFAULT_QUALITY_SINGLE_SOURCE
        elif source_count == 2:
            score *= DEFAULT_QUALITY_TWO_SOURCES

        # Sapmaya göre
        max_dev = max(deviations.values()) if deviations else 0
        if max_dev > 1.0:
            score *= DEFAULT_QUALITY_DEV_HIGH
        elif max_dev > 0.5:
            score *= DEFAULT_QUALITY_DEV_MED
        elif max_dev > 0.1:
            score *= DEFAULT_QUALITY_DEV_LOW

        # Çakışma varsa
        if conflict:
            score *= DEFAULT_QUALITY_CONFLICT_PENALTY

        return score

    def get_quality_report(
        self,
        results: dict[str, ReconciliationResult],
    ) -> dict[str, Any]:
        """Toplu kalite raporu oluşturur.

        Args:
            results: {ticker: ReconciliationResult} sözlüğü.

        Returns:
            Kalite raporu: total_tickers, consistent, conflicts, consistency_rate,
            avg_quality_score, warnings.
        """
        total = len(results)
        consistent = sum(1 for r in results.values() if not r.conflict)
        avg_quality = sum(r.quality_score for r in results.values()) / total if total > 0 else 0

        all_warnings: list[str] = []
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


__all__ = [
    "ReconciliationResult",
    "SourceReconciler",
    "source_reconciler",
]
