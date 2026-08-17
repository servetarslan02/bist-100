"""ALPHA BIST — Options Greeks."""
import numpy as np
from typing import Dict, Any

def calculate_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> Dict[str, float]:
    """Delta, Gamma, Theta, Vega, Rho."""
    from scipy.stats import norm
    if T <= 0 or sigma <= 0: return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0}
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100
    if option_type == "call":
        delta = norm.cdf(d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100
    else:
        delta = norm.cdf(d1) - 1
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100
    return {"delta": round(delta, 4), "gamma": round(gamma, 6), "theta": round(theta, 4), "vega": round(vega, 4), "rho": round(rho, 4)}
