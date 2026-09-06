"""
ALPHA BIST — Olay, Bildirim ve Operasyonel Altyapı Motoru (Event Infrastructure)

Bu modül, sistem genelindeki asenkron olay koordinasyonu, yaklaşan şirket/makro katalizörleri,
kullanıcı/risk bildirimleri, periyodik durum anlık görüntüleri (snapshot), TTL tabanlı önbellek
ve öncelikli iş kuyruğu (job queue) bileşenlerini merkezi, thread-safe ve hataya kapalı yönetir.

Bileşenler:
1. EventOrchestrator: Öncelik seviyeli ve asenkron/senkron olay yönlendirme
2. CatalystEngine: BIST hisseleri ve makro için yaklaşan takvim olayları ve etki analizi
3. NotificationSystem: Kategori ve önem dereceli bildirim yönetimi
4. AlertEngine: Çekilme (drawdown), günlük zarar ve pozisyon limit denetimleri
5. SnapshotSystem: Sistem çalışma zamanı durum anlık görüntüleri
6. CacheSystem: TTL destekli hafıza içi önbellek mekanizması
7. JobQueue: Öncelik tabanlı arka plan iş sırası
8. Polars ve DuckDB: Analitik sorgulama ve denetim izi dışa aktarımı
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (CONSTANTS)
# =====================================================

DEFAULT_MAX_CATALYSTS: Final[int] = 500
DEFAULT_MAX_NOTIFICATIONS: Final[int] = 500
DEFAULT_MAX_SNAPSHOTS: Final[int] = 100
DEFAULT_MAX_QUEUE_SIZE: Final[int] = 100
DEFAULT_INFRASTRUCTURE_MAX_QUEUE_SIZE: Final[int] = DEFAULT_MAX_QUEUE_SIZE
DEFAULT_MAX_COMPLETED_JOBS: Final[int] = 1000
DEFAULT_CACHE_TTL_SECONDS: Final[int] = 3600
DEFAULT_MAX_CACHE_ENTRIES: Final[int] = 5000
DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH: Final[Path] = Path("data/duckdb/alpha_bist_audit.duckdb")

# Risk ve Alarm Varsayılan Eşikleri
DEFAULT_MAX_DRAWDOWN_PCT: Final[float] = 15.0
DEFAULT_DAILY_LOSS_PCT: Final[float] = 5.0
DEFAULT_POSITION_LIMIT_PCT: Final[float] = 10.0
DEFAULT_SECTOR_LIMIT_PCT: Final[float] = 30.0


# =====================================================
# NUMARALANDIRMALAR VE VERİ MODELLERİ
# =====================================================


class EventPriority(StrEnum):
    """Olay ve iş öncelik dereceleri."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class NotificationCategory(StrEnum):
    """Sistem bildirim kategorileri."""

    OPPORTUNITY = "OPPORTUNITY"
    RISK = "RISK"
    NEWS = "NEWS"
    KAP = "KAP"
    REGIME = "REGIME"
    PORTFOLIO = "PORTFOLIO"
    MODEL = "MODEL"
    SYSTEM = "SYSTEM"
    SECURITY = "SECURITY"


@dataclass(slots=True)
class CatalystEvent:
    """BIST hissesi veya piyasa genelini etkileyecek yaklaşan takvim olayı.

    Attributes:
        catalyst_id: Tekil katalizör kimliği.
        ticker: İlgili hisse kodu veya endeks sembolü (ör: THYAO, XU100).
        catalyst_type: Olay tipi (earnings, dividend, assembly, contract, macro vb.).
        date: Olay tarihi (ISO 8601).
        importance: 0.0 - 1.0 aralığında önem ağırlığı.
        expected_impact: Beklenen piyasa etkisi (POSITIVE, NEGATIVE, UNKNOWN).
        uncertainty: 0.0 - 1.0 aralığında belirsizlik katsayısı.
        description: Olay açıklaması veya kaynak referansı.
    """

    catalyst_id: str
    ticker: str
    catalyst_type: str
    date: str
    importance: float
    expected_impact: str
    uncertainty: float
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Katalizör olayını sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Serileştirilebilir sözlük.
        """
        return {
            "catalyst_id": self.catalyst_id,
            "ticker": self.ticker,
            "catalyst_type": self.catalyst_type,
            "date": self.date,
            "importance": self.importance,
            "expected_impact": self.expected_impact,
            "uncertainty": self.uncertainty,
            "description": self.description,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli yüksek hızlı JSON bayt dizisine serileştirir.

        Returns:
            bytes: orjson kodlu baytlar.
        """
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CatalystEvent:
        """Sözlükten CatalystEvent nesnesi türetir.

        Args:
            d: Model verilerini içeren sözlük.

        Returns:
            CatalystEvent: Yapılandırılmış model nesnesi.
        """
        return cls(
            catalyst_id=str(d.get("catalyst_id", "")),
            ticker=str(d.get("ticker", "")),
            catalyst_type=str(d.get("catalyst_type", "")),
            date=str(d.get("date", "")),
            importance=float(d.get("importance", 0.5)),
            expected_impact=str(d.get("expected_impact", "UNKNOWN")),
            uncertainty=float(d.get("uncertainty", 0.5)),
            description=str(d.get("description", "")),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> CatalystEvent:
        """JSON metni veya baytlarından CatalystEvent nesnesi türetir.

        Args:
            raw: JSON dizgisi veya bayt dizisi.

        Returns:
            CatalystEvent: Çözümlenmiş model nesnesi.
        """
        data = orjson.loads(raw)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Türkçe açıklayıcı metin gösterimi.

        Returns:
            str: Model özeti.
        """
        return (
            f"CatalystEvent(ticker='{self.ticker}', tip='{self.catalyst_type}', "
            f"tarih='{self.date}', onem={self.importance:.2f}, etki='{self.expected_impact}')"
        )


@dataclass(slots=True)
class NotificationItem:
    """Sistem içi üretilen yapılandırılmış bildirim modeli.

    Attributes:
        id: Bildirim tekil kimliği.
        category: Bildirim kategorisi.
        title: Bildirim başlığı.
        message: Bildirim detay mesajı.
        severity: Önem seviyesi (INFO, WARNING, HIGH, CRITICAL).
        data: İlave yapılandırılmış yük.
        timestamp: Bildirimin oluşturulma UTC zaman damgası.
        read: Okunma durumu.
    """

    id: str
    category: str
    title: str
    message: str
    severity: str
    data: dict[str, Any]
    timestamp: str
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Bildirimi sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Sözlük yapısı.
        """
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "data": self.data,
            "timestamp": self.timestamp,
            "read": self.read,
        }

    def to_orjson_bytes(self) -> bytes:
        """Bildirimi JSON baytlarına dönüştürür.

        Returns:
            bytes: orjson kodlu baytlar.
        """
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NotificationItem:
        """Sözlükten NotificationItem nesnesi türetir.

        Args:
            d: Bildirim verilerini içeren sözlük.

        Returns:
            NotificationItem: Bildirim modeli nesnesi.
        """
        return cls(
            id=str(d.get("id", "")),
            category=str(d.get("category", NotificationCategory.SYSTEM.value)),
            title=str(d.get("title", "")),
            message=str(d.get("message", "")),
            severity=str(d.get("severity", "INFO")),
            data=dict(d.get("data", {})),
            timestamp=str(d.get("timestamp", datetime.now(UTC).isoformat())),
            read=bool(d.get("read", False)),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> NotificationItem:
        """JSON metni veya baytlarından NotificationItem nesnesi türetir.

        Args:
            raw: JSON dizgisi veya bayt dizisi.

        Returns:
            NotificationItem: Çözümlenmiş model nesnesi.
        """
        data = orjson.loads(raw)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Türkçe açıklayıcı bildirim gösterimi.

        Returns:
            str: Bildirim özeti.
        """
        okundu = "Okundu" if self.read else "Okunmadı"
        return f"NotificationItem(id='{self.id}', kategori='{self.category}', baslik='{self.title}', seviye='{self.severity}', durum='{okundu}')"


@dataclass(slots=True)
class SystemSnapshot:
    """Sistem çalışma zamanı durum anlık görüntüsü.

    Attributes:
        timestamp: UTC ISO formatında zaman damgası.
        state: Yakalanan sistem durumu sözlüğü.
    """

    timestamp: str
    state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Sözlük formatında durum.
        """
        return {
            "timestamp": self.timestamp,
            "state": self.state,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson bayt dizisine dönüştürür.

        Returns:
            bytes: JSON baytları.
        """
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SystemSnapshot:
        """Sözlükten SystemSnapshot nesnesi türetir.

        Args:
            d: Snapshot verilerini içeren sözlük.

        Returns:
            SystemSnapshot: Durum anlık görüntüsü nesnesi.
        """
        return cls(
            timestamp=str(d.get("timestamp", datetime.now(UTC).isoformat())),
            state=dict(d.get("state", {})),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> SystemSnapshot:
        """JSON metni veya baytlarından SystemSnapshot nesnesi türetir.

        Args:
            raw: JSON dizgisi veya bayt dizisi.

        Returns:
            SystemSnapshot: Çözümlenmiş snapshot nesnesi.
        """
        data = orjson.loads(raw)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Türkçe açıklayıcı metin gösterimi.

        Returns:
            str: Snapshot özeti.
        """
        return f"SystemSnapshot(zaman='{self.timestamp}', anahtar_sayisi={len(self.state)})"


@dataclass(slots=True)
class JobItem:
    """Öncelikli iş kuyruğunda yer alan görev kaydı.

    Attributes:
        job_id: Tekil iş kimliği.
        job_type: İş türü tanımı.
        payload: Görev parametreleri.
        priority: Görev önceliği (CRITICAL, HIGH, NORMAL, LOW).
        status: İş durumu (QUEUED, RUNNING, COMPLETED, FAILED).
        created_at: Oluşturulma UTC zaman damgası.
        completed_at: Tamamlanma zamanı.
        result: İşlem çıktısı veya hata mesajı.
    """

    job_id: str
    job_type: str
    payload: dict[str, Any]
    priority: str
    status: str
    created_at: str
    completed_at: str | None = None
    result: Any = None

    def to_dict(self) -> dict[str, Any]:
        """İş kaydını sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Sözlük formatı.
        """
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "payload": self.payload,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "result": self.result,
        }

    def to_orjson_bytes(self) -> bytes:
        """İş kaydını JSON bayt dizisine dönüştürür.

        Returns:
            bytes: orjson kodlu baytlar.
        """
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> JobItem:
        """Sözlükten JobItem nesnesi türetir.

        Args:
            d: Görev parametre ve durum sözlüğü.

        Returns:
            JobItem: Görev nesnesi.
        """
        return cls(
            job_id=str(d.get("job_id", "")),
            job_type=str(d.get("job_type", "")),
            payload=dict(d.get("payload", {})),
            priority=str(d.get("priority", "NORMAL")),
            status=str(d.get("status", "QUEUED")),
            created_at=str(d.get("created_at", datetime.now(UTC).isoformat())),
            completed_at=d.get("completed_at"),
            result=d.get("result"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> JobItem:
        """JSON metni veya baytlarından JobItem nesnesi türetir.

        Args:
            raw: JSON dizgisi veya bayt dizisi.

        Returns:
            JobItem: Çözümlenmiş iş nesnesi.
        """
        data = orjson.loads(raw)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Türkçe açıklayıcı iş kaydı gösterimi.

        Returns:
            str: İş durumu özeti.
        """
        return f"JobItem(id='{self.job_id}', tip='{self.job_type}', oncelik='{self.priority}', durum='{self.status}')"


# =====================================================
# 1. OLAY YÖNLENDİRİCİ (EVENT ORCHESTRATOR)
# =====================================================


class EventOrchestrator:
    """Sistem içi senkron ve asenkron olayların dağıtımını yöneten servis."""

    def __init__(self) -> None:
        """Olay orkestratörünü başlatır."""
        self._lock = threading.RLock()
        self._handlers: dict[str, list[dict[str, Any]]] = {}

    @otel_trace("event_orchestrator.register")
    def register(
        self,
        event_type: str,
        handler: Callable[..., Any],
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        """Belirtilen olay türü için dinleyici fonksiyon kaydeder.

        Args:
            event_type: Abone olunacak olay tipi.
            handler: Çağrılacak senkron veya asenkron fonksiyon.
            priority: Yürütme öncelik seviyesi.
        """
        if not event_type or not isinstance(event_type, str):
            logger.warning("gecersiz_olay_tipi_kaydi", olay_tipi=event_type)
            return
        if not callable(handler):
            logger.warning("cagrilamaz_dinleyici_kaydi", olay_tipi=event_type)
            return

        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append({"handler": handler, "priority": priority})
            logger.debug("olay_dinleyici_kaydedildi", olay_tipi=event_type, oncelik=str(priority))

    @otel_trace("event_orchestrator.dispatch")
    async def dispatch(
        self,
        event_type: str,
        data: dict[str, Any],
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        """Olayı kayıtlı tüm dinleyicilere öncelik sırasına göre iletir.

        Args:
            event_type: Dağıtılacak olayın adı.
            data: Dinleyicilere aktarılacak veri yükü.
            priority: Dağıtım önceliği.
        """
        if not event_type or not isinstance(event_type, str):
            logger.warning("gecersiz_olay_dagitimi", olay_tipi=event_type)
            return

        handlers: list[dict[str, Any]] = []
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))

        priority_order = {
            "CRITICAL": 0,
            "HIGH": 1,
            "NORMAL": 2,
            "LOW": 3,
            EventPriority.CRITICAL: 0,
            EventPriority.HIGH: 1,
            EventPriority.NORMAL: 2,
            EventPriority.LOW: 3,
        }
        sorted_handlers = sorted(
            handlers,
            key=lambda x: priority_order.get(x["priority"], priority_order.get(str(x["priority"]).upper(), 2)),
        )

        logger.debug("olay_dagitiliyor", olay_tipi=event_type, oncelik=str(priority), dinleyici_sayisi=len(sorted_handlers))

        for h in sorted_handlers:
            try:
                fn = h["handler"]
                if asyncio.iscoroutinefunction(fn):
                    await fn(data)
                else:
                    fn(data)
            except Exception as e:
                logger.error(
                    "olay_dinleyici_yurutme_hatasi",
                    olay_tipi=event_type,
                    hata=str(e),
                )

    def clear(self) -> None:
        """Kayıtlı tüm dinleyicileri temizler."""
        with self._lock:
            self._handlers.clear()

    def get_registered_events(self) -> list[str]:
        """Kayıtlı olay türlerini döndürür.

        Returns:
            list[str]: Olay adları listesi.
        """
        with self._lock:
            return list(self._handlers.keys())

    def handler_count(self, event_type: str | None = None) -> int:
        """Kayıtlı dinleyici sayısını döndürür.

        Args:
            event_type: Belirli bir olay türü veya None.

        Returns:
            int: Dinleyici sayısı.
        """
        with self._lock:
            if event_type is not None:
                return len(self._handlers.get(event_type, []))
            return sum(len(handlers) for handlers in self._handlers.values())

    def __repr__(self) -> str:
        """Orkestratör metin özeti.

        Returns:
            str: Kayıtlı dinleyici ve olay sayısı özeti.
        """
        with self._lock:
            return f"EventOrchestrator(olay_turleri={list(self._handlers.keys())})"


# =====================================================
# 2. KATALİZÖR MOTORU (CATALYST ENGINE)
# =====================================================


class CatalystEngine:
    """Hisse ve piyasa duyarlılığı yüksek yaklaşan takvim olaylarını izler."""

    def __init__(self) -> None:
        """Katalizör takip motorunu başlatır."""
        self._lock = threading.RLock()
        self._catalysts: list[CatalystEvent] = []

    @otel_trace("catalyst_engine.add_catalyst")
    def add_catalyst(
        self,
        catalyst_or_ticker: CatalystEvent | str,
        catalyst_type: str = "",
        date: str = "",
        importance: float = 0.5,
        expected_impact: str = "UNKNOWN",
        uncertainty: float = 0.5,
        description: str = "",
    ) -> CatalystEvent:
        """Yeni bir takvim olayını izleme listesine ekler.

        Args:
            catalyst_or_ticker: CatalystEvent nesnesi veya hisse/endeks kodu.
            catalyst_type: Olay türü (earnings, dividend, macro vb.).
            date: Olay tarihi (ISO 8601).
            importance: 0.0 - 1.0 aralığında önem derecesi.
            expected_impact: Beklenen etki (POSITIVE, NEGATIVE, UNKNOWN).
            uncertainty: 0.0 - 1.0 aralığında belirsizlik katsayısı.
            description: Olay açıklaması.

        Returns:
            CatalystEvent: Kaydedilen katalizör nesnesi.
        """
        with self._lock:
            if isinstance(catalyst_or_ticker, CatalystEvent):
                item = catalyst_or_ticker
            else:
                seed = f"{catalyst_or_ticker}:{catalyst_type}:{date}:{time.time_ns()}".encode()
                cat_id = hashlib.sha256(seed).hexdigest()[:12]
                item = CatalystEvent(
                    catalyst_id=cat_id,
                    ticker=catalyst_or_ticker,
                    catalyst_type=catalyst_type,
                    date=date,
                    importance=importance,
                    expected_impact=expected_impact,
                    uncertainty=uncertainty,
                    description=description,
                )

            self._catalysts.append(item)
            if len(self._catalysts) > DEFAULT_MAX_CATALYSTS:
                self._catalysts = self._catalysts[-DEFAULT_MAX_CATALYSTS:]
            logger.info("katalizor_eklendi", ticker=item.ticker, tip=item.catalyst_type, tarih=item.date)
            return item

    @otel_trace("catalyst_engine.get_upcoming")
    def get_upcoming(
        self,
        days: int = 7,
        days_ahead: int | None = None,
        min_importance: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Gelecek N gün içindeki yaklaşan olayları döndürür.

        Args:
            days: Önümüzdeki gün sayısı penceresi.
            days_ahead: Alternatif gün penceresi parametresi.
            min_importance: Minimum önem filtre eşiği.

        Returns:
            list[dict[str, Any]]: Yaklaşan olayların sıralı listesi.
        """
        effective_days = days_ahead if days_ahead is not None else days
        now = datetime.now(UTC)
        upcoming: list[dict[str, Any]] = []

        with self._lock:
            for c in self._catalysts:
                try:
                    cat_date = datetime.fromisoformat(c.date)
                    if cat_date.tzinfo is None:
                        cat_date = cat_date.replace(tzinfo=UTC)
                    days_until = (cat_date - now).days
                    if 0 <= days_until <= effective_days and c.importance >= min_importance:
                        upcoming.append({
                            "ticker": c.ticker,
                            "type": c.catalyst_type,
                            "date": c.date,
                            "days_until": days_until,
                            "importance": c.importance,
                            "expected_impact": c.expected_impact,
                            "uncertainty": c.uncertainty,
                            "description": c.description,
                        })
                except Exception as e:
                    logger.debug("katalizor_tarih_ayristirma_hatasi", hata=str(e), tarih=c.date)

        return sorted(upcoming, key=lambda x: x["days_until"])

    def export_to_polars(self) -> pl.DataFrame:
        """Tüm kayıtlı katalizörleri Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Katalizör veri tablosu.
        """
        with self._lock:
            schema = {
                "catalyst_id": pl.String,
                "ticker": pl.String,
                "catalyst_type": pl.String,
                "date": pl.String,
                "importance": pl.Float64,
                "expected_impact": pl.String,
                "uncertainty": pl.Float64,
                "description": pl.String,
            }
            if not self._catalysts:
                return pl.DataFrame(schema=schema)
            return pl.DataFrame([c.to_dict() for c in self._catalysts], schema=schema)

    def export_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """Katalizör listesini DuckDB `bist_catalysts` tablosuna atomik yazar.

        Args:
            db_path: DuckDB dosya yolu.

        Returns:
            int: Eklenen veya güncellenen kayıt sayısı.
        """
        df = self.export_to_polars()
        if df.is_empty():
            return 0

        target_path = Path(db_path) if db_path is not None else DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.is_file() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_catalysts (
                    catalyst_id VARCHAR PRIMARY KEY,
                    ticker VARCHAR,
                    catalyst_type VARCHAR,
                    date VARCHAR,
                    importance DOUBLE,
                    expected_impact VARCHAR,
                    uncertainty DOUBLE,
                    description VARCHAR,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            arrow_table = df.to_arrow()
            con.register("cat_arrow", arrow_table)
            con.execute("""
                INSERT OR REPLACE INTO bist_catalysts (
                    catalyst_id, ticker, catalyst_type, date, importance, expected_impact, uncertainty, description
                )
                SELECT catalyst_id, ticker, catalyst_type, date, importance, expected_impact, uncertainty, description
                FROM cat_arrow
            """)
            con.unregister("cat_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    @staticmethod
    def query_catalysts_duckdb(
        db_path: str | Path | None = None,
        limit: int = 100,
        ticker: str | None = None,
        min_importance: float = 0.0,
    ) -> pl.DataFrame:
        """DuckDB bist_catalysts tablosundan Polars DataFrame olarak sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            limit: Maksimum kayıt adedi.
            ticker: Opsiyonel hisse filtresi.
            min_importance: Minimum önem filtre eşiği.

        Returns:
            pl.DataFrame: Katalizör veri çerçevesi.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH
        if not target_path.exists() or (target_path.is_file() and target_path.stat().st_size == 0):
            return pl.DataFrame()

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            query = "SELECT * FROM bist_catalysts WHERE importance >= ?"
            params: list[Any] = [min_importance]
            if ticker:
                query += " AND ticker = ?"
                params.append(ticker)
            query += " ORDER BY date ASC LIMIT ?"
            params.append(limit)
            return con.execute(query, params).pl()
        finally:
            con.close()

    def clear(self) -> None:
        """Hafızadaki tüm katalizörleri temizler."""
        with self._lock:
            self._catalysts.clear()

    def __repr__(self) -> str:
        """Katalizör motoru metin gösterimi.

        Returns:
            str: Durum özeti.
        """
        with self._lock:
            return f"CatalystEngine(kayitli_katalizor_sayisi={len(self._catalysts)})"


# =====================================================
# 3. BİLDİRİM SİSTEMİ (NOTIFICATION SYSTEM)
# =====================================================


class NotificationSystem:
    """Kategori ve önem seviyesine göre sistem içi bildirimleri yöneten servis."""

    def __init__(self) -> None:
        """Bildirim sistemini başlatır."""
        self._lock = threading.RLock()
        self._notifications: list[NotificationItem] = []

    @otel_trace("notification_system.notify")
    def notify(
        self,
        category: str,
        title: str,
        message: str,
        severity: str = "INFO",
        data: dict[str, Any] | None = None,
    ) -> NotificationItem:
        """Sistem bildirimi üretir ve hafızaya kaydeder.

        Args:
            category: Bildirim kategorisi (OPPORTUNITY, RISK, SYSTEM vb.).
            title: Bildirim başlığı.
            message: Açıklayıcı mesaj metni.
            severity: Önem seviyesi (INFO, WARNING, HIGH, CRITICAL).
            data: Opsiyonel veri yükü.

        Returns:
            NotificationItem: Oluşturulan bildirim modeli.
        """
        with self._lock:
            now_iso = datetime.now(UTC).isoformat()
            seed = f"{category}:{title}:{now_iso}".encode()
            notif_id = hashlib.sha256(seed).hexdigest()[:12]

            item = NotificationItem(
                id=notif_id,
                category=category,
                title=title,
                message=message,
                severity=severity,
                data=data if data is not None else {},
                timestamp=now_iso,
                read=False,
            )

            self._notifications.append(item)
            if len(self._notifications) > DEFAULT_MAX_NOTIFICATIONS:
                self._notifications = self._notifications[-DEFAULT_MAX_NOTIFICATIONS:]

            logger.info("bildirim_olusturuldu", kategori=category, baslik=title, seviye=severity)
            return item

    @otel_trace("notification_system.get_unread")
    def get_unread(self, limit: int = 20) -> list[dict[str, Any]]:
        """Okunmamış son bildirimleri döndürür.

        Args:
            limit: Maksimum bildirim sayısı.

        Returns:
            list[dict[str, Any]]: Bildirim sözlükleri listesi.
        """
        with self._lock:
            unread = [n.to_dict() for n in self._notifications if not n.read]
            return unread[-limit:]

    @otel_trace("notification_system.mark_read")
    def mark_read(self, notification_id: str) -> bool:
        """Bildirimi okundu olarak işaretler.

        Args:
            notification_id: İşaretlenecek bildirim kimliği.

        Returns:
            bool: Bildirim bulunup işaretlendiyse True, aksi halde False.
        """
        with self._lock:
            for n in self._notifications:
                if n.id == notification_id:
                    n.read = True
                    return True
            return False

    def export_to_polars(self) -> pl.DataFrame:
        """Tüm bildirimleri Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Bildirimler tablosu.
        """
        with self._lock:
            schema = {
                "id": pl.String,
                "category": pl.String,
                "title": pl.String,
                "message": pl.String,
                "severity": pl.String,
                "timestamp": pl.String,
                "read": pl.Boolean,
            }
            if not self._notifications:
                return pl.DataFrame(schema=schema)
            rows = [
                {
                    "id": n.id,
                    "category": n.category,
                    "title": n.title,
                    "message": n.message,
                    "severity": n.severity,
                    "timestamp": n.timestamp,
                    "read": n.read,
                }
                for n in self._notifications
            ]
            return pl.DataFrame(rows, schema=schema)

    def export_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """Bildirimleri DuckDB `bist_notifications` tablosuna depolar.

        Args:
            db_path: DuckDB dosya yolu.

        Returns:
            int: Depolanan bildirim adedi.
        """
        df = self.export_to_polars()
        if df.is_empty():
            return 0

        target_path = Path(db_path) if db_path is not None else DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.is_file() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_notifications (
                    id VARCHAR PRIMARY KEY,
                    category VARCHAR,
                    title VARCHAR,
                    message VARCHAR,
                    severity VARCHAR,
                    timestamp VARCHAR,
                    read BOOLEAN,
                    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            arrow_table = df.to_arrow()
            con.register("notif_arrow", arrow_table)
            con.execute("""
                INSERT OR REPLACE INTO bist_notifications (id, category, title, message, severity, timestamp, read)
                SELECT id, category, title, message, severity, timestamp, read
                FROM notif_arrow
            """)
            con.unregister("notif_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    @staticmethod
    def query_notifications_duckdb(
        db_path: str | Path | None = None,
        limit: int = 50,
        category: str | None = None,
        unread_only: bool = False,
    ) -> pl.DataFrame:
        """DuckDB bist_notifications tablosundan Polars DataFrame olarak bildirimleri sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            limit: Maksimum kayıt sayısı.
            category: Opsiyonel bildirim kategorisi.
            unread_only: Sadece okunmamış bildirimleri getirme bayrağı.

        Returns:
            pl.DataFrame: Bildirimler veri çerçevesi.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH
        if not target_path.exists() or (target_path.is_file() and target_path.stat().st_size == 0):
            return pl.DataFrame()

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            query = "SELECT * FROM bist_notifications WHERE 1=1"
            params: list[Any] = []
            if category:
                query += " AND category = ?"
                params.append(category)
            if unread_only:
                query += " AND read = FALSE"
            query += " ORDER BY recorded_at DESC LIMIT ?"
            params.append(limit)
            return con.execute(query, params).pl()
        finally:
            con.close()

    def clear(self) -> None:
        """Hafızadaki tüm bildirimleri temizler."""
        with self._lock:
            self._notifications.clear()

    def __repr__(self) -> str:
        """Bildirim sistemi metin gösterimi.

        Returns:
            str: Durum özeti.
        """
        with self._lock:
            okunmamis = sum(1 for n in self._notifications if not n.read)
            return f"NotificationSystem(toplam={len(self._notifications)}, okunmamis={okunmamis})"


# =====================================================
# 4. ALARM MOTORU (ALERT ENGINE)
# =====================================================


class AlertEngine:
    """Portföy çekilmesi, günlük zarar ve pozisyon limitlerini denetleyen motor."""

    def __init__(
        self,
        notification_system: NotificationSystem,
        max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
        daily_loss_pct: float = DEFAULT_DAILY_LOSS_PCT,
        position_limit_pct: float = DEFAULT_POSITION_LIMIT_PCT,
        sector_limit_pct: float = DEFAULT_SECTOR_LIMIT_PCT,
    ) -> None:
        """Alarm motorunu başlatır.

        Args:
            notification_system: Bildirimlerin iletileceği bildirim sistemi.
            max_drawdown_pct: Maksimum çekilme eşiği (%).
            daily_loss_pct: Günlük zarar eşiği (%).
            position_limit_pct: Tekil hisse pozisyon limit eşiği (%).
            sector_limit_pct: Sektör ağırlık limit eşiği (%).
        """
        self._lock = threading.RLock()
        self._notifications = notification_system
        self._thresholds = {
            "max_drawdown_pct": max_drawdown_pct,
            "daily_loss_pct": daily_loss_pct,
            "position_limit_pct": position_limit_pct,
            "sector_limit_pct": sector_limit_pct,
        }

    @otel_trace("alert_engine.check_drawdown")
    def check_drawdown(self, current_drawdown: float) -> bool:
        """Mevcut portföy çekilmesini eşik değere göre denetler.

        Args:
            current_drawdown: Yüzdesel tepe-dip çekilmesi.

        Returns:
            bool: Eşik aşıldıysa ve alarm üretildiyse True, aksi halde False.
        """
        with self._lock:
            threshold = self._thresholds["max_drawdown_pct"]
            if current_drawdown > threshold:
                self._notifications.notify(
                    category=NotificationCategory.RISK.value,
                    title="Portföy Çekilme Alarmı (Drawdown)",
                    message=f"Portföy çekilmesi %{current_drawdown:.1f}, kritik eşik %{threshold:.1f}'i aştı!",
                    severity="CRITICAL",
                )
                return True
            return False

    @otel_trace("alert_engine.check_daily_loss")
    def check_daily_loss(self, daily_loss_pct: float) -> bool:
        """Günlük zarar oranını denetler.

        Args:
            daily_loss_pct: Yüzdesel günlük zarar (pozitif veya negatif).

        Returns:
            bool: Eşik aşıldıysa True.
        """
        with self._lock:
            threshold = self._thresholds["daily_loss_pct"]
            loss = abs(daily_loss_pct)
            if loss > threshold:
                self._notifications.notify(
                    category=NotificationCategory.RISK.value,
                    title="Günlük Zarar Alarmı",
                    message=f"Günlük kayıp %{loss:.1f}, maksimum sınır %{threshold:.1f}'i aştı!",
                    severity="HIGH",
                )
                return True
            return False

    @otel_trace("alert_engine.check_position_limit")
    def check_position_limit(self, ticker: str, position_pct: float) -> bool:
        """Tek hisse portföy ağırlık limitini denetler.

        Args:
            ticker: Hisse sembolü.
            position_pct: Hisse portföy yüzdesi (%).

        Returns:
            bool: Limit aşıldıysa True.
        """
        with self._lock:
            threshold = self._thresholds["position_limit_pct"]
            if position_pct > threshold:
                self._notifications.notify(
                    category=NotificationCategory.RISK.value,
                    title="Pozisyon Ağırlık Limiti Aşıldı",
                    message=f"{ticker} hissesi %{position_pct:.1f} ağırlık ile sınır %{threshold:.1f}'i geçti!",
                    severity="HIGH",
                )
                return True
            return False

    @otel_trace("alert_engine.check_sector_limit")
    def check_sector_limit(self, sector: str, sector_pct: float) -> bool:
        """Sektör toplam portföy ağırlık limitini denetler.

        Args:
            sector: Sektör adı.
            sector_pct: Sektör portföy yüzdesi (%).

        Returns:
            bool: Limit aşıldıysa True.
        """
        with self._lock:
            threshold = self._thresholds["sector_limit_pct"]
            if sector_pct > threshold:
                self._notifications.notify(
                    category=NotificationCategory.RISK.value,
                    title="Sektör Konsantrasyon Limiti Aşıldı",
                    message=f"{sector} sektörü %{sector_pct:.1f} ağırlık ile sınır %{threshold:.1f}'i geçti!",
                    severity="HIGH",
                )
                return True
            return False

    def __repr__(self) -> str:
        """Alarm motoru metin gösterimi.

        Returns:
            str: Eşik değerleri özeti.
        """
        with self._lock:
            return f"AlertEngine(esikler={self._thresholds})"


# =====================================================
# 5. DURUM ANLIK GÖRÜNTÜSÜ (SNAPSHOT SYSTEM)
# =====================================================


class SnapshotSystem:
    """Sistem çalışma zamanı durum anlık görüntülerini (snapshot) yöneten servis."""

    def __init__(self) -> None:
        """Snapshot servisini başlatır."""
        self._lock = threading.RLock()
        self._snapshots: list[SystemSnapshot] = []

    @otel_trace("snapshot_system.take_snapshot")
    def take_snapshot(self, state: dict[str, Any]) -> SystemSnapshot:
        """Yeni bir durum snapshot'ı kaydeder.

        Args:
            state: Saklanacak durum sözlüğü.

        Returns:
            SystemSnapshot: Üretilen anlık görüntü nesnesi.
        """
        with self._lock:
            now_iso = datetime.now(UTC).isoformat()
            snapshot = SystemSnapshot(timestamp=now_iso, state=state)
            self._snapshots.append(snapshot)
            if len(self._snapshots) > DEFAULT_MAX_SNAPSHOTS:
                self._snapshots = self._snapshots[-DEFAULT_MAX_SNAPSHOTS:]
            return snapshot

    @otel_trace("snapshot_system.get_latest")
    def get_latest(self) -> dict[str, Any] | None:
        """En son alınan durum snapshot'ını döndürür.

        Returns:
            dict[str, Any] | None: En son durum veya None.
        """
        with self._lock:
            return self._snapshots[-1].to_dict() if self._snapshots else None

    @otel_trace("snapshot_system.get_history")
    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Son N adet snapshot geçmişini döndürür.

        Args:
            limit: Maksimum geçmiş adedi.

        Returns:
            list[dict[str, Any]]: Geçmiş snapshot listesi.
        """
        with self._lock:
            return [s.to_dict() for s in self._snapshots[-limit:]]

    def export_to_polars(self) -> pl.DataFrame:
        """Kayıtlı sistem snapshot'larını Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Snapshot tablosu.
        """
        with self._lock:
            schema = {
                "timestamp": pl.String,
                "state_json": pl.String,
                "key_count": pl.Int64,
            }
            if not self._snapshots:
                return pl.DataFrame(schema=schema)
            rows = [
                {
                    "timestamp": s.timestamp,
                    "state_json": s.to_orjson_bytes().decode("utf-8"),
                    "key_count": len(s.state),
                }
                for s in self._snapshots
            ]
            return pl.DataFrame(rows, schema=schema)

    def export_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """Sistem snapshot'larını DuckDB `bist_system_snapshots` tablosuna yazar.

        Args:
            db_path: DuckDB veritabanı yolu.

        Returns:
            int: Depolanan snapshot adedi.
        """
        df = self.export_to_polars()
        if df.is_empty():
            return 0

        target_path = Path(db_path) if db_path is not None else DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.is_file() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_system_snapshots (
                    timestamp VARCHAR PRIMARY KEY,
                    state_json VARCHAR,
                    key_count BIGINT,
                    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            arrow_table = df.to_arrow()
            con.register("snap_arrow", arrow_table)
            con.execute("""
                INSERT OR REPLACE INTO bist_system_snapshots (timestamp, state_json, key_count)
                SELECT timestamp, state_json, key_count
                FROM snap_arrow
            """)
            con.unregister("snap_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    @staticmethod
    def query_snapshots_duckdb(
        db_path: str | Path | None = None,
        limit: int = 50,
    ) -> pl.DataFrame:
        """DuckDB bist_system_snapshots tablosundan Polars DataFrame olarak durum kayıtlarını sorgular.

        Args:
            db_path: DuckDB veritabanı yolu.
            limit: Maksimum kayıt adedi.

        Returns:
            pl.DataFrame: Durum görüntüleri veri çerçevesi.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH
        if not target_path.exists() or (target_path.is_file() and target_path.stat().st_size == 0):
            return pl.DataFrame()

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            query = "SELECT * FROM bist_system_snapshots ORDER BY recorded_at DESC LIMIT ?"
            return con.execute(query, [limit]).pl()
        finally:
            con.close()

    def clear(self) -> None:
        """Hafızadaki tüm durum anlık görüntülerini temizler."""
        with self._lock:
            self._snapshots.clear()

    def __repr__(self) -> str:
        """Snapshot servisi metin gösterimi.

        Returns:
            str: Kayıt sayısı özeti.
        """
        with self._lock:
            return f"SnapshotSystem(toplam_snapshot={len(self._snapshots)})"


# =====================================================
# 6. TTL TABANLI ÖNBELLEK (CACHE SYSTEM)
# =====================================================


class CacheSystem:
    """TTL (Time-To-Live) süresi destekli, thread-safe hafıza içi önbellek servisi."""

    def __init__(self) -> None:
        """Önbellek servisini başlatır."""
        self._lock = threading.RLock()
        self._cache: dict[str, dict[str, Any]] = {}

    @otel_trace("cache_system.get")
    def get(self, key: str) -> Any | None:
        """Önbellekten anahtara karşılık gelen değeri okur. Süresi dolduysa siler.

        Args:
            key: Önbellek anahtarı.

        Returns:
            Any | None: Değer veya geçerli değilse None.
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                expires_at = entry.get("expires_at")
                if expires_at and time.time() > expires_at:
                    del self._cache[key]
                    return None
                return entry.get("value")
            return None

    @otel_trace("cache_system.set")
    def set(self, key: str, value: Any, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        """Önbelleğe anahtar-değer çiftini belirtilen TTL ile kaydeder.

        Args:
            key: Önbellek anahtarı.
            value: Saklanacak değer.
            ttl_seconds: Yaşam süresi (saniye).
        """
        with self._lock:
            now_ts = time.time()
            if len(self._cache) >= DEFAULT_MAX_CACHE_ENTRIES:
                expired_keys = [k for k, v in self._cache.items() if v.get("expires_at") and now_ts > v["expires_at"]]
                for k in expired_keys:
                    del self._cache[k]
                if len(self._cache) >= DEFAULT_MAX_CACHE_ENTRIES:
                    excess = len(self._cache) - DEFAULT_MAX_CACHE_ENTRIES + 1
                    oldest_keys = sorted(
                        self._cache.keys(),
                        key=lambda k: self._cache[k].get("expires_at", 0),
                    )[:excess]
                    for k in oldest_keys:
                        del self._cache[k]

            self._cache[key] = {
                "value": value,
                "expires_at": now_ts + ttl_seconds,
                "created_at": datetime.now(UTC).isoformat(),
            }

    @otel_trace("cache_system.invalidate")
    def invalidate(self, key: str) -> None:
        """Belirtilen anahtarı önbellekten temizler.

        Args:
            key: Silinecek anahtar.
        """
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Önbellekteki tüm kayıtları temizler."""
        with self._lock:
            self._cache.clear()

    @otel_trace("cache_system.get_stats")
    def get_stats(self) -> dict[str, Any]:
        """Önbellek istatistiklerini döndürür.

        Returns:
            dict[str, Any]: Önbellek doluluk bilgisi.
        """
        with self._lock:
            return {"entries": len(self._cache)}

    def __enter__(self) -> CacheSystem:
        """Context manager başlangıcı."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager çıkışı: önbellek içeriğini temizler."""
        self.clear()

    def __repr__(self) -> str:
        """Önbellek metin gösterimi.

        Returns:
            str: Önbellek anahtar sayısı özeti.
        """
        with self._lock:
            return f"CacheSystem(anahtar_sayisi={len(self._cache)})"


# =====================================================
# 7. ÖNCELİKLİ İŞ KUYRUĞU (JOB QUEUE)
# =====================================================


class JobQueue:
    """Öncelik sıralı, thread-safe arka plan iş kuyruğu servisi."""

    def __init__(self) -> None:
        """İş kuyruğunu başlatır."""
        self._lock = threading.RLock()
        self._queue: list[JobItem] = []
        self._running: list[JobItem] = []
        self._completed: list[JobItem] = []

    @otel_trace("job_queue.enqueue")
    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        priority: str = "NORMAL",
    ) -> str:
        """Kuyruğa yeni bir iş ekler.

        Args:
            job_type: İş türü adı.
            payload: İş parametreleri.
            priority: Öncelik derecesi (CRITICAL, HIGH, NORMAL, LOW).

        Returns:
            str: Üretilen tekil iş kimliği (job_id).
        """
        with self._lock:
            now_iso = datetime.now(UTC).isoformat()
            seed = f"{job_type}:{now_iso}:{time.time_ns()}".encode()
            job_id = hashlib.sha256(seed).hexdigest()[:12]

            job = JobItem(
                job_id=job_id,
                job_type=job_type,
                payload=payload,
                priority=priority,
                status="QUEUED",
                created_at=now_iso,
            )
            self._queue.append(job)
            if len(self._queue) > DEFAULT_MAX_QUEUE_SIZE:
                self._queue = self._queue[-DEFAULT_MAX_QUEUE_SIZE:]

            logger.info("is_kuyruga_eklendi", job_id=job_id, tip=job_type, oncelik=priority)
            return job_id

    @otel_trace("job_queue.dequeue")
    def dequeue(self) -> dict[str, Any] | None:
        """Öncelik sırasına göre sıradaki işi çeker ve çalışma durumuna alır.

        Returns:
            dict[str, Any] | None: Sıradaki iş sözlüğü veya kuyruk boşsa None.
        """
        with self._lock:
            if not self._queue:
                return None

            priority_order = {
                "CRITICAL": 0,
                "HIGH": 1,
                "NORMAL": 2,
                "LOW": 3,
                EventPriority.CRITICAL: 0,
                EventPriority.HIGH: 1,
                EventPriority.NORMAL: 2,
                EventPriority.LOW: 3,
            }
            self._queue.sort(
                key=lambda x: priority_order.get(x.priority, priority_order.get(str(x.priority).upper(), 2))
            )
            job = self._queue.pop(0)
            job.status = "RUNNING"
            self._running.append(job)
            if len(self._running) > DEFAULT_MAX_COMPLETED_JOBS:
                self._running = self._running[-DEFAULT_MAX_COMPLETED_JOBS:]

            return job.to_dict()

    @otel_trace("job_queue.complete")
    def complete(self, job_id: str, result: Any = None) -> None:
        """Çalışan bir işin başarıyla tamamlandığını kaydeder.

        Args:
            job_id: Tamamlanan işin kimliği.
            result: İşlem sonucu veya çıktısı.
        """
        with self._lock:
            for i, job in enumerate(self._running):
                if job.job_id == job_id:
                    job.status = "COMPLETED"
                    job.result = result
                    job.completed_at = datetime.now(UTC).isoformat()
                    completed_job = self._running.pop(i)
                    self._completed.append(completed_job)
                    if len(self._completed) > DEFAULT_MAX_COMPLETED_JOBS:
                        self._completed = self._completed[-DEFAULT_MAX_COMPLETED_JOBS:]
                    logger.info("is_tamamlandi", job_id=job_id)
                    return
            logger.warning("calisan_is_bulunamadi", job_id=job_id)

    @otel_trace("job_queue.fail")
    def fail(self, job_id: str, error: str) -> None:
        """Çalışan veya kuyruktaki bir işin başarısız olduğunu kaydeder.

        Args:
            job_id: Başarısız olan işin kimliği.
            error: Hata mesajı veya nedeni.
        """
        with self._lock:
            for i, job in enumerate(self._running):
                if job.job_id == job_id:
                    job.status = "FAILED"
                    job.result = {"error": error}
                    job.completed_at = datetime.now(UTC).isoformat()
                    failed_job = self._running.pop(i)
                    self._completed.append(failed_job)
                    if len(self._completed) > DEFAULT_MAX_COMPLETED_JOBS:
                        self._completed = self._completed[-DEFAULT_MAX_COMPLETED_JOBS:]
                    logger.warning("is_basarisiz_oldu", job_id=job_id, hata=error)
                    return
            for i, job in enumerate(self._queue):
                if job.job_id == job_id:
                    job.status = "FAILED"
                    job.result = {"error": error}
                    job.completed_at = datetime.now(UTC).isoformat()
                    failed_job = self._queue.pop(i)
                    self._completed.append(failed_job)
                    if len(self._completed) > DEFAULT_MAX_COMPLETED_JOBS:
                        self._completed = self._completed[-DEFAULT_MAX_COMPLETED_JOBS:]
                    logger.warning("kuyruktaki_is_iptal_edildi", job_id=job_id, hata=error)
                    return
            logger.warning("is_bulunamadi_basarisiz_isaretlenemedi", job_id=job_id)

    @otel_trace("job_queue.get_stats")
    def get_stats(self) -> dict[str, int]:
        """Kuyruk durum istatistiklerini döndürür.

        Returns:
            dict[str, int]: Kuyruktaki, çalışan ve tamamlanan iş sayıları.
        """
        with self._lock:
            return {
                "queued": len(self._queue),
                "running": len(self._running),
                "completed": len(self._completed),
            }

    def export_to_polars(self) -> pl.DataFrame:
        """Tamamlanan ve kuyruktaki işleri Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: İş kuyruğu tablosu.
        """
        with self._lock:
            schema = {
                "job_id": pl.String,
                "job_type": pl.String,
                "priority": pl.String,
                "status": pl.String,
                "created_at": pl.String,
                "completed_at": pl.String,
            }
            all_jobs = self._queue + self._running + self._completed
            if not all_jobs:
                return pl.DataFrame(schema=schema)
            rows = [
                {
                    "job_id": j.job_id,
                    "job_type": j.job_type,
                    "priority": j.priority,
                    "status": j.status,
                    "created_at": j.created_at,
                    "completed_at": j.completed_at or "",
                }
                for j in all_jobs
            ]
            return pl.DataFrame(rows, schema=schema)

    def export_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """İş kuyruğu geçmişini DuckDB `bist_job_queue_history` tablosuna yazar.

        Args:
            db_path: DuckDB dosya yolu.

        Returns:
            int: Kaydedilen iş sayısı.
        """
        df = self.export_to_polars()
        if df.is_empty():
            return 0

        target_path = Path(db_path) if db_path is not None else DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.is_file() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_job_queue_history (
                    job_id VARCHAR PRIMARY KEY,
                    job_type VARCHAR,
                    priority VARCHAR,
                    status VARCHAR,
                    created_at VARCHAR,
                    completed_at VARCHAR,
                    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            arrow_table = df.to_arrow()
            con.register("job_arrow", arrow_table)
            con.execute("""
                INSERT OR REPLACE INTO bist_job_queue_history (
                    job_id, job_type, priority, status, created_at, completed_at
                )
                SELECT job_id, job_type, priority, status, created_at, completed_at
                FROM job_arrow
            """)
            con.unregister("job_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    @staticmethod
    def query_jobs_duckdb(
        db_path: str | Path | None = None,
        limit: int = 50,
        status: str | None = None,
        job_type: str | None = None,
    ) -> pl.DataFrame:
        """DuckDB bist_job_queue_history tablosundan Polars DataFrame olarak işleri sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            limit: Maksimum kayıt sayısı.
            status: Opsiyonel iş durumu filtresi.
            job_type: Opsiyonel iş tipi filtresi.

        Returns:
            pl.DataFrame: İş kuyruğu geçmiş tablosu.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH
        if not target_path.exists() or (target_path.is_file() and target_path.stat().st_size == 0):
            return pl.DataFrame()

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            query = "SELECT * FROM bist_job_queue_history WHERE 1=1"
            params: list[Any] = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if job_type:
                query += " AND job_type = ?"
                params.append(job_type)
            query += " ORDER BY logged_at DESC LIMIT ?"
            params.append(limit)
            return con.execute(query, params).pl()
        finally:
            con.close()

    def clear(self) -> None:
        """Kuyruk, çalışan ve tamamlanan tüm işleri temizler."""
        with self._lock:
            self._queue.clear()
            self._running.clear()
            self._completed.clear()

    def shutdown(self) -> None:
        """İş kuyruğunu güvenli biçimde durdurur ve temizler."""
        self.clear()
        logger.info("is_kuyrugu_kapatildi")

    def __enter__(self) -> JobQueue:
        """Context manager girişi."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager çıkışı: kuyruğu güvenle durdurur."""
        self.shutdown()

    def __repr__(self) -> str:
        """İş kuyruğu metin gösterimi.

        Returns:
            str: Durum özeti.
        """
        with self._lock:
            return (
                f"JobQueue(bekleyen={len(self._queue)}, "
                f"calisan={len(self._running)}, tamamlanan={len(self._completed)})"
            )


# =====================================================
# GLOBAL SINGLETON ÖRNEKLERİ
# =====================================================

event_orchestrator: Final[EventOrchestrator] = EventOrchestrator()
catalyst_engine: Final[CatalystEngine] = CatalystEngine()
notification_system: Final[NotificationSystem] = NotificationSystem()
alert_engine: Final[AlertEngine] = AlertEngine(notification_system)
snapshot_system: Final[SnapshotSystem] = SnapshotSystem()
cache_system: Final[CacheSystem] = CacheSystem()
job_queue: Final[JobQueue] = JobQueue()


# =====================================================
# MODÜL SEVİYESİ KOLAYLIK FONKSİYONLARI (CONVENIENCE HELPERS)
# =====================================================


def notify(
    category: str,
    title: str,
    message: str,
    severity: str = "INFO",
    data: dict[str, Any] | None = None,
) -> NotificationItem:
    """Genel bildirim sistemine yeni bildirim gönderir."""
    return notification_system.notify(category, title, message, severity, data)


def get_unread_notifications(limit: int = 20) -> list[dict[str, Any]]:
    """Okunmamış son bildirimleri listeler."""
    return notification_system.get_unread(limit=limit)


def mark_notification_read(notification_id: str) -> bool:
    """Bildirimi okundu olarak işaretler."""
    return notification_system.mark_read(notification_id)


def add_catalyst(
    ticker: str,
    catalyst_type: str,
    date: str,
    importance: float,
    expected_impact: str,
    uncertainty: float = 0.5,
    description: str = "",
) -> CatalystEvent:
    """Katalizör motoruna yeni bir olay kaydeder."""
    return catalyst_engine.add_catalyst(
        ticker, catalyst_type, date, importance, expected_impact, uncertainty, description
    )


def get_upcoming_catalysts(days_ahead: int = 30, min_importance: float = 0.5) -> list[dict[str, Any]]:
    """Yaklaşan önemli piyasa ve şirket katalizörlerini getirir."""
    return catalyst_engine.get_upcoming(days_ahead=days_ahead, min_importance=min_importance)


def check_portfolio_risk(drawdown_pct: float, daily_loss_pct: float) -> dict[str, bool]:
    """Portföy çekilme ve günlük zarar risk kontrollerini icra eder."""
    dd_alarm = alert_engine.check_drawdown(drawdown_pct)
    loss_alarm = alert_engine.check_daily_loss(daily_loss_pct)
    return {"drawdown_breach": dd_alarm, "daily_loss_breach": loss_alarm}


def take_snapshot(state: dict[str, Any]) -> SystemSnapshot:
    """Sistem anlık durum görüntüsünü kaydeder."""
    return snapshot_system.take_snapshot(state)


def get_latest_snapshot() -> dict[str, Any] | None:
    """En son sistem snapshot'ını döndürür."""
    return snapshot_system.get_latest()


def cache_get(key: str) -> Any | None:
    """Hafıza içi önbellekten veri okur."""
    return cache_system.get(key)


def cache_set(key: str, value: Any, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
    """Hafıza içi önbelleğe değer kaydeder."""
    cache_system.set(key, value, ttl_seconds=ttl_seconds)


def cache_invalidate(key: str) -> None:
    """Önbellekten belirtilen anahtarı siler."""
    cache_system.invalidate(key)


def enqueue_job(job_type: str, payload: dict[str, Any], priority: str = "NORMAL") -> str:
    """İş kuyruğuna yeni görev ekler."""
    return job_queue.enqueue(job_type, payload, priority=priority)


def dequeue_job() -> dict[str, Any] | None:
    """İş kuyruğundan sıradaki görevi alır."""
    return job_queue.dequeue()


def complete_job(job_id: str, result: Any = None) -> None:
    """Görev tamamlanma durumunu işler."""
    job_queue.complete(job_id, result=result)


def fail_job(job_id: str, error: str) -> None:
    """Görev başarısızlık durumunu işler."""
    job_queue.fail(job_id, error=error)


def get_event_orchestrator() -> EventOrchestrator:
    """Merkezi olay yöneticisi tekil örneğini döndürür."""
    return event_orchestrator


def get_catalyst_engine() -> CatalystEngine:
    """Katalizör motoru tekil örneğini döndürür."""
    return catalyst_engine


def get_notification_system() -> NotificationSystem:
    """Bildirim sistemi tekil örneğini döndürür."""
    return notification_system


def get_alert_engine() -> AlertEngine:
    """Alarm motoru tekil örneğini döndürür."""
    return alert_engine


def get_snapshot_system() -> SnapshotSystem:
    """Sistem durum anlık görüntü servisi tekil örneğini döndürür."""
    return snapshot_system


def get_cache_system() -> CacheSystem:
    """Önbellek servisi tekil örneğini döndürür."""
    return cache_system


def get_job_queue() -> JobQueue:
    """İş kuyruğu servisi tekil örneğini döndürür."""
    return job_queue


def query_catalysts_duckdb(
    db_path: str | Path | None = None,
    limit: int = 100,
    ticker: str | None = None,
    min_importance: float = 0.0,
) -> pl.DataFrame:
    """DuckDB üzerinden kayıtlı katalizörleri doğrudan Polars DataFrame olarak sorgular."""
    return CatalystEngine.query_catalysts_duckdb(
        db_path=db_path, limit=limit, ticker=ticker, min_importance=min_importance
    )


def query_notifications_duckdb(
    db_path: str | Path | None = None,
    limit: int = 50,
    category: str | None = None,
    unread_only: bool = False,
) -> pl.DataFrame:
    """DuckDB üzerinden bildirimleri doğrudan Polars DataFrame olarak sorgular."""
    return NotificationSystem.query_notifications_duckdb(
        db_path=db_path, limit=limit, category=category, unread_only=unread_only
    )


def query_snapshots_duckdb(
    db_path: str | Path | None = None,
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB üzerinden sistem snapshot kayıtlarını doğrudan Polars DataFrame olarak sorgular."""
    return SnapshotSystem.query_snapshots_duckdb(db_path=db_path, limit=limit)


def query_jobs_duckdb(
    db_path: str | Path | None = None,
    limit: int = 50,
    status: str | None = None,
    job_type: str | None = None,
) -> pl.DataFrame:
    """DuckDB üzerinden iş kuyruğu geçmişini doğrudan Polars DataFrame olarak sorgular."""
    return JobQueue.query_jobs_duckdb(
        db_path=db_path, limit=limit, status=status, job_type=job_type
    )


def export_catalysts_to_polars() -> pl.DataFrame:
    """Kayıtlı tüm katalizörleri Polars DataFrame formatında dışa aktarır."""
    return catalyst_engine.export_to_polars()


def export_catalysts_to_duckdb(db_path: str | Path | None = None) -> int:
    """Kayıtlı katalizörleri DuckDB bist_catalysts tablosuna kaydeder."""
    return catalyst_engine.export_to_duckdb(db_path=db_path)


def export_notifications_to_polars() -> pl.DataFrame:
    """Kayıtlı bildirimleri Polars DataFrame formatında dışa aktarır."""
    return notification_system.export_to_polars()


def export_notifications_to_duckdb(db_path: str | Path | None = None) -> int:
    """Kayıtlı bildirimleri DuckDB bist_notifications tablosuna kaydeder."""
    return notification_system.export_to_duckdb(db_path=db_path)


def export_snapshots_to_polars() -> pl.DataFrame:
    """Sistem snapshot kayıtlarını Polars DataFrame formatında dışa aktarır."""
    return snapshot_system.export_to_polars()


def export_snapshots_to_duckdb(db_path: str | Path | None = None) -> int:
    """Sistem snapshot kayıtlarını DuckDB bist_system_snapshots tablosuna kaydeder."""
    return snapshot_system.export_to_duckdb(db_path=db_path)


def export_jobs_to_polars() -> pl.DataFrame:
    """İş kuyruğu kayıtlarını Polars DataFrame formatında dışa aktarır."""
    return job_queue.export_to_polars()


def export_jobs_to_duckdb(db_path: str | Path | None = None) -> int:
    """İş kuyruğu kayıtlarını DuckDB bist_job_queue_history tablosuna kaydeder."""
    return job_queue.export_to_duckdb(db_path=db_path)


__all__: list[str] = [
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_DAILY_LOSS_PCT",
    "DEFAULT_INFRASTRUCTURE_AUDIT_DB_PATH",
    "DEFAULT_INFRASTRUCTURE_MAX_QUEUE_SIZE",
    "DEFAULT_MAX_CACHE_ENTRIES",
    "DEFAULT_MAX_CATALYSTS",
    "DEFAULT_MAX_COMPLETED_JOBS",
    "DEFAULT_MAX_DRAWDOWN_PCT",
    "DEFAULT_MAX_NOTIFICATIONS",
    "DEFAULT_MAX_QUEUE_SIZE",
    "DEFAULT_MAX_SNAPSHOTS",
    "DEFAULT_POSITION_LIMIT_PCT",
    "DEFAULT_SECTOR_LIMIT_PCT",
    "AlertEngine",
    "CacheSystem",
    "CatalystEngine",
    "CatalystEvent",
    "EventOrchestrator",
    "EventPriority",
    "JobItem",
    "JobQueue",
    "NotificationCategory",
    "NotificationItem",
    "NotificationSystem",
    "SnapshotSystem",
    "SystemSnapshot",
    "add_catalyst",
    "alert_engine",
    "cache_get",
    "cache_invalidate",
    "cache_set",
    "cache_system",
    "catalyst_engine",
    "check_portfolio_risk",
    "complete_job",
    "dequeue_job",
    "enqueue_job",
    "event_orchestrator",
    "export_catalysts_to_duckdb",
    "export_catalysts_to_polars",
    "export_jobs_to_duckdb",
    "export_jobs_to_polars",
    "export_notifications_to_duckdb",
    "export_notifications_to_polars",
    "export_snapshots_to_duckdb",
    "export_snapshots_to_polars",
    "fail_job",
    "get_alert_engine",
    "get_cache_system",
    "get_catalyst_engine",
    "get_event_orchestrator",
    "get_job_queue",
    "get_latest_snapshot",
    "get_notification_system",
    "get_snapshot_system",
    "get_upcoming_catalysts",
    "get_unread_notifications",
    "job_queue",
    "mark_notification_read",
    "notification_system",
    "notify",
    "query_catalysts_duckdb",
    "query_jobs_duckdb",
    "query_notifications_duckdb",
    "query_snapshots_duckdb",
    "snapshot_system",
    "take_snapshot",
]
