"""ALPHA BIST — Portfolio Hedging."""
from typing import Dict, Any

def hedge_portfolio(portfolio_value: float, beta: float, futures_price: float, multiplier: float = 100) -> Dict[str, Any]:
    """Portföy hedge hesaplama."""
    hedge_ratio = beta * portfolio_value / (futures_price * multiplier)
    contracts_needed = int(round(hedge_ratio))
    return {"hedge_ratio": round(hedge_ratio, 4), "contracts_needed": contracts_needed, "hedge_type": "SHORT_FUTURES"}
