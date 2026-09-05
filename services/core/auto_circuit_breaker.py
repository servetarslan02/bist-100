"""ALPHA BIST — Otomatik Devre Kesici Tetikleme Motoru (Auto Circuit Breaker Engine).

Bu modül, Borsa İstanbul (BIST) pay piyasası ve endeks devre kesici kurallarını
gerçek zamanlı fiyat akışları üzerinde otomatik olarak denetler ve tetikler:
- Pay bazında devre kesici (Pazar bazlı dinamik eşikler: Yıldız Pazar, Ana Pazar, Alt Pazar)
- Endekse Bağlı Devre Kesici Sistemi (EBDKS: BIST-100 endeksi düşüş eşiği ve ardışık seviyeler)
- Günlük tetikleme ve seans durumu takip döngüsü
- Eşzamanlı (thread-safe) olay kuyruğu ve durum raporlaması
- Polars DataFrame ve DuckDB kalıcı analitik veri dışa aktarımı

Referans: Borsa İstanbul Pay Piyasası Prosedürü ve Ağustos 2025 Düzenlemeleri.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import trace

from services.core.market_session_fsm import BISTMarketPhase, bist_session_fsm
from services.core.otel import otel_trace

if TYPE_CHECKING:
    from datetime import datetime

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.auto_circuit_breaker")

# =====================================================
# DEVRE KESİCİ YAPILANDIRMA SABİTLERİ
# =====================================================

DEFAULT_EVENT_QUEUE_MAXLEN: Final[int] = 1000
DEFAULT_MARKET_TYPE: Final[str] = "ana"
VALID_MARKET_TYPES: Final[frozenset[str]] = frozenset({"yildiz", "ana", "alt"})
DEFAULT_CB_DB_PATH: Final[str] = "data/circuit_breaker_events.duckdb"


@dataclass(slots=True)
class CircuitBreakerEvent:
    """Devre kesici tetikleme olayı veri modeli."""

    ticker: str
    event_type: str  # "PAY_BAZINDA" | "EBDKS"
    trigger_price: float
    reference_price: float
    change_pct: float
    threshold_pct: float
    triggered_at: datetime
    duration_minutes: int
    feature_code: str | None = None
    market_phase: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Olay verilerini serileştirilebilir sözlük biçimine dönüştürür.

        Returns:
            dict[str, Any]: Devre kesici olayına ait alanları içeren sözlük.
        """
        iso_time = (
            self.triggered_at.isoformat()
            if hasattr(self.triggered_at, "isoformat")
            else str(self.triggered_at)
        )
        return {
            "ticker": self.ticker,
            "event_type": self.event_type,
            "trigger_price": self.trigger_price,
            "reference_price": self.reference_price,
            "change_pct": round(self.change_pct, 4),
            "threshold_pct": self.threshold_pct,
            "triggered_at": iso_time,
            "duration_minutes": self.duration_minutes,
            "feature_code": self.feature_code,
            "market_phase": self.market_phase,
        }

    def to_orjson_bytes(self) -> bytes:
        """Olay verilerini yüksek performanslı ikili JSON baytlarına dönüştürür.

        Returns:
            bytes: UTF-8 kodlu JSON bayt dizisi.
        """
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Devre kesici olayının okunabilir temsilini döner."""
        iso_time = (
            self.triggered_at.isoformat()
            if hasattr(self.triggered_at, "isoformat")
            else str(self.triggered_at)
        )
        return (
            f"CircuitBreakerEvent(ticker={self.ticker!r}, tip={self.event_type!r}, "
            f"degisim=%{self.change_pct:.2f}, esik=%{self.threshold_pct:.2f}, zaman={iso_time!r})"
        )


class AutoCircuitBreakerEngine:
    """Otomatik devre kesici tetikleme ve takip motoru.

    Her fiyat güncellemesinde:
    1. Pay bazında devre kesici eşiklerini kontrol eder.
    2. BIST-100 endeks değişimini izler (EBDKS).
    3. Eşik aşıldığında BIST Seans FSM üzerinden otomatik tetikler.
    """

    def __init__(
        self,
        queue_limit: int = DEFAULT_EVENT_QUEUE_MAXLEN,
        maxlen: int | None = None,
    ) -> None:
        """Devre kesici motorunu başlatır.

        Args:
            queue_limit: Olay kuyruğunda saklanacak maksimum olay adedi.
            maxlen: queue_limit ile eşanlamlı opsiyonel parametre.
        """
        effective_limit = maxlen if maxlen is not None else queue_limit
        if effective_limit <= 0:
            effective_limit = DEFAULT_EVENT_QUEUE_MAXLEN

        self._lock: threading.RLock = threading.RLock()
        self._events: deque[CircuitBreakerEvent] = deque(maxlen=effective_limit)
        self._triggered_today: dict[str, list[float]] = {}  # ticker -> [threshold_pct, ...]
        self._bist100_reference: float = 0.0  # Önceki gün kapanış değeri
        self._bist100_current: float = 0.0
        self._ebdks_triggered_today: int = 0

    def set_bist100_reference(self, reference_price: float) -> None:
        """BIST-100 referans fiyatını (önceki gün kapanışı) belirler.

        Args:
            reference_price: Pozitif BIST-100 baz referans fiyatı.
        """
        if reference_price <= 0 or not math.isfinite(reference_price):
            logger.warning("gecersiz_bist100_referans_fiyati", referans=reference_price)
            return

        with self._lock:
            self._bist100_reference = reference_price

    @otel_trace("auto_circuit_breaker.update_bist100_price")
    def update_bist100_price(
        self,
        current_price: float,
        feature_code: str | None = None,
        current_time: datetime | None = None,
    ) -> CircuitBreakerEvent | None:
        """BIST-100 güncel endeks değerini günceller ve EBDKS eşik kontrolü yapar.

        Args:
            current_price: Güncel BIST-100 endeks değeri.
            feature_code: Opsiyonel BIST özellik kodu.
            current_time: Opsiyonel simülasyon/seans zamanı (varsayılan: anlık Türkiye saati).

        Returns:
            CircuitBreakerEvent | None: Eşik aşılıp EBDKS tetiklenirse olay nesnesi, aksi halde None.
        """
        if current_price <= 0 or not math.isfinite(current_price):
            return None

        with self._lock:
            self._bist100_current = current_price
            ref_price = self._bist100_reference

        if ref_price <= 0 or not math.isfinite(ref_price):
            return None

        # Piyasa açık değilse kontrol etme
        phase = bist_session_fsm.get_phase(current_time=current_time)
        if phase == BISTMarketPhase.CLOSED:
            return None

        change_pct = round(((current_price / ref_price) - 1.0) * 100.0, 4)

        # EBDKS: BIST-100 %6 veya daha fazla düşüş
        threshold_pct = bist_session_fsm.EBDKS_THRESHOLD_PCT
        if change_pct <= -threshold_pct:
            should_trigger = False
            effective_threshold = threshold_pct
            with self._lock:
                current_count = self._ebdks_triggered_today
                effective_threshold = (
                    threshold_pct if current_count == 0 else threshold_pct + (current_count * 2.0)
                )
                should_trigger = current_count == 0 or (
                    current_count > 0 and change_pct <= -effective_threshold
                )
                if should_trigger:
                    self._ebdks_triggered_today += 1

            if should_trigger:
                try:
                    bist_session_fsm.trigger_ebdks(feature_code=feature_code)
                except Exception as exc:
                    with self._lock:
                        self._ebdks_triggered_today = max(0, self._ebdks_triggered_today - 1)
                    logger.error("ebdks_fsm_tetikleme_hatasi", error=str(exc))
                    raise

                trigger_time = current_time if current_time is not None else bist_session_fsm.now_istanbul()
                duration = (
                    bist_session_fsm.EBDKS_DURATION_BY_FEATURE.get(
                        feature_code, bist_session_fsm.EBDKS_DEFAULT_DURATION
                    )
                    if feature_code
                    else bist_session_fsm.EBDKS_DEFAULT_DURATION
                )
                event = CircuitBreakerEvent(
                    ticker="BIST-100",
                    event_type="EBDKS",
                    trigger_price=current_price,
                    reference_price=ref_price,
                    change_pct=change_pct,
                    threshold_pct=effective_threshold,
                    triggered_at=trigger_time,
                    duration_minutes=duration,
                    feature_code=feature_code,
                    market_phase=phase.value,
                )

                with self._lock:
                    self._events.append(event)
                    total_count = self._ebdks_triggered_today

                logger.warning(
                    "ebdks_otomatik_tetiklendi",
                    degisim_yuzdesi=f"{change_pct:.2f}%",
                    esik=f"%{effective_threshold:.1f}",
                    guncel_fiyat=current_price,
                    referans_fiyat=ref_price,
                    gunluk_tetiklenme_sayisi=total_count,
                    sure_dk=duration,
                )
                return event

        return None

    @otel_trace("auto_circuit_breaker.check_pay_circuit_breaker")
    def check_pay_circuit_breaker(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
        market_type: str = DEFAULT_MARKET_TYPE,
        current_time: datetime | None = None,
    ) -> CircuitBreakerEvent | None:
        """Hisse payı bazında devre kesici tetikleme kontrolü gerçekleştirir.

        Args:
            ticker: BIST hisse kodu (örn. 'EREGL').
            current_price: Güncel işlem fiyatı.
            reference_price: İlgili hissenin baz/kapanış referans fiyatı.
            market_type: Pazar segmenti ('yildiz', 'ana', 'alt').
            current_time: Opsiyonel simülasyon/seans zamanı (varsayılan: anlık Türkiye saati).

        Returns:
            CircuitBreakerEvent | None: Eşik aşılıp devre kesici devreye girerse olay nesnesi, aksi halde None.
        """
        if not ticker or not isinstance(ticker, str):
            return None
        norm_ticker = ticker.upper().strip()
        if not norm_ticker:
            return None

        if reference_price <= 0 or current_price <= 0:
            return None
        if not math.isfinite(current_price) or not math.isfinite(reference_price):
            return None

        # Piyasa kapalıysa devre kesici tetiklenmez
        phase = bist_session_fsm.get_phase(ticker=norm_ticker, current_time=current_time)
        if phase == BISTMarketPhase.CLOSED:
            return None

        change_pct = round(((current_price / reference_price) - 1.0) * 100.0, 4)

        # Pazar tipini normalize et
        normalized_market = market_type.lower().strip() if isinstance(market_type, str) else DEFAULT_MARKET_TYPE
        if normalized_market not in VALID_MARKET_TYPES:
            normalized_market = DEFAULT_MARKET_TYPE

        # Pazar bazında eşikleri al
        thresholds = bist_session_fsm.CIRCUIT_BREAKER_THRESHOLDS.get(
            normalized_market, bist_session_fsm.CIRCUIT_BREAKER_THRESHOLDS["ana"]
        )

        threshold_to_trigger: float | None = None
        with self._lock:
            triggered_thresholds = set(self._triggered_today.get(norm_ticker, []))
            for threshold in sorted(thresholds):
                if change_pct <= -threshold and threshold not in triggered_thresholds:
                    if norm_ticker not in self._triggered_today:
                        self._triggered_today[norm_ticker] = []
                    self._triggered_today[norm_ticker].append(threshold)
                    threshold_to_trigger = threshold
                    break

        if threshold_to_trigger is not None:
            try:
                bist_session_fsm.trigger_circuit_breaker(norm_ticker)
            except Exception as exc:
                with self._lock:
                    if norm_ticker in self._triggered_today and threshold_to_trigger in self._triggered_today[norm_ticker]:
                        self._triggered_today[norm_ticker].remove(threshold_to_trigger)
                logger.error("pay_devre_kesici_fsm_tetikleme_hatasi", ticker=norm_ticker, error=str(exc))
                raise

            trigger_time = current_time if current_time is not None else bist_session_fsm.now_istanbul()
            event = CircuitBreakerEvent(
                ticker=norm_ticker,
                event_type="PAY_BAZINDA",
                trigger_price=current_price,
                reference_price=reference_price,
                change_pct=change_pct,
                threshold_pct=threshold_to_trigger,
                triggered_at=trigger_time,
                duration_minutes=bist_session_fsm.CIRCUIT_BREAKER_DURATION_MINUTES,
                market_phase=phase.value,
            )

            with self._lock:
                self._events.append(event)

            logger.warning(
                "pay_devre_kesici_tetiklendi",
                ticker=norm_ticker,
                degisim_yuzdesi=f"{change_pct:.2f}%",
                esik=f"%{threshold_to_trigger}",
                guncel_fiyat=current_price,
                referans_fiyat=reference_price,
                pazar_tipi=normalized_market,
            )
            return event

        return None

    def is_ticker_in_circuit_breaker(self, ticker: str, current_time: datetime | None = None) -> bool:
        """Belirtilen hissenin şu an devre kesici seansında olup olmadığını kontrol eder.

        Args:
            ticker: BIST hisse sembolü.
            current_time: Opsiyonel simülasyon/seans zamanı (varsayılan: anlık Türkiye saati).

        Returns:
            bool: Devre kesici aktif ise True, değilse False.
        """
        if not ticker or not isinstance(ticker, str):
            return False
        norm_ticker = ticker.upper().strip()
        if not norm_ticker:
            return False
        return (
            bist_session_fsm.get_phase(ticker=norm_ticker, current_time=current_time)
            == BISTMarketPhase.CIRCUIT_BREAKER_AUCTION
        )

    def is_ebdks_active(self) -> bool:
        """Endekse bağlı devre kesicinin (EBDKS) anlık olarak aktif olup olmadığını döner.

        Returns:
            bool: EBDKS aktif ise True, değilse False.
        """
        return bist_session_fsm.is_ebdks_active()

    def reset_daily(self) -> None:
        """Günlük tetikleme sayaçlarını ve EBDKS durumunu sıfırlar (seans sonu çağrılır)."""
        with self._lock:
            self._triggered_today.clear()
            self._ebdks_triggered_today = 0
            bist_session_fsm.clear_ebdks()
            if hasattr(bist_session_fsm, "_circuit_breaker_active"):
                bist_session_fsm._circuit_breaker_active.clear()

        logger.info("devre_kesici_gunluk_sayaclari_sifirlandi")

    def get_events_today(self) -> list[dict[str, Any]]:
        """Günün gerçekleşen tüm devre kesici olaylarını sözlük listesi olarak döner.

        Returns:
            list[dict[str, Any]]: Olayların sözlük listesi.
        """
        with self._lock:
            events = list(self._events)
        return [e.to_dict() for e in events]

    def get_events_for_ticker(self, ticker: str) -> list[dict[str, Any]]:
        """Belirtilen hisse veya endekse ait gerçekleşen devre kesici olaylarını döner.

        Args:
            ticker: BIST hisse sembolü veya 'BIST-100'.

        Returns:
            list[dict[str, Any]]: İlgili hisseye ait olaylar listesi.
        """
        if not ticker or not isinstance(ticker, str):
            return []
        target = ticker.upper().strip()
        if not target:
            return []
        with self._lock:
            events = [e.to_dict() for e in self._events if e.ticker == target]
        return events

    def get_status(self) -> dict[str, Any]:
        """Devre kesici motorunun anlık durum özetini döner.

        Returns:
            dict[str, Any]: EBDKS ve hisse devre kesici metriklerini içeren durum sözlüğü.
        """
        with self._lock:
            ref = self._bist100_reference
            curr = self._bist100_current
            change = (
                round(((curr / ref) - 1.0) * 100.0, 4)
                if ref > 0 and curr > 0 and math.isfinite(curr) and math.isfinite(ref)
                else 0.0
            )
            return {
                "ebdks_triggered_today": self._ebdks_triggered_today,
                "bist100_reference": ref,
                "bist100_current": curr,
                "bist100_change_pct": change,
                "pay_circuit_breakers_today": len(self._triggered_today),
                "pay_circuit_breakers_triggered": list(self._triggered_today.keys()),
                "total_events_today": len(self._events),
                "ebdks_active": bist_session_fsm.is_ebdks_active(),
                "ebdks_late_session": bist_session_fsm.is_ebdks_late_session(),
            }

    # Geriye dönük uyumluluk ve takma ad
    get_status_summary = get_status

    def get_recent_events(self, limit: int = 10) -> list[dict[str, Any]]:
        """Son gerçekleşen devre kesici olaylarını getirir.

        Args:
            limit: Döndürülecek maksimum olay sayısı.

        Returns:
            list[dict[str, Any]]: En son olayların listesi (yeniden eskiye).
        """
        eff_limit = max(0, limit)
        if eff_limit == 0:
            return []
        with self._lock:
            events = list(self._events)
        slice_start = max(0, len(events) - eff_limit)
        return [e.to_dict() for e in reversed(events[slice_start:])]

    @otel_trace("auto_circuit_breaker.export_to_polars")
    def export_to_polars(self) -> pl.DataFrame:
        """Devre kesici olaylarını Polars DataFrame olarak döner.

        Returns:
            pl.DataFrame: Katı şemalı Polars veri çerçevesi.
        """
        with self._lock:
            events = list(self._events)

        schema = {
            "ticker": pl.String,
            "event_type": pl.String,
            "trigger_price": pl.Float64,
            "reference_price": pl.Float64,
            "change_pct": pl.Float64,
            "threshold_pct": pl.Float64,
            "triggered_at": pl.String,
            "duration_minutes": pl.Int64,
            "feature_code": pl.String,
            "market_phase": pl.String,
        }

        if not events:
            return pl.DataFrame([], schema=schema)

        records = [
            {
                "ticker": e.ticker,
                "event_type": e.event_type,
                "trigger_price": e.trigger_price,
                "reference_price": e.reference_price,
                "change_pct": round(e.change_pct, 4),
                "threshold_pct": e.threshold_pct,
                "triggered_at": e.triggered_at.isoformat(),
                "duration_minutes": e.duration_minutes,
                "feature_code": e.feature_code or "",
                "market_phase": e.market_phase,
            }
            for e in events
        ]
        return pl.DataFrame(records, schema=schema)

    @otel_trace("auto_circuit_breaker.export_to_duckdb")
    def export_to_duckdb(self, db_path: str = DEFAULT_CB_DB_PATH) -> int:
        """Mevcut devre kesici olaylarını DuckDB tablosuna toplu (batch) olarak yazar.

        Args:
            db_path: Hedef DuckDB dosya yolu.

        Returns:
            int: Veritabanına aktarılan olay sayısı.
        """
        target_path = Path(db_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            events = list(self._events)

            if not events:
                return 0

            conn = duckdb.connect(database=str(target_path))
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS circuit_breaker_events (
                        ticker VARCHAR NOT NULL,
                        event_type VARCHAR NOT NULL,
                        trigger_price DOUBLE NOT NULL,
                        reference_price DOUBLE NOT NULL,
                        change_pct DOUBLE NOT NULL,
                        threshold_pct DOUBLE NOT NULL,
                        triggered_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        duration_minutes INTEGER NOT NULL,
                        feature_code VARCHAR,
                        market_phase VARCHAR NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_cb_events_ticker ON circuit_breaker_events (ticker);
                    CREATE INDEX IF NOT EXISTS idx_cb_events_time ON circuit_breaker_events (triggered_at);
                    """
                )
                batch = [
                    [
                        e.ticker,
                        e.event_type,
                        e.trigger_price,
                        e.reference_price,
                        e.change_pct,
                        e.threshold_pct,
                        e.triggered_at,
                        e.duration_minutes,
                        e.feature_code,
                        e.market_phase,
                    ]
                    for e in events
                ]
                conn.executemany(
                    """
                    INSERT INTO circuit_breaker_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    batch,
                )
                logger.info("circuit_breaker_events_duckdb_aktarildi", adet=len(events), db_path=str(target_path))
                return len(events)
            except Exception as exc:
                logger.error("circuit_breaker_duckdb_aktarim_hatasi", error=str(exc), db_path=str(target_path))
                raise
            finally:
                conn.close()

    @otel_trace("auto_circuit_breaker.query_persisted_duckdb")
    def query_persisted_duckdb(
        self,
        db_path: str = DEFAULT_CB_DB_PATH,
        ticker: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """DuckDB üzerinde kalıcı olarak saklanan devre kesici olaylarını sorgular.

        Args:
            db_path: Hedef DuckDB dosya yolu.
            ticker: Filtrelenecek hisse sembolü veya BIST-100.
            event_type: Filtrelenecek olay türü ('PAY_BAZINDA', 'EBDKS').
            limit: Maksimum kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Olay kayıtları listesi.
        """
        target_path = Path(db_path)
        if not target_path.exists():
            return []

        try:
            conn = duckdb.connect(database=str(target_path), read_only=True)
        except Exception as exc:
            logger.warning(
                "circuit_breaker_duckdb_okuma_baglanti_hatasi", error=str(exc), db_path=str(target_path)
            )
            return []

        try:
            query = "SELECT ticker, event_type, trigger_price, reference_price, change_pct, threshold_pct, triggered_at, duration_minutes, feature_code, market_phase FROM circuit_breaker_events WHERE 1=1"
            params: list[Any] = []
            if ticker:
                query += " AND ticker = ?"
                params.append(ticker.upper().strip())
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type.upper().strip())

            query += " ORDER BY triggered_at DESC LIMIT ?"
            params.append(max(1, limit))

            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "ticker": r[0],
                    "event_type": r[1],
                    "trigger_price": r[2],
                    "reference_price": r[3],
                    "change_pct": r[4],
                    "threshold_pct": r[5],
                    "triggered_at": str(r[6]),
                    "duration_minutes": r[7],
                    "feature_code": r[8],
                    "market_phase": r[9],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.error("circuit_breaker_duckdb_sorgu_hatasi", error=str(exc), db_path=str(target_path))
            return []
        finally:
            conn.close()

    def __repr__(self) -> str:
        """Devre kesici motorunun durum temsilini döner."""
        with self._lock:
            return (
                f"AutoCircuitBreakerEngine(ebdks_tetiklenme={self._ebdks_triggered_today}, "
                f"hisse_sayisi={len(self._triggered_today)}, toplam_olay={len(self._events)})"
            )


# Kolay kullanım için takma ad (alias)
AutoCircuitBreaker = AutoCircuitBreakerEngine

# Global Singleton örneği
auto_circuit_breaker: Final[AutoCircuitBreakerEngine] = AutoCircuitBreakerEngine()


# =====================================================
# MODÜL DÜZEYİ KOLAYLIK FONKSİYONLARI (CONVENIENCE API)
# =====================================================


def set_bist100_reference_price(
    reference_price: float,
    engine: AutoCircuitBreakerEngine | None = None,
) -> None:
    """BIST-100 önceki gün kapanış referans fiyatını ayarlar."""
    inst = engine if engine is not None else auto_circuit_breaker
    inst.set_bist100_reference(reference_price=reference_price)


def update_bist100_index(
    current_price: float,
    feature_code: str | None = None,
    current_time: datetime | None = None,
    engine: AutoCircuitBreakerEngine | None = None,
) -> CircuitBreakerEvent | None:
    """BIST-100 endeks değerini günceller ve EBDKS kontrolü yapar."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.update_bist100_price(
        current_price=current_price, feature_code=feature_code, current_time=current_time
    )


def check_stock_circuit_breaker(
    ticker: str,
    current_price: float,
    reference_price: float,
    market_type: str = DEFAULT_MARKET_TYPE,
    current_time: datetime | None = None,
    engine: AutoCircuitBreakerEngine | None = None,
) -> CircuitBreakerEvent | None:
    """Hisse payı bazında devre kesici tetikleme kontrolü yapar."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.check_pay_circuit_breaker(
        ticker=ticker,
        current_price=current_price,
        reference_price=reference_price,
        market_type=market_type,
        current_time=current_time,
    )


def is_stock_in_circuit_breaker(
    ticker: str,
    current_time: datetime | None = None,
    engine: AutoCircuitBreakerEngine | None = None,
) -> bool:
    """Hissenin şu an devre kesicide olup olmadığını denetler."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.is_ticker_in_circuit_breaker(ticker=ticker, current_time=current_time)


def is_ebdks_in_effect(engine: AutoCircuitBreakerEngine | None = None) -> bool:
    """EBDKS endeks devre kesicisinin aktif olup olmadığını sorgular."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.is_ebdks_active()


def get_circuit_breaker_status(engine: AutoCircuitBreakerEngine | None = None) -> dict[str, Any]:
    """Devre kesici anlık durum özetini döner."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.get_status()


def get_circuit_breaker_events_for_ticker(
    ticker: str,
    engine: AutoCircuitBreakerEngine | None = None,
) -> list[dict[str, Any]]:
    """Belirli bir hisseye ait gerçekleşen devre kesici olaylarını döner."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.get_events_for_ticker(ticker=ticker)


def get_recent_circuit_breaker_events(
    limit: int = 10,
    engine: AutoCircuitBreakerEngine | None = None,
) -> list[dict[str, Any]]:
    """En son gerçekleşen devre kesici olaylarını döner."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.get_recent_events(limit=limit)


def reset_circuit_breaker_daily(engine: AutoCircuitBreakerEngine | None = None) -> None:
    """Günlük devre kesici sayaçlarını sıfırlar."""
    inst = engine if engine is not None else auto_circuit_breaker
    inst.reset_daily()


def export_circuit_breaker_events_to_polars(
    engine: AutoCircuitBreakerEngine | None = None,
) -> pl.DataFrame:
    """Devre kesici olaylarını Polars DataFrame olarak döner."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.export_to_polars()


def export_circuit_breaker_events_to_duckdb(
    db_path: str = DEFAULT_CB_DB_PATH, engine: AutoCircuitBreakerEngine | None = None
) -> int:
    """Devre kesici olaylarını DuckDB tablosuna aktarır."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.export_to_duckdb(db_path=db_path)


def query_circuit_breaker_events_from_duckdb(
    db_path: str = DEFAULT_CB_DB_PATH,
    ticker: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
    engine: AutoCircuitBreakerEngine | None = None,
) -> list[dict[str, Any]]:
    """DuckDB'de saklanan geçmiş devre kesici olaylarını sorgular."""
    inst = engine if engine is not None else auto_circuit_breaker
    return inst.query_persisted_duckdb(
        db_path=db_path, ticker=ticker, event_type=event_type, limit=limit
    )


def get_auto_circuit_breaker() -> AutoCircuitBreakerEngine:
    """Tekil AutoCircuitBreakerEngine örneğini döner."""
    return auto_circuit_breaker


__all__: list[str] = [
    "DEFAULT_CB_DB_PATH",
    "DEFAULT_EVENT_QUEUE_MAXLEN",
    "DEFAULT_MARKET_TYPE",
    "VALID_MARKET_TYPES",
    "AutoCircuitBreaker",
    "AutoCircuitBreakerEngine",
    "CircuitBreakerEvent",
    "auto_circuit_breaker",
    "check_stock_circuit_breaker",
    "export_circuit_breaker_events_to_duckdb",
    "export_circuit_breaker_events_to_polars",
    "get_auto_circuit_breaker",
    "get_circuit_breaker_events_for_ticker",
    "get_circuit_breaker_status",
    "get_recent_circuit_breaker_events",
    "is_ebdks_in_effect",
    "is_stock_in_circuit_breaker",
    "query_circuit_breaker_events_from_duckdb",
    "reset_circuit_breaker_daily",
    "set_bist100_reference_price",
    "update_bist100_index",
]
