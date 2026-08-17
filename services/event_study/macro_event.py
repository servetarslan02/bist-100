"""ALPHA BIST — Macro Event Analysis."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def analyze_tcmb_event(rate_actual: float, rate_expected: float, market_returns: list) -> Dict[str, Any]:
    """TCMB faiz kararı etki analizi."""
    surprise = rate_actual - rate_expected
    import numpy as np
    mr = np.array(market_returns)
    car = float(np.sum(mr)) if len(mr) > 0 else 0
    return {"surprise": round(surprise, 4), "car_5d": round(car, 4), "direction": "HAWKISH" if surprise > 0 else "DOVISH"}
