"""
ALPHA BIST — Enhanced Execution Simulator v2.0

Gelişmiş execution simülasyonu:
- Square root market impact model
- Regime-aware slippage
- Bid/ask spread bazlı slippage
- Likidite profili
- Gelişmiş partial fill

Kaynaklar: mbrenndoerfer Market Microstructure (2026), arXiv Agentic Trading (2026)
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class LiquidityProfile:
    """Likidite profili."""

    avg_daily_volume: int  # Günlük ortalama hacim
    bid_depth: float = 0.0  # Bid derinliği (TL)
    ask_depth: float = 0.0  # Ask derinliği (TL)
    spread_pct: float = 0.1  # Spread %
    tick_size: float = 0.01  # Minimum fiyat adımı


@dataclass
class MarketImpactResult:
    """Market impact sonucu."""

    base_slippage: float
    volume_impact: float
    regime_impact: float
    total_slippage: float
    fill_price: float
    impact_breakdown: dict[str, float]


class SquareRootMarketImpact:
    """Square root market impact modeli.

    Formül: Impact = σ × √(Q / V) × η

    σ = volatility
    Q = order size (shares)
    V = average daily volume (shares)
    η = impact coefficient (0.1-0.5)

    Kaynak: mbrenndoerfer (2026)
    """

    def __init__(self, eta: float = 0.3):
        self.eta = eta  # Impact coefficient

    def calculate(
        self,
        order_value: float,
        adv_value: float,
        volatility: float,
    ) -> float:
        """Square root market impact hesapla.

        Args:
            order_value: Emir değeri (TL)
            adv_value: Günlük ortalama hacim değeri (TL)
            volatility: Günlük volatilite

        Returns:
            Market impact (oran, 0.01 = %1)
        """
        if adv_value <= 0:
            return 0.001  # Default

        participation = order_value / adv_value
        impact = volatility * np.sqrt(participation) * self.eta

        return min(impact, 0.05)  # Max %5


class RegimeAwareSlippage:
    """Rejime göre slippage ayarlaması.

    Yüksek volatilite/rejim → daha yüksek slippage.
    """

    REGIME_MULTIPLIERS = {
        "BULL": 0.8,
        "BEAR": 1.3,
        "SIDEWAYS": 1.0,
        "HIGH-VOLATILITY": 1.5,
        "LOW-VOLATILITY": 0.7,
        "RISK-ON": 0.9,
        "RISK-OFF": 1.4,
        "PANIC": 2.0,
        "CRISIS": 2.5,
        "RECOVERY": 1.1,
        "MOMENTUM-EXPANSION": 0.9,
        "MOMENTUM-CONTRACTION": 1.2,
        "RANGE": 1.0,
        "TRENDING-UP": 0.85,
        "TRENDING-DOWN": 1.15,
    }

    def adjust_slippage(self, base_slippage: float, regime: str) -> float:
        """Slippage'ı rejime göre ayarla.

        Args:
            base_slippage: Temel slippage
            regime: Piyasa rejimi

        Returns:
            Ayarlanmış slippage
        """
        multiplier = self.REGIME_MULTIPLIERS.get(regime, 1.0)
        return base_slippage * multiplier


class EnhancedExecutionSimulator:
    """Gelişmiş execution simülatörü.

    Özellikler:
    - Square root market impact
    - Regime-aware slippage
    - Bid/ask spread bazlı slippage
    - Likidite profili
    - Gelişmiş partial fill
    """

    # BIST komisyon oranları
    BROKER_COMMISSION_RATE = 0.0003  # %0.03
    EXCHANGE_FEE_RATE = 0.000056  # %0.0056
    BSMV_RATE = 0.05  # BSMV (%5)
    MIN_COMMISSION = 1.0  # Minimum 1 TL

    def __init__(self):
        self._impact_model = SquareRootMarketImpact(eta=0.3)
        self._regime_slippage = RegimeAwareSlippage()

    def execute_order(
        self,
        order,
        market_price: float,
        liquidity: LiquidityProfile,
        regime: str = "RANGE",
        volatility: float = 0.25,
        bid: float = 0,
        ask: float = 0,
    ) -> dict[str, Any]:
        """Gelişmiş emir simülasyonu.

        Args:
            order: Emir objesi
            market_price: Güncel fiyat
            liquidity: Likidite profili
            regime: Piyasa rejimi
            volatility: Günlük volatilite
            bid: En iyi bid fiyatı
            ask: En iyi ask fiyatı

        Returns:
            Execution sonucu
        """
        # 1. Base slippage (bid/ask spread)
        if bid > 0 and ask > 0 and ask > bid:
            spread = (ask - bid) / market_price
            base_slippage = spread / 2
        else:
            base_slippage = (liquidity.spread_pct / 100) / 2

        # 2. Square root market impact
        order_value = order.quantity * market_price
        adv_value = liquidity.avg_daily_volume * market_price
        volume_impact = self._impact_model.calculate(order_value, adv_value, volatility)

        # 3. Regime impact
        regime_impact = self._regime_slippage.adjust_slippage(base_slippage + volume_impact, regime) - (
            base_slippage + volume_impact
        )

        # 4. Toplam slippage
        total_slippage = base_slippage + volume_impact + regime_impact
        total_slippage = min(total_slippage, 0.05)  # Max %5

        # 5. Fill fiyatı
        if order.side.value == "BUY":
            fill_price = market_price * (1 + total_slippage)
        else:
            fill_price = market_price * (1 - total_slippage)

        # 6. Komisyon
        amount = order.quantity * fill_price
        commission = self._compute_commission(amount)

        # 7. Partial fill
        fill_qty = order.quantity
        max_qty = int(liquidity.avg_daily_volume * 0.1)
        if order.quantity > max_qty:
            fill_qty = max_qty

        return {
            "fill_quantity": fill_qty,
            "fill_price": round(fill_price, 4),
            "commission": round(commission, 2),
            "slippage_pct": round(total_slippage * 100, 4),
            "base_slippage_pct": round(base_slippage * 100, 4),
            "volume_impact_pct": round(volume_impact * 100, 4),
            "regime_impact_pct": round(regime_impact * 100, 4),
            "partial_fill": fill_qty < order.quantity,
            "fill_ratio": round(fill_qty / order.quantity, 4) if order.quantity > 0 else 0,
        }

    def _compute_commission(self, amount: float) -> float:
        """BIST komisyon hesaplama."""
        broker_fee = amount * self.BROKER_COMMISSION_RATE
        exchange_fee = amount * self.EXCHANGE_FEE_RATE
        base_commission = broker_fee + exchange_fee
        bsmv = base_commission * self.BSMV_RATE
        total = base_commission + bsmv
        return max(total, self.MIN_COMMISSION)

    def compare_slippage_models(
        self,
        order_value: float,
        adv_value: float,
        volatility: float,
        regime: str = "RANGE",
    ) -> dict[str, Any]:
        """Slippage modellerini karşılaştır.

        Args:
            order_value: Emir değeri
            adv_value: ADV değeri
            volatility: Volatilite
            regime: Rejim

        Returns:
            Karşılaştırma sonucu
        """
        # Linear model (eski)
        linear_impact = (order_value / adv_value) * volatility * 0.5 if adv_value > 0 else 0

        # Square root model (yeni)
        sqrt_impact = self._impact_model.calculate(order_value, adv_value, volatility)

        # Regime adjusted
        regime_adjusted = self._regime_slippage.adjust_slippage(sqrt_impact, regime)

        return {
            "linear_impact_pct": round(linear_impact * 100, 4),
            "sqrt_impact_pct": round(sqrt_impact * 100, 4),
            "regime_adjusted_pct": round(regime_adjusted * 100, 4),
            "regime": regime,
            "improvement": "Square root model daha gerçekçi (büyük emirlerde daha düşük impact)",
        }


# Singleton
enhanced_execution = EnhancedExecutionSimulator()
