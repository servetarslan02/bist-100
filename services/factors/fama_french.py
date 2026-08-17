"""ALPHA BIST — Fama-French Factor Scores."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def calculate_factor_scores(stock: Dict[str, Any], universe_stats: Dict[str, Any]) -> Dict[str, float]:
    """Fama-French faktör skorları."""
    scores = {}
    # Value (P/B, P/E)
    pb = stock.get("pb_ratio", 1)
    pb_median = universe_stats.get("pb_median", 1)
    scores["value"] = 1.0 - min(pb / max(pb_median, 0.1), 2.0) / 2.0
    # Momentum (6-1 aylık getiri)
    scores["momentum"] = min(stock.get("mom_6m", 0) / 20.0, 1.0)
    # Quality (ROE)
    scores["quality"] = min(stock.get("roe", 0) / 30.0, 1.0)
    # Size (piyasa değeri — küçük = yüksek skor)
    mcap = stock.get("market_cap", 0)
    mcap_median = universe_stats.get("mcap_median", 1)
    scores["size"] = 1.0 - min(mcap / max(mcap_median, 1), 2.0) / 2.0
    # Low Volatility
    vol = stock.get("volatility", 20)
    vol_median = universe_stats.get("vol_median", 20)
    scores["low_vol"] = 1.0 - min(vol / max(vol_median, 1), 2.0) / 2.0
    return scores
