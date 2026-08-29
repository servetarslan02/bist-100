from typing import Any
"""
ALPHA BIST — Settlement Rules (T+2)

BIST takas kuralları:
- Normal işlemler: T+2 (işlem gününden 2 iş günü sonra)
- Brüt takas: T+0 (aynı gün)
- Takas günleri: sadece işlem günleri sayılır

Kaynak: Borsa İstanbul Takas Esasları
"""

import functools
from dataclasses import dataclass
from datetime import date, timedelta

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.settlement")


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
class SettlementInfo:
    """Takas bilgisi."""

    trade_date: date
    settlement_date: date
    settlement_days: int  # T+N
    is_gross: bool = False


class SettlementCalculator:
    """BIST takas günü hesaplayıcı."""

    # Normal takas: T+2
    NORMAL_SETTLEMENT_DAYS = 2
    # Brüt takas: T+0
    GROSS_SETTLEMENT_DAYS = 0

    def __init__(self, holidays: set | None = None):
        """Otomatik eklendi."""
        self._holidays = holidays or set()

    def set_holidays(self, holidays: set) -> Any:
        """Otomatik eklendi."""
        self._holidays = holidays

    def is_trading_day(self, d: date) -> bool:
        """Bu gün işlem günü mü?"""
        if d.weekday() >= 5:
            return False
        return d.strftime("%Y-%m-%d") not in self._holidays

    def add_trading_days(self, start_date: date, days: int) -> date:
        """İşlem günü ekleyerek takas gününü hesapla."""
        current = start_date
        added = 0
        while added < days:
            current += timedelta(days=1)
            if self.is_trading_day(current):
                added += 1
        return current

    @otel_trace("settlement.get_settlement_date")
    def get_settlement_date(
        self,
        trade_date: date,
        is_gross: bool = False,
    ) -> date:
        """Takas gününü hesapla.

        Args:
            trade_date: İşlem tarihi
            is_gross: Brüt takas mı?
        """
        if is_gross:
            return trade_date  # T+0
        return self.add_trading_days(trade_date, self.NORMAL_SETTLEMENT_DAYS)  # T+2

    @otel_trace("settlement.get_settlement_info")
    def get_settlement_info(
        self,
        trade_date: date,
        is_gross: bool = False,
    ) -> SettlementInfo:
        """Takas bilgisi döndür."""
        settlement_date = self.get_settlement_date(trade_date, is_gross)
        return SettlementInfo(
            trade_date=trade_date,
            settlement_date=settlement_date,
            settlement_days=0 if is_gross else self.NORMAL_SETTLEMENT_DAYS,
            is_gross=is_gross,
        )

    @otel_trace("settlement.is_settled")
    def is_settled(self, trade_date: date, current_date: date, is_gross: bool = False) -> bool:
        """İşlem takas olmuş mu?"""
        settlement_date = self.get_settlement_date(trade_date, is_gross)
        return current_date >= settlement_date


# Singleton
settlement_calculator = SettlementCalculator()
