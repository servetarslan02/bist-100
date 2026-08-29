"""
ALPHA BIST — Scanner Interface v1.0

Abstract interface for scanner implementations.
Ensures backtest and live scanning use the same code path.

Kaynaklar: awesome-quant, SCANNER-NIHAI-SPEC.md
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ScanResult:
    """Standart tarama sonucu — tüm scanner'lar bu formatta döndürür."""

    ticker: str
    timestamp: datetime
    price: float = 0.0
    change_1d_pct: float = 0.0
    volume: int = 0

    # Skorlar
    opportunity_score: float = 0.0
    risk_adjusted_score: float = 0.0
    opportunity_rank: int = 0

    # Sinyal
    signal_type: str = ""
    signal_direction: str = ""
    signal_score: float = 0.0
    signal_confidence: float = 0.0

    # Tier
    current_tier: int = 0

    # Bileşen skorları
    momentum_score: float = 0.0
    volume_anomaly_score: float = 0.0
    breakout_score: float = 0.0
    volatility_score: float = 0.0
    relative_strength_score: float = 0.0
    technical_score: float = 0.0
    regime_fit_score: float = 0.0

    # ML
    ml_score: float = 0.0
    event_score: float = 0.0

    # Gerekçe
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp.isoformat(),
            "price": self.price,
            "change_1d_pct": self.change_1d_pct,
            "volume": self.volume,
            "opportunity_score": round(self.opportunity_score, 1),
            "risk_adjusted_score": round(self.risk_adjusted_score, 1),
            "opportunity_rank": self.opportunity_rank,
            "signal_type": self.signal_type,
            "signal_direction": self.signal_direction,
            "signal_score": round(self.signal_score, 1),
            "signal_confidence": round(self.signal_confidence, 2),
            "current_tier": self.current_tier,
            "momentum_score": round(self.momentum_score, 1),
            "volume_anomaly_score": round(self.volume_anomaly_score, 1),
            "breakout_score": round(self.breakout_score, 1),
            "volatility_score": round(self.volatility_score, 1),
            "relative_strength_score": round(self.relative_strength_score, 1),
            "technical_score": round(self.technical_score, 1),
            "regime_fit_score": round(self.regime_fit_score, 1),
            "ml_score": round(self.ml_score, 1),
            "event_score": round(self.event_score, 1),
            "evidence": self.evidence,
            "risks": self.risks,
        }


class ScannerInterface(ABC):
    """Abstract scanner interface.

    Tüm scanner implementasyonları bu interface'i kullanmalıdır.
    Bu sayede backtest ve canlı tarama aynı kod yolunu kullanır.
    """

    @abstractmethod
    def scan(
        self,
        universe: list[str],
        features_map: dict[str, dict[str, float]],
        market_regime: str = "RANGE",
        regime_confidence: float = 0.5,
        ml_scores: dict[str, float] | None = None,
        event_scores: dict[str, float] | None = None,
        sentiment_scores: dict[str, float] | None = None,
        fundamental_scores: dict[str, float] | None = None,
        valuation_scores: dict[str, float] | None = None,
        macro_scores: dict[str, float] | None = None,
    ) -> list[ScanResult]:
        """Tüm evreni tara ve sonuçları döndür.

        Args:
            universe: Taranacak hisseler
            features_map: ticker → features dict
            market_regime: Mevcut piyasa rejimi
            regime_confidence: Rejim güven skoru
            ml_scores: ML model skorları (opsiyonel)
            event_scores: Event skorları (opsiyonel)
            sentiment_scores: Sentiment skorları (opsiyonel)
            fundamental_scores: Fundamental skorlar (opsiyonel)
            valuation_scores: Değerleme skorları (opsiyonel)
            macro_scores: Makro skorlar (opsiyonel)

        Returns:
            ScanResult listesi (skora göre sıralı)
        """

    @abstractmethod
    def get_opportunities(
        self,
        results: list[ScanResult],
        top_n: int = 50,
        min_score: float = 50.0,
    ) -> list[ScanResult]:
        """En iyi fırsatları seç.

        Args:
            results: Tarama sonuçları
            top_n: Maksimum fırsat sayısı
            min_score: Minimum skor eşiği

        Returns:
            Filtrelenmiş fırsatlar
        """

    @abstractmethod
    def generate_signals(
        self,
        results: list[ScanResult],
    ) -> list[ScanResult]:
        """Sinyal üret.

        Args:
            results: Tarama sonuçları

        Returns:
            Sinyal üretilmiş sonuçlar
        """

    def scan_and_rank(
        self,
        universe: list[str],
        features_map: dict[str, dict[str, float]],
        market_regime: str = "RANGE",
        regime_confidence: float = 0.5,
        ml_scores: dict[str, float] | None = None,
        event_scores: dict[str, float] | None = None,
        top_n: int = 50,
    ) -> list[ScanResult]:
        """Tam pipeline: scan → rank → signals.

        Backtest ve canlı tarama bu metodu kullanır.
        """
        results = self.scan(
            universe=universe,
            features_map=features_map,
            market_regime=market_regime,
            regime_confidence=regime_confidence,
            ml_scores=ml_scores,
            event_scores=event_scores,
        )

        # Rank
        results.sort(key=lambda r: r.opportunity_score, reverse=True)
        for i, r in enumerate(results):
            r.opportunity_rank = i + 1

        # Top N'e filtrele
        top_results = results[:top_n]

        # Sinyal üret
        self.generate_signals(top_results)

        return top_results
