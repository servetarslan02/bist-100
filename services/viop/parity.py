"""ALPHA BIST — Put-Call Parity."""
from typing import Dict, Any
import numpy as np

def check_put_call_parity(call_price: float, put_price: float, spot_price: float, strike: float, r: float, T: float) -> Dict[str, Any]:
    """Put-Call Parity: C - P = S - K × e^(-rT)."""
    theoretical_diff = spot_price - strike * np.exp(-r * T)
    actual_diff = call_price - put_price
    deviation = actual_diff - theoretical_diff
    return {"parity_holds": abs(deviation) < 0.01, "deviation": round(deviation, 4), "arbitrage_opportunity": abs(deviation) > 0.05}
