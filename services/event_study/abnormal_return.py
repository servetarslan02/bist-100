"""ALPHA BIST — Abnormal Return."""
import numpy as np

def calculate_abnormal_return(stock_returns: np.ndarray, market_returns: np.ndarray, alpha: float, beta: float) -> np.ndarray:
    """AR = R_stock - (α + β × R_market)."""
    expected = alpha + beta * market_returns
    return stock_returns - expected
