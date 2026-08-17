"""
ALPHA BIST — Gross Settlement Monitor

Brüt takas kontrolü:
- Brüt takaslı hisselerde açığa satış yasak
- T+0 ödeme (nakit aynı gün)
- SPK tarafından belirlenir
"""

from typing import Dict, Any, List, Set
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class GrossSettlementStatus:
    is_gross: bool
    effect: str = ""        # "NO_SHORT_SELL", "T_PLUS_0", "NONE"
    impact: str = ""        # Etki açıklaması
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_gross": self.is_gross,
            "effect": self.effect,
            "impact": self.impact,
        }


class GrossSettlementMonitor:
    """Brüt takas kontrolü."""

    def __init__(self):
        self._gross_tickers: Set[str] = set()

    def set_gross_tickers(self, tickers: List[str]):
        """Brüt takaslı hisseleri güncelle."""
        self._gross_tickers = set(tickers)
        logger.info("Gross settlement tickers updated", count=len(tickers))

    def add_gross_ticker(self, ticker: str):
        """Brüt takaslı hisse ekle."""
        self._gross_tickers.add(ticker)

    def remove_gross_ticker(self, ticker: str):
        """Brüt takaslı hisse kaldır."""
        self._gross_tickers.discard(ticker)

    def check_gross_settlement(self, ticker: str) -> GrossSettlementStatus:
        """Brüt takas kontrolü."""
        if ticker in self._gross_tickers:
            return GrossSettlementStatus(
                is_gross=True,
                effect="NO_SHORT_SELL",
                impact=f"{ticker} brüt takasta — açığa satış yasak, T+0 ödeme",
                details={"ticker": ticker},
            )

        return GrossSettlementStatus(
            is_gross=False,
            effect="NONE",
            impact="Normal takas (T+2)",
        )

    def get_all_gross(self) -> List[str]:
        """Tüm brüt takaslı hisseleri getir."""
        return list(self._gross_tickers)


# Singleton
gross_settlement_monitor = GrossSettlementMonitor()
