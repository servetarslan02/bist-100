"""
ALPHA BIST — VIOP Strategies Wrapper

Opsiyon stratejileri: Covered Call, Protective Put, vb.
Enhanced_options modülünden delegate eder.
"""

from .enhanced_options import OptionsStrategies, StrategyResult, options_strategies


def create_covered_call(spot: float, call_strike: float, call_premium: float,
                        shares: int = 100) -> dict:
    """Covered Call stratejisi oluştur."""
    result = options_strategies.covered_call(spot, call_strike, call_premium, shares)
    return result.to_dict() if hasattr(result, 'to_dict') else {
        "strategy": result.strategy,
        "max_profit": result.max_profit,
        "max_loss": result.max_loss,
        "breakeven": result.breakeven,
        "risk_reward": result.risk_reward,
        "legs": result.legs,
    }


def create_protective_put(spot: float, put_strike: float, put_premium: float,
                          shares: int = 100) -> dict:
    """Protective Put stratejisi oluştur."""
    result = options_strategies.protective_put(spot, put_strike, put_premium, shares)
    return result.to_dict() if hasattr(result, 'to_dict') else {
        "strategy": result.strategy,
        "max_profit": result.max_profit,
        "max_loss": result.max_loss,
        "breakeven": result.breakeven,
        "risk_reward": result.risk_reward,
        "legs": result.legs,
    }


__all__ = [
    "create_covered_call",
    "create_protective_put",
    "options_strategies",
    "OptionsStrategies",
    "StrategyResult",
]
