"""ALPHA BIST — Tax Calculator."""
from dataclasses import dataclass
import structlog
logger = structlog.get_logger()

# BIST vergi oranları
TAX_RATES = {
    "stock": {"short_term": 0.15, "long_term": 0.10},  # Kısa/uzun vadeli
    "dividend": 0.15,  # Temettü stopajı (%15, 2025 itibariyle)
    "bond": 0.10,      # Tahvil
}

HOLDING_PERIOD_THRESHOLD = 180  # gün (6 ay)

@dataclass
class TaxResult:
    profit: float
    tax_rate: float
    tax: float
    holding_days: int
    is_long_term: bool

def calculate_tax(buy_price: float, sell_price: float, quantity: int, holding_days: int, asset_type: str = "stock") -> TaxResult:
    """Vergi hesapla."""
    profit = (sell_price - buy_price) * quantity
    is_long_term = holding_days >= HOLDING_PERIOD_THRESHOLD
    if asset_type == "stock":
        rate = TAX_RATES["stock"]["long_term"] if is_long_term else TAX_RATES["stock"]["short_term"]
    else:
        rate = TAX_RATES.get(asset_type, 0.15)
    tax = max(0, profit * rate)
    return TaxResult(profit=profit, tax_rate=rate, tax=tax, holding_days=holding_days, is_long_term=is_long_term)
