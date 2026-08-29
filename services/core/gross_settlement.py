"""
ALPHA BIST — Gross Settlement Monitor

Brüt takas kontrolü:
- Brüt takaslı hisselerde açığa satış yasak
- T+0 ödeme (nakit aynı gün)
- SPK tarafından belirlenir
"""

import functools
from dataclasses import dataclass
from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.gross_settlement")


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
class GrossSettlementStatus:
    """Otomatik eklendi."""
    is_gross: bool
    effect: str = ""  # "NO_SHORT_SELL", "T_PLUS_0", "NONE"
    impact: str = ""  # Etki açıklaması
    details: dict[str, Any] = None

    def __post_init__(self):
        """Otomatik eklendi."""
        if self.details is None:
            self.details = {}

    def to_dict(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return {
            "is_gross": self.is_gross,
            "effect": self.effect,
            "impact": self.impact,
        }


class GrossSettlementMonitor:
    """Brüt takas kontrolü.

    Brüt takaslı hisselerde:
    - Açığa satış yasak
    - Kredili işlem yasak
    - T+0 ödeme (nakit aynı gün)
    - Gün içi al-sat kısıtlaması (SPK belirler)
    - SPK tarafından belirlenir
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._gross_tickers: set[str] = set()
        self._gross_tickers_with_details: dict[str, dict[str, Any]] = {}  # Detaylı bilgi

    def set_gross_tickers(self, tickers: list[str]) -> Any:
        """Brüt takaslı hisseleri güncelle."""
        self._gross_tickers = set(tickers)
        logger.info("Gross settlement tickers updated", count=len(tickers))

    def set_gross_ticker_detail(self, ticker: str, details: dict[str, Any]) -> Any:
        """Brüt takaslı hisse detay bilgisi ekle.

        Args:
            details: {"reason": str, "start_date": str, "end_date": str, "day_trade_restricted": bool}
        """
        self._gross_tickers.add(ticker)
        self._gross_tickers_with_details[ticker] = details

    def add_gross_ticker(self, ticker: str) -> Any:
        """Brüt takaslı hisse ekle."""
        self._gross_tickers.add(ticker)

    def remove_gross_ticker(self, ticker: str) -> Any:
        """Brüt takaslı hisse kaldır."""
        self._gross_tickers.discard(ticker)
        self._gross_tickers_with_details.pop(ticker, None)

    @otel_trace("gross_settlement.check_gross_settlement")
    def check_gross_settlement(self, ticker: str) -> GrossSettlementStatus:
        """Brüt takas kontrolü."""
        if ticker in self._gross_tickers:
            details = self._gross_tickers_with_details.get(ticker, {})
            day_trade_msg = "" if not details.get("day_trade_restricted") else ", gün içi al-sat kısıtlı"
            return GrossSettlementStatus(
                is_gross=True,
                effect="NO_SHORT_SELL_NO_MARGIN",
                impact=f"{ticker} brüt takasta — açığa satış yasak, kredili işlem yasak, T+0 ödeme{day_trade_msg}",
                details={"ticker": ticker, **details},
            )

        return GrossSettlementStatus(
            is_gross=False,
            effect="NONE",
            impact="Normal takas (T+2)",
        )

    def is_short_sell_blocked(self, ticker: str) -> bool:
        """Bu hisse brüt takas nedeniyle açığa satış yapamaz mı?"""
        return ticker in self._gross_tickers

    def is_margin_blocked(self, ticker: str) -> bool:
        """Bu hisse brüt takas nedeniyle kredili işlem yapamaz mı?"""
        return ticker in self._gross_tickers

    def is_day_trade_restricted(self, ticker: str) -> bool:
        """Bu hisse brüt takas nedeniyle gün içi al-sat kısıtlı mı?"""
        details = self._gross_tickers_with_details.get(ticker, {})
        return details.get("day_trade_restricted", False)

    def get_all_gross(self) -> list[str]:
        """Tüm brüt takaslı hisseleri getir."""
        return list(self._gross_tickers)


# Singleton
gross_settlement_monitor = GrossSettlementMonitor()
