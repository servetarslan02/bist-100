"""
ALPHA BIST — Market Session State Machine

Borsa İstanbul Pay Piyasası Seans Çizelgesi ve Durum Makinesi (Official BIST Rules):
- 09:40 — 09:55 : Açılış Açık Artırması — Emir Toplama (OPENING_AUCTION_COLLECTION)
- 09:55 — 10:00 : Açılış Açık Artırması — Fiyat Belirleme / Eşleşme (OPENING_AUCTION_DETERMINATION)
- 10:00 — 18:00 : Sürekli Müzayede (CONTINUOUS_AUCTION)
- [Dinamik]     : Devre Kesici Çağrı Seansı (CIRCUIT_BREAKER_AUCTION — 5 dk emir toplama + 2 dk eşleşme)
- 18:01 — 18:05 : Kapanış Açık Artırması — Emir Toplama (CLOSING_AUCTION_COLLECTION)
- 18:05 — 18:07 : Kapanış Fiyatı Belirleme / Eşleşme (CLOSING_AUCTION_DETERMINATION)
- 18:08 — 18:10 : Kapanış Fiyatından İşlemler (CLOSING_PRICE_TRADING / Trade at Close)
- 18:10 — 09:40 : Piyasa Kapalı (CLOSED)
"""

from datetime import datetime, time, timezone, timedelta
from enum import Enum
from typing import Optional, Dict
import structlog

logger = structlog.get_logger()

_TZ_ISTANBUL = timezone(timedelta(hours=3))


class BISTMarketPhase(Enum):
    CLOSED = "CLOSED"
    OPENING_AUCTION_COLLECTION = "OPENING_AUCTION_COLLECTION"       # 09:40 - 09:55
    OPENING_AUCTION_DETERMINATION = "OPENING_AUCTION_DETERMINATION" # 09:55 - 10:00
    CONTINUOUS_AUCTION = "CONTINUOUS_AUCTION"                       # 10:00 - 18:00
    CIRCUIT_BREAKER_AUCTION = "CIRCUIT_BREAKER_AUCTION"             # Tetiklendiğinde
    CLOSING_AUCTION_COLLECTION = "CLOSING_AUCTION_COLLECTION"       # 18:01 - 18:05
    CLOSING_AUCTION_DETERMINATION = "CLOSING_AUCTION_DETERMINATION" # 18:05 - 18:07
    CLOSING_PRICE_TRADING = "CLOSING_PRICE_TRADING"                 # 18:08 - 18:10


class MarketSessionStateMachine:
    """Borsa İstanbul Pay Piyasası Resmî Seans Durum Makinesi."""

    # Seans Zaman Eşikleri (Europe/Istanbul)
    T_OPEN_COLL_START = time(9, 40)
    T_OPEN_DET_START = time(9, 55)
    T_CONT_START = time(10, 0)
    T_CONT_END = time(18, 0)
    T_CLOSE_COLL_START = time(18, 1)
    T_CLOSE_DET_START = time(18, 5)
    T_CLOSE_TRADE_START = time(18, 8)
    T_CLOSE_TRADE_END = time(18, 10)

    def __init__(self, holidays: Optional[set] = None):
        self._holidays = holidays or set()
        self._circuit_breaker_active: Dict[str, datetime] = {}  # Ticker bazlı devre kesici bitiş zamanı

    def now_istanbul(self) -> datetime:
        return datetime.now(_TZ_ISTANBUL)

    def trigger_circuit_breaker(self, ticker: str, duration_minutes: int = 5):
        """Hisse bazında devre kesici çağrı seansı başlatır."""
        now = self.now_istanbul()
        expiry = now + timedelta(minutes=duration_minutes)
        self._circuit_breaker_active[ticker] = expiry
        logger.warning("BIST Circuit Breaker Triggered", ticker=ticker, expiry=expiry.isoformat())

    def clear_circuit_breaker(self, ticker: str):
        self._circuit_breaker_active.pop(ticker, None)

    def get_phase(self, ticker: Optional[str] = None, current_time: Optional[datetime] = None) -> BISTMarketPhase:
        """Belirtilen an ve hisse için güncel seans fazını belirler."""
        dt = current_time or self.now_istanbul()

        # Hafta sonu veya resmi tatil kontrolü
        if dt.weekday() >= 5 or dt.strftime("%Y-%m-%d") in self._holidays:
            return BISTMarketPhase.CLOSED

        # Hisse bazlı devre kesici kontrolü
        if ticker and ticker in self._circuit_breaker_active:
            if dt < self._circuit_breaker_active[ticker]:
                return BISTMarketPhase.CIRCUIT_BREAKER_AUCTION
            else:
                self.clear_circuit_breaker(ticker)

        t = dt.time()

        if t < self.T_OPEN_COLL_START:
            return BISTMarketPhase.CLOSED
        elif t < self.T_OPEN_DET_START:
            return BISTMarketPhase.OPENING_AUCTION_COLLECTION
        elif t < self.T_CONT_START:
            return BISTMarketPhase.OPENING_AUCTION_DETERMINATION
        elif t < self.T_CONT_END:
            return BISTMarketPhase.CONTINUOUS_AUCTION
        elif t < self.T_CLOSE_COLL_START:
            # 18:00 - 18:01 arası seans arası / aktarım
            return BISTMarketPhase.CLOSED
        elif t < self.T_CLOSE_DET_START:
            return BISTMarketPhase.CLOSING_AUCTION_COLLECTION
        elif t < self.T_CLOSE_TRADE_START:
            return BISTMarketPhase.CLOSING_AUCTION_DETERMINATION
        elif t < self.T_CLOSE_TRADE_END:
            return BISTMarketPhase.CLOSING_PRICE_TRADING
        else:
            return BISTMarketPhase.CLOSED

    def is_order_entry_allowed(self, phase: BISTMarketPhase) -> bool:
        """Emir kabul edilen seans fazları."""
        return phase in {
            BISTMarketPhase.OPENING_AUCTION_COLLECTION,
            BISTMarketPhase.CONTINUOUS_AUCTION,
            BISTMarketPhase.CIRCUIT_BREAKER_AUCTION,
            BISTMarketPhase.CLOSING_AUCTION_COLLECTION,
            BISTMarketPhase.CLOSING_PRICE_TRADING,
        }

    def is_matching_active(self, phase: BISTMarketPhase) -> bool:
        """İşlemlerin eşleştiği seans fazları."""
        return phase in {
            BISTMarketPhase.OPENING_AUCTION_DETERMINATION,
            BISTMarketPhase.CONTINUOUS_AUCTION,
            BISTMarketPhase.CLOSING_AUCTION_DETERMINATION,
            BISTMarketPhase.CLOSING_PRICE_TRADING,
        }


# Singleton
bist_session_fsm = MarketSessionStateMachine()
