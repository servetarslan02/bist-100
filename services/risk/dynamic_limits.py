"""
ALPHA BIST — Dynamic Risk Limits v1.0

Volatilite, rejim ve drawdown'a göre dinamik risk limitleri.
Sabit limitler yerine piyasa koşullarına uyum sağlayan limit sistemi.

Kaynaklar:
- ScienceDirect — Integrated Risk Management Framework (2026)
- arXiv 2605.19337 — Agentic Trading Meta-Analiz (2026)
- Nature — ML-Based Dynamic Risk Allocation (2025)
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class RiskLimits:
    """Risk limitleri."""
    max_position_pct: float = 10.0       # Tek pozisyon max %
    max_sector_pct: float = 30.0         # Sektör max %
    max_exposure_pct: float = 95.0       # Toplam maruziyet max %
    daily_loss_limit_pct: float = 5.0    # Günlük zarar limiti %
    max_drawdown_pct: float = 20.0       # Max drawdown %
    max_order_pct: float = 5.0           # Tek emir max %
    min_confidence: float = 0.3          # Min güven eşiği
    max_var_pct: float = 5.0             # Max VaR %
    max_correlation: float = 0.8         # Max korelasyon
    kelly_fraction: float = 0.5          # Kelly fraction


@dataclass
class LimitAdjustment:
    """Limit ayarlama kaydı."""
    reason: str
    original: float
    adjusted: float
    scale_factor: float


class DynamicRiskLimits:
    """Volatilite, rejim ve drawdown'a göre dinamik risk limitleri.

    Prensip: Piyasa koşulları kötüleşince limitler otomatik sıkılaşır,
    iyileşince gevşer. Bu sayede risk yönetimi adaptif olur.
    """

    # Baz limitler (normal piyasa koşulları)
    BASE_LIMITS = RiskLimits()

    # Rejim bazlı çarpanlar
    REGIME_MULTIPLIERS = {
        "BULL":              {"position": 1.1, "exposure": 1.05, "kelly": 1.2, "confidence": 0.9},
        "BEAR":              {"position": 0.7, "exposure": 0.8,  "kelly": 0.6, "confidence": 1.1},
        "SIDEWAYS":          {"position": 1.0, "exposure": 1.0,  "kelly": 0.8, "confidence": 1.0},
        "HIGH_VOLATILITY":   {"position": 0.6, "exposure": 0.7,  "kelly": 0.5, "confidence": 1.2},
        "LOW_VOLATILITY":    {"position": 1.15, "exposure": 1.1, "kelly": 1.1, "confidence": 0.9},
        "RISK_ON":           {"position": 1.1, "exposure": 1.05, "kelly": 1.1, "confidence": 0.95},
        "RISK_OFF":          {"position": 0.5, "exposure": 0.6,  "kelly": 0.5, "confidence": 1.2},
        "CRISIS":            {"position": 0.3, "exposure": 0.4,  "kelly": 0.3, "confidence": 1.5},
        "RECOVERY":          {"position": 0.9, "exposure": 0.9,  "kelly": 0.9, "confidence": 1.0},
    }

    # Volatilite eşikleri (yıllık)
    VOL_THRESHOLDS = {
        "very_low":  0.10,   # < %10 yıllık vol
        "low":       0.15,   # %10-15
        "normal":    0.20,   # %15-20
        "high":      0.30,   # %20-30
        "very_high": 0.50,   # > %30
    }

    # Drawdown eşikleri ve aksiyonları
    DRAWDOWN_THRESHOLDS = [
        {"threshold": 5.0,  "action": "REDUCE_SIZE",  "position_scale": 0.5, "description": "Pozisyon boyutunu %50 azalt"},
        {"threshold": 10.0, "action": "STOP_NEW",     "position_scale": 0.0, "description": "Yeni pozisyon durdur"},
        {"threshold": 15.0, "action": "CLOSE_POSITIONS", "position_scale": 0.0, "description": "Pozisyon kapat"},
        {"threshold": 20.0, "action": "HALT_SYSTEM",  "position_scale": 0.0, "description": "Sistem durdur"},
    ]

    def get_limits(
        self,
        annualized_volatility: float = 0.20,
        regime: str = "SIDEWAYS",
        current_drawdown_pct: float = 0.0,
        vix_level: Optional[float] = None,
    ) -> RiskLimits:
        """Dinamik limitler hesapla.

        Args:
            annualized_volatility: Yıllık volatilite (0.20 = %20)
            regime: Mevcut rejim
            current_drawdown_pct: Mevcut drawdown %
            vix_level: VIX seviyesi (opsiyonel)

        Returns:
            Ayarlanmış RiskLimits
        """
        limits = RiskLimits()  # Baz limitlerden kopyala
        adjustments = []

        # 1. Volatilite bazlı ayarlama
        vol_scale = self._volatility_scale(annualized_volatility)
        limits.max_position_pct *= vol_scale
        limits.max_sector_pct *= vol_scale
        limits.max_exposure_pct *= vol_scale
        limits.max_order_pct *= vol_scale
        adjustments.append(LimitAdjustment(
            reason=f"Volatility {annualized_volatility:.1%}",
            original=self.BASE_LIMITS.max_position_pct,
            adjusted=limits.max_position_pct,
            scale_factor=vol_scale,
        ))

        # 2. Rejim bazlı ayarlama
        regime_mult = self.REGIME_MULTIPLIERS.get(regime, self.REGIME_MULTIPLIERS["SIDEWAYS"])
        limits.max_position_pct *= regime_mult["position"]
        limits.max_exposure_pct *= regime_mult["exposure"]
        limits.kelly_fraction *= regime_mult["kelly"]
        limits.min_confidence *= regime_mult["confidence"]
        adjustments.append(LimitAdjustment(
            reason=f"Regime: {regime}",
            original=limits.max_position_pct / regime_mult["position"],
            adjusted=limits.max_position_pct,
            scale_factor=regime_mult["position"],
        ))

        # 3. Drawdown bazlı ayarlama
        dd_scale = self._drawdown_scale(current_drawdown_pct)
        if dd_scale < 1.0:
            limits.max_position_pct *= dd_scale
            limits.max_exposure_pct *= dd_scale
            limits.kelly_fraction *= dd_scale
            adjustments.append(LimitAdjustment(
                reason=f"Drawdown {current_drawdown_pct:.1f}%",
                original=limits.max_position_pct / dd_scale,
                adjusted=limits.max_position_pct,
                scale_factor=dd_scale,
            ))

        # 4. VIX bazlı ayarlama (global risk algısı)
        if vix_level is not None:
            vix_scale = self._vix_scale(vix_level)
            if vix_scale < 1.0:
                limits.max_position_pct *= vix_scale
                limits.max_exposure_pct *= vix_scale
                adjustments.append(LimitAdjustment(
                    reason=f"VIX {vix_level:.1f}",
                    original=limits.max_position_pct / vix_scale,
                    adjusted=limits.max_position_pct,
                    scale_factor=vix_scale,
                ))

        # Sınırla
        limits.max_position_pct = max(1.0, min(20.0, limits.max_position_pct))
        limits.max_sector_pct = max(5.0, min(40.0, limits.max_sector_pct))
        limits.max_exposure_pct = max(20.0, min(100.0, limits.max_exposure_pct))
        limits.kelly_fraction = max(0.1, min(0.75, limits.kelly_fraction))
        limits.min_confidence = max(0.2, min(0.8, limits.min_confidence))

        # Log
        if adjustments:
            logger.info("Dynamic limits adjusted",
                       adjustments=[(a.reason, f"{a.scale_factor:.2f}x") for a in adjustments],
                       final_position_limit=f"{limits.max_position_pct:.1f}%")

        return limits

    def get_drawdown_action(self, current_drawdown_pct: float) -> Optional[Dict[str, Any]]:
        """Drawdown eşiğine göre aksiyon belirle.

        Args:
            current_drawdown_pct: Mevcut drawdown %

        Returns:
            Aksiyon sözlüğü veya None
        """
        for threshold in reversed(self.DRAWDOWN_THRESHOLDS):
            if current_drawdown_pct >= threshold["threshold"]:
                return {
                    "action": threshold["action"],
                    "drawdown_pct": current_drawdown_pct,
                    "threshold": threshold["threshold"],
                    "position_scale": threshold["position_scale"],
                    "description": threshold["description"],
                }
        return None

    def _volatility_scale(self, annualized_vol: float) -> float:
        """Volatilite bazlı çarpan."""
        if annualized_vol <= self.VOL_THRESHOLDS["very_low"]:
            return 1.20  # Çok düşük vol → gevşet
        elif annualized_vol <= self.VOL_THRESHOLDS["low"]:
            return 1.10
        elif annualized_vol <= self.VOL_THRESHOLDS["normal"]:
            return 1.00  # Normal
        elif annualized_vol <= self.VOL_THRESHOLDS["high"]:
            return 0.75  # Yüksek vol → sıkılaştır
        else:
            return 0.50  # Çok yüksek vol → çok sıkılaştır

    def _drawdown_scale(self, drawdown_pct: float) -> float:
        """Drawdown bazlı çarpan."""
        if drawdown_pct <= 3.0:
            return 1.0
        elif drawdown_pct <= 5.0:
            return 0.80
        elif drawdown_pct <= 10.0:
            return 0.50
        elif drawdown_pct <= 15.0:
            return 0.25
        else:
            return 0.10  # Neredeyse durdur

    def _vix_scale(self, vix_level: float) -> float:
        """VIX bazlı çarpan (global risk algısı)."""
        if vix_level < 15:
            return 1.1   # Düşük VIX → gevşet
        elif vix_level < 20:
            return 1.0   # Normal
        elif vix_level < 25:
            return 0.85  # Yüksek VIX → sıkılaştır
        elif vix_level < 35:
            return 0.65  # Çok yüksek
        else:
            return 0.40  # Ekstrem VIX → çok sıkılaştır

    def compare_limits(
        self,
        static_limits: RiskLimits,
        dynamic_limits: RiskLimits,
    ) -> Dict[str, Dict[str, float]]:
        """Statik vs dinamik limit karşılaştırması."""
        return {
            "max_position_pct": {"static": static_limits.max_position_pct, "dynamic": dynamic_limits.max_position_pct},
            "max_sector_pct": {"static": static_limits.max_sector_pct, "dynamic": dynamic_limits.max_sector_pct},
            "max_exposure_pct": {"static": static_limits.max_exposure_pct, "dynamic": dynamic_limits.max_exposure_pct},
            "kelly_fraction": {"static": static_limits.kelly_fraction, "dynamic": dynamic_limits.kelly_fraction},
            "min_confidence": {"static": static_limits.min_confidence, "dynamic": dynamic_limits.min_confidence},
        }


# Singleton
dynamic_limits = DynamicRiskLimits()
