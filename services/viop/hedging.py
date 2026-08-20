"""
ALPHA BIST — VIOP Hedging Wrapper

Portföy hedge önerileri.
Enhanced_options modülünden delegate eder.
"""

from typing import Dict, Any
from .enhanced_options import delta_hedger, DeltaHedger, DeltaHedgeResult


def hedge_portfolio(portfolio_value: float, beta: float, futures_price: float) -> Dict[str, Any]:
    """Portföy hedge önerisi.

    Args:
        portfolio_value: Portföy değeri (TL)
        beta: Portföy beta'sı (BIST-30'a göre)
        futures_price: Futures fiyatı (TL)

    Returns:
        {"contracts_needed", "action", "hedge_value", "estimated_cost", ...}
    """
    # Portföy deltasını hesapla: portfolio_value * beta / futures_price
    portfolio_delta = portfolio_value * beta / futures_price if futures_price > 0 else 0

    # BIST-30 futures contract multiplier: futures_price * 10
    contract_multiplier = futures_price * 10 if futures_price > 0 else 100

    result = delta_hedger.hedge(
        portfolio_delta=portfolio_delta,
        spot_price=futures_price,
        futures_price=futures_price,
        contract_multiplier=contract_multiplier,
    )

    return {
        "contracts_needed": abs(result.contracts_needed),
        "action": result.action,
        "hedge_value": round(abs(result.contracts_needed) * contract_multiplier, 2),
        "estimated_cost": round(result.estimated_cost, 2),
        "current_delta": result.current_delta,
        "target_delta": result.target_delta,
        "delta_gap": result.delta_gap,
    }


__all__ = ["hedge_portfolio", "delta_hedger", "DeltaHedger", "DeltaHedgeResult"]
