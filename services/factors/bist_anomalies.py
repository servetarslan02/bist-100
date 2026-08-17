"""ALPHA BIST — BIST Specific Anomalies."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def calculate_bist_anomalies(stock: Dict[str, Any], market_data: Dict[str, Any]) -> Dict[str, float]:
    """BIST'e özgü anomaliler."""
    anomalies = {}
    # Temettü anomalisi (yüksek temettü verimi → excess return)
    anomalies["dividend_yield"] = stock.get("dividend_yield", 0)
    # Likidite anomalisi (düşük likidite → premium)
    anomalies["liquidity_premium"] = 1.0 - min(stock.get("avg_volume", 0) / 1000000, 1.0)
    # Kur etkisi (USDTRY hassasiyeti)
    anomalies["fx_sensitivity"] = stock.get("usdtry_beta", 0)
    # Sektör momentum
    anomalies["sector_momentum"] = stock.get("sector_momentum", 0)
    return anomalies
