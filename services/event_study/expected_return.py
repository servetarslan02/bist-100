"""ALPHA BIST — Expected Return (Market Model)."""
import numpy as np
from typing import Tuple
import structlog
logger = structlog.get_logger()

def calculate_expected_return(stock_returns: np.ndarray, market_returns: np.ndarray) -> Tuple[float, float]:
    """Market Model: E[R] = α + β × R_m."""
    if len(stock_returns) < 10 or len(market_returns) < 10:
        return 0.0, 1.0
    # OLS regression
    x = market_returns.reshape(-1, 1)
    x = np.hstack([np.ones((len(x), 1)), x])
    y = stock_returns
    try:
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        return float(beta[0]), float(beta[1])  # alpha, beta
    except:
        return 0.0, 1.0
