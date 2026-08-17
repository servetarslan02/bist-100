"""ALPHA BIST — Options Strategies."""
from typing import Dict, Any

def create_covered_call(spot_price: float, call_strike: float, call_premium: float, shares: int) -> Dict[str, Any]:
    """Covered Call: hisse sat + call sat."""
    max_profit = (call_strike - spot_price + call_premium) * shares
    max_loss = (spot_price - call_premium) * shares
    breakeven = spot_price - call_premium
    return {"strategy": "COVERED_CALL", "max_profit": max_profit, "max_loss": max_loss, "breakeven": breakeven}

def create_protective_put(spot_price: float, put_strike: float, put_premium: float, shares: int) -> Dict[str, Any]:
    """Protective Put: hisse al + put al."""
    max_loss = (spot_price - put_strike + put_premium) * shares
    breakeven = spot_price + put_premium
    return {"strategy": "PROTECTIVE_PUT", "max_loss": max_loss, "breakeven": breakeven}
