"""ALPHA BIST — KAP Event Analysis."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def analyze_kap_event(ticker: str, event_type: str, stock_returns: list, market_returns: list) -> Dict[str, Any]:
    """KAP açıklaması etki analizi."""
    from .expected_return import calculate_expected_return
    from .abnormal_return import calculate_abnormal_return
    from .car import calculate_car
    from .statistical_test import test_significance
    import numpy as np
    sr = np.array(stock_returns); mr = np.array(market_returns)
    alpha, beta = calculate_expected_return(sr, mr)
    ar = calculate_abnormal_return(sr, mr, alpha, beta)
    car = calculate_car(ar)
    stats = test_significance(car, ar)
    return {"ticker": ticker, "event_type": event_type, "car": round(car, 4), **stats}
