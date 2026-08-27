"""
ALPHA BIST — Tail Risk Hedging v1.0

Kuyruk riski koruma stratejileri:
- Protective put strategy
- VIX-based hedge ratio
- Crisis alpha detection
- Hedge maliyeti hesaplama

Kaynaklar:
- Resonanz Capital — Tail-Risk Hedging (2025)
- CFA Institute — Measuring and Managing Market Risk (2026)
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class HedgeRecommendation:
    """Hedge önerisi."""

    strategy: str
    hedge_ratio: float  # 0.0-1.0 (portföyün ne kadarı hedge edilmeli)
    estimated_cost_pct: float  # Maliyet (portföyün %'si)
    estimated_cost_amount: float  # Maliyet (TL)
    protection_level: str  # LOW, MEDIUM, HIGH
    description: str
    instruments: list[str]  # Önerilen enstrümanlar


@dataclass
class CrisisAlphaSignal:
    """Crisis alpha sinyali."""

    signal_strength: float  # 0.0-1.0
    regime: str  # NORMAL, ELEVATED, CRISIS
    vix_level: float
    correlation_breakdown: bool
    recommended_action: str
    description: str


class TailRiskHedger:
    """Tail risk koruma sistemi.

    VIX, korelasyon çöküşü ve rejim değişimlerini kullanarak
    portföyü kuyruk riskinden korur.
    """

    # VIX eşikleri
    VIX_LEVELS = {
        "LOW": 15,
        "NORMAL": 20,
        "ELEVATED": 25,
        "HIGH": 30,
        "CRISIS": 40,
    }

    # Hedge stratejileri
    STRATEGIES = {
        "PROTECTIVE_PUT": {
            "name": "Protective Put",
            "description": "Endeks put opsiyonu ile aşağı yönlü koruma",
            "cost_range": (0.5, 2.0),  # Portföyün %-si
            "protection": "HIGH",
        },
        "COLLAR": {
            "name": "Collar Strategy",
            "description": "Put al + call sat → maliyeti düşürür",
            "cost_range": (0.2, 1.0),
            "protection": "MEDIUM",
        },
        "TAIL_SPREAD": {
            "name": "Tail Risk Spread",
            "description": "OTM put spread — ucuz koruma",
            "cost_range": (0.1, 0.5),
            "protection": "LOW",
        },
        "VIX_CALL": {
            "name": "VIX Call",
            "description": "VIX call opsiyonu — volatilite artışından kazanç",
            "cost_range": (0.3, 1.5),
            "protection": "HIGH",
        },
        "CRISIS_ALPHA": {
            "name": "Crisis Alpha",
            "description": "Negatif korelasyonlu varlık (altın, tahvil)",
            "cost_range": (0.0, 0.5),
            "protection": "MEDIUM",
        },
    }

    def analyze(
        self,
        portfolio_value: float,
        vix_level: float = 20.0,
        current_drawdown_pct: float = 0.0,
        regime: str = "SIDEWAYS",
        portfolio_beta: float = 1.0,
        correlation_to_market: float = 0.8,
    ) -> HedgeRecommendation:
        """Hedge analizi yap.

        Args:
            portfolio_value: Portföy değeri
            vix_level: VIX seviyesi
            current_drawdown_pct: Mevcut drawdown
            regime: Mevcut rejim
            portfolio_beta: Portföy betası
            market_korelasyonu: Piyasa ile korelasyon

        Returns:
            HedgeRecommendation
        """
        # Risk seviyesi belirle
        risk_level = self._assess_risk_level(vix_level, current_drawdown_pct, regime)

        # Hedge ratio hesapla
        hedge_ratio = self._calculate_hedge_ratio(risk_level, portfolio_beta, correlation_to_market, vix_level)

        # Strateji seç
        strategy = self._select_strategy(risk_level, vix_level, hedge_ratio)

        # Maliyet hesapla
        cost_range = self.STRATEGIES[strategy]["cost_range"]
        estimated_cost_pct = np.mean(cost_range) * hedge_ratio
        estimated_cost_amount = portfolio_value * estimated_cost_pct / 100

        return HedgeRecommendation(
            strategy=self.STRATEGIES[strategy]["name"],
            hedge_ratio=round(hedge_ratio, 3),
            estimated_cost_pct=round(estimated_cost_pct, 2),
            estimated_cost_amount=round(estimated_cost_amount, 2),
            protection_level=self.STRATEGIES[strategy]["protection"],
            description=self.STRATEGIES[strategy]["description"],
            instruments=self._get_instruments(strategy, vix_level),
        )

    def detect_crisis_alpha(
        self,
        vix_level: float = 20.0,
        market_return_5d: float = 0.0,
        gold_return_5d: float = 0.0,
        bond_return_5d: float = 0.0,
        correlation_gold_market: float = -0.2,
    ) -> CrisisAlphaSignal:
        """Crisis alpha sinyali tespit et.

        Crisis alpha: Piyasa çökerken negatif korelasyonlu varlıkların yükselmesi.

        Args:
            vix_level: VIX seviyesi
            market_return_5d: Son 5 gün piyasa getirisi
            gold_return_5d: Son 5 gün altın getirisi
            bond_return_5d: Son 5 gün tahvil getirisi
            gold_market_corr: Altın-piyasa korelasyonu

        Returns:
            CrisisAlphaSignal
        """
        # Sinyal gücü
        signal_strength = 0.0

        # VIX yüksekse crisis alpha daha güçlü
        if vix_level > 30:
            signal_strength += 0.4
        elif vix_level > 25:
            signal_strength += 0.2

        # Piyasa düşerken altın/tahvil yükseliyorsa
        if market_return_5d < -0.02:
            if gold_return_5d > 0:
                signal_strength += 0.3
            if bond_return_5d > 0:
                signal_strength += 0.2

        # Korelasyon breakdown
        correlation_breakdown = correlation_gold_market < -0.3
        if correlation_breakdown:
            signal_strength += 0.1

        signal_strength = min(1.0, signal_strength)

        # Rejim
        if signal_strength > 0.7:
            regime = "CRISIS"
        elif signal_strength > 0.4:
            regime = "ELEVATED"
        else:
            regime = "NORMAL"

        # Aksiyon
        if regime == "CRISIS":
            action = "ALTIN ve TAHVİL ağırlığını artır, riskli varlıkları azalt"
        elif regime == "ELEVATED":
            action = "Hedge pozisyonu aç, altın/tahvil allocation artır"
        else:
            action = "Normal allocation — crisis alpha izle"

        return CrisisAlphaSignal(
            signal_strength=round(signal_strength, 2),
            regime=regime,
            vix_level=vix_level,
            correlation_breakdown=correlation_breakdown,
            recommended_action=action,
            description=f"VIX: {vix_level:.1f}, Piyasa 5g: {market_return_5d:.1%}, Altın 5g: {gold_return_5d:.1%}",
        )

    def calculate_hedge_cost_benefit(
        self,
        portfolio_value: float,
        hedge_cost_pct: float,
        max_loss_without_hedge_pct: float,
        max_loss_with_hedge_pct: float,
    ) -> dict[str, Any]:
        """Hedge maliyet-fayda analizi.

        Args:
            portfolio_value: Portföy değeri
            hedge_cost_pct: Hedge maliyeti (%)
            max_loss_without_hedge: Hedge olmadan max kayıp (%)
            max_loss_with_hedge: Hedge ile max kayıp (%)

        Returns:
            Maliyet-fayda analizi
        """
        hedge_cost = portfolio_value * hedge_cost_pct / 100
        loss_without = portfolio_value * max_loss_without_hedge_pct / 100
        loss_with = portfolio_value * max_loss_with_hedge_pct / 100
        savings = loss_without - loss_with - hedge_cost

        return {
            "hedge_cost": round(hedge_cost, 2),
            "hedge_cost_pct": hedge_cost_pct,
            "loss_without_hedge": round(loss_without, 2),
            "loss_with_hedge": round(loss_with, 2),
            "net_savings": round(savings, 2),
            "net_savings_pct": round(savings / portfolio_value * 100, 2),
            "worth_hedging": savings > 0,
            "breakeven_loss_pct": round(hedge_cost_pct / (1 - max_loss_with_hedge_pct / max_loss_without_hedge_pct), 2)
            if max_loss_without_hedge_pct > max_loss_with_hedge_pct
            else 0,
        }

    def _assess_risk_level(
        self,
        vix_level: float,
        drawdown_pct: float,
        regime: str,
    ) -> str:
        """Risk seviyesi belirle."""
        score = 0

        # VIX
        if vix_level > 35:
            score += 3
        elif vix_level > 25:
            score += 2
        elif vix_level > 20:
            score += 1

        # Drawdown
        if drawdown_pct > 15:
            score += 3
        elif drawdown_pct > 10:
            score += 2
        elif drawdown_pct > 5:
            score += 1

        # Rejim
        if regime in ["CRISIS", "RISK_OFF"]:
            score += 3
        elif regime == "BEAR":
            score += 2
        elif regime == "HIGH_VOLATILITY":
            score += 1

        if score >= 6:
            return "CRITICAL"
        elif score >= 4:
            return "HIGH"
        elif score >= 2:
            return "ELEVATED"
        return "NORMAL"

    def _calculate_hedge_ratio(
        self,
        risk_level: str,
        beta: float,
        correlation: float,
        vix_level: float,
    ) -> float:
        """Hedge ratio hesapla (0.0-1.0)."""
        base_ratio = {
            "NORMAL": 0.0,
            "ELEVATED": 0.2,
            "HIGH": 0.5,
            "CRITICAL": 0.8,
        }.get(risk_level, 0.0)

        # Beta ayarlaması (yüksek beta → daha fazla hedge)
        beta_adj = min(1.5, beta) / 1.0

        # VIX ayarlaması
        vix_adj = min(2.0, vix_level / 20.0)

        ratio = base_ratio * beta_adj * vix_adj
        return min(1.0, max(0.0, ratio))

    def _select_strategy(
        self,
        risk_level: str,
        vix_level: float,
        hedge_ratio: float,
    ) -> str:
        """Hedge stratejisi seç."""
        if risk_level == "CRITICAL":
            if vix_level > 30:
                return "VIX_CALL"  # VIX zaten yüksekse VIX call
            return "PROTECTIVE_PUT"
        elif risk_level == "HIGH":
            return "COLLAR"
        elif risk_level == "ELEVATED":
            return "TAIL_SPREAD"
        return "CRISIS_ALPHA"  # Normal durumda düşük maliyetli

    def _get_instruments(self, strategy: str, vix_level: float) -> list[str]:
        """Strateji için önerilen enstrümanlar."""
        instruments = {
            "PROTECTIVE_PUT": ["XU030 Put Opsiyon", "VIOP Endeks Put"],
            "COLLAR": ["XU030 Put + Call Opsiyon", "VIOP Collar"],
            "TAIL_SPREAD": ["XU030 OTM Put Spread", "VIOP Bear Put Spread"],
            "VIX_CALL": ["VIX Call Opsiyon", "Volatilite Vadeli"],
            "CRISIS_ALPHA": ["Altın (GLD/GOLD)", "Tahvil (TL Hazine)", "USD/TRY Long"],
        }
        return instruments.get(strategy, [])


# Singleton
tail_hedger = TailRiskHedger()
