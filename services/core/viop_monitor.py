"""
ALPHA BIST — VIOP Monitor

Vadeli İşlem ve Opsiyon Piyasası takibi:
- SPAN teminat hesaplama
- Teminat yeterliliği kontrolü
- Margin call tespiti
"""

import functools
from dataclasses import dataclass
from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.viop_monitor")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


@dataclass
class MarginStatus:
    """Otomatik eklendi."""
    margin_call: bool
    required: float = 0.0
    available: float = 0.0
    surplus: float = 0.0
    action: str = ""  # "OK", "MARGIN_CALL", "LIQUIDATE"
    details: dict[str, Any] = None

    def __post_init__(self):
        """Otomatik eklendi."""
        if self.details is None:
            self.details = {}

    def to_dict(self) -> dict[str, Any]:
        """Otomatik eklendi."""
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
    DEFAULT_MARGIN_RATE = 0.15  # %15 başlangıç teminatı
    MAINTENANCE_MARGIN = 0.12  # %12 sürdürme teminatı
    MARGIN_CALL_THRESHOLD = 0.13  # %13 margin call eşiği

    def __init__(self):
        """Otomatik eklendi."""
        self._custom_margin_rates: dict[str, float] = {}

    def set_margin_rate(self, ticker: str, rate: float) -> Any:
        """Özel teminat oranı ata."""
        self._custom_margin_rates[ticker] = rate

    @otel_trace("viop_monitor.check_viop_margin")
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

        if surplus < 0 or available_margin < position_value * self.MARGIN_CALL_THRESHOLD:
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
