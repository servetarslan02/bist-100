"""
ALPHA BIST — Market Calendar v1.0

BIST işlem saatleri, tatiller, devre kesici durumları.
Market kapalıyken veri veya işlem üretmemeli.

FAZ 1.7: Trading Calendar
"""

from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Tuple
from enum import Enum
import structlog

logger = structlog.get_logger()


class MarketSession(str, Enum):
    """BIST işlem seansları (2015 BISTECH sonrası tek seans)."""
    PRE_MARKET = "PRE_MARKET"      # 09:40 - 10:00 (Açılış seansı emir toplama)
    OPENING = "OPENING"             # 09:55 - 10:00 (Fiyat belirleme)
    CONTINUOUS = "CONTINUOUS"       # 10:00 - 18:00 (Sürekli işlem — tek seans)
    CLOSING = "CLOSING"             # 18:00 - 18:10 (Kapanış seansı)
    CLOSED = "CLOSED"


class MarketStatus(str, Enum):
    """Piyasa durumu."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    HALT = "HALT"                   # Devre kesici
    EARLY_CLOSE = "EARLY_CLOSE"     # Yarım gün


# 2026 Türkiye resmi tatilleri
TURKEY_HOLIDAYS_2026 = [
    # Ulusal bayramlar
    date(2026, 1, 1),    # Yılbaşı
    date(2026, 4, 23),   # Ulusal Egemenlik ve Çocuk Bayramı
    date(2026, 5, 1),    # Emek ve Dayanışma Günü
    date(2026, 5, 19),   # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    date(2026, 7, 15),   # Demokrasi ve Millî Birlik Günü
    date(2026, 8, 30),   # Zafer Bayramı
    date(2026, 10, 29),  # Cumhuriyet Bayramı
    # Dini bayramlar (tahmini - her yıl değişir)
    date(2026, 3, 20),   # Ramazan Bayramı Arife
    date(2026, 3, 21),   # Ramazan Bayramı 1. gün
    date(2026, 3, 22),   # Ramazan Bayramı 2. gün
    date(2026, 3, 23),   # Ramazan Bayramı 3. gün
    date(2026, 5, 27),   # Kurban Bayramı Arife
    date(2026, 5, 28),   # Kurban Bayramı 1. gün
    date(2026, 5, 29),   # Kurban Bayramı 2. gün
    date(2026, 5, 30),   # Kurban Bayramı 3. gün
    date(2026, 5, 31),   # Kurban Bayramı 4. gün
]


class MarketCalendar:
    """BIST işlem takvimi."""

    # BIST normal işlem saatleri (2015 BISTECH sonrası tek seans)
    MARKET_OPEN = time(10, 0)
    MARKET_CLOSE = time(18, 0)
    PRE_MARKET_START = time(9, 40)
    OPENING_END = time(10, 0)
    CLOSING_START = time(18, 0)
    CLOSING_END = time(18, 10)

    def __init__(self, holidays: Optional[List[date]] = None):
        self._holidays = set(holidays or TURKEY_HOLIDAYS_2026)
        self._halts: Dict[date, List[Tuple[time, time]]] = {}

    def is_trading_day(self, d: Optional[date] = None) -> bool:
        """Bu gün işlem günü mü?"""
        if d is None:
            d = date.today()

        # Hafta sonu
        if d.weekday() >= 5:
            return False

        # Resmi tatil
        if d in self._holidays:
            return False

        return True

    def is_market_open(self, dt: Optional[datetime] = None) -> bool:
        """Şu an piyasa açık mı?"""
        if dt is None:
            dt = datetime.now()

        # İşlem günü değilse kapalı
        if not self.is_trading_day(dt.date()):
            return False

        current_time = dt.time()

        # Piyasa saatleri dışında
        if current_time < self.MARKET_OPEN or current_time >= self.MARKET_CLOSE:
            return False

        # Devre kesici
        if self._is_halt(dt):
            return False

        return True

    def get_session(self, dt: Optional[datetime] = None) -> MarketSession:
        """Mevcut işlem seansını döndür (tek seans sistemi)."""
        if dt is None:
            dt = datetime.now()

        if not self.is_trading_day(dt.date()):
            return MarketSession.CLOSED

        t = dt.time()

        if t < self.PRE_MARKET_START:
            return MarketSession.CLOSED
        elif t < self.OPENING_END:
            return MarketSession.PRE_MARKET
        elif t < self.CLOSING_START:
            return MarketSession.CONTINUOUS
        elif t < self.CLOSING_END:
            return MarketSession.CLOSING
        else:
            return MarketSession.CLOSED

    def get_status(self, dt: Optional[datetime] = None) -> MarketStatus:
        """Piyasa durumunu döndür."""
        if dt is None:
            dt = datetime.now()

        session = self.get_session(dt)

        if session == MarketSession.CLOSED:
            if self.is_trading_day(dt.date()):
                return MarketStatus.CLOSED
            return MarketStatus.CLOSED
        elif session == MarketSession.PRE_MARKET:
            return MarketStatus.PRE_MARKET
        elif self._is_halt(dt):
            return MarketStatus.HALT
        else:
            return MarketStatus.OPEN

    def next_open(self, dt: Optional[datetime] = None) -> datetime:
        """Bir sonraki piyasa açılış zamanını döndür."""
        if dt is None:
            dt = datetime.now()

        # Bugün açıksa ve henüz açılmadıysa
        if self.is_trading_day(dt.date()):
            today_open = datetime.combine(dt.date(), self.MARKET_OPEN)
            if dt < today_open:
                return today_open

        # Sonraki işlem gününü bul
        check_date = dt.date() + timedelta(days=1)
        for _ in range(10):  # Max 10 gün ileriye bak
            if self.is_trading_day(check_date):
                return datetime.combine(check_date, self.MARKET_OPEN)
            check_date += timedelta(days=1)

        # Fallback
        return dt + timedelta(days=1)

    def next_close(self, dt: Optional[datetime] = None) -> datetime:
        """Bir sonraki piyasa kapanış zamanını döndür."""
        if dt is None:
            dt = datetime.now()

        if self.is_trading_day(dt.date()):
            today_close = datetime.combine(dt.date(), self.MARKET_CLOSE)
            if dt < today_close:
                return today_close

        check_date = dt.date() + timedelta(days=1)
        for _ in range(10):
            if self.is_trading_day(check_date):
                return datetime.combine(check_date, self.MARKET_CLOSE)
            check_date += timedelta(days=1)

        return dt + timedelta(days=1)

    def trading_days_between(self, start: date, end: date) -> int:
        """İki tarih arasındaki işlem günü sayısı."""
        count = 0
        current = start
        while current <= end:
            if self.is_trading_day(current):
                count += 1
            current += timedelta(days=1)
        return count

    def add_halt(self, d: date, start: time, end: time):
        """Devre kesici ekle."""
        if d not in self._halts:
            self._halts[d] = []
        self._halts[d].append((start, end))
        logger.info("Trading halt added", date=d.isoformat(), start=start.isoformat(), end=end.isoformat())

    def _is_halt(self, dt: datetime) -> bool:
        """Devre kesici durumunda mı?"""
        halts = self._halts.get(dt.date(), [])
        for halt_start, halt_end in halts:
            if halt_start <= dt.time() < halt_end:
                return True
        return False

    def get_info(self, dt: Optional[datetime] = None) -> Dict:
        """Piyasa bilgisi döndür."""
        if dt is None:
            dt = datetime.now()

        return {
            "is_trading_day": self.is_trading_day(dt.date()),
            "is_market_open": self.is_market_open(dt),
            "session": self.get_session(dt).value,
            "status": self.get_status(dt).value,
            "next_open": self.next_open(dt).isoformat(),
            "next_close": self.next_close(dt).isoformat(),
            "date": dt.date().isoformat(),
            "time": dt.time().isoformat(),
        }


# Singleton
market_calendar = MarketCalendar()
