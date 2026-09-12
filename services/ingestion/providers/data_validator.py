"""
ALPHA BIST — Data Validator v1.0

Kaynaklar arası cross-validation:
Yahoo ↔ Matriks ↔ BIST resmi

Farklılık varsa → DATA QUALITY WARNING
"""

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

# Varsayılan sabitler
DEFAULT_SOURCE_WEIGHTS: dict[str, float] = {
    "bist_official": 1.00,
    "matriks": 0.90,
    "yfinance": 0.85,
    "investing": 0.70,
    "google_news": 0.50,
    "social": 0.30,
}
"""Kaynak güvenilirlik ağırlıkları (0.0-1.0)."""

DEFAULT_MAX_DEVIATION_PCT: float = 0.5
"""Varsayılan maksimum kabul edilebilir sapma (%)."""

DEFAULT_QUALITY_SINGLE_SOURCE: float = 0.6
DEFAULT_QUALITY_TWO_SOURCES: float = 0.8
DEFAULT_QUALITY_DEV_HIGH: float = 0.5
DEFAULT_QUALITY_DEV_MED: float = 0.7
DEFAULT_QUALITY_DEV_LOW: float = 0.9


@dataclass
class ValidationResult:
    """Doğrulama sonucu.

    Attributes:
        ticker: Hisse sembolü.
        canonical_price: Uzlaştırılmış fiyat.
        sources: {kaynak: fiyat} sözlüğü.
        is_consistent: Kaynaklar tutarlı mı.
        max_deviation_pct: Maksimum sapma yüzdesi.
        quality_score: Kalite puanı (0.0-1.0).
        warnings: Uyarı mesajları.
    """

    ticker: str
    canonical_price: float
    sources: dict[str, float]
    is_consistent: bool
    max_deviation_pct: float
    quality_score: float
    warnings: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        """ValidationResult string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return (
            f"ValidationResult(ticker={self.ticker!r}, "
            f"price={self.canonical_price}, consistent={self.is_consistent}, "
            f"quality={self.quality_score:.2f})"
        )


class DataValidator:
    """Kaynaklar arası cross-validation.

    Yahoo ↔ Matriks ↔ BIST resmi karşılaştırması.
    """

    def __repr__(self) -> str:
        """DataValidator string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return "DataValidator()"

    @property
    def source_weights(self) -> dict[str, float]:
        """Kaynak güvenilirlik ağırlıklarını döndürür.

        Returns:
            {kaynak_adı: ağırlık} sözlüğü.
        """
        return DEFAULT_SOURCE_WEIGHTS

    def validate_price(
        self,
        ticker: str,
        prices: dict[str, float],
    ) -> ValidationResult:
        """Fiyat doğrulama — kaynaklar arası karşılaştırma.

        Args:
            ticker: Hisse sembolü.
            prices: {kaynak_adı: fiyat} sözlüğü.

        Returns:
            ValidationResult: Doğrulama sonucu.
        """
        if not prices:
            return ValidationResult(
                ticker=ticker,
                canonical_price=0,
                sources=prices,
                is_consistent=False,
                max_deviation_pct=100,
                quality_score=0,
                warnings=["Hiçbir kaynaktan fiyat verisi yok"],
            )

        # Ağırlıklı ortalama → canonical price
        canonical = self._compute_canonical_price(prices)

        # Sapmaları hesapla
        deviations: dict[str, float] = {}
        for source, price in prices.items():
            if price > 0:
                deviation = abs(price - canonical) / canonical * 100
                deviations[source] = deviation

        max_deviation = max(deviations.values()) if deviations else 0
        is_consistent = max_deviation <= DEFAULT_MAX_DEVIATION_PCT

        # Kalite skoru
        quality = self._compute_quality_score(prices, deviations)

        # Uyarılar
        warnings: list[str] = []
        if not is_consistent:
            for source, dev in deviations.items():
                if dev > DEFAULT_MAX_DEVIATION_PCT:
                    warnings.append(f"{source}: %{dev:.2f} sapma (canonical'dan)")

        if len(prices) < 2:
            warnings.append("Tek kaynak mevcut — çapraz doğrulama yok")

        return ValidationResult(
            ticker=ticker,
            canonical_price=round(canonical, 2),
            sources={k: round(v, 2) for k, v in prices.items()},
            is_consistent=is_consistent,
            max_deviation_pct=round(max_deviation, 3),
            quality_score=round(quality, 3),
            warnings=warnings,
        )

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
                weight = self.source_weights.get(source, 0.5)
                weighted_sum += price * weight
                total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _compute_quality_score(self, prices: dict[str, float], deviations: dict[str, float]) -> float:
        """Kalite skoru hesaplar (0-1).

        Args:
            prices: {kaynak: fiyat} sözlüğü.
            deviations: {kaynak: sapma_%} sözlüğü.

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

        return score

    def validate_batch(self, data: dict[str, dict[str, float]]) -> dict[str, ValidationResult]:
        """Toplu doğrulama yapar.

        Args:
            data: {ticker: {kaynak: fiyat}} sözlüğü.

        Returns:
            {ticker: ValidationResult} sözlüğü.
        """
        results: dict[str, ValidationResult] = {}
        for ticker, prices in data.items():
            results[ticker] = self.validate_price(ticker, prices)
        return results

    def get_quality_report(self, results: dict[str, ValidationResult]) -> dict[str, Any]:
        """Toplu kalite raporu oluşturur.

        Args:
            results: {ticker: ValidationResult} sözlüğü.

        Returns:
            Kalite raporu sözlüğü.
        """
        total = len(results)
        consistent = sum(1 for r in results.values() if r.is_consistent)
        avg_quality = sum(r.quality_score for r in results.values()) / total if total > 0 else 0
        warnings: list[str] = []
        for r in results.values():
            warnings.extend(r.warnings)

        return {
            "total_tickers": total,
            "consistent": consistent,
            "inconsistent": total - consistent,
            "consistency_rate": round(consistent / max(total, 1) * 100, 1),
            "avg_quality_score": round(avg_quality, 3),
            "warnings": warnings[:20],
        }


# Singleton
data_validator = DataValidator()


__all__ = ["ValidationResult", "DataValidator", "data_validator"]
