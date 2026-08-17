"""ALPHA BIST — Beneish M-Score."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def calculate_m_score(financials: Dict[str, Any]) -> float:
    """Beneish M-Score (eşik: -1.78)."""
    dsri = financials.get("dsri", 1)  # Days Sales in Receivables Index
    gmi = financials.get("gmi", 1)    # Gross Margin Index
    aqi = financials.get("aqi", 1)    # Asset Quality Index
    sgi = financials.get("sgi", 1)    # Sales Growth Index
    depi = financials.get("depi", 1)  # Depreciation Index
    sgai = financials.get("sgai", 1)  # SGA Expense Index
    lvgi = financials.get("lvgi", 1)  # Leverage Index
    tata = financials.get("tata", 0)  # Total Accruals to Total Assets
    m_score = (-4.84 + 0.92*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi +
               0.115*depi - 0.172*sgai + 4.679*tata - 0.327*lvgi)
    return m_score
