"""
ALPHA BIST — VIOP Put-Call Parity & Synthetic Arbitrage Engine (Institutional Grade)

Avrupa tipi opsiyonlarda C - P = S - K * exp(-r*T) paritesi,
sentetik pozisyon eşlemeleri, kutu arbitrajı (box spread) ve ters dönüşüm (reversal/conversion) fırsatları.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enhanced_options import check_put_call_parity


@dataclass
class ArbitrageOpportunity:
    """Tespit edilen arbitraj veya parite sapma sinyali."""

    strategy_type: str  # CONVERSION, REVERSAL, BOX_SPREAD
    ticker: str
    strike: float
    deviation: float
    expected_profit_tl: float
    action_call: str
    action_put: str
    action_underlying: str
    is_actionable: bool

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return (
            f"ArbitrageOpportunity(strategy={self.strategy_type!r}, "
            f"deviation={self.deviation:+.4f}, profit={self.expected_profit_tl:.2f} TL)"
        )

    def to_dict(self) -> dict[str, Any]:
        """Arbitraj fırsatını sözlük olarak döndürür."""
        return {
            "strategy_type": self.strategy_type,
            "ticker": self.ticker,
            "strike": self.strike,
            "deviation": round(self.deviation, 4),
            "expected_profit_tl": round(self.expected_profit_tl, 2),
            "action_call": self.action_call,
            "action_put": self.action_put,
            "action_underlying": self.action_underlying,
            "is_actionable": self.is_actionable,
        }


class PutCallParityEngine:
    """Kurumsal Put-Call Paritesi ve Sentetik Arbitraj Tarama Motoru."""

    def __init__(self, default_tolerance: float = 0.01, min_arbitrage_profit_tl: float = 250.0):
        """Parite ve arbitraj motorunu ilklendirir."""
        self.default_tolerance = default_tolerance
        self.min_arbitrage_profit_tl = min_arbitrage_profit_tl

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return (
            f"PutCallParityEngine(tolerance={self.default_tolerance}, "
            f"min_profit={self.min_arbitrage_profit_tl:.0f}TL)"
        )

    def verify_parity(
        self,
        call_price: float,
        put_price: float,
        spot_price: float,
        strike: float,
        r: float,
        T: float,
        ticker: str = "BIST30",
        contract_multiplier: int = 100,
    ) -> dict[str, Any]:
        """Put-Call paritesini doğrular ve olası arbitraj kurgusunu belirler."""
        base = check_put_call_parity(call_price, put_price, spot_price, strike, r, T, self.default_tolerance)
        deviation = base["deviation"]

        # Teorik kâr hesaplama (1 sözleşme bazında)
        profit_per_share = abs(deviation)
        profit_tl = profit_per_share * contract_multiplier

        is_arbitrage = profit_tl >= self.min_arbitrage_profit_tl
        if deviation > self.default_tolerance:
            strat = "CONVERSION (Pahalı Call Sat, Ucuz Put Al, Spot Al)"
            action_call = "SELL"
            action_put = "BUY"
            action_spot = "BUY"
        elif deviation < -self.default_tolerance:
            strat = "REVERSAL (Ucuz Call Al, Pahalı Put Sat, Spot Sat/Short)"
            action_call = "BUY"
            action_put = "SELL"
            action_spot = "SELL"
        else:
            strat = "PARITY_BALANCED"
            action_call = "HOLD"
            action_put = "HOLD"
            action_spot = "HOLD"

        opp = ArbitrageOpportunity(
            strategy_type=strat,
            ticker=ticker,
            strike=strike,
            deviation=deviation,
            expected_profit_tl=profit_tl,
            action_call=action_call,
            action_put=action_put,
            action_underlying=action_spot,
            is_actionable=is_arbitrage,
        )

        result = dict(base)
        result["arbitrage_details"] = opp.to_dict()
        return result

    def scan_chain_for_arbitrage(
        self,
        chain: list[dict[str, Any]],
        spot_price: float,
        r: float,
        T: float,
        ticker: str = "BIST30",
    ) -> list[ArbitrageOpportunity]:
        """Tüm opsiyon zincirini tarayarak arbitraj fırsatlarını listeler."""
        opportunities = []
        for item in chain:
            strike = item["strike"]
            call_p = item.get("call_price", 0.0)
            put_p = item.get("put_price", 0.0)
            if call_p > 0 and put_p > 0:
                res = self.verify_parity(call_p, put_p, spot_price, strike, r, T, ticker)
                det = res["arbitrage_details"]
                if det["is_actionable"]:
                    opportunities.append(ArbitrageOpportunity(**det))
        return opportunities


put_call_parity_engine = PutCallParityEngine()

__all__ = [
    "check_put_call_parity",
    "ArbitrageOpportunity",
    "PutCallParityEngine",
    "put_call_parity_engine",
]
