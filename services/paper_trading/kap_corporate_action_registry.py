from typing import Any

"""
ALPHA BIST — Timestamped KAP Corporate Action & VBTS Registry

Bu modül, kamuya açık yayımlanmış VBTS (Volatilite Bazlı Tedbir Sistemi) kararlarını,
brüt takas, kredili işlem yasağı ve işlem sırası durdurma bildirimlerini zaman damgalı olarak tutar.
Eğer hissenin kurumsal/seans durumu doğrulanamıyorsa fail-safe olarak NO_TRADE kuralını işletir.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

logger = structlog.get_logger()


@dataclass
class CorporateActionRecord:
    """Zaman damgalı KAP bildirim/tedbir kaydı."""

    ticker: str
    action_type: str  # "VBTS_GROSS_SETTLEMENT" | "VBTS_SHORT_BAN" | "HALT" | "DIVIDEND" | "SPLIT"
    effective_date: str  # YYYY-MM-DD
    end_date: str | None = None
    details: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class KAPCorporateActionRegistry:
    """Zaman damgalı KAP tedbir ve kısıt sicil yöneticisi."""

    def __init__(self):
        """Otomatik eklendi."""
        self._actions: dict[str, list[CorporateActionRecord]] = {}
        self._halted_tickers: set[str] = set()
        self._gross_settlement_tickers: set[str] = set()
        self._short_ban_tickers: set[str] = set()

    def register_action(
        self,
        ticker: str,
        action_type: str,
        effective_date: str,
        end_date: str | None = None,
        details: str = "",
    ) -> Any:
        """Yeni bir kurumsal tedbir / olay kaydeder."""
        record = CorporateActionRecord(
            ticker=ticker,
            action_type=action_type,
            effective_date=effective_date,
            end_date=end_date,
            details=details,
        )
        if ticker not in self._actions:
            self._actions[ticker] = []
        self._actions[ticker].append(record)

        if action_type == "HALT":
            self._halted_tickers.add(ticker)
        elif action_type == "VBTS_GROSS_SETTLEMENT":
            self._gross_settlement_tickers.add(ticker)
        elif action_type == "VBTS_SHORT_BAN":
            self._short_ban_tickers.add(ticker)

        logger.info("KAP Corporate Action Registered", ticker=ticker, action=action_type, effective=effective_date)

    def is_halted(self, ticker: str, date: str) -> bool:
        """Hisse belirtilen tarihte durdurulmuş mu?"""
        if ticker in self._halted_tickers:
            return True
        for rec in self._actions.get(ticker, []):
            if rec.action_type == "HALT" and rec.effective_date <= date:
                if rec.end_date is None or rec.end_date >= date:
                    return True
        return False

    def is_gross_settlement(self, ticker: str, date: str) -> bool:
        """Hisse belirtilen tarihte Brüt Takas kapsamında mı?"""
        if ticker in self._gross_settlement_tickers:
            return True
        for rec in self._actions.get(ticker, []):
            if rec.action_type == "VBTS_GROSS_SETTLEMENT" and rec.effective_date <= date:
                if rec.end_date is None or rec.end_date >= date:
                    return True
        return False

    def is_short_sale_banned(self, ticker: str, date: str) -> bool:
        """Açığa satış yasağı var mı?"""
        if ticker in self._short_ban_tickers:
            return True
        for rec in self._actions.get(ticker, []):
            if rec.action_type == "VBTS_SHORT_BAN" and rec.effective_date <= date:
                if rec.end_date is None or rec.end_date >= date:
                    return True
        return False

    def validate_trading_eligibility(self, ticker: str, date: str, side: str) -> tuple[bool, str | None]:
        """
        İşlem öncesi kurumsal uygunluk denetimi:
        Durdurulmuş sıra veya belirsiz durumda NO_TRADE döner.
        """
        if self.is_halted(ticker, date):
            return False, f"NO_TRADE: KAP_HALT_ACTIVE - {ticker} işlem sırası durdurulmuş"

        if side in {"SHORT", "SELL_SHORT"} and self.is_short_sale_banned(ticker, date):
            return False, f"NO_TRADE: VBTS_SHORT_BAN - {ticker} için açığa satış yasak"

        return True, None


# Singleton instance
kap_registry = KAPCorporateActionRegistry()
