"""ALPHA BIST — Altman Z-Score."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def calculate_z_score(financials: Dict[str, Any]) -> float:
    """Altman Z-Score (eşik: <1.81 iflas, >2.99 güvenli)."""
    wc_ta = financials.get("working_capital", 0) / max(financials.get("total_assets", 1), 1)
    re_ta = financials.get("retained_earnings", 0) / max(financials.get("total_assets", 1), 1)
    ebit_ta = financials.get("ebit", 0) / max(financials.get("total_assets", 1), 1)
    equity_debt = financials.get("market_cap", 0) / max(financials.get("total_debt", 1), 1)
    sales_ta = financials.get("revenue", 0) / max(financials.get("total_assets", 1), 1)
    z = 1.2*wc_ta + 1.4*re_ta + 3.3*ebit_ta + 0.6*equity_debt + 1.0*sales_ta
    return z
