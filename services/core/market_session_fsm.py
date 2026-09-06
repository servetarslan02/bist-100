"""ALPHA BIST — Market Session State Machine (Single Source of Truth)

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

import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Istanbul Zaman Dilimi (UTC+3)
_TZ_ISTANBUL = timezone(timedelta(hours=3))

# --- Varsayılan Seans Zaman Eşikleri ve Sabitler ---
DEFAULT_OPEN_COLL_START = time(9, 40)
DEFAULT_OPEN_DET_START = time(9, 55)
DEFAULT_CONT_START = time(10, 0)
DEFAULT_CONT_END = time(18, 0)
DEFAULT_CLOSE_COLL_START = time(18, 1)
DEFAULT_CLOSE_DET_START = time(18, 5)
DEFAULT_CLOSE_TRADE_START = time(18, 8)
DEFAULT_CLOSE_TRADE_END = time(18, 10)

# Yarım Gün Seans Zaman Eşikleri
DEFAULT_HALF_CONT_END = time(12, 30)
DEFAULT_HALF_CLOSE_COLL_START = time(12, 31)
DEFAULT_HALF_CLOSE_DET_START = time(12, 35)
DEFAULT_HALF_CLOSE_TRADE_START = time(12, 37)
DEFAULT_HALF_CLOSE_TRADE_END = time(12, 40)

# Devre Kesici ve EBDKS Sabitleri
DEFAULT_CIRCUIT_BREAKER_DURATION_MINUTES = 10
DEFAULT_EBDKS_THRESHOLD_PCT = 6.0
DEFAULT_EBDKS_DEFAULT_DURATION = 20
DEFAULT_EBDKS_LATE_SESSION_CUTOFF = time(17, 30)

DEFAULT_DUCKDB_PATH = Path("data/market_session.duckdb")


class BISTMarketPhase(StrEnum):
    """Borsa İstanbul Pay Piyasası Resmî Seans Fazları."""

    CLOSED = "CLOSED"
    OPENING_AUCTION_COLLECTION = "OPENING_AUCTION_COLLECTION"  # 09:40 - 09:55
    OPENING_AUCTION_DETERMINATION = "OPENING_AUCTION_DETERMINATION"  # 09:55 - 10:00
    CONTINUOUS_AUCTION = "CONTINUOUS_AUCTION"  # 10:00 - 18:00
    CIRCUIT_BREAKER_AUCTION = "CIRCUIT_BREAKER_AUCTION"  # Tetiklendiğinde
    CLOSING_AUCTION_COLLECTION = "CLOSING_AUCTION_COLLECTION"  # 18:01 - 18:05
    CLOSING_AUCTION_DETERMINATION = "CLOSING_AUCTION_DETERMINATION"  # 18:05 - 18:07
    CLOSING_PRICE_TRADING = "CLOSING_PRICE_TRADING"  # 18:08 - 18:10


@dataclass(slots=True)
class MarketSessionStatus:
    """BIST seans anlık durum bilgisi veri modeli.

    Attributes:
        phase: Mevcut seans fazı adı.
        istanbul_time: ISO-8601 formatında İstanbul yerel zamanı.
        weekday: Haftanın günü adı (İngilizce).
        is_trading_day: Bugün işlem günü mü (hafta sonu/resmi tatil değil mi).
        is_market_open: Emir girişine açık mı.
        is_trading_hours: Sürekli müzayede seansında mı.
        ebdks_active: Endekse bağlı devre kesici aktif mi.
        active_circuit_breakers: Hisseler bazında aktif devre kesici ticker listesi.
        ebdks_triggered_count: Bugün kaç kez EBDKS tetiklendiği.
        is_half_day: Bugün yarım iş günü mü.
    """

    phase: str
    istanbul_time: str
    weekday: str
    is_trading_day: bool
    is_market_open: bool
    is_trading_hours: bool
    ebdks_active: bool
    active_circuit_breakers: list[str]
    ebdks_triggered_count: int = 0
    is_half_day: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür."""
        return {
            "phase": self.phase,
            "istanbul_time": self.istanbul_time,
            "weekday": self.weekday,
            "is_trading_day": self.is_trading_day,
            "is_market_open": self.is_market_open,
            "is_trading_hours": self.is_trading_hours,
            "ebdks_active": self.ebdks_active,
            "active_circuit_breakers": list(self.active_circuit_breakers),
            "ebdks_triggered_count": self.ebdks_triggered_count,
            "is_half_day": self.is_half_day,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson ile ikili JSON bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def to_json(self) -> str:
        """Modeli JSON dizgisine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketSessionStatus":
        """Sözlük verisinden MarketSessionStatus nesnesi üretir."""
        return cls(
            phase=str(data.get("phase", "CLOSED")),
            istanbul_time=str(data.get("istanbul_time", "")),
            weekday=str(data.get("weekday", "")),
            is_trading_day=bool(data.get("is_trading_day", False)),
            is_market_open=bool(data.get("is_market_open", False)),
            is_trading_hours=bool(data.get("is_trading_hours", False)),
            ebdks_active=bool(data.get("ebdks_active", False)),
            active_circuit_breakers=list(data.get("active_circuit_breakers", [])),
            ebdks_triggered_count=int(data.get("ebdks_triggered_count", 0)),
            is_half_day=bool(data.get("is_half_day", False)),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> "MarketSessionStatus":
        """JSON dizgisinden veya baytından orjson ile model oluşturur."""
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Kullanıcı dostu Türkçe metin gösterimi."""
        return (
            f"<MarketSessionStatus faz={self.phase} acik={self.is_market_open} "
            f"surekli_islem={self.is_trading_hours} ebdks={self.ebdks_active} "
            f"aktif_dk={len(self.active_circuit_breakers)}>"
        )


class MarketSessionStateMachine:
    """Borsa İstanbul Pay Piyasası Resmî Seans Durum Makinesi.

    Bu dosya BIST seans saatleri için TEK KAYNAK (single source of truth).
    market_session.py ve market_calendar.py bu dosyayı kullanır.
    Tüm mutable durumlar thread-safe `threading.RLock` ile korunur.
    """

    # Zaman Dilimi
    _TZ_ISTANBUL = _TZ_ISTANBUL

    # Seans Zaman Eşikleri — TAM İŞ GÜNLERİ (Europe/Istanbul)
    T_OPEN_COLL_START = DEFAULT_OPEN_COLL_START
    T_OPEN_DET_START = DEFAULT_OPEN_DET_START
    T_CONT_START = DEFAULT_CONT_START
    T_CONT_END = DEFAULT_CONT_END
    T_CLOSE_COLL_START = DEFAULT_CLOSE_COLL_START
    T_CLOSE_DET_START = DEFAULT_CLOSE_DET_START
    T_CLOSE_TRADE_START = DEFAULT_CLOSE_TRADE_START
    T_CLOSE_TRADE_END = DEFAULT_CLOSE_TRADE_END

    # Seans Zaman Eşikleri — YARIM İŞ GÜNLERİ (Resmi Tatil Arifeleri)
    HALF_T_CONT_END = DEFAULT_HALF_CONT_END
    HALF_T_CLOSE_COLL_START = DEFAULT_HALF_CLOSE_COLL_START
    HALF_T_CLOSE_DET_START = DEFAULT_HALF_CLOSE_DET_START
    HALF_T_CLOSE_TRADE_START = DEFAULT_HALF_CLOSE_TRADE_START
    HALF_T_CLOSE_TRADE_END = DEFAULT_HALF_CLOSE_TRADE_END

    # Devre kesici sabitleri (Ağustos 2025 güncel)
    CIRCUIT_BREAKER_DURATION_MINUTES = DEFAULT_CIRCUIT_BREAKER_DURATION_MINUTES
    EBDKS_THRESHOLD_PCT = DEFAULT_EBDKS_THRESHOLD_PCT

    # EBDKS durdurma süreleri — özellik koduna göre farklılaştırılmış (Ağustos 2025)
    EBDKS_DURATION_BY_FEATURE = {
        "E": 10,
        "F1": 10,
        "F2": 10,
        "S1": 10,
        "G": 10,
        "V": 20,
        "C": 20,
        "F": 20,
        "R": 20,
        "BE": 20,
        "AOF": 20,
    }
    EBDKS_DEFAULT_DURATION = DEFAULT_EBDKS_DEFAULT_DURATION

    # EBDKS geç seans kuralı: 17:30'dan sonra tetiklenirse kapanış seansı ile yeniden başlatılır
    EBDKS_LATE_SESSION_CUTOFF = DEFAULT_EBDKS_LATE_SESSION_CUTOFF

    # Pay bazında devre kesici eşikleri (Ağustos 2025 güncel)
    CIRCUIT_BREAKER_THRESHOLDS = {
        "yildiz": [5.0, 10.0, 15.0],
        "ana": [5.0, 10.0, 15.0],
        "alt": [5.0, 10.0],
    }

    def __init__(
        self,
        holidays: set[str] | None = None,
        half_days: set[str] | None = None,
    ) -> None:
        """Seans durum makinesini başlatır ve tatil/yarım gün listelerini yapılandırır.

        Args:
            holidays: YYYY-MM-DD formatında resmi tatil günleri kümesi.
            half_days: YYYY-MM-DD formatında yarım iş günleri kümesi.
        """
        self._lock = threading.RLock()
        self._holidays: set[str] = self._normalize_date_set(holidays)
        self._half_days: set[str] = self._normalize_date_set(half_days)
        self._circuit_breaker_active: dict[str, datetime] = {}  # Ticker -> Bitiş zamanı
        self._ebdks_active: datetime | None = None  # Endekse bağlı devre kesici bitiş zamanı
        self._ebdks_triggered_at: datetime | None = None  # EBDKS tetiklenme anı
        self._ebdks_triggered_count: int = 0  # Bugün kaç kez tetiklendiği
        self._ebdks_last_date: str | None = None  # Günlük sayaç sıfırlama takibi

    @staticmethod
    def _normalize_date_set(dates: Any) -> set[str]:
        """Verilen tarih koleksiyonunu YYYY-MM-DD formatında set[str] yapısına dönüştürür."""
        if not dates:
            return set()
        normalized: set[str] = set()
        for d in dates:
            if isinstance(d, (date, datetime)):
                normalized.add(d.strftime("%Y-%m-%d"))
            elif isinstance(d, str):
                normalized.add(d.strip())
            else:
                normalized.add(str(d).strip())
        return normalized

    def now_istanbul(self) -> datetime:
        """İstanbul yerel zamanını (Europe/Istanbul, UTC+3) döndürür.

        Returns:
            Timezone-aware datetime nesnesi.
        """
        return datetime.now(_TZ_ISTANBUL)

    def set_holidays(self, holidays: Any) -> None:
        """Tatil günlerini günceller.

        Args:
            holidays: Tarih veya metin koleksiyonu.
        """
        with self._lock:
            self._holidays = self._normalize_date_set(holidays)
            logger.info("BIST Tatil Günleri Güncellendi", adet=len(self._holidays))

    def set_half_days(self, half_days: Any) -> None:
        """Yarım gün tarihlerini günceller.

        Args:
            half_days: Tarih veya metin koleksiyonu.
        """
        with self._lock:
            self._half_days = self._normalize_date_set(half_days)
            logger.info("BIST Yarım Günleri Güncellendi", adet=len(self._half_days))

    def _ensure_tz(self, dt: datetime) -> datetime:
        """Tarih nesnesinin timezone-aware olmasını sağlar, naive ise Istanbul TZ ekler."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_TZ_ISTANBUL)
        return dt.astimezone(_TZ_ISTANBUL)

    def _cleanup_expired_circuit_breakers(self, now: datetime) -> None:
        """Süresi dolmuş hisse bazlı devre kesicileri bellekten temizler (memory leak koruması)."""
        expired = [t for t, exp in self._circuit_breaker_active.items() if now >= exp]
        for t in expired:
            self._circuit_breaker_active.pop(t, None)
            logger.info("Devre Kesici Süresi Doldu ve Temizlendi", ticker=t)

    def _check_and_reset_ebdks_daily(self, now: datetime) -> None:
        """Günün değişip değişmediğini kontrol ederek günlük EBDKS sayacını sıfırlar."""
        today_str = now.strftime("%Y-%m-%d")
        if self._ebdks_last_date != today_str:
            self._ebdks_triggered_count = 0
            self._ebdks_last_date = today_str

    @otel_trace("fsm.trigger_circuit_breaker")
    def trigger_circuit_breaker(self, ticker: str, duration_minutes: int | None = None) -> None:
        """Hisse bazında devre kesici çağrı seansı başlatır.

        Args:
            ticker: Hisse sembolü (örn. "THYAO").
            duration_minutes: Emir toplama süresi (dakika). Belirtilmezse varsayılan 10 dk.

        Raises:
            ValueError: Ticker boş veya süre pozitif tam sayı değilse.
        """
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("Geçersiz hisse kodu: ticker boş veya tanımsız olamaz.")

        clean_ticker = ticker.strip().upper()
        dur = duration_minutes if duration_minutes is not None else self.CIRCUIT_BREAKER_DURATION_MINUTES
        if dur <= 0:
            raise ValueError(f"Devre kesici süresi pozitif olmalıdır, girilen: {dur}")

        with self._lock:
            now = self.now_istanbul()
            expiry = now + timedelta(minutes=dur)
            self._circuit_breaker_active[clean_ticker] = expiry
            logger.warning(
                "BIST Pay Bazında Devre Kesici Tetiklendi",
                ticker=clean_ticker,
                expiry=expiry.isoformat(),
                duration_min=dur,
            )

    @otel_trace("fsm.trigger_ebdks")
    def trigger_ebdks(self, feature_code: str | None = None) -> None:
        """Endekse bağlı devre kesici (EBDKS) başlatır.

        BIST-100 %6 veya daha fazla düşüşte tetiklenir (Ağustos 2025: tek aşamalı).
        Tüm Pay Piyasası ve VİOP pay sözleşmelerinde işlemler durdurulur.

        Özellik koduna göre süre farklılaştırılmıştır:
        - .E, .F1, .F2, .S1, .G → 10 dakika
        - .V, .C, .F, .R, .BE, .AOF → 20 dakika
        - VİOP → 20 dakika

        Geç seans kuralı: 17:30'dan sonra tetiklenirse kapanış seansı ile yeniden başlatılır.

        Args:
            feature_code: BIST özellik kodu (örn. "E", "F1", "V").
        """
        clean_feature = feature_code.strip().upper() if feature_code else None

        with self._lock:
            now = self.now_istanbul()
            self._check_and_reset_ebdks_daily(now)

            if clean_feature:
                duration = self.EBDKS_DURATION_BY_FEATURE.get(clean_feature, self.EBDKS_DEFAULT_DURATION)
            else:
                duration = self.EBDKS_DEFAULT_DURATION

            expiry = now + timedelta(minutes=duration)
            self._ebdks_active = expiry
            self._ebdks_triggered_at = now
            self._ebdks_triggered_count += 1

            late_session = now.time() >= self.EBDKS_LATE_SESSION_CUTOFF
            logger.warning(
                "BIST EBDKS Tetiklendi",
                expiry=expiry.isoformat(),
                duration_min=duration,
                feature_code=clean_feature,
                count_today=self._ebdks_triggered_count,
                late_session_rule=late_session,
            )

    @otel_trace("fsm.clear_circuit_breaker")
    def clear_circuit_breaker(self, ticker: str) -> None:
        """Hisse bazında aktif devre kesiciyi sonlandırır ve kaydı temizler.

        Args:
            ticker: Hisse sembolü.
        """
        if not ticker or not isinstance(ticker, str):
            return
        clean_ticker = ticker.strip().upper()
        with self._lock:
            if clean_ticker in self._circuit_breaker_active:
                self._circuit_breaker_active.pop(clean_ticker, None)
                logger.info("Devre Kesici Manuel Temizlendi", ticker=clean_ticker)

    @otel_trace("fsm.clear_ebdks")
    def clear_ebdks(self) -> None:
        """Aktif endekse bağlı devre kesiciyi (EBDKS) sonlandırır ve temizler."""
        with self._lock:
            self._ebdks_active = None
            self._ebdks_triggered_at = None
            logger.info("BIST EBDKS Manuel Temizlendi")

    def is_ebdks_active(self) -> bool:
        """Endekse bağlı devre kesici aktif mi?

        Returns:
            EBDKS devam ediyorsa True, aksi halde False.
        """
        with self._lock:
            if self._ebdks_active is None:
                return False
            now = self.now_istanbul()
            if now >= self._ebdks_active:
                self._ebdks_active = None
                return False
            return True

    def is_ebdks_late_session(self) -> bool:
        """EBDKS geç seans kuralı uygulanmalı mı?

        17:30'dan sonra EBDKS tetiklenirse kapanış seansı ile yeniden başlatılır.

        Returns:
            Geç seans kuralı geçerliyse True, aksi halde False.
        """
        with self._lock:
            if self._ebdks_triggered_at is None:
                return False
            return self._ebdks_triggered_at.time() >= self.EBDKS_LATE_SESSION_CUTOFF

    def is_circuit_breaker_active(self, ticker: str) -> bool:
        """Belirtilen hisse için devre kesici aktif mi kontrol eder.

        Args:
            ticker: Hisse sembolü.

        Returns:
            Aktifse True, aksi halde False.
        """
        if not ticker or not isinstance(ticker, str):
            return False
        clean_ticker = ticker.strip().upper()
        with self._lock:
            now = self.now_istanbul()
            self._cleanup_expired_circuit_breakers(now)
            return clean_ticker in self._circuit_breaker_active

    def get_circuit_breaker_remaining(self, ticker: str) -> float:
        """Hisse bazında devre kesicinin kalan süresini saniye cinsinden döndürür.

        Args:
            ticker: Hisse sembolü.

        Returns:
            Kalan süre (saniye). Aktif değilse 0.0.
        """
        if not ticker or not isinstance(ticker, str):
            return 0.0
        clean_ticker = ticker.strip().upper()
        with self._lock:
            now = self.now_istanbul()
            expiry = self._circuit_breaker_active.get(clean_ticker)
            if not expiry or now >= expiry:
                return 0.0
            return max(0.0, (expiry - now).total_seconds())

    def get_ebdks_remaining(self) -> float:
        """EBDKS için kalan süreyi saniye cinsinden döndürür.

        Returns:
            Kalan süre (saniye). Aktif değilse 0.0.
        """
        with self._lock:
            if self._ebdks_active is None:
                return 0.0
            now = self.now_istanbul()
            if now >= self._ebdks_active:
                self._ebdks_active = None
                return 0.0
            return max(0.0, (self._ebdks_active - now).total_seconds())

    def get_active_circuit_breakers(self) -> dict[str, dict[str, Any]]:
        """Şu anda aktif olan hisse bazlı devre kesicilerin detaylarını döndürür.

        Returns:
            {ticker: {"expires_at": ISO8601, "remaining_seconds": float}} sözlüğü.
        """
        with self._lock:
            now = self.now_istanbul()
            self._cleanup_expired_circuit_breakers(now)
            result: dict[str, dict[str, Any]] = {}
            for t, exp in self._circuit_breaker_active.items():
                rem = max(0.0, (exp - now).total_seconds())
                result[t] = {
                    "expires_at": exp.isoformat(),
                    "remaining_seconds": rem,
                }
            return result

    @otel_trace("fsm.get_phase")
    def get_phase(
        self,
        ticker: str | None = None,
        current_time: datetime | None = None,
    ) -> BISTMarketPhase:
        """Belirtilen an ve hisse için güncel seans fazını belirler.

        Yarım günlerde (resmi tatil arifeleri) seans 12:30'da sürekli müzayededen çıkar.

        Args:
            ticker: İsteğe bağlı hisse sembolü (devre kesici kontrolü için).
            current_time: İsteğe bağlı zaman damgası (belirtilmezse şu anki İstanbul saati).

        Returns:
            BISTMarketPhase seans fazı enum değeri.
        """
        with self._lock:
            raw_dt = current_time or self.now_istanbul()
            dt = self._ensure_tz(raw_dt)
            self._check_and_reset_ebdks_daily(dt)
            if current_time is None:
                self._cleanup_expired_circuit_breakers(self.now_istanbul())

            # Hafta sonu veya resmi tatil kontrolü
            date_str = dt.strftime("%Y-%m-%d")
            if dt.weekday() >= 5 or date_str in self._holidays:
                return BISTMarketPhase.CLOSED

            # EBDKS kontrolü (tüm piyasayı etkiler)
            if self.is_ebdks_active():
                return BISTMarketPhase.CIRCUIT_BREAKER_AUCTION

            # Hisse bazlı devre kesici kontrolü
            if ticker:
                clean_ticker = ticker.strip().upper()
                if clean_ticker in self._circuit_breaker_active:
                    if dt < self._circuit_breaker_active[clean_ticker]:
                        return BISTMarketPhase.CIRCUIT_BREAKER_AUCTION
                    elif current_time is None:
                        self.clear_circuit_breaker(clean_ticker)

            t = dt.time()
            is_half_day = date_str in self._half_days

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

    def is_order_entry_allowed(self, phase: BISTMarketPhase | None = None) -> bool:
        """Verilen veya anlık seans fazında emir kabul edilip edilmediğini kontrol eder.

        Args:
            phase: İsteğe bağlı faz değeri. Belirtilmezse anlık faz kullanılır.

        Returns:
            Emir kabul ediliyorsa True, aksi halde False.
        """
        current_phase = phase if phase is not None else self.get_phase()
        return current_phase in {
            BISTMarketPhase.OPENING_AUCTION_COLLECTION,
            BISTMarketPhase.CONTINUOUS_AUCTION,
            BISTMarketPhase.CIRCUIT_BREAKER_AUCTION,
            BISTMarketPhase.CLOSING_AUCTION_COLLECTION,
            BISTMarketPhase.CLOSING_PRICE_TRADING,
        }

    def is_matching_active(self, phase: BISTMarketPhase | None = None) -> bool:
        """Verilen veya anlık seans fazında emir eşleşmesinin yapılıp yapılmadığını kontrol eder.

        Args:
            phase: İsteğe bağlı faz değeri. Belirtilmezse anlık faz kullanılır.

        Returns:
            Eşleşme aktifse True, aksi halde False.
        """
        current_phase = phase if phase is not None else self.get_phase()
        return current_phase in {
            BISTMarketPhase.OPENING_AUCTION_DETERMINATION,
            BISTMarketPhase.CONTINUOUS_AUCTION,
            BISTMarketPhase.CLOSING_AUCTION_DETERMINATION,
            BISTMarketPhase.CLOSING_PRICE_TRADING,
        }

    def is_trading_hours(self) -> bool:
        """Piyasanın sürekli müzayede (normal işlem saatleri) fazında olup olmadığını bildirir.

        Returns:
            Sürekli müzayede aktifse True, aksi halde False.
        """
        return self.get_phase() == BISTMarketPhase.CONTINUOUS_AUCTION

    def is_market_open(self) -> bool:
        """Piyasanın açık (emir kabul edilen herhangi bir fazda) olup olmadığını bildirir.

        Returns:
            Emir kabul ediliyorsa True, aksi halde False.
        """
        phase = self.get_phase()
        return self.is_order_entry_allowed(phase)

    def is_closed(self) -> bool:
        """Piyasanın tamamen kapalı olup olmadığını bildirir.

        Returns:
            Piyasa kapalıysa True, aksi halde False.
        """
        return self.get_phase() == BISTMarketPhase.CLOSED

    def get_time_until_next_phase(self, current_time: datetime | None = None) -> float:
        """Bir sonraki seans fazı geçişine kalan süreyi saniye cinsinden hesaplar.

        Args:
            current_time: Referans zaman. Belirtilmezse anlık İstanbul saati.

        Returns:
            Kalan saniye (float).
        """
        with self._lock:
            raw_dt = current_time or self.now_istanbul()
            dt = self._ensure_tz(raw_dt)
            date_str = dt.strftime("%Y-%m-%d")
            is_half = date_str in self._half_days
            t = dt.time()

            # Schedule eşik zamanları
            if is_half:
                thresholds = [
                    self.T_OPEN_COLL_START,
                    self.T_OPEN_DET_START,
                    self.T_CONT_START,
                    self.HALF_T_CONT_END,
                    self.HALF_T_CLOSE_COLL_START,
                    self.HALF_T_CLOSE_DET_START,
                    self.HALF_T_CLOSE_TRADE_START,
                    self.HALF_T_CLOSE_TRADE_END,
                ]
            else:
                thresholds = [
                    self.T_OPEN_COLL_START,
                    self.T_OPEN_DET_START,
                    self.T_CONT_START,
                    self.T_CONT_END,
                    self.T_CLOSE_COLL_START,
                    self.T_CLOSE_DET_START,
                    self.T_CLOSE_TRADE_START,
                    self.T_CLOSE_TRADE_END,
                ]

            for thresh in thresholds:
                if t < thresh:
                    target_dt = dt.replace(
                        hour=thresh.hour,
                        minute=thresh.minute,
                        second=thresh.second,
                        microsecond=0,
                    )
                    return max(0.0, (target_dt - dt).total_seconds())

            # Günün tüm seansları bittiyse ertesi gün açılışına kadar olan süre
            tomorrow = (dt + timedelta(days=1)).replace(
                hour=self.T_OPEN_COLL_START.hour,
                minute=self.T_OPEN_COLL_START.minute,
                second=0,
                microsecond=0,
            )
            return max(0.0, (tomorrow - dt).total_seconds())

    @otel_trace("fsm.get_status")
    def get_status(self) -> dict[str, Any]:
        """Piyasa seans durum özetini sözlük yapısında döndürür.

        Returns:
            Seans durumu, faz, açık devre kesiciler ve EBDKS bilgilerini içeren sözlük.
        """
        model = self.get_status_model()
        return model.to_dict()

    def get_status_model(self) -> MarketSessionStatus:
        """Piyasa seans durumunu tip güvenli `MarketSessionStatus` modeli olarak döndürür.

        Returns:
            MarketSessionStatus veri nesnesi.
        """
        with self._lock:
            now = self.now_istanbul()
            phase = self.get_phase(current_time=now)
            date_str = now.strftime("%Y-%m-%d")
            is_half = date_str in self._half_days
            is_trad_day = now.weekday() < 5 and date_str not in self._holidays
            active_cbs = list(self.get_active_circuit_breakers().keys())

            return MarketSessionStatus(
                phase=phase.value,
                istanbul_time=now.isoformat(),
                weekday=now.strftime("%A"),
                is_trading_day=is_trad_day,
                is_market_open=self.is_order_entry_allowed(phase),
                is_trading_hours=phase == BISTMarketPhase.CONTINUOUS_AUCTION,
                ebdks_active=self.is_ebdks_active(),
                active_circuit_breakers=active_cbs,
                ebdks_triggered_count=self._ebdks_triggered_count,
                is_half_day=is_half,
            )

    def export_schedule_to_polars(self, is_half_day: bool = False) -> pl.DataFrame:
        """BIST seans çizelgesini Polars DataFrame olarak dışa aktarır.

        Args:
            is_half_day: Yarım iş günü çizelgesi mi aktarılacak.

        Returns:
            Katı tip şemasıyla oluşturulmuş Polars DataFrame.
        """
        schema = {
            "phase": pl.Utf8,
            "start_time": pl.Utf8,
            "end_time": pl.Utf8,
            "order_entry_allowed": pl.Boolean,
            "matching_active": pl.Boolean,
            "is_half_day": pl.Boolean,
        }

        if is_half_day:
            rows = [
                ("CLOSED", "00:00", "09:40", False, False, True),
                ("OPENING_AUCTION_COLLECTION", "09:40", "09:55", True, False, True),
                ("OPENING_AUCTION_DETERMINATION", "09:55", "10:00", False, True, True),
                ("CONTINUOUS_AUCTION", "10:00", "12:30", True, True, True),
                ("CLOSED", "12:30", "12:31", False, False, True),
                ("CLOSING_AUCTION_COLLECTION", "12:31", "12:35", True, False, True),
                ("CLOSING_AUCTION_DETERMINATION", "12:35", "12:37", False, True, True),
                ("CLOSING_PRICE_TRADING", "12:37", "12:40", True, True, True),
                ("CLOSED", "12:40", "23:59", False, False, True),
            ]
        else:
            rows = [
                ("CLOSED", "00:00", "09:40", False, False, False),
                ("OPENING_AUCTION_COLLECTION", "09:40", "09:55", True, False, False),
                ("OPENING_AUCTION_DETERMINATION", "09:55", "10:00", False, True, False),
                ("CONTINUOUS_AUCTION", "10:00", "18:00", True, True, False),
                ("CLOSED", "18:00", "18:01", False, False, False),
                ("CLOSING_AUCTION_COLLECTION", "18:01", "18:05", True, False, False),
                ("CLOSING_AUCTION_DETERMINATION", "18:05", "18:07", False, True, False),
                ("CLOSING_PRICE_TRADING", "18:08", "18:10", True, True, False),
                ("CLOSED", "18:10", "23:59", False, False, False),
            ]

        data = {
            "phase": [r[0] for r in rows],
            "start_time": [r[1] for r in rows],
            "end_time": [r[2] for r in rows],
            "order_entry_allowed": [r[3] for r in rows],
            "matching_active": [r[4] for r in rows],
            "is_half_day": [r[5] for r in rows],
        }
        return pl.DataFrame(data, schema=schema)

    def export_active_circuit_breakers_to_polars(self) -> pl.DataFrame:
        """Aktif devre kesicileri Polars DataFrame olarak dışa aktarır.

        Returns:
            Polars DataFrame (ticker, expires_at, remaining_seconds).
        """
        active = self.get_active_circuit_breakers()
        schema = {
            "ticker": pl.Utf8,
            "expires_at": pl.Utf8,
            "remaining_seconds": pl.Float64,
        }
        if not active:
            return pl.DataFrame(schema=schema)

        data = {
            "ticker": list(active.keys()),
            "expires_at": [v["expires_at"] for v in active.values()],
            "remaining_seconds": [v["remaining_seconds"] for v in active.values()],
        }
        return pl.DataFrame(data, schema=schema)

    def export_session_status_to_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_session_status_log",
    ) -> int:
        """Anlık seans durumunu DuckDB tablosuna denetim amacıyla kaydeder.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            table_name: Hedef tablo adı.

        Returns:
            Eklenen satır sayısı (1).
        """
        status = self.get_status_model()
        target_path = Path(db_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists() and target_path.stat().st_size == 0:
            target_path.unlink()

        conn = duckdb.connect(str(target_path))
        try:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    istanbul_time VARCHAR,
                    phase VARCHAR,
                    weekday VARCHAR,
                    is_trading_day BOOLEAN,
                    is_market_open BOOLEAN,
                    is_trading_hours BOOLEAN,
                    ebdks_active BOOLEAN,
                    active_cbs_count INTEGER,
                    ebdks_triggered_count INTEGER,
                    is_half_day BOOLEAN,
                    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                f"""
                INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
                """,
                [
                    status.istanbul_time,
                    status.phase,
                    status.weekday,
                    status.is_trading_day,
                    status.is_market_open,
                    status.is_trading_hours,
                    status.ebdks_active,
                    len(status.active_circuit_breakers),
                    status.ebdks_triggered_count,
                    status.is_half_day,
                ],
            )
            return 1
        finally:
            conn.close()

    def query_session_status_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_session_status_log",
        limit: int = 50,
    ) -> pl.DataFrame:
        """DuckDB'den seans durumu denetim geçmişini Polars DataFrame olarak sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame.
        """
        target_path = Path(db_path)
        schema_dict = {
            "istanbul_time": pl.Utf8,
            "phase": pl.Utf8,
            "weekday": pl.Utf8,
            "is_trading_day": pl.Boolean,
            "is_market_open": pl.Boolean,
            "is_trading_hours": pl.Boolean,
            "ebdks_active": pl.Boolean,
            "active_cbs_count": pl.Int32,
            "ebdks_triggered_count": pl.Int32,
            "is_half_day": pl.Boolean,
            "logged_at": pl.Datetime,
        }

        if not target_path.exists():
            return pl.DataFrame(schema=schema_dict)

        if target_path.stat().st_size == 0:
            target_path.unlink()
            return pl.DataFrame(schema=schema_dict)

        conn = duckdb.connect(str(target_path), read_only=True)
        try:
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [table_name],
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(schema=schema_dict)

            arrow_table = conn.execute(
                f"SELECT * FROM {table_name} ORDER BY logged_at DESC LIMIT {int(limit)}"
            ).fetch_arrow_table()
            return pl.from_arrow(arrow_table)
        finally:
            conn.close()

    def __repr__(self) -> str:
        """Nesnenin açıklayıcı Türkçe metin gösterimi."""
        status = self.get_status_model()
        return (
            f"<MarketSessionStateMachine faz={status.phase} acik={status.is_market_open} "
            f"tatil_sayisi={len(self._holidays)} yarim_gun_sayisi={len(self._half_days)} "
            f"ebdks={status.ebdks_active}>"
        )


# Singleton Örnek
bist_session_fsm = MarketSessionStateMachine()


# --- Modül Seviyesinde Kolaylık Fonksiyonları ---

def get_phase(ticker: str | None = None, current_time: datetime | None = None) -> BISTMarketPhase:
    """Mevcut seans fazını döndürür."""
    return bist_session_fsm.get_phase(ticker=ticker, current_time=current_time)


def is_market_open() -> bool:
    """Piyasanın emir girişine açık olup olmadığını döndürür."""
    return bist_session_fsm.is_market_open()


def is_trading_hours() -> bool:
    """Piyasanın sürekli müzayede fazında olup olmadığını döndürür."""
    return bist_session_fsm.is_trading_hours()


def is_order_entry_allowed(phase: BISTMarketPhase | None = None) -> bool:
    """Emir kabul fazı kontrolü yapar."""
    return bist_session_fsm.is_order_entry_allowed(phase)


def is_matching_active(phase: BISTMarketPhase | None = None) -> bool:
    """Eşleşme fazı kontrolü yapar."""
    return bist_session_fsm.is_matching_active(phase)


def is_closed() -> bool:
    """Piyasanın kapalı olup olmadığını döndürür."""
    return bist_session_fsm.is_closed()


def is_ebdks_active() -> bool:
    """EBDKS durumunu döndürür."""
    return bist_session_fsm.is_ebdks_active()


def is_ebdks_late_session() -> bool:
    """EBDKS geç seans kuralını kontrol eder."""
    return bist_session_fsm.is_ebdks_late_session()


def trigger_circuit_breaker(ticker: str, duration_minutes: int | None = None) -> None:
    """Hisse bazında devre kesici tetikler."""
    bist_session_fsm.trigger_circuit_breaker(ticker, duration_minutes)


def clear_circuit_breaker(ticker: str) -> None:
    """Hisse bazında devre kesiciyi temizler."""
    bist_session_fsm.clear_circuit_breaker(ticker)


def trigger_ebdks(feature_code: str | None = None) -> None:
    """EBDKS tetikler."""
    bist_session_fsm.trigger_ebdks(feature_code)


def clear_ebdks() -> None:
    """EBDKS durumunu temizler."""
    bist_session_fsm.clear_ebdks()


def get_session_status() -> dict[str, Any]:
    """Piyasa durum özetini döndürür."""
    return bist_session_fsm.get_status()


def get_session_status_model() -> MarketSessionStatus:
    """Piyasa durumunu tip güvenli model olarak döndürür."""
    return bist_session_fsm.get_status_model()


def get_active_circuit_breakers() -> dict[str, dict[str, Any]]:
    """Aktif devre kesicileri döndürür."""
    return bist_session_fsm.get_active_circuit_breakers()


def get_time_until_next_phase(current_time: datetime | None = None) -> float:
    """Bir sonraki seans fazına kalan süreyi saniye cinsinden döndürür."""
    return bist_session_fsm.get_time_until_next_phase(current_time)


def export_schedule_to_polars(is_half_day: bool = False) -> pl.DataFrame:
    """Seans takvimini Polars DataFrame olarak döndürür."""
    return bist_session_fsm.export_schedule_to_polars(is_half_day)


def export_active_circuit_breakers_to_polars() -> pl.DataFrame:
    """Aktif devre kesicileri Polars DataFrame olarak döndürür."""
    return bist_session_fsm.export_active_circuit_breakers_to_polars()


def export_session_status_to_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_session_status_log",
) -> int:
    """Anlık seans durumunu DuckDB tablosuna kaydeder."""
    return bist_session_fsm.export_session_status_to_duckdb(db_path, table_name)


def query_session_status_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_session_status_log",
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB'den seans durum loglarını sorgular."""
    return bist_session_fsm.query_session_status_duckdb(db_path, table_name, limit)


__all__ = [
    "_TZ_ISTANBUL",
    "BISTMarketPhase",
    "MarketSessionStatus",
    "MarketSessionStateMachine",
    "bist_session_fsm",
    "otel_trace",
    "DEFAULT_OPEN_COLL_START",
    "DEFAULT_OPEN_DET_START",
    "DEFAULT_CONT_START",
    "DEFAULT_CONT_END",
    "DEFAULT_CLOSE_COLL_START",
    "DEFAULT_CLOSE_DET_START",
    "DEFAULT_CLOSE_TRADE_START",
    "DEFAULT_CLOSE_TRADE_END",
    "DEFAULT_HALF_CONT_END",
    "DEFAULT_HALF_CLOSE_COLL_START",
    "DEFAULT_HALF_CLOSE_DET_START",
    "DEFAULT_HALF_CLOSE_TRADE_START",
    "DEFAULT_HALF_CLOSE_TRADE_END",
    "DEFAULT_CIRCUIT_BREAKER_DURATION_MINUTES",
    "DEFAULT_EBDKS_THRESHOLD_PCT",
    "DEFAULT_EBDKS_DEFAULT_DURATION",
    "DEFAULT_EBDKS_LATE_SESSION_CUTOFF",
    "DEFAULT_DUCKDB_PATH",
    "get_phase",
    "is_market_open",
    "is_trading_hours",
    "is_order_entry_allowed",
    "is_matching_active",
    "is_closed",
    "is_ebdks_active",
    "is_ebdks_late_session",
    "trigger_circuit_breaker",
    "clear_circuit_breaker",
    "trigger_ebdks",
    "clear_ebdks",
    "get_session_status",
    "get_session_status_model",
    "get_active_circuit_breakers",
    "get_time_until_next_phase",
    "export_schedule_to_polars",
    "export_active_circuit_breakers_to_polars",
    "export_session_status_to_duckdb",
    "query_session_status_duckdb",
]
