"""
ALPHA BIST — Price Limits

BIST fiyat limitleri (pazara göre):
- Yıldız Pazar: ±%20
- Ana Pazar: ±%15
- Alt Pazar: ±%10
- Devre kesici: sadece aşağı yönlü tetiklenir
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class PriceLimitResult:
    limit_hit: bool
    direction: str = ""       # "UP" veya "DOWN"
    change_pct: float = 0.0
    limit: float = 10.0       # Yüzde limit
    reference_price: float = 0.0
    current_price: float = 0.0
    upper_limit: float = 0.0
    lower_limit: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "limit_hit": self.limit_hit,
            "direction": self.direction,
            "change_pct": round(self.change_pct, 2),
            "limit": self.limit,
            "reference_price": self.reference_price,
            "current_price": self.current_price,
            "upper_limit": round(self.upper_limit, 2),
            "lower_limit": round(self.lower_limit, 2),
        }


class PriceLimitMonitor:
    """BIST fiyat limitleri kontrolü."""

    # Varsayılan limitler (BIST standardı: ±%10)
    DEFAULT_LIMIT = 10.0    # %10 (Standart BIST Fiyat Marjı)
    YILDIZ_LIMIT = 10.0     # %10 (Yıldız Pazar)
    ANA_LIMIT = 10.0        # %10 (Ana Pazar)
    ALT_LIMIT = 10.0        # %10 (Alt Pazar)
    VOLATILE_LIMIT = 5.0    # %5 (devre kesici sonrası)
    WIDE_LIMIT = 20.0       # %20

    def __init__(self):
        self._custom_limits: Dict[str, float] = {}

    def set_custom_limit(self, ticker: str, limit_pct: float):
        """Özel limit ata (volatil hisseler)."""
        self._custom_limits[ticker] = limit_pct

    def check_price_limit(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
    ) -> PriceLimitResult:
        """Fiyat limiti kontrolü.

        Args:
            ticker: Hisse kodu
            current_price: Güncel fiyat
            reference_price: Referans fiyat (önceki kapanış)
        """
        if reference_price <= 0 or current_price <= 0:
            return PriceLimitResult(limit_hit=False)

        # Limit belirle
        limit = self._custom_limits.get(ticker, self.DEFAULT_LIMIT)

        # Değişim hesapla
        change_pct = ((current_price / reference_price) - 1) * 100

        # Limitler
        upper_limit = reference_price * (1 + limit / 100)
        lower_limit = reference_price * (1 - limit / 100)

        # Limit aşıldı mı?
        limit_hit = False
        direction = ""

        # Floating point toleransı ile kontrol
        tol = reference_price * 0.0001  # %0.01 tolerans
        if current_price >= upper_limit - tol:
            limit_hit = True
            direction = "UP"
        elif current_price <= lower_limit + tol:
            limit_hit = True
            direction = "DOWN"

        return PriceLimitResult(
            limit_hit=limit_hit,
            direction=direction,
            change_pct=change_pct,
            limit=limit,
            reference_price=reference_price,
            current_price=current_price,
            upper_limit=upper_limit,
            lower_limit=lower_limit,
        )


# Singleton
price_limit_monitor = PriceLimitMonitor()
