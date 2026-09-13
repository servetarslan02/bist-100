"""
ALPHA BIST — VIOP Options Multi-Leg Strategy Builder (Institutional Grade)

Opsiyon stratejileri: Covered Call, Protective Put, Collar, Iron Condor,
Straddle, Strangle, Bull Call Spread, Bear Put Spread, Long Butterfly.
"""

from __future__ import annotations

from typing import Any

from .enhanced_options import OptionsStrategies, StrategyResult, options_strategies


def create_covered_call(spot: float, call_strike: float, call_premium: float, shares: int = 100) -> dict[str, Any]:
    """Covered Call: Hisse senedi uzun + Call opsiyonu kısa pozisyon."""
    result = options_strategies.covered_call(spot, call_strike, call_premium, shares)
    return result.to_dict()


def create_protective_put(spot: float, put_strike: float, put_premium: float, shares: int = 100) -> dict[str, Any]:
    """Protective Put: Hisse senedi uzun + Put opsiyonu uzun (Aşağı yönlü sigorta)."""
    result = options_strategies.protective_put(spot, put_strike, put_premium, shares)
    return result.to_dict()


def create_collar(
    spot: float,
    put_strike: float,
    put_premium: float,
    call_strike: float,
    call_premium: float,
    shares: int = 100,
) -> dict[str, Any]:
    """Collar Stratejisi: Hisse + Alttan Put Al + Üstten Call Sat (Sıfır/Düşük maliyetli koruma)."""
    result = options_strategies.collar(spot, put_strike, put_premium, call_strike, call_premium, shares)
    return result.to_dict()


def create_straddle(spot: float, strike: float, call_premium: float, put_premium: float) -> dict[str, Any]:
    """Long Straddle: Aynı kullanım fiyatlı Call + Put Al (Yüksek volatilite beklentisi)."""
    result = options_strategies.straddle(spot, strike, call_premium, put_premium)
    return result.to_dict()


def create_strangle(
    spot: float,
    put_strike: float,
    put_premium: float,
    call_strike: float,
    call_premium: float,
) -> dict[str, Any]:
    """Long Strangle: Düşük strike Put Al + Yüksek strike Call Al (Daha ucuz volatilite oyunu)."""
    result = options_strategies.strangle(spot, put_strike, put_premium, call_strike, call_premium)
    return result.to_dict()


def create_iron_condor(
    spot: float,
    put_buy_strike: float,
    put_buy_premium: float,
    put_sell_strike: float,
    put_sell_premium: float,
    call_sell_strike: float,
    call_sell_premium: float,
    call_buy_strike: float,
    call_buy_premium: float,
) -> dict[str, Any]:
    """Iron Condor: 4 bacaklı piyasa yatay/nötr seyir stratejisi (Maksimum zaman erimesi kazancı)."""
    result = options_strategies.iron_condor(
        spot,
        put_buy_strike,
        put_buy_premium,
        put_sell_strike,
        put_sell_premium,
        call_sell_strike,
        call_sell_premium,
        call_buy_strike,
        call_buy_premium,
    )
    return result.to_dict()


def create_bull_call_spread(
    spot: float,
    lower_strike: float,
    lower_premium: float,
    higher_strike: float,
    higher_premium: float,
) -> dict[str, Any]:
    """Bull Call Spread: Düşük strike Call Al + Yüksek strike Call Sat (Ilımlı yükseliş)."""
    result = options_strategies.bull_call_spread(spot, lower_strike, lower_premium, higher_strike, higher_premium)
    return result.to_dict()


def create_bear_put_spread(
    spot: float,
    higher_strike: float,
    higher_premium: float,
    lower_strike: float,
    lower_premium: float,
) -> dict[str, Any]:
    """Bear Put Spread: Yüksek strike Put Al + Düşük strike Put Sat (Ilımlı düşüş)."""
    result = options_strategies.bear_put_spread(spot, higher_strike, higher_premium, lower_strike, lower_premium)
    return result.to_dict()


def create_butterfly(
    spot: float,
    lower_strike: float,
    lower_premium: float,
    mid_strike: float,
    mid_premium: float,
    higher_strike: float,
    higher_premium: float,
) -> dict[str, Any]:
    """Long Butterfly: 1 Alt Call Al + 2 Orta Call Sat + 1 Üst Call Al (Hassas hedef fiyat)."""
    result = options_strategies.butterfly(
        spot, lower_strike, lower_premium, mid_strike, mid_premium, higher_strike, higher_premium
    )
    return result.to_dict()


__all__ = [
    "create_covered_call",
    "create_protective_put",
    "create_collar",
    "create_straddle",
    "create_strangle",
    "create_iron_condor",
    "create_bull_call_spread",
    "create_bear_put_spread",
    "create_butterfly",
    "options_strategies",
    "OptionsStrategies",
    "StrategyResult",
]
