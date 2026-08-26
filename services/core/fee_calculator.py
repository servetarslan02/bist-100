"""
ALPHA BIST — Fee Calculator

BIST işlem maliyetleri:
- Broker komisyonu (değişken)
- BIST payı (%0.0056)
- MKK payı (%0.00109)
- BSMV (%5, sadece komisyon üzerinden)
- Minimum komisyon ₺1
"""

from typing import Dict, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class FeeBreakdown:
    """İşlem maliyet detayı."""
    amount: float           # İşlem tutarı
    broker_fee: float       # Broker komisyonu
    bist_fee: float         # BIST payı
    mkk_fee: float          # MKK payı
    bsmv: float             # Banka ve Sigorta Muameleleri Vergisi
    total: float            # Toplam maliyet
    effective_rate: float   # Efektif oran (%)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount": round(self.amount, 2),
            "broker_fee": round(self.broker_fee, 2),
            "bist_fee": round(self.bist_fee, 2),
            "mkk_fee": round(self.mkk_fee, 2),
            "bsmv": round(self.bsmv, 2),
            "total": round(self.total, 2),
            "effective_rate": round(self.effective_rate, 4),
        }


class FeeCalculator:
    """BIST işlem maliyetleri hesaplayıcı."""

    # Standart oranlar
    BIST_FEE_RATE = 0.000056    # %0.0056
    MKK_FEE_RATE = 0.0000109    # %0.00109
    BSMV_RATE = 0.05            # %5 (komisyon üzerinden)
    MIN_COMMISSION = 1.0        # Minimum ₺1

    def __init__(self, broker_rate: float = 0.0003):
        """Args:
            broker_rate: Broker komisyon oranı (default: %0.03)
        """
        self.broker_rate = broker_rate

    def calculate(self, amount: float) -> FeeBreakdown:
        """İşlem maliyeti hesapla.

        Args:
            amount: İşlem tutarı (fiyat × adet)
        """
        if amount <= 0:
            return FeeBreakdown(0, 0, 0, 0, 0, 0, 0)

        # Broker komisyonu (minimum ₺1)
        broker_fee = max(amount * self.broker_rate, self.MIN_COMMISSION)

        # BIST payı
        bist_fee = amount * self.BIST_FEE_RATE

        # MKK payı
        mkk_fee = amount * self.MKK_FEE_RATE

        # BSMV (sadece broker komisyonu üzerinden — BIST ve MKK payları üzerinden alınmaz)
        bsmv = broker_fee * self.BSMV_RATE

        # Toplam
        total = broker_fee + bist_fee + mkk_fee + bsmv
        effective_rate = (total / amount) * 100 if amount > 0 else 0

        return FeeBreakdown(
            amount=amount,
            broker_fee=broker_fee,
            bist_fee=bist_fee,
            mkk_fee=mkk_fee,
            bsmv=bsmv,
            total=total,
            effective_rate=effective_rate,
        )


# Singleton
fee_calculator = FeeCalculator()
