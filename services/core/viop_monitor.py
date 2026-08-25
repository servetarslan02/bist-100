"""
ALPHA BIST — VIOP Monitor

Vadeli İşlem ve Opsiyon Piyasası takibi:
- SPAN teminat hesaplama
- Teminat yeterliliği kontrolü
- Margin call tespiti
"""

from typing import Dict, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class MarginStatus:
    margin_call: bool
    required: float = 0.0
    available: float = 0.0
    surplus: float = 0.0
    action: str = ""       # "OK", "MARGIN_CALL", "LIQUIDATE"
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "margin_call": self.margin_call,
            "required": round(self.required, 2),
            "available": round(self.available, 2),
            "surplus": round(self.surplus, 2),
            "action": self.action,
        }


class VIOPMonitor:
    """VIOP teminat takibi."""

    # SPAN teminat oranları (yaklaşık)
    DEFAULT_MARGIN_RATE = 0.15    # %15 başlangıç teminatı
    MAINTENANCE_MARGIN = 0.12     # %12 sürdürme teminatı
    MARGIN_CALL_THRESHOLD = 0.13  # %13 margin call eşiği

    def __init__(self):
        self._custom_margin_rates: Dict[str, float] = {}

    def set_margin_rate(self, ticker: str, rate: float):
        """Özel teminat oranı ata."""
        self._custom_margin_rates[ticker] = rate

    def check_viop_margin(
        self,
        position_value: float,
        available_margin: float,
        ticker: str = "",
    ) -> MarginStatus:
        """Teminat yeterliliği kontrolü.

        Args:
            position_value: Pozisyon değeri
            available_margin: Kullanılabilir teminat
            ticker: Hisse kodu (opsiyonel)
        """
        if position_value <= 0:
            return MarginStatus(margin_call=False, action="OK")

        # Teminat oranı
        margin_rate = self._custom_margin_rates.get(ticker, self.DEFAULT_MARGIN_RATE)

        # Gerekli teminat
        required = position_value * margin_rate

        # Fazla/eksik
        surplus = available_margin - required

        # Margin call?
        margin_call = False
        action = "OK"

        if surplus < 0:
            margin_call = True
            action = "MARGIN_CALL"
        elif available_margin < position_value * self.MARGIN_CALL_THRESHOLD:
            margin_call = True
            action = "MARGIN_CALL"

        return MarginStatus(
            margin_call=margin_call,
            required=required,
            available=available_margin,
            surplus=surplus,
            action=action,
            details={"ticker": ticker, "position_value": position_value},
        )


# Singleton
viop_monitor = VIOPMonitor()
