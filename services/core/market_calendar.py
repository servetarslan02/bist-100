"""
ALPHA BIST — Market Calendar v2.0

BIST işlem saatleri, tatiller, devre kesici durumları.
market_session_fsm.py'yi kullanır (tek kaynak).

Eylül 2025 güncel kurallar:
- Tek seans: 10:00 - 18:00
- Açılış seansı: 09:40 - 10:00
- Kapanış seansı: 18:01 - 18:10
- EBDKS: BIST-100 %6 düşüşte tetiklenir
"""

from datetime import date, datetime, time, timedelta
from enum import StrEnum

import structlog

from .market_session_fsm import _TZ_ISTANBUL, BISTMarketPhase, bist_session_fsm

logger = structlog.get_logger()


class MarketSession(StrEnum):
    """BIST işlem seansları."""
    PRE_MARKET = "PRE_MARKET"      # 09:40 - 10:00
    OPENING = "OPENING"             # 09:55 - 10:00
    CONTINUOUS = "CONTINUOUS"       # 10:00 - 18:00
    CLOSING = "CLOSING"             # 18:01 - 18:10
    CLOSED = "CLOSED"


class MarketStatus(StrEnum):
    """Piyasa durumu."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    HALT = "HALT"
    EARLY_CLOSE = "EARLY_CLOSE"


# 2026 Türkiye resmi tatilleri
TURKEY_HOLIDAYS_2026 = [
    date(2026, 1, 1),    # Yılbaşı
    date(2026, 4, 23),   # Ulusal Egemenlik ve Çocuk Bayramı
    date(2026, 5, 1),    # Emek ve Dayanışma Günü
    date(2026, 5, 19),   # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    date(2026, 7, 15),   # Demokrasi ve Millî Birlik Günü
    date(2026, 8, 30),   # Zafer Bayramı
    date(2026, 10, 29),  # Cumhuriyet Bayramı
    date(2026, 3, 21),   # Ramazan Bayramı 1. gün
    date(2026, 3, 22),   # Ramazan Bayramı 2. gün
    date(2026, 3, 23),   # Ramazan Bayramı 3. gün
    date(2026, 5, 28),   # Kurban Bayramı 1. gün
    date(2026, 5, 29),   # Kurban Bayramı 2. gün
    date(2026, 5, 30),   # Kurban Bayramı 3. gün
    date(2026, 5, 31),   # Kurban Bayramı 4. gün
]

# 2026 Türkiye yarım gün tatilleri (resmi tatil arifeleri)
# Bu günlerde piyasa 12:30'da kapanır
TURKEY_HALF_DAYS_2026 = [
    date(2026, 3, 20),   # Ramazan Bayramı Arifesi
    date(2026, 5, 27),   # Kurban Bayramı Arifesi
    date(2026, 10, 28),  # Cumhuriyet Bayramı Arifesi (yarım gün)
]


class MarketCalendar:
    """BIST işlem takvimi — market_session_fsm.py wrapper."""

    MARKET_OPEN = time(10, 0)
    MARKET_CLOSE = time(18, 0)
    HALF_MARKET_CLOSE = time(12, 30)  # Yarım gün kapanış
    PRE_MARKET_START = time(9, 40)
    CLOSING_END = time(18, 10)
    HALF_CLOSING_END = time(12, 40)  # Yarım gün kapanış sonu

    def __init__(self, holidays: list[date] | None = None, half_days: list[date] | None = None):
        self._holidays = set(holidays or TURKEY_HOLIDAYS_2026)
        self._half_days = set(half_days or TURKEY_HALF_DAYS_2026)
        # FSM'ye tatil günlerini string formatında aktar
        holiday_strs = {d.strftime("%Y-%m-%d") for d in self._holidays}
        half_day_strs = {d.strftime("%Y-%m-%d") for d in self._half_days}
        bist_session_fsm.set_holidays(holiday_strs)
        bist_session_fsm.set_half_days(half_day_strs)
        self._halts: dict[date, list[tuple[time, time]]] = {}

    def is_half_day(self, d: date | None = None) -> bool:
        """Bu gün yarım gün mü?"""
        if d is None:
            d = date.today()
        return d in self._half_days

    def is_trading_day(self, d: date | None = None) -> bool:
        if d is None:
            d = date.today()
        if d.weekday() >= 5:
            return False
        return d not in self._holidays

    def is_market_open(self, dt: datetime | None = None) -> bool:
        if dt is None:
            dt = datetime.now(_TZ_ISTANBUL)
        if not self.is_trading_day(dt.date()):
            return False
        phase = bist_session_fsm.get_phase(current_time=dt)
        return bist_session_fsm.is_order_entry_allowed(phase)

    def get_session(self, dt: datetime | None = None) -> MarketSession:
        if dt is None:
            dt = datetime.now(_TZ_ISTANBUL)
        if not self.is_trading_day(dt.date()):
            return MarketSession.CLOSED

        phase = bist_session_fsm.get_phase(current_time=dt)
        mapping = {
            BISTMarketPhase.CLOSED: MarketSession.CLOSED,
            BISTMarketPhase.OPENING_AUCTION_COLLECTION: MarketSession.PRE_MARKET,
            BISTMarketPhase.OPENING_AUCTION_DETERMINATION: MarketSession.OPENING,
            BISTMarketPhase.CONTINUOUS_AUCTION: MarketSession.CONTINUOUS,
            BISTMarketPhase.CIRCUIT_BREAKER_AUCTION: MarketSession.CONTINUOUS,
            BISTMarketPhase.CLOSING_AUCTION_COLLECTION: MarketSession.CLOSING,
            BISTMarketPhase.CLOSING_AUCTION_DETERMINATION: MarketSession.CLOSING,
            BISTMarketPhase.CLOSING_PRICE_TRADING: MarketSession.CLOSING,
        }
        return mapping.get(phase, MarketSession.CLOSED)

    def get_status(self, dt: datetime | None = None) -> MarketStatus:
        if dt is None:
            dt = datetime.now(_TZ_ISTANBUL)
        session = self.get_session(dt)
        if session == MarketSession.CLOSED:
            return MarketStatus.CLOSED
        elif session == MarketSession.PRE_MARKET:
            return MarketStatus.PRE_MARKET
        elif bist_session_fsm.is_ebdks_active():
            return MarketStatus.HALT
        else:
            return MarketStatus.OPEN

    def next_open(self, dt: datetime | None = None) -> datetime:
        if dt is None:
            dt = datetime.now(_TZ_ISTANBUL)
        if self.is_trading_day(dt.date()):
            today_open = datetime.combine(dt.date(), self.MARKET_OPEN, tzinfo=_TZ_ISTANBUL)
            if dt < today_open:
                return today_open
        check_date = dt.date() + timedelta(days=1)
        for _ in range(10):
            if self.is_trading_day(check_date):
                return datetime.combine(check_date, self.MARKET_OPEN, tzinfo=_TZ_ISTANBUL)
            check_date += timedelta(days=1)
        return dt + timedelta(days=1)

    def next_close(self, dt: datetime | None = None) -> datetime:
        if dt is None:
            dt = datetime.now(_TZ_ISTANBUL)
        if self.is_trading_day(dt.date()):
            close_time = self.HALF_MARKET_CLOSE if self.is_half_day(dt.date()) else self.MARKET_CLOSE
            today_close = datetime.combine(dt.date(), close_time, tzinfo=_TZ_ISTANBUL)
            if dt < today_close:
                return today_close
        check_date = dt.date() + timedelta(days=1)
        for _ in range(10):
            if self.is_trading_day(check_date):
                close_time = self.HALF_MARKET_CLOSE if self.is_half_day(check_date) else self.MARKET_CLOSE
                return datetime.combine(check_date, close_time, tzinfo=_TZ_ISTANBUL)
            check_date += timedelta(days=1)
        return dt + timedelta(days=1)

    def trading_days_between(self, start: date, end: date) -> int:
        count = 0
        current = start
        while current <= end:
            if self.is_trading_day(current):
                count += 1
            current += timedelta(days=1)
        return count

    def add_halt(self, d: date, start: time, end: time):
        if d not in self._halts:
            self._halts[d] = []
        self._halts[d].append((start, end))

    def get_info(self, dt: datetime | None = None) -> dict:
        if dt is None:
            dt = datetime.now(_TZ_ISTANBUL)
        return {
            "is_trading_day": self.is_trading_day(dt.date()),
            "is_half_day": self.is_half_day(dt.date()),
            "is_market_open": self.is_market_open(dt),
            "session": self.get_session(dt).value,
            "status": self.get_status(dt).value,
            "next_open": self.next_open(dt).isoformat(),
            "next_close": self.next_close(dt).isoformat(),
            "ebdks_active": bist_session_fsm.is_ebdks_active(),
        }


# Singleton
market_calendar = MarketCalendar()


def get_market_calendar() -> MarketCalendar:
    """Cache warmer uyumluluğu için."""
    return market_calendar
