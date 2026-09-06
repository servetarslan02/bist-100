"""ALPHA BIST — Market Session Manager (Wrapper & Legacy Compatibility)

Bu modül `market_session_fsm.py` ve `auto_circuit_breaker.py` servislerine yüksek seviyeli,
thread-safe ve geriye dönük uyumlu bir arayüz sağlar.
BIST işlem seansı saatleri için tek doğruluk kaynağı (single source of truth) `market_session_fsm.py`'dir.
"""

import math
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

from .auto_circuit_breaker import auto_circuit_breaker
from .market_session_fsm import (
    _TZ_ISTANBUL,
    BISTMarketPhase,
    bist_session_fsm,
)

logger = structlog.get_logger(__name__)

# Geçerli pazar tipleri ve endeks tanımları
VALID_MARKET_TYPES = ("yildiz", "ana", "alt")
DEFAULT_MARKET_TYPE = "ana"
DEFAULT_INDEX_TICKER = "BIST-100"
INDEX_TICKERS = ("BIST-100", "BIST100", "XU100", "XU100.IS")
DEFAULT_DUCKDB_PATH = Path("data/market_session_wrapper.duckdb")


class MarketPhase(StrEnum):
    """Eski API uyumluluğu için seans fazı sabitleri.

    Yeni geliştirilen kodlarda doğrudan `BISTMarketPhase` enum'ı kullanılmalıdır.
    String kalıtımı sayesinde hem `MarketPhase.ACTIVE == 'active'` kontrolü
    hem de `isinstance(phase, str)` desteği sunar.
    """

    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    ACTIVE = "active"
    POST_MARKET = "post_market"
    AFTER_HOURS = "after_hours"

    # Geriye dönük uyumluluk takma adları (alias)
    CONTINUOUS = "active"
    CLOSING = "post_market"
    NIGHT = "closed"

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return f"<MarketPhase.{self.name}: '{self.value}'>"


@dataclass(slots=True)
class MarketSessionUpdateResult:
    """Fiyat güncellemesi ve devre kesici denetim sonucu veri modeli.

    Attributes:
        ticker: Hisse veya endeks kodu.
        event: Tetiklenen devre kesici olayı sözlüğü veya None.
        ebdks_active: Endekse bağlı devre kesici aktif mi.
        ebdks_late_session: Geç seans kuralı devrede mi.
        timestamp: Güncelleme zaman damgası (ISO-8601).
    """

    ticker: str
    event: dict[str, Any] | None
    ebdks_active: bool
    ebdks_late_session: bool
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür."""
        return {
            "ticker": self.ticker,
            "event": self.event,
            "ebdks_active": self.ebdks_active,
            "ebdks_late_session": self.ebdks_late_session,
            "timestamp": self.timestamp,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson ile ikili JSON bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def to_json(self) -> str:
        """Modeli JSON dizgisine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketSessionUpdateResult":
        """Sözlük verisinden model nesnesi oluşturur."""
        return cls(
            ticker=str(data.get("ticker", "")),
            event=data.get("event"),
            ebdks_active=bool(data.get("ebdks_active", False)),
            ebdks_late_session=bool(data.get("ebdks_late_session", False)),
            timestamp=str(data.get("timestamp", "")),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> "MarketSessionUpdateResult":
        """JSON dizgisinden model nesnesi oluşturur."""
        return cls.from_dict(orjson.loads(json_str_or_bytes))

    def __repr__(self) -> str:
        """Açıklayıcı Türkçe metin gösterimi."""
        has_evt = self.event is not None
        return (
            f"<MarketSessionUpdateResult ticker={self.ticker} olay_var_mi={has_evt} "
            f"ebdks={self.ebdks_active} zaman={self.timestamp}>"
        )


class MarketSessionManager:
    """BIST piyasa seans yönetimi sarmalayıcısı (wrapper).

    `market_session_fsm.py` ve `auto_circuit_breaker.py` servislerini entegre eder.
    Tüm zaman hesaplamaları Europe/Istanbul (+03:00) zaman dilimindedir.
    Eşzamanlı çağrılar `threading.RLock` ile korunur.
    """

    def __init__(self, holidays: Any = None, half_days: Any = None) -> None:
        """Seans yöneticisini başlatır ve isteğe bağlı tatil/yarım günleri fsm'e aktarır.

        Args:
            holidays: İsteğe bağlı resmi tatil günleri koleksiyonu.
            half_days: İsteğe bağlı yarım iş günleri koleksiyonu.
        """
        self._lock = threading.RLock()
        if holidays:
            bist_session_fsm.set_holidays(holidays)
        if half_days:
            bist_session_fsm.set_half_days(half_days)

    def set_holidays(self, holidays: Any) -> None:
        """Resmi tatil günlerini günceller."""
        with self._lock:
            bist_session_fsm.set_holidays(holidays)

    def set_half_days(self, half_days: Any) -> None:
        """Yarım iş günlerini günceller."""
        with self._lock:
            bist_session_fsm.set_half_days(half_days)

    def now_istanbul(self) -> datetime:
        """İstanbul yerel zamanını (Europe/Istanbul, UTC+3) döndürür.

        Returns:
            Timezone-aware datetime nesnesi.
        """
        return datetime.now(_TZ_ISTANBUL)

    @otel_trace("market_session.current_phase")
    def current_phase(self, current_time: datetime | None = None) -> MarketPhase:
        """Piyasanın anlık veya belirtilen zamandaki durumunu eski API formatında döndürür.

        Args:
            current_time: İsteğe bağlı referans zamanı.

        Returns:
            MarketPhase enum değeri (örn. MarketPhase.ACTIVE, MarketPhase.CLOSED).
        """
        with self._lock:
            phase = bist_session_fsm.get_phase(current_time=current_time)
            mapping = {
                BISTMarketPhase.CLOSED: MarketPhase.CLOSED,
                BISTMarketPhase.OPENING_AUCTION_COLLECTION: MarketPhase.PRE_MARKET,
                BISTMarketPhase.OPENING_AUCTION_DETERMINATION: MarketPhase.PRE_MARKET,
                BISTMarketPhase.CONTINUOUS_AUCTION: MarketPhase.ACTIVE,
                BISTMarketPhase.CIRCUIT_BREAKER_AUCTION: MarketPhase.ACTIVE,
                BISTMarketPhase.CLOSING_AUCTION_COLLECTION: MarketPhase.POST_MARKET,
                BISTMarketPhase.CLOSING_AUCTION_DETERMINATION: MarketPhase.POST_MARKET,
                BISTMarketPhase.CLOSING_PRICE_TRADING: MarketPhase.POST_MARKET,
            }
            return mapping.get(phase, MarketPhase.CLOSED)

    @otel_trace("market_session.is_trading_hours")
    def is_trading_hours(self, current_time: datetime | None = None) -> bool:
        """Piyasanın sürekli müzayede (normal işlem saatleri) fazında olup olmadığını bildirir.

        Args:
            current_time: İsteğe bağlı referans zamanı.

        Returns:
            Sürekli müzayede aktifse True, aksi halde False.
        """
        with self._lock:
            if current_time is not None:
                return bist_session_fsm.get_phase(current_time=current_time) == BISTMarketPhase.CONTINUOUS_AUCTION
            return bist_session_fsm.is_trading_hours()

    @otel_trace("market_session.is_pre_market")
    def is_pre_market(self, current_time: datetime | None = None) -> bool:
        """Açılış seansı (emir toplama veya fiyat belirleme) fazında mı kontrol eder.

        Args:
            current_time: İsteğe bağlı referans zamanı.

        Returns:
            Açılış seansı aktifse True, aksi halde False.
        """
        with self._lock:
            phase = bist_session_fsm.get_phase(current_time=current_time)
            return phase in (
                BISTMarketPhase.OPENING_AUCTION_COLLECTION,
                BISTMarketPhase.OPENING_AUCTION_DETERMINATION,
            )

    @otel_trace("market_session.is_post_market")
    def is_post_market(self, current_time: datetime | None = None) -> bool:
        """Kapanış seansı (emir toplama, fiyat belirleme veya kapanıştan işlem) fazında mı kontrol eder.

        Args:
            current_time: İsteğe bağlı referans zamanı.

        Returns:
            Kapanış seansı aktifse True, aksi halde False.
        """
        with self._lock:
            phase = bist_session_fsm.get_phase(current_time=current_time)
            return phase in (
                BISTMarketPhase.CLOSING_AUCTION_COLLECTION,
                BISTMarketPhase.CLOSING_AUCTION_DETERMINATION,
                BISTMarketPhase.CLOSING_PRICE_TRADING,
            )

    @otel_trace("market_session.is_closed")
    def is_closed(self, current_time: datetime | None = None) -> bool:
        """Piyasanın kapalı olup olmadığını bildirir.

        Args:
            current_time: İsteğe bağlı referans zamanı.

        Returns:
            Piyasa kapalıysa True, aksi halde False.
        """
        with self._lock:
            if current_time is not None:
                return bist_session_fsm.get_phase(current_time=current_time) == BISTMarketPhase.CLOSED
            return bist_session_fsm.is_closed()

    @otel_trace("market_session.is_order_entry_allowed")
    def is_order_entry_allowed(self, current_time: datetime | None = None) -> bool:
        """Anlık veya belirtilen zamanda emir girişine izin verilip verilmediğini kontrol eder.

        Args:
            current_time: İsteğe bağlı referans zamanı.

        Returns:
            Emir girişi mümkünse True, aksi halde False.
        """
        with self._lock:
            phase = bist_session_fsm.get_phase(current_time=current_time)
            return bist_session_fsm.is_order_entry_allowed(phase)

    @otel_trace("market_session.is_matching_active")
    def is_matching_active(self, current_time: datetime | None = None) -> bool:
        """Anlık veya belirtilen zamanda emir eşleşmesinin aktif olup olmadığını kontrol eder.

        Args:
            current_time: İsteğe bağlı referans zamanı.

        Returns:
            Eşleşme aktifse True, aksi halde False.
        """
        with self._lock:
            phase = bist_session_fsm.get_phase(current_time=current_time)
            return bist_session_fsm.is_matching_active(phase)

    @otel_trace("market_session.should_run_trading_job")
    def should_run_trading_job(self, current_time: datetime | None = None) -> bool:
        """İşlem/sipariş botlarının çalıştırılması gereken fazda olup olmadığını bildirir.

        Args:
            current_time: İsteğe bağlı referans zamanı.

        Returns:
            Sürekli müzayede veya açılış emir toplama aktifse True, aksi halde False.
        """
        with self._lock:
            phase = bist_session_fsm.get_phase(current_time=current_time)
            return phase in (
                BISTMarketPhase.CONTINUOUS_AUCTION,
                BISTMarketPhase.OPENING_AUCTION_COLLECTION,
            )

    @otel_trace("market_session.get_status")
    def get_status(self) -> dict[str, Any]:
        """Piyasa ve seans durum özetini sözlük olarak döndürür.

        Returns:
            Seans fazı, İstanbul saati, devre kesici ve tatil durumları sözlüğü.
        """
        return bist_session_fsm.get_status()

    def get_active_circuit_breakers(self) -> dict[str, dict[str, Any]]:
        """Şu anda aktif olan hisse bazlı devre kesicileri döndürür."""
        return bist_session_fsm.get_active_circuit_breakers()

    def get_time_until_next_phase(self, current_time: datetime | None = None) -> float:
        """Bir sonraki seans fazına kalan süreyi saniye cinsinden döndürür."""
        return bist_session_fsm.get_time_until_next_phase(current_time)

    @otel_trace("market_session.update_price")
    def update_price(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
        market_type: str = DEFAULT_MARKET_TYPE,
    ) -> dict[str, Any]:
        """Fiyat güncellemesi gerçekleştirir ve hisse/endeks devre kesici kontrolünü tetikler.

        Args:
            ticker: Hisse kodu veya endeks ("BIST-100", "XU100", "THYAO").
            current_price: Güncel işlem fiyatı.
            reference_price: Referans baz fiyat (önceki gün kapanışı veya baz fiyat).
            market_type: Pazar segmenti ("yildiz", "ana", "alt").

        Returns:
            Güncelleme sonucu ve tetiklenen olay detaylarını içeren sözlük.

        Raises:
            ValueError: Ticker geçersizse veya fiyatlar pozitif sayı değilse.
        """
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("Geçersiz hisse/endeks sembolü: ticker boş olamaz.")

        clean_ticker = ticker.strip().upper()

        if (
            not isinstance(current_price, (int, float))
            or math.isnan(current_price)
            or math.isinf(current_price)
            or current_price <= 0
        ):
            raise ValueError(f"Geçersiz güncel fiyat: {current_price}. Fiyat pozitif bir sayı olmalıdır.")

        if (
            not isinstance(reference_price, (int, float))
            or math.isnan(reference_price)
            or math.isinf(reference_price)
            or reference_price <= 0
        ):
            raise ValueError(f"Geçersiz referans fiyat: {reference_price}. Fiyat pozitif bir sayı olmalıdır.")

        clean_market = market_type.strip().lower() if market_type else DEFAULT_MARKET_TYPE
        if clean_market not in VALID_MARKET_TYPES:
            clean_market = DEFAULT_MARKET_TYPE

        with self._lock:
            try:
                if clean_ticker in INDEX_TICKERS:
                    if reference_price > 0 and math.isfinite(reference_price):
                        auto_circuit_breaker.set_bist100_reference(reference_price)
                    event = auto_circuit_breaker.update_bist100_price(current_price)
                else:
                    # Sonek temizleme (.IS veya .E)
                    norm_ticker = clean_ticker
                    if norm_ticker.endswith(".IS"):
                        norm_ticker = norm_ticker[:-3]
                    elif norm_ticker.endswith(".E"):
                        norm_ticker = norm_ticker[:-2]

                    event = auto_circuit_breaker.check_pay_circuit_breaker(
                        ticker=norm_ticker,
                        current_price=current_price,
                        reference_price=reference_price,
                        market_type=clean_market,
                    )
            except Exception as e:
                logger.error(
                    "Devre kesici fiyat güncellemesinde beklenmeyen hata",
                    ticker=clean_ticker,
                    hata=str(e),
                )
                raise

            event_dict = (
                event.to_dict()
                if hasattr(event, "to_dict")
                else (event if isinstance(event, dict) else None)
            )

            res = MarketSessionUpdateResult(
                ticker=clean_ticker,
                event=event_dict,
                ebdks_active=bist_session_fsm.is_ebdks_active(),
                ebdks_late_session=bist_session_fsm.is_ebdks_late_session(),
                timestamp=self.now_istanbul().isoformat(),
            )
            return res.to_dict()

    def update_price_model(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
        market_type: str = DEFAULT_MARKET_TYPE,
    ) -> MarketSessionUpdateResult:
        """Fiyat günceller ve tip güvenli MarketSessionUpdateResult modeli döndürür."""
        data = self.update_price(
            ticker=ticker,
            current_price=current_price,
            reference_price=reference_price,
            market_type=market_type,
        )
        return MarketSessionUpdateResult.from_dict(data)

    @otel_trace("market_session.reset_daily_circuit_breakers")
    def reset_daily_circuit_breakers(self) -> None:
        """Günlük devre kesici sayaçlarını sıfırlar (gün sonu seans kapanışında çağrılır)."""
        with self._lock:
            auto_circuit_breaker.reset_daily()
            logger.info("Günlük Devre Kesici Sayaçları Sıfırlandı")

    def export_phase_mappings_to_polars(self) -> pl.DataFrame:
        """BISTMarketPhase ile eski MarketPhase arasındaki eşleşmeyi Polars DataFrame olarak dışa aktarır.

        Returns:
            Polars DataFrame (bist_phase, legacy_phase, description).
        """
        rows = [
            ("CLOSED", "closed", "Piyasa kapalı"),
            ("OPENING_AUCTION_COLLECTION", "pre_market", "Açılış seansı emir toplama"),
            ("OPENING_AUCTION_DETERMINATION", "pre_market", "Açılış seansı eşleşme ve fiyat belirleme"),
            ("CONTINUOUS_AUCTION", "active", "Sürekli müzayede işlem seansı"),
            ("CIRCUIT_BREAKER_AUCTION", "active", "Devre kesici çağrı seansı"),
            ("CLOSING_AUCTION_COLLECTION", "post_market", "Kapanış seansı emir toplama"),
            ("CLOSING_AUCTION_DETERMINATION", "post_market", "Kapanış fiyatı belirleme"),
            ("CLOSING_PRICE_TRADING", "post_market", "Kapanış fiyatından işlemler"),
        ]
        schema = {
            "bist_phase": pl.Utf8,
            "legacy_phase": pl.Utf8,
            "description": pl.Utf8,
        }
        data = {
            "bist_phase": [r[0] for r in rows],
            "legacy_phase": [r[1] for r in rows],
            "description": [r[2] for r in rows],
        }
        return pl.DataFrame(data, schema=schema)

    def export_price_update_to_duckdb(
        self,
        update_result: dict[str, Any] | MarketSessionUpdateResult,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_price_update_log",
    ) -> int:
        """Fiyat güncellemesi ve devre kesici denetim sonucunu DuckDB tablosuna kaydeder.

        Args:
            update_result: Güncelleme sonucu modeli veya sözlüğü.
            db_path: DuckDB veritabanı dosya yolu.
            table_name: Hedef tablo adı.

        Returns:
            Eklenen satır sayısı (1).
        """
        if isinstance(update_result, dict):
            res = MarketSessionUpdateResult.from_dict(update_result)
        else:
            res = update_result

        target_path = Path(db_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists() and target_path.stat().st_size == 0:
            target_path.unlink()

        conn = duckdb.connect(str(target_path))
        try:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    ticker VARCHAR,
                    has_event BOOLEAN,
                    event_type VARCHAR,
                    ebdks_active BOOLEAN,
                    ebdks_late_session BOOLEAN,
                    event_payload VARCHAR,
                    timestamp VARCHAR,
                    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            event_dict = (
                res.event
                if isinstance(res.event, dict)
                else (res.event.to_dict() if hasattr(res.event, "to_dict") else None)
            )
            event_type = event_dict.get("event_type", "") if event_dict else None
            payload = (
                orjson.dumps(event_dict, default=str).decode("utf-8")
                if event_dict
                else None
            )

            conn.execute(
                f"""
                INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
                """,
                [
                    res.ticker,
                    res.event is not None,
                    event_type,
                    res.ebdks_active,
                    res.ebdks_late_session,
                    payload,
                    res.timestamp,
                ],
            )
            return 1
        finally:
            conn.close()

    def query_price_updates_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_price_update_log",
        limit: int = 50,
    ) -> pl.DataFrame:
        """DuckDB'den fiyat güncelleme geçmişini Polars DataFrame olarak sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame.
        """
        target_path = Path(db_path)
        schema_dict = {
            "ticker": pl.Utf8,
            "has_event": pl.Boolean,
            "event_type": pl.Utf8,
            "ebdks_active": pl.Boolean,
            "ebdks_late_session": pl.Boolean,
            "event_payload": pl.Utf8,
            "timestamp": pl.Utf8,
            "logged_at": pl.Datetime,
        }

        if not target_path.exists():
            return pl.DataFrame(schema=schema_dict)

        if target_path.stat().st_size == 0:
            target_path.unlink()
            return pl.DataFrame(schema=schema_dict)

        try:
            conn = duckdb.connect(str(target_path), read_only=True)
        except Exception as e:
            logger.warning("DuckDB bağlantısı açılamadı", db_path=str(target_path), hata=str(e))
            return pl.DataFrame(schema=schema_dict)

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
        except Exception as e:
            logger.warning("DuckDB sorgu hatası", tablo=table_name, hata=str(e))
            return pl.DataFrame(schema=schema_dict)
        finally:
            conn.close()

    def __repr__(self) -> str:
        """Nesnenin açıklayıcı Türkçe metin gösterimi."""
        phase = self.current_phase()
        return (
            f"<MarketSessionManager faz={phase.value} acik_mi={not self.is_closed()} "
            f"surekli_islem={self.is_trading_hours()}>"
        )


# Singleton Örnek (Geriye Uyumluluk)
market_session = MarketSessionManager()


# --- Modül Seviyesinde Kolaylık Fonksiyonları ---

def current_phase(current_time: datetime | None = None) -> MarketPhase:
    """Piyasanın şu anki fazını döndürür."""
    return market_session.current_phase(current_time=current_time)


def is_trading_hours(current_time: datetime | None = None) -> bool:
    """Sürekli müzayede işlem saati mi kontrol eder."""
    return market_session.is_trading_hours(current_time=current_time)


def is_pre_market(current_time: datetime | None = None) -> bool:
    """Açılış seansı mı kontrol eder."""
    return market_session.is_pre_market(current_time=current_time)


def is_post_market(current_time: datetime | None = None) -> bool:
    """Kapanış seansı mı kontrol eder."""
    return market_session.is_post_market(current_time=current_time)


def is_closed(current_time: datetime | None = None) -> bool:
    """Piyasa kapalı mı kontrol eder."""
    return market_session.is_closed(current_time=current_time)


def is_order_entry_allowed(current_time: datetime | None = None) -> bool:
    """Emir girişi yapılabilir mi kontrol eder."""
    return market_session.is_order_entry_allowed(current_time=current_time)


def is_matching_active(current_time: datetime | None = None) -> bool:
    """Eşleşme aktif mi kontrol eder."""
    return market_session.is_matching_active(current_time=current_time)


def should_run_trading_job(current_time: datetime | None = None) -> bool:
    """İşlem robotları çalıştırılmalı mı kontrol eder."""
    return market_session.should_run_trading_job(current_time=current_time)


def get_status() -> dict[str, Any]:
    """Piyasa durum özetini döndürür."""
    return market_session.get_status()


def get_active_circuit_breakers() -> dict[str, dict[str, Any]]:
    """Aktif hisse bazlı devre kesicileri döndürür."""
    return market_session.get_active_circuit_breakers()


def get_time_until_next_phase(current_time: datetime | None = None) -> float:
    """Bir sonraki seans fazına kalan süreyi saniye cinsinden döndürür."""
    return market_session.get_time_until_next_phase(current_time)


def update_price(
    ticker: str,
    current_price: float,
    reference_price: float,
    market_type: str = DEFAULT_MARKET_TYPE,
) -> dict[str, Any]:
    """Fiyat günceller ve devre kesici denetler."""
    return market_session.update_price(
        ticker=ticker,
        current_price=current_price,
        reference_price=reference_price,
        market_type=market_type,
    )


def update_price_model(
    ticker: str,
    current_price: float,
    reference_price: float,
    market_type: str = DEFAULT_MARKET_TYPE,
) -> MarketSessionUpdateResult:
    """Fiyat günceller ve tip güvenli MarketSessionUpdateResult modeli döndürür."""
    return market_session.update_price_model(
        ticker=ticker,
        current_price=current_price,
        reference_price=reference_price,
        market_type=market_type,
    )


def reset_daily_circuit_breakers() -> None:
    """Günlük devre kesici sayaçlarını sıfırlar."""
    market_session.reset_daily_circuit_breakers()


def get_market_session_manager() -> MarketSessionManager:
    """Singleton MarketSessionManager nesnesini döndürür."""
    return market_session


def export_phase_mappings_to_polars() -> pl.DataFrame:
    """Faz eşleşmelerini Polars DataFrame olarak döndürür."""
    return market_session.export_phase_mappings_to_polars()


def export_price_update_to_duckdb(
    update_result: dict[str, Any] | MarketSessionUpdateResult,
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_price_update_log",
) -> int:
    """Fiyat güncelleme logunu DuckDB'ye kaydeder."""
    return market_session.export_price_update_to_duckdb(update_result, db_path, table_name)


def query_price_updates_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_price_update_log",
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB'den fiyat güncelleme loglarını sorgular."""
    return market_session.query_price_updates_duckdb(db_path, table_name, limit)


__all__ = [
    "MarketPhase",
    "MarketSessionManager",
    "MarketSessionUpdateResult",
    "market_session",
    "otel_trace",
    "VALID_MARKET_TYPES",
    "DEFAULT_MARKET_TYPE",
    "DEFAULT_INDEX_TICKER",
    "INDEX_TICKERS",
    "DEFAULT_DUCKDB_PATH",
    "current_phase",
    "is_trading_hours",
    "is_pre_market",
    "is_post_market",
    "is_closed",
    "is_order_entry_allowed",
    "is_matching_active",
    "should_run_trading_job",
    "get_status",
    "get_active_circuit_breakers",
    "get_time_until_next_phase",
    "update_price",
    "update_price_model",
    "reset_daily_circuit_breakers",
    "get_market_session_manager",
    "export_phase_mappings_to_polars",
    "export_price_update_to_duckdb",
    "query_price_updates_duckdb",
]
