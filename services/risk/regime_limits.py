"""ALPHA BIST — Regime-Aware Risk Limits v1.0

Piyasa rejimine göre dinamik risk limitleri:
- Rejime göre max pozisyon boyutu
- Rejime göre toplam maruziyet limiti
- Rejime göre sektör konsantrasyon limiti
- Rejime göre likidite eşiği
- Model confidence → position size bağlantısı

Kullanım:
    from services.risk.regime_limits import regime_limits

    limits = regime_limits.get_limits("BEAR")
    adjusted_size = regime_limits.adjust_for_confidence(base_size, confidence=0.7, regime="BEAR")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class RegimeRiskLimits:
    """Rejime göre risk limitleri."""

    regime: str
    max_position_pct: float  # Tek hisse max %
    max_total_exposure: float  # Toplam maruziyet max %
    max_sector_concentration: float  # Sektör konsantrasyonu max %
    min_liquidity_score: float  # Minimum likidite skoru
    max_leverage: float  # Maks kaldıraç
    stop_loss_pct: float  # Stop-loss %
    confidence_multiplier: float  # Confidence çarpanı
    description: str
    max_positions: int = 30  # Rejim bazlı maksimum hisse sayısı (0 ile max arası dinamik)
    min_cash_pct: float = 0.08  # Fırsatlar için nakit rezerv tamponu (%5-10)


class RegimeLimitsManager:
    """Rejime göre risk limitleri yöneticisi.

    Özellikler:
    - Her rejim için ayrı limit seti
    - Dinamik limit ayarlama
    - Confidence → position size bağlantısı
    - Sektör konsantrasyon kontrolü
    - Likidite-aware sizing
    """

    # Rejim limitleri (BIST'e özel)
    REGIME_LIMITS: dict[str, RegimeRiskLimits] = {
        "BULL": RegimeRiskLimits(
            regime="BULL",
            max_position_pct=0.20,  # Kullanıcı Kuralı: Bir hisse en fazla %20 (Alt sınır serbest)
            max_total_exposure=0.92,  # %8 nakit tamponu (fırsatlar için %5-10 arası)
            max_sector_concentration=0.35,
            min_liquidity_score=0.3,
            max_leverage=1.0,
            stop_loss_pct=0.06,
            confidence_multiplier=1.1,
            max_positions=30,  # Boğada 0 ile 30 hisseye kadar esnek
            min_cash_pct=0.08,
            description="Boğa piyasası — 0-30 hisse, tek hisse max %20, min %8 nakit",
        ),
        "BEAR": RegimeRiskLimits(
            regime="BEAR",
            max_position_pct=0.05,
            max_total_exposure=0.40,  # %60 nakit kalesi (çöküş koruması)
            max_sector_concentration=0.18,
            min_liquidity_score=0.5,
            max_leverage=0.5,
            stop_loss_pct=0.04,
            confidence_multiplier=0.7,
            max_positions=6,  # Ayıda sadece 0-6 defansif lider
            min_cash_pct=0.60,
            description="Ayı piyasası — 0-6 hisse, %60 nakit koruması",
        ),
        "SIDEWAYS": RegimeRiskLimits(
            regime="SIDEWAYS",
            max_position_pct=0.07,
            max_total_exposure=0.75,  # %25 nakit tamponu
            max_sector_concentration=0.25,
            min_liquidity_score=0.4,
            max_leverage=0.7,
            stop_loss_pct=0.05,
            confidence_multiplier=0.9,
            max_positions=15,  # Normal/yatayda 0-15 seçkin hisse
            min_cash_pct=0.25,
            description="Yatay/Normal piyasa — 0-15 hisse, %25 nakit",
        ),
        "HIGH_VOL": RegimeRiskLimits(
            regime="HIGH_VOL",
            max_position_pct=0.04,
            max_total_exposure=0.35,
            max_sector_concentration=0.15,
            min_liquidity_score=0.6,
            max_leverage=0.4,
            stop_loss_pct=0.03,
            confidence_multiplier=0.6,
            max_positions=5,
            min_cash_pct=0.65,
            description="Yüksek volatilite — sıkı limitler, %65 nakit",
        ),
        "LOW_VOL": RegimeRiskLimits(
            regime="LOW_VOL",
            max_position_pct=0.10,
            max_total_exposure=0.90,
            max_sector_concentration=0.30,
            min_liquidity_score=0.3,
            max_leverage=0.9,
            stop_loss_pct=0.05,
            confidence_multiplier=1.0,
            max_positions=25,
            min_cash_pct=0.10,
            description="Düşük volatilite — genişleme, %10 nakit",
        ),
        "CRISIS": RegimeRiskLimits(
            regime="CRISIS",
            max_position_pct=0.03,
            max_total_exposure=0.15,  # %85 nakit kalesi (tam çöküş savunması)
            max_sector_concentration=0.10,
            min_liquidity_score=0.7,
            max_leverage=0.2,
            stop_loss_pct=0.02,
            confidence_multiplier=0.4,
            max_positions=3,  # Krizde en fazla 0-3 altın/maden/savunma hissesi
            min_cash_pct=0.85,
            description="Kriz modu — %85 nakit kalesi, max 3 hisse",
        ),
        "UNKNOWN": RegimeRiskLimits(
            regime="UNKNOWN",
            max_position_pct=0.06,
            max_total_exposure=0.50,
            max_sector_concentration=0.20,
            min_liquidity_score=0.5,
            max_leverage=0.5,
            stop_loss_pct=0.04,
            confidence_multiplier=0.7,
            max_positions=10,
            min_cash_pct=0.50,
            description="Bilinmeyen rejim — muhafazakar",
        ),
    }

    def __init__(self):
        """Otomatik eklendi."""
        self._custom_limits: dict[str, RegimeRiskLimits] = {}

    def get_limits(self, regime: str) -> RegimeRiskLimits:
        """Rejim için limitleri döndür.

        Args:
            regime: Rejim adı

        Returns:
            RegimeRiskLimits
        """
        if regime in self._custom_limits:
            return self._custom_limits[regime]
        return self.REGIME_LIMITS.get(regime, self.REGIME_LIMITS["UNKNOWN"])

    def set_custom_limits(self, regime: str, limits: RegimeRiskLimits) -> None:
        """Özel limit seti tanımla.

        Args:
            regime: Rejim adı
            limits: Limit seti
        """
        self._custom_limits[regime] = limits
        logger.info("custom_regime_limits_set", regime=regime)

    def adjust_for_confidence(
        self,
        base_size: float,
        confidence: float,
        regime: str,
    ) -> float:
        """Confidence'a göre pozisyon boyutu ayarla.

        Yüksek confidence → daha büyük pozisyon (limit dahilinde)
        Düşük confidence → daha küçük pozisyon

        Args:
            base_size: Temel pozisyon boyutu
            confidence: Model confidence'ı [0, 1]
            regime: Mevcut rejim

        Returns:
            Ayarlanmış pozisyon boyutu
        """
        limits = self.get_limits(regime)

        # Confidence çarpanı (0.5 = neutral)
        # confidence=0.5 → multiplier=1.0
        # confidence=1.0 → multiplier=limits.confidence_multiplier
        # confidence=0.0 → multiplier=1.0 - (limits.confidence_multiplier - 1.0)
        conf_factor = 1.0 + (confidence - 0.5) * 2 * (limits.confidence_multiplier - 1.0)
        conf_factor = max(0.3, min(2.0, conf_factor))

        adjusted = base_size * conf_factor

        # Max position limitini aşma
        max_size = limits.max_position_pct
        adjusted = min(adjusted, max_size)

        logger.debug(
            "confidence_adjusted_size",
            base_size=base_size,
            confidence=confidence,
            conf_factor=round(conf_factor, 3),
            adjusted=round(adjusted, 4),
            regime=regime,
        )

        return adjusted

    def check_sector_concentration(
        self,
        positions: dict[str, float],
        sector_map: dict[str, str],
        regime: str,
    ) -> tuple[bool, dict[str, float]]:
        """Sektör konsantrasyonu kontrolü.

        Args:
            positions: {ticker: weight}
            sector_map: {ticker: sector}
            regime: Mevcut rejim

        Returns:
            (is_within_limit, {sector: concentration})
        """
        limits = self.get_limits(regime)

        # Sektör bazlı toplam ağırlık
        sector_weights: dict[str, float] = {}
        for ticker, weight in positions.items():
            sector = sector_map.get(ticker, "UNKNOWN")
            sector_weights[sector] = sector_weights.get(sector, 0.0) + weight

        # Limit kontrolü
        is_within = True
        for sector, concentration in sector_weights.items():
            if concentration > limits.max_sector_concentration:
                is_within = False
                logger.warning(
                    "sector_concentration_exceeded",
                    sector=sector,
                    concentration=round(concentration, 4),
                    limit=limits.max_sector_concentration,
                    regime=regime,
                )

        return is_within, sector_weights

    def check_liquidity(
        self,
        ticker: str,
        liquidity_score: float,
        regime: str,
    ) -> bool:
        """Likidite kontrolü.

        Args:
            ticker: Hisse kodu
            liquidity_score: Likidite skoru [0, 1]
            regime: Mevcut rejim

        Returns:
            Likidite yeterli mi?
        """
        limits = self.get_limits(regime)
        is_sufficient = liquidity_score >= limits.min_liquidity_score

        if not is_sufficient:
            logger.warning(
                "liquidity_insufficient",
                ticker=ticker,
                liquidity_score=liquidity_score,
                min_required=limits.min_liquidity_score,
                regime=regime,
            )

        return is_sufficient

    def get_all_regimes(self) -> list[str]:
        """Tüm rejim isimlerini döndür."""
        return list(self.REGIME_LIMITS.keys())

    def get_limits_summary(self) -> dict[str, dict[str, Any]]:
        """Tüm rejimlerin limit özeti."""
        summary: dict[str, dict[str, Any]] = {}
        for regime in self.REGIME_LIMITS:
            limits = self.get_limits(regime)
            summary[regime] = {
                "max_position_pct": limits.max_position_pct,
                "max_total_exposure": limits.max_total_exposure,
                "max_sector_concentration": limits.max_sector_concentration,
                "min_liquidity_score": limits.min_liquidity_score,
                "max_leverage": limits.max_leverage,
                "stop_loss_pct": limits.stop_loss_pct,
                "confidence_multiplier": limits.confidence_multiplier,
            }
        return summary


# Singleton
regime_limits = RegimeLimitsManager()
