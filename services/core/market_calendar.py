from typing import Any

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

import functools
from datetime import date, datetime, time, timedelta
from enum import StrEnum

import structlog
from opentelemetry import trace

from .market_session_fsm import _TZ_ISTANBUL, BISTMarketPhase, bist_session_fsm

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.market_calendar")


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


class MarketSession(StrEnum):
    """BIST işlem seansları."""

    PRE_MARKET = "PRE_MARKET"  # 09:40 - 10:00
    OPENING = "OPENING"  # 09:55 - 10:00
    CONTINUOUS = "CONTINUOUS"  # 10:00 - 18:00
    CLOSING = "CLOSING"  # 18:01 - 18:10
    CLOSED = "CLOSED"


class MarketStatus(StrEnum):
    """Piyasa durumu."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    HALT = "HALT"
    EARLY_CLOSE = "EARLY_CLOSE"


# Tatil günleri artık HolidayManager tarafından dinamik olarak hesaplanıyor.
# Statik liste kaldırıldı — holiday_manager.py kullanılıyor.


class MarketCalendar:
    """BIST işlem takvimi — market_session_fsm.py wrapper."""

    MARKET_OPEN = time(10, 0)
    MARKET_CLOSE = time(18, 0)
    HALF_MARKET_CLOSE = time(12, 30)  # Yarım gün kapanış
    PRE_MARKET_START = time(9, 40)
    CLOSING_END = time(18, 10)
    HALF_CLOSING_END = time(12, 40)  # Yarım gün kapanış sonu

    def __init__(self, holidays: list[date] | None = None, half_days: list[date] | None = None):
        """Otomatik eklendi."""
        from .holiday_manager import holiday_manager

        self._hm = holiday_manager

        # Dinamik tatil yöneticisinden al (yıl otomatik hesaplanır)
        today = date.today()
        self._holidays = set(holidays) if holidays else self._hm.get_holidays(today.year)
        self._half_days = set(half_days) if half_days else self._hm.get_half_days(today.year)

        # FSM'ye tatil günlerini string formatında aktar
        holiday_strs = {d.strftime("%Y-%m-%d") for d in self._holidays}
        half_day_strs = {d.strftime("%Y-%m-%d") for d in self._half_days}
        bist_session_fsm.set_holidays(holiday_strs)
        bist_session_fsm.set_half_days(half_day_strs)
        self._halts: dict[date, list[tuple[time, time]]] = {}

        logger.info(
            "MarketCalendar initialized with HolidayManager",
            year=today.year,
            holidays=len(self._holidays),
            half_days=len(self._half_days),
        )

    @otel_trace("market_calendar.is_half_day")
    def is_half_day(self, d: date | None = None) -> bool:
        """Bu gün yarım gün mü?"""
        if d is None:
            d = date.today()
        # Yıl değiştiyse güncelle
        if d.year not in self._hm._half_days:
            self._half_days = self._hm.get_half_days(d.year)
        return d in self._half_days

    @otel_trace("market_calendar.is_trading_day")
    def is_trading_day(self, d: date | None = None) -> bool:
        """Otomatik eklendi."""
        if d is None:
            d = date.today()
        if d.weekday() >= 5:
            return False
        # Yıl değiştiyse veya anlık tatil eklendiyse güncelle
        holidays = self._hm.get_holidays(d.year)
        return d not in holidays

    @otel_trace("market_calendar.is_market_open")
    def is_market_open(self, dt: datetime | None = None) -> bool:
        """Otomatik eklendi."""
        if dt is None:
            dt = datetime.now(_TZ_ISTANBUL)
        if not self.is_trading_day(dt.date()):
            return False
        phase = bist_session_fsm.get_phase(current_time=dt)
        return bist_session_fsm.is_order_entry_allowed(phase)

    @otel_trace("market_calendar.get_session")
    def get_session(self, dt: datetime | None = None) -> MarketSession:
        """Otomatik eklendi."""
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

    @otel_trace("market_calendar.get_status")
    def get_status(self, dt: datetime | None = None) -> MarketStatus:
        """Otomatik eklendi."""
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

    @otel_trace("market_calendar.next_open")
    def next_open(self, dt: datetime | None = None) -> datetime:
        """Otomatik eklendi."""
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

    @otel_trace("market_calendar.next_close")
    def next_close(self, dt: datetime | None = None) -> datetime:
        """Otomatik eklendi."""
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

    @otel_trace("market_calendar.trading_days_between")
    def trading_days_between(self, start: date, end: date) -> int:
        """Otomatik eklendi."""
        count = 0
        current = start
        while current <= end:
            if self.is_trading_day(current):
                count += 1
            current += timedelta(days=1)
        return count

    @otel_trace("market_calendar.add_halt")
    def add_halt(self, d: date, start: time, end: time) -> Any:
        """Otomatik eklendi."""
        if d not in self._halts:
            self._halts[d] = []
        self._halts[d].append((start, end))

    @otel_trace("market_calendar.report_no_data")
    def report_no_data(self, d: date | None = None) -> bool:
        """Veri gelmediğini rapor et — anlık tatil tespiti."""
        return self._hm.report_no_data(d)

    @otel_trace("market_calendar.add_manual_holiday")
    def add_manual_holiday(self, d: date, reason: str = "") -> None:
        """Manuel tatil ekle (anlık ilan edilen tatiller için)."""
        self._hm.add_manual_holiday(d, reason)
        # FSM'yi güncelle
        holiday_strs = {dd.strftime("%Y-%m-%d") for dd in self._hm.get_holidays(d.year)}
        bist_session_fsm.set_holidays(holiday_strs)

    @otel_trace("market_calendar.sync_from_bist")
    async def sync_from_bist(self) -> bool:
        """BIST resmi web sitesinden tatilleri çek."""
        return await self._hm.sync_from_bist()

    @otel_trace("market_calendar.get_holiday_info")
    def get_holiday_info(self, year: int | None = None) -> str:
        """Yılın tüm tatillerini okunabilir formatta döndür."""
        return self._hm.get_all_holidays_text(year)

    @otel_trace("market_calendar.get_info")
    def get_info(self, dt: datetime | None = None) -> dict:
        """Otomatik eklendi."""
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
