"""ALPHA BIST — Black-Scholes Options Pricing."""
import numpy as np
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def black_scholes(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
    """Black-Scholes opsiyon fiyatlaması."""
    from scipy.stats import norm
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
