"""
ALPHA BIST — Market Session State Machine (Single Source of Truth)

Borsa İstanbul Pay Piyasası Resmî Seans Çizelgesi (Eylül 2025 Güncel Kurallar):

TAM İŞ GÜNLERİ:
- 09:40 — 09:55 : Açılış Açık Artırması — Emir Toplama (OPENING_AUCTION_COLLECTION)
- 09:55 — 10:00 : Açılış Açık Artırması — Fiyat Belirleme / Eşleşme (OPENING_AUCTION_DETERMINATION)
- 10:00 — 18:00 : Sürekli Müzayede (CONTINUOUS_AUCTION)
- [Dinamik]     : Devre Kesici Çağrı Seansı (CIRCUIT_BREAKER_AUCTION — 10 dk emir toplama)
- 18:01 — 18:05 : Kapanış Açık Artırması — Emir Toplama (CLOSING_AUCTION_COLLECTION)
- 18:05 — 18:07 : Kapanış Fiyatı Belirleme / Eşleşme (CLOSING_AUCTION_DETERMINATION)
- 18:08 — 18:10 : Kapanış Fiyatından İşlemler (CLOSING_PRICE_TRADING / Trade at Close)
- 18:10 — 09:40 : Piyasa Kapalı (CLOSED)

YARIM İŞ GÜNLERİ (Resmi Tatil Arifeleri — Ramazan/Kurban Bayramı Arife, 29 Ekim vs.):
- 09:40 — 09:55 : Açılış Açık Artırması — Emir Toplama
- 09:55 — 10:00 : Açılış Açık Artırması — Fiyat Belirleme
- 10:00 — 12:30 : Sürekli Müzayede
- 12:30 — 12:31 : Kapanış Marj Yayını
- 12:31 — 12:35 : Kapanış Açık Artırması — Emir Toplama
- 12:35 — 12:37 : Kapanış Fiyatı Belirleme
- 12:37 — 12:38 : Kapanış Fiyatından Marj Yayını
- 12:38 — 12:40 : Kapanış Fiyatından İşlemler
- 12:40 — 09:40 : Piyasa Kapalı

Kaynak: Borsa İstanbul resmi, Eylül 2025 duyurusu
"""

from datetime import datetime, time, timedelta, timezone
from enum import Enum

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

    # Seans Zaman Eşikleri — TAM İŞ GÜNLERİ (Europe/Istanbul)
    T_OPEN_COLL_START = time(9, 40)
    T_OPEN_DET_START = time(9, 55)
    T_CONT_START = time(10, 0)
    T_CONT_END = time(18, 0)
    T_CLOSE_COLL_START = time(18, 1)
    T_CLOSE_DET_START = time(18, 5)
    T_CLOSE_TRADE_START = time(18, 8)
    T_CLOSE_TRADE_END = time(18, 10)

    # Seans Zaman Eşikleri — YARIM İŞ GÜNLERİ (Resmi Tatil Arifeleri)
    HALF_T_CONT_END = time(12, 30)
    HALF_T_CLOSE_COLL_START = time(12, 31)
    HALF_T_CLOSE_DET_START = time(12, 35)
    HALF_T_CLOSE_TRADE_START = time(12, 37)
    HALF_T_CLOSE_TRADE_END = time(12, 40)

    # Devre kesici sabitleri (Ağustos 2025 güncel)
    CIRCUIT_BREAKER_DURATION_MINUTES = 10  # BIST resmi: 10 dakika emir toplama (tüm paylar)
    EBDKS_THRESHOLD_PCT = 6.0              # Endekse bağlı devre kesici: BIST-100 %6 düşüş (tek aşamalı)

    # EBDKS durdurma süreleri — özellik koduna göre farklılaştırılmış (Ağustos 2025)
    # .E, .F1, .F2, .S1, .G → 10 dakika
    # .V, .C, .F, .R, .BE, .AOF → 20 dakika
    # VİOP pay/endeks sözleşmeleri → 20 dakika
    EBDKS_DURATION_BY_FEATURE = {
        "E": 10, "F1": 10, "F2": 10, "S1": 10, "G": 10,
        "V": 20, "C": 20, "F": 20, "R": 20, "BE": 20, "AOF": 20,
    }
    EBDKS_DEFAULT_DURATION = 20  # VİOP ve tanımsız özellik kodları için

    # EBDKS geç seans kuralı: 17:30'dan sonra tetiklenirse kapanış seansı ile yeniden başlatılır
    EBDKS_LATE_SESSION_CUTOFF = time(17, 30)

    # Pay bazında devre kesici eşikleri (Ağustos 2025 güncel)
    # Yıldız/Ana Pazar: %5, %10, %15 düşüş
    # Alt Pazar: %5, %10 düşüş
    CIRCUIT_BREAKER_THRESHOLDS = {
        "yildiz": [5.0, 10.0, 15.0],
        "ana": [5.0, 10.0, 15.0],
        "alt": [5.0, 10.0],
    }

    def __init__(self, holidays: set | None = None, half_days: set | None = None):
        self._holidays = holidays or set()
        self._half_days = half_days or set()  # Yarım gün tarihleri (YYYY-MM-DD)
        self._circuit_breaker_active: dict[str, datetime] = {}  # Ticker bazlı devre kesici bitiş zamanı
        self._ebdks_active: datetime | None = None  # Endekse bağlı devre kesici bitiş zamanı
        self._ebdks_triggered_at: datetime | None = None  # EBDKS tetiklenme anı
        self._ebdks_triggered_count: int = 0  # Bugün kaç kez tetiklendi

    def now_istanbul(self) -> datetime:
        return datetime.now(_TZ_ISTANBUL)

    def set_holidays(self, holidays: set):
        """Tatil günlerini güncelle."""
        self._holidays = holidays

    def set_half_days(self, half_days: set):
        """Yarım gün tarihlerini güncelle (YYYY-MM-DD formatında)."""
        self._half_days = half_days

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

    def trigger_ebdks(self, feature_code: str | None = None):
        """Endekse bağlı devre kesici (EBDKS) başlatır.

        BIST-100 %6 veya daha fazla düşüşte tetiklenir (Ağustos 2025: tek aşamalı).
        Tüm Pay Piyasası ve VİOP pay sözleşmelerinde işlemler durdurulur.

        Özellik koduna göre süre farklılaştırılmıştır:
        - .E, .F1, .F2, .S1, .G → 10 dakika
        - .V, .C, .F, .R, .BE, .AOF → 20 dakika
        - VİOP → 20 dakika

        Geç seans kuralı: 17:30'dan sonra tetiklenirse kapanış seansı ile yeniden başlatılır.
        """
        now = self.now_istanbul()

        # Özellik koduna göre süre belirle
        if feature_code:
            duration = self.EBDKS_DURATION_BY_FEATURE.get(feature_code, self.EBDKS_DEFAULT_DURATION)
        else:
            duration = self.EBDKS_DEFAULT_DURATION

        expiry = now + timedelta(minutes=duration)
        self._ebdks_active = expiry
        self._ebdks_triggered_at = now  # Tetiklenme anını kaydet
        self._ebdks_triggered_count += 1

        # Geç seans kuralı: 17:30'dan sonra tetiklenirse kapanış seansı başlatılmalı
        late_session = now.time() >= self.EBDKS_LATE_SESSION_CUTOFF

        logger.warning("BIST EBDKS Tetiklendi",
                       expiry=expiry.isoformat(),
                       duration_min=duration,
                       feature_code=feature_code,
                       count_today=self._ebdks_triggered_count,
                       late_session_rule=late_session)

    def clear_circuit_breaker(self, ticker: str):
        self._circuit_breaker_active.pop(ticker, None)

    def clear_ebdks(self):
        self._ebdks_active = None
        self._ebdks_triggered_at = None

    def is_ebdks_active(self) -> bool:
        """Endekse bağlı devre kesici aktif mi?"""
        if self._ebdks_active is None:
            return False
        if self.now_istanbul() >= self._ebdks_active:
            self._ebdks_active = None
            return False
        return True

    def is_ebdks_late_session(self) -> bool:
        """EBDKS geç seans kuralı uygulanmalı mı?

        17:30'dan sonra EBDKS tetiklenirse kapanış seansı ile yeniden başlatılır.
        """
        if self._ebdks_triggered_at is None:
            return False
        return self._ebdks_triggered_at.time() >= self.EBDKS_LATE_SESSION_CUTOFF

    def get_phase(self, ticker: str | None = None, current_time: datetime | None = None) -> BISTMarketPhase:
        """Belirtilen an ve hisse için güncel seans fazını belirler.

        Yarım günlerde (resmi tatil arifeleri) seans 12:30'da sona erer.
        """
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
        is_half_day = dt.strftime("%Y-%m-%d") in self._half_days

        # Ortak açılış seansı (tam gün ve yarım gün aynı)
        if t < self.T_OPEN_COLL_START:
            return BISTMarketPhase.CLOSED
        elif t < self.T_OPEN_DET_START:
            return BISTMarketPhase.OPENING_AUCTION_COLLECTION
        elif t < self.T_CONT_START:
            return BISTMarketPhase.OPENING_AUCTION_DETERMINATION

        if is_half_day:
            # YARIM İŞ GÜNÜ seans çizelgesi
            if t < self.HALF_T_CONT_END:
                return BISTMarketPhase.CONTINUOUS_AUCTION
            elif t < self.HALF_T_CLOSE_COLL_START:
                return BISTMarketPhase.CLOSED  # 12:30-12:31 arası geçiş
            elif t < self.HALF_T_CLOSE_DET_START:
                return BISTMarketPhase.CLOSING_AUCTION_COLLECTION
            elif t < self.HALF_T_CLOSE_TRADE_START:
                return BISTMarketPhase.CLOSING_AUCTION_DETERMINATION
            elif t < self.HALF_T_CLOSE_TRADE_END:
                return BISTMarketPhase.CLOSING_PRICE_TRADING
            else:
                return BISTMarketPhase.CLOSED
        else:
            # TAM İŞ GÜNÜ seans çizelgesi
            if t < self.T_CONT_END:
                return BISTMarketPhase.CONTINUOUS_AUCTION
            elif t < self.T_CLOSE_COLL_START:
                return BISTMarketPhase.CLOSED  # 18:00-18:01 arası geçiş
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
