"""ALPHA BIST — Piotroski F-Score."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def calculate_f_score(financials: Dict[str, Any]) -> int:
    """Piotroski F-Score (0-9)."""
    score = 0
    # 1. Net income > 0
    if financials.get("net_income", 0) > 0: score += 1
    # 2. Operating cash flow > 0
    if financials.get("operating_cf", 0) > 0: score += 1
    # 3. ROA increasing
    if financials.get("roa_current", 0) > financials.get("roa_prev", 0): score += 1
    # 4. Cash flow > Net income (accruals)
    if financials.get("operating_cf", 0) > financials.get("net_income", 0): score += 1
    # 5. Debt decreasing
    if financials.get("leverage_current", 1) < financials.get("leverage_prev", 1): score += 1
    # 6. Current ratio increasing
    if financials.get("current_ratio", 0) > financials.get("current_ratio_prev", 0): score += 1
    # 7. No dilution (shares not increasing)
    if financials.get("shares_current", 1) <= financials.get("shares_prev", 1): score += 1
    # 8. Gross margin increasing
    if financials.get("gross_margin", 0) > financials.get("gross_margin_prev", 0): score += 1
    # 9. Asset turnover increasing
    if financials.get("asset_turnover", 0) > financials.get("asset_turnover_prev", 0): score += 1
    return score
