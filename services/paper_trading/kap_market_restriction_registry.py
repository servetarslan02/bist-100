"""
ALPHA BIST — Timestamped KAP Market Restriction & VBTS Registry

Bu modül, kamuya açık yayımlanmış VBTS (Volatilite Bazlı Tedbir Sistemi) kararlarını,
brüt takas, kredili işlem yasağı ve işlem sırası durdurma bildirimlerini zaman damgalı olarak tutar.

Kritik İlke:
- published_at (Yayın Zamanı) ile effective_date (Yürürlük Tarihi) birbirinden ayrıdır.
- Seans kapandıktan sonra (18:15+) yayımlanan tedbir, ertesi seans (T+1) başından itibaren yürürlüğe girer.
- Eksik veya gecikmiş veri durumunda fail-safe olarak NO_TRADE kuralı işletilir.
"""

from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class MarketRestrictionRecord:
    """Zaman damgalı KAP piyasa kısıtı ve tedbir kaydı."""
    ticker: str
    restriction_type: str        # "VBTS_GROSS_SETTLEMENT" | "VBTS_SHORT_BAN" | "HALT" | "CIRCUIT_BREAKER"
    published_at: str            # ISO Timestamp (KAP yayin zamani)
    effective_date: str          # Yürürlüğe girdiği ilk seans tarihi (YYYY-MM-DD)
    end_date: Optional[str] = None # Tedbirin bittiği tarih (YYYY-MM-DD)
    details: str = ""


class KAPMarketRestrictionRegistry:
    """Zaman damgalı KAP piyasa tedbir ve kısıt sicil yöneticisi."""

    def __init__(self):
        self._restrictions: Dict[str, List[MarketRestrictionRecord]] = {}
        self._halted_tickers: Set[str] = set()
        self._gross_settlement_tickers: Set[str] = set()
        self._short_ban_tickers: Set[str] = set()

    def register_restriction(
        self,
        ticker: str,
        restriction_type: str,
        published_at: str,
        effective_date: str,
        end_date: Optional[str] = None,
        details: str = "",
    ):
        """Yeni bir piyasa tedbiri / kısıtı kaydeder."""
        record = MarketRestrictionRecord(
            ticker=ticker,
            restriction_type=restriction_type,
            published_at=published_at,
            effective_date=effective_date,
            end_date=end_date,
            details=details,
        )
        if ticker not in self._restrictions:
            self._restrictions[ticker] = []
        self._restrictions[ticker].append(record)

        if restriction_type == "HALT":
            self._halted_tickers.add(ticker)
        elif restriction_type == "VBTS_GROSS_SETTLEMENT":
            self._gross_settlement_tickers.add(ticker)
        elif restriction_type == "VBTS_SHORT_BAN":
            self._short_ban_tickers.add(ticker)

        logger.info("KAP Market Restriction Registered",
                    ticker=ticker, type=restriction_type,
                    published=published_at, effective=effective_date)

    def is_halted(self, ticker: str, current_date: str) -> bool:
        """Hisse belirtilen işlem gününde durdurulmuş mu?"""
        for rec in self._restrictions.get(ticker, []):
            if rec.restriction_type == "HALT" and rec.effective_date <= current_date:
                if rec.end_date is None or rec.end_date >= current_date:
                    return True
        return False

    def is_gross_settlement(self, ticker: str, current_date: str) -> bool:
        """Hisse belirtilen tarihte Brüt Takas kapsamında mı?"""
        for rec in self._restrictions.get(ticker, []):
            if rec.restriction_type == "VBTS_GROSS_SETTLEMENT" and rec.effective_date <= current_date:
                if rec.end_date is None or rec.end_date >= current_date:
                    return True
        return False

    def is_short_sale_banned(self, ticker: str, current_date: str) -> bool:
        """Açığa satış yasağı var mı?"""
        for rec in self._restrictions.get(ticker, []):
            if rec.restriction_type == "VBTS_SHORT_BAN" and rec.effective_date <= current_date:
                if rec.end_date is None or rec.end_date >= current_date:
                    return True
        return False

    def validate_trading_eligibility(
        self,
        ticker: str,
        current_date: str,
        side: str,
        data_quality_ok: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """
        İşlem öncesi piyasa kısıtı ve veri güvenilirlik denetimi.
        Eksik/gecikmiş veride doğrudan NO_TRADE döner.
        """
        if not data_quality_ok:
            return False, f"NO_TRADE: DATA_QUALITY_UNVERIFIED - {ticker} için güncel seans verisi teyit edilemedi"

        if self.is_halted(ticker, current_date):
            return False, f"NO_TRADE: MARKET_HALTED - {ticker} işlem sırası durdurulmuş"

        if side in {"SHORT", "SELL_SHORT"} and self.is_short_sale_banned(ticker, current_date):
            return False, f"NO_TRADE: VBTS_SHORT_BAN - {ticker} için açığa satış yasak"

        return True, None


# Singleton instance
kap_restriction_registry = KAPMarketRestrictionRegistry()
