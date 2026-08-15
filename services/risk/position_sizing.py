"""
ALPHA BIST — Position Sizing v1.0

Pozisyon büyüklüğü hesaplama:
- Risk budget
- Stop distance
- Volatility
- Confidence
- Portfolio exposure
- Correlation

FAZ 11: Position Sizing
"""

from typing import Dict, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class PositionSize:
    """Pozisyon boyutlandırma sonucu."""
    ticker: str
    shares: int
    position_value: float
    position_pct: float        # Portföyün yüzdesi
    risk_amount: float         # Maksimum zarar (TL)
    risk_pct: float            # Maksimum zarar (yüzde)
    stop_distance: float       # Giriş - stop arası
    stop_price: float
    entry_price: float
    method: str                # RISK_BUDGET | KELLY | FIXED


class PositionSizer:
    """Pozisyon boyutlandırma motoru."""

    def calculate(
        self,
        ticker: str,
        entry_price: float,
        stop_price: float,
        portfolio_value: float,
        max_position_pct: float = 10.0,
        max_risk_per_trade_pct: float = 2.0,
        confidence: float = 0.5,
        volatility: float = 0.25,
        correlation_to_portfolio: float = 0.5,
    ) -> PositionSize:
        """Risk budget yöntemiyle pozisyon boyutu hesapla.

        Portfolio: 100,000 TL
        Risk budget: 0.75%
        Maximum loss: 750 TL
        Stop distance: 5 TL
        → Shares: 150
        """
        # Stop distance
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            logger.warning("Invalid stop distance", ticker=ticker, stop=stop_price, entry=entry_price)
            return PositionSize(
                ticker=ticker, shares=0, position_value=0, position_pct=0,
                risk_amount=0, risk_pct=0, stop_distance=0, stop_price=stop_price,
                entry_price=entry_price, method="INVALID",
            )

        # Risk budget (TL)
        risk_pct = max_risk_per_trade_pct * confidence  # Düşük güven = düşük risk
        risk_pct = min(risk_pct, max_risk_per_trade_pct)
        risk_amount = portfolio_value * (risk_pct / 100)

        # Shares from risk budget
        shares = int(risk_amount / stop_distance)

        # Position value
        position_value = shares * entry_price

        # Position % check
        position_pct = (position_value / portfolio_value) * 100 if portfolio_value > 0 else 0

        # Max position limit
        if position_pct > max_position_pct:
            position_pct = max_position_pct
            position_value = portfolio_value * (max_position_pct / 100)
            shares = int(position_value / entry_price)
            position_value = shares * entry_price
            position_pct = (position_value / portfolio_value) * 100 if portfolio_value > 0 else 0

        # Correlation adjustment
        if correlation_to_portfolio > 0.8:
            # Yüksek korelasyon → pozisyonu küçült
            shares = int(shares * 0.7)
            position_value = shares * entry_price
            position_pct = (position_value / portfolio_value) * 100 if portfolio_value > 0 else 0

        # Volatility adjustment
        if volatility > 0.4:
            # Çok yüksek volatilite → pozisyonu küçült
            shares = int(shares * 0.8)
            position_value = shares * entry_price
            position_pct = (position_value / portfolio_value) * 100 if portfolio_value > 0 else 0

        # Recalculate actual risk
        actual_risk = shares * stop_distance
        actual_risk_pct = (actual_risk / portfolio_value) * 100 if portfolio_value > 0 else 0

        return PositionSize(
            ticker=ticker,
            shares=shares,
            position_value=round(position_value, 2),
            position_pct=round(position_pct, 2),
            risk_amount=round(actual_risk, 2),
            risk_pct=round(actual_risk_pct, 2),
            stop_distance=round(stop_distance, 2),
            stop_price=stop_price,
            entry_price=entry_price,
            method="RISK_BUDGET",
        )


# Singleton
position_sizer = PositionSizer()
