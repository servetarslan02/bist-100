"""
ALPHA BIST — Short Selling Monitor

BIST açığa satış kuralları:
- Sadece BIST-50 hisseleri açığa satılabilir
- Uptick rule: son işlem fiyatından yüksek fiyatla açığa satış
- Brüt takaslı hisselerde açığa satış yasak
- SPK geçici yasak kontrolü
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class ShortSellingDecision:
    allowed: bool
    reason: str = ""
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class ShortSellingMonitor:
    """BIST açığa satış kuralları kontrolü."""

    def __init__(self):
        self._bist30_cache: Optional[List[str]] = None
        self._gross_settlement_tickers: set = set()
        self._spk_banned_tickers: set = set()

    def _get_bist30(self) -> List[str]:
        """BIST-50 hisselerini getir."""
        if self._bist30_cache is None:
            try:
                from services.ingestion.bist_universe import bist_universe
                self._bist30_cache = bist_universe.BIST_50_TICKERS if hasattr(bist_universe, 'BIST_50_TICKERS') else bist_universe.BIST_30_TICKERS
            except ImportError:
                self._bist30_cache = []
        return self._bist30_cache

    def set_gross_settlement(self, tickers: List[str]):
        """Brüt takaslı hisseleri güncelle."""
        self._gross_settlement_tickers = set(tickers)

    def set_spk_banned(self, tickers: List[str]):
        """SPK geçici yasaklı hisseleri güncelle."""
        self._spk_banned_tickers = set(tickers)

    def can_short_sell(
        self,
        ticker: str,
        current_price: float = 0,
        last_trade_price: float = 0,
    ) -> ShortSellingDecision:
        """Açığa satış yapılabilir mi kontrol et.

        Args:
            ticker: Hisse kodu
            current_price: Güncel fiyat
            last_trade_price: Son işlem fiyatı (uptick rule için)
        """
        details = {"ticker": ticker}

        # 1. BIST-50 kontrolü (BIST-30 değil)
        bist50 = self._get_bist30()
        if ticker not in bist50:
            return ShortSellingDecision(
                allowed=False,
                reason=f"{ticker} BIST-30 / BIST-50 listesinde değil — açığa satış sadece BIST-30/50",
                details=details,
            )

        # 2. Brüt takas kontrolü
        if ticker in self._gross_settlement_tickers:
            return ShortSellingDecision(
                allowed=False,
                reason=f"{ticker} brüt takasta — açığa satış yasak",
                details=details,
            )

        # 3. SPK geçici yasak kontrolü
        if ticker in self._spk_banned_tickers:
            return ShortSellingDecision(
                allowed=False,
                reason=f"{ticker} SPK geçici yasak listesinde",
                details=details,
            )

        # 4. Uptick rule (fiyat kontrolü)
        if current_price > 0 and last_trade_price > 0:
            if current_price < last_trade_price:
                return ShortSellingDecision(
                    allowed=False,
                    reason=f"Uptick rule: güncel ({current_price}) < son işlem ({last_trade_price})",
                    details={**details, "current_price": current_price, "last_trade_price": last_trade_price},
                )

        return ShortSellingDecision(
            allowed=True,
            reason="Açığa satış uygun",
            details=details,
        )


# Singleton
short_selling_monitor = ShortSellingMonitor()
