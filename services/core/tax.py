"""ALPHA BIST — Tax Calculator (Güncel Vergi Oranları)

BIST vergi oranları (2025-2026):
- Hisse senedi: Gelir vergisi dilimine göre %15-%40
- Temettü: %15 stopaj
- Devlet tahvili/faiz: %10 stopaj
- Yatırım fonu katılma payları: %0 (muafiyet olabilir)

Kaynak: GVK, SPK mevzuatı
"""
from dataclasses import dataclass
from typing import Optional
import structlog
logger = structlog.get_logger()

# BIST vergi oranları (2025-2026)
# Hisse senedi kâr vergisi: Gelir vergisi dilimine göre değişir
INCOME_TAX_BRACKETS = [
    (110_000, 0.15),   # 110.000 TL'ye kadar %15
    (230_000, 0.20),   # 110.001-230.000 arası %20
    (580_000, 0.27),   # 230.001-580.000 arası %27
    (3_000_000, 0.35), # 580.001-3.000.000 arası %35
    (float('inf'), 0.40),  # 3.000.001 üzeri %40
]

# Stopaj oranları
TAX_RATES = {
    "stock": {
        "short_term": None,  # Gelir vergisi dilimine göre (aşağıda hesaplanır)
        "long_term": None,   # Gelir vergisi dilimine göre (aşağıda hesaplanır)
    },
    "dividend": 0.15,       # Temettü stopajı (%15)
    "bond": 0.10,           # Tahvil/faiz stopajı (%10)
    "fund": 0.00,           # Yatırım fonu katılma payları (muaf)
    "repo": 0.10,           # Repo stopajı (%10)
}

# Uzun vadeli holding eşiği (6 ay = 180 gün)
HOLDING_PERIOD_THRESHOLD = 180  # gün

# Yıllık gelir vergisi matrahı (basitleştirilmiş — gerçek vergi dilimi için)
ANUAL_TAX_FREE_ALLOWANCE = 110_000  # TL (2025-2026)


def _get_income_tax_rate(annual_income: float) -> float:
    """Yıllık gelir vergisi dilimine göre oran döndür."""
    for threshold, rate in INCOME_TAX_BRACKETS:
        if annual_income <= threshold:
            return rate
    return 0.40  # En üst dilim


@dataclass
class TaxResult:
    profit: float
    tax_rate: float
    tax: float
    holding_days: int
    is_long_term: bool
    tax_bracket: Optional[str] = None  # Hangi dilimde


def calculate_tax(
    buy_price: float,
    sell_price: float,
    quantity: int,
    holding_days: int,
    asset_type: str = "stock",
    annual_income: float = 0,  # Yıllık toplam gelir (vergi dilimi için)
) -> TaxResult:
    """Vergi hesapla.

    Args:
        buy_price: Alış fiyatı
        sell_price: Satış fiyatı
        quantity: Adet
        holding_days: Tutma süresi (gün)
        asset_type: Varlık tipi (stock, dividend, bond, fund, repo)
        annual_income: Yıllık toplam gelir (vergi dilimi hesaplaması için)
    """
    profit = (sell_price - buy_price) * quantity
    is_long_term = holding_days >= HOLDING_PERIOD_THRESHOLD

    if asset_type == "stock":
        # Hisse senedi: Gelir vergisi dilimine göre
        # Uzun vadeli (6+ ay) holding avantajı: sadece %50'si vergilendirilir
        if is_long_term:
            taxable_income = annual_income + (profit * 0.50)  # %50 istisna
        else:
            taxable_income = annual_income + profit

        rate = _get_income_tax_rate(taxable_income)
        tax_bracket = f"{rate*100:.0f}% dilim"
    else:
        # Stopaj oranları
        rate = TAX_RATES.get(asset_type, 0.15)
        tax_bracket = f"Stopaj {rate*100:.0f}%"

    tax = max(0, profit * rate)

    return TaxResult(
        profit=profit,
        tax_rate=rate,
        tax=tax,
        holding_days=holding_days,
        is_long_term=is_long_term,
        tax_bracket=tax_bracket,
    )
