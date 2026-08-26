"""
ALPHA BIST — Market Session State Machine (Single Source of Truth)

Borsa İstanbul Pay Piyasası Resmî Seans Çizelgesi (Eylül 2025 Güncel Kurallar):
- 09:40 — 09:55 : Açılış Açık Artırması — Emir Toplama (OPENING_AUCTION_COLLECTION)
- 09:55 — 10:00 : Açılış Açık Artırması — Fiyat Belirleme / Eşleşme (OPENING_AUCTION_DETERMINATION)
- 10:00 — 18:00 : Sürekli Müzayede (CONTINUOUS_AUCTION)
- [Dinamik]     : Devre Kesici Çağrı Seansı (CIRCUIT_BREAKER_AUCTION — 10 dk emir toplama)
- 18:01 — 18:05 : Kapanış Açık Artırması — Emir Toplama (CLOSING_AUCTION_COLLECTION)
- 18:05 — 18:07 : Kapanış Fiyatı Belirleme / Eşleşme (CLOSING_AUCTION_DETERMINATION)
- 18:08 — 18:10 : Kapanış Fiyatından İşlemler (CLOSING_PRICE_TRADING / Trade at Close)
- 18:10 — 09:40 : Piyasa Kapalı (CLOSED)

Kaynak: Borsa İstanbul resmi, Eylül 2025 duyurusu
"""

from datetime import datetime, time, timezone, timedelta
from enum import Enum
from typing import Optional, Dict, List
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
    """Borsa İstanbul Pay Piyasası Resmî Seans Durum Makinesi.

    Bu dosya BIST seans saatleri için TEK KAYNAK (single source of truth).
    market_session.py ve market_calendar.py bu dosyayı kullanır.
    """

    # Seans Zaman Eşikleri (Europe/Istanbul)
    T_OPEN_COLL_START = time(9, 40)
    T_OPEN_DET_START = time(9, 55)
    T_CONT_START = time(10, 0)
    T_CONT_END = time(18, 0)
    T_CLOSE_COLL_START = time(18, 1)
    T_CLOSE_DET_START = time(18, 5)
    T_CLOSE_TRADE_START = time(18, 8)
    T_CLOSE_TRADE_END = time(18, 10)

    # Devre kesici sabitleri (Eylül 2025 güncel)
    CIRCUIT_BREAKER_DURATION_MINUTES = 10  # BIST resmi: 10 dakika emir toplama
    EBDKS_THRESHOLD_PCT = 6.0              # Endekse bağlı devre kesici: BIST-100 %6 düşüş
    EBDKS_DURATION_MINUTES = 20            # EBDKS durdurma süresi

    # Pay bazında devre kesici eşikleri (Eylül 2025 güncel)
    # Yıldız/Ana Pazar: %5, %10, %15 düşüş
    # Alt Pazar: %5, %10 düşüş
    CIRCUIT_BREAKER_THRESHOLDS = {
        "yildiz": [5.0, 10.0, 15.0],
        "ana": [5.0, 10.0, 15.0],
        "alt": [5.0, 10.0],
    }

    def __init__(self, holidays: Optional[set] = None):
        self._holidays = holidays or set()
        self._circuit_breaker_active: Dict[str, datetime] = {}  # Ticker bazlı devre kesici bitiş zamanı
        self._ebdks_active: Optional[datetime] = None  # Endekse bağlı devre kesici bitiş zamanı
        self._ebdks_triggered_count: int = 0  # Bugün kaç kez tetiklendi

    def now_istanbul(self) -> datetime:
        return datetime.now(_TZ_ISTANBUL)

    def set_holidays(self, holidays: set):
        """Tatil günlerini güncelle."""
        self._holidays = holidays

    def trigger_circuit_breaker(self, ticker: str, duration_minutes: int = None):
        """Hisse bazında devre kesici çağrı seansı başlatır.

        BIST resmi: 10 dakika emir toplama süresi.
        """
        if duration_minutes is None:
            duration_minutes = self.CIRCUIT_BREAKER_DURATION_MINUTES
        now = self.now_istanbul()
        expiry = now + timedelta(minutes=duration_minutes)
        self._circuit_breaker_active[ticker] = expiry
        logger.warning("BIST Pay Bazında Devre Kesici",
                       ticker=ticker, expiry=expiry.isoformat(),
                       duration_min=duration_minutes)

    def trigger_ebdks(self):
        """Endekse bağlı devre kesici (EBDKS) başlatır.

        BIST-100 %6 veya daha fazla düşüşte tetiklenir.
        Tüm Pay Piyasası ve VİOP pay sözleşmelerinde işlemler durdurulur.
        """
        now = self.now_istanbul()
        expiry = now + timedelta(minutes=self.EBDKS_DURATION_MINUTES)
        self._ebdks_active = expiry
        self._ebdks_triggered_count += 1
        logger.warning("BIST EBDKS Tetiklendi",
                       expiry=expiry.isoformat(),
                       duration_min=self.EBDKS_DURATION_MINUTES,
                       count_today=self._ebdks_triggered_count)

    def clear_circuit_breaker(self, ticker: str):
        self._circuit_breaker_active.pop(ticker, None)

    def clear_ebdks(self):
        self._ebdks_active = None

    def is_ebdks_active(self) -> bool:
        """Endekse bağlı devre kesici aktif mi?"""
        if self._ebdks_active is None:
            return False
        if self.now_istanbul() >= self._ebdks_active:
            self._ebdks_active = None
            return False
        return True

    def get_phase(self, ticker: Optional[str] = None, current_time: Optional[datetime] = None) -> BISTMarketPhase:
        """Belirtilen an ve hisse için güncel seans fazını belirler."""
        dt = current_time or self.now_istanbul()

        # Hafta sonu veya resmi tatil kontrolü
        if dt.weekday() >= 5 or dt.strftime("%Y-%m-%d") in self._holidays:
            return BISTMarketPhase.CLOSED

        # EBDKS kontrolü (tüm piyasayı etkiler)
        if self.is_ebdks_active():
            return BISTMarketPhase.CIRCUIT_BREAKER_AUCTION

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

    def is_trading_hours(self) -> bool:
        """Piyasa açık mı? (sürekli işlem fazı)"""
        return self.get_phase() == BISTMarketPhase.CONTINUOUS_AUCTION

    def is_market_open(self) -> bool:
        """Piyasa açık mı? (emir kabul edilen herhangi bir faz)"""
        phase = self.get_phase()
        return self.is_order_entry_allowed(phase)

    def is_closed(self) -> bool:
        return self.get_phase() == BISTMarketPhase.CLOSED

    def get_status(self) -> dict:
        """Durum bilgisi."""
        now = self.now_istanbul()
        phase = self.get_phase()
        return {
            "phase": phase.value,
            "istanbul_time": now.isoformat(),
            "weekday": now.strftime("%A"),
            "is_trading_day": now.weekday() < 5 and now.strftime("%Y-%m-%d") not in self._holidays,
            "ebdks_active": self.is_ebdks_active(),
            "active_circuit_breakers": list(self._circuit_breaker_active.keys()),
        }


# Singleton
bist_session_fsm = MarketSessionStateMachine()
