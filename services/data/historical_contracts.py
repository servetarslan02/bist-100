"""ALPHA BIST — Tarihsel Veri Sözleşmeleri ve Arayüzleri (Historical Data Contracts).

Point-In-Time (PIT) uyumlu tarihsel veri sözleşmeleri ve soyut veri deposu arayüzleri.
Backtest ve model eğitimi süreçlerinde kullanılan tüm tarihsel veriler (temel analiz snapshot'ları,
KAP ve haber olayları, şirket katalistleri) bu sözleşmeler üzerinden doğrulanarak akar.

Temel Kural:
- `publication_date <= current_date` (veya `available_at <= current_date`) kuralına uymayan
  hiçbir veri geleceği görecek şekilde (lookahead bias) sisteme dahil edilemez.
"""

from __future__ import annotations

import abc
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# ==============================================================================
# Yapılandırma ve WAL Sabitleri
# ==============================================================================

DEFAULT_MAX_IN_MEMORY_ITEMS: Final[int] = 500
DEFAULT_CONTRACTS_AUDIT_DB_PATH: Final[str] = "data/contracts_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


# ==============================================================================
# DuckDB WAL ve orjson Yardımcıları
# ==============================================================================


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


# ==============================================================================
# Veri Sözleşmeleri (Data Contracts)
# ==============================================================================


@dataclass(slots=True)
class FundamentalSnapshot:
    """Tarihsel temel analiz verisi snapshot sözleşmesi.

    Point-In-Time Kuralı: available_at <= current_date

    Attributes:
        ticker: Hisse senedi sembolü.
        period_end: Finansal tablonun ait olduğu dönem sonu (YYYY-MM-DD).
        available_at: Tablonun kamuya açıklandığı kesin tarih (YYYY-MM-DD).
        values: Temel rasyolar ve bilanço kalemleri sözlüğü.
        source: Veri kaynağı ('fintables', 'kap', 'yfinance' vb.).
        status: Veri tazelik durumu ('FRESH', 'STALE', 'MISSING', 'UNKNOWN').
    """

    ticker: str
    period_end: str
    available_at: str
    values: dict[str, Any]
    source: str = "unknown"
    status: str = "FRESH"

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "type": "fundamental",
            "ticker": self.ticker,
            "period_end": self.period_end,
            "available_at": self.available_at,
            "values": self.values,
            "source": self.source,
            "status": self.status,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"FundamentalSnapshot(hisse='{self.ticker}', donem='{self.period_end}', "
            f"yayin='{self.available_at}', durum='{self.status}')"
        )


@dataclass(slots=True)
class EventSnapshot:
    """Tarihsel KAP veya haber olayı snapshot sözleşmesi.

    Point-In-Time Kuralı: published_at <= current_date

    Attributes:
        event_id: Tekil olay kimliği.
        ticker: İlgili hisse kodu.
        published_at: Yayınlanma zaman damgası (ISO-8601).
        event_type: Olay kategorisi veya tipi.
        title: Olay başlığı.
        sentiment: Duygu skoru (-1.0 ile +1.0 arası).
        importance: Önem katsayısı (0.0 ile 1.0 arası).
        source: Veri kaynağı ('kap', 'news', 'rss').
        content: Detay metni veya özeti.
    """

    event_id: str
    ticker: str
    published_at: str
    event_type: str
    title: str = ""
    sentiment: float = 0.0
    importance: float = 0.5
    source: str = "unknown"
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "type": "event",
            "event_id": self.event_id,
            "ticker": self.ticker,
            "published_at": self.published_at,
            "event_type": self.event_type,
            "title": self.title,
            "sentiment": self.sentiment,
            "importance": self.importance,
            "source": self.source,
            "content": self.content,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"EventSnapshot(id='{self.event_id}', hisse='{self.ticker}', "
            f"tur='{self.event_type}', duygu={self.sentiment:.2f})"
        )


@dataclass(slots=True)
class CatalystSnapshot:
    """Tarihsel şirket katalisti snapshot sözleşmesi.

    Point-In-Time Kuralı: announcement_date <= current_date

    Attributes:
        event_id: Tekil katalist kimliği.
        ticker: İlgili hisse kodu.
        announcement_date: Duyurunun yapıldığı tarih.
        event_date: Olayın gerçekleşeceği/gerçekleştiği tarih.
        catalyst_type: Katalist tipi ('EARNINGS', 'DIVIDEND', 'SPLIT' vb.).
        importance: Önem katsayısı (0.0 - 1.0).
        source: Veri kaynağı.
    """

    event_id: str
    ticker: str
    announcement_date: str
    event_date: str
    catalyst_type: str
    importance: float = 0.5
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "type": "catalyst",
            "event_id": self.event_id,
            "ticker": self.ticker,
            "announcement_date": self.announcement_date,
            "event_date": self.event_date,
            "catalyst_type": self.catalyst_type,
            "importance": self.importance,
            "source": self.source,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"CatalystSnapshot(hisse='{self.ticker}', duyuru='{self.announcement_date}', "
            f"olay_tarih='{self.event_date}', tur='{self.catalyst_type}')"
        )


# ==============================================================================
# Soyut Veri Deposu Arayüzü (Repository Interface)
# ==============================================================================


class HistoricalDataRepository(abc.ABC):
    """Tarihsel veri deposu soyut taban sınıfı."""

    @abc.abstractmethod
    def get_fundamental_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> list[FundamentalSnapshot]:
        """Belirtilen tarihte bilinen temel analiz snapshot'larını döner."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_event_snapshots(
        self,
        ticker: str,
        as_of_date: str,
        event_types: list[str] | None = None,
    ) -> list[EventSnapshot]:
        """Belirtilen tarihte bilinen olay snapshot'larını döner."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_catalyst_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> list[CatalystSnapshot]:
        """Belirtilen tarihte bilinen katalist snapshot'larını döner."""
        raise NotImplementedError

    @abc.abstractmethod
    def add_fundamental_snapshot(self, snapshot: FundamentalSnapshot) -> None:
        """Yeni bir temel analiz snapshot'ı ekler."""
        raise NotImplementedError

    @abc.abstractmethod
    def add_event_snapshot(self, snapshot: EventSnapshot) -> None:
        """Yeni bir olay snapshot'ı ekler."""
        raise NotImplementedError

    @abc.abstractmethod
    def add_catalyst_snapshot(self, snapshot: CatalystSnapshot) -> None:
        """Yeni bir katalist snapshot'ı ekler."""
        raise NotImplementedError

    @abc.abstractmethod
    def clear(self) -> None:
        """Depodaki tüm verileri temizler."""
        raise NotImplementedError


# ==============================================================================
# Bellek İçi Referans Uygulama (In-Memory Implementation)
# ==============================================================================


class InMemoryHistoricalRepository(HistoricalDataRepository):
    """Birim testler ve izole mikro simülasyonlar için thread-safe bellek içi depo."""

    def __init__(self, max_items: int = DEFAULT_MAX_IN_MEMORY_ITEMS) -> None:
        """InMemoryHistoricalRepository başlatıcı.

        Args:
            max_items: Her kategoride tutulacak maksimum snapshot sayısı.
        """
        self._max_items = max(10, max_items)
        self._lock = threading.RLock()
        self._fundamentals: list[FundamentalSnapshot] = []
        self._events: list[EventSnapshot] = []
        self._catalysts: list[CatalystSnapshot] = []

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"InMemoryHistoricalRepository(temel={len(self._fundamentals)}, "
                f"olay={len(self._events)}, katalist={len(self._catalysts)})"
            )

    def to_dict(self) -> dict[str, Any]:
        """Depo durumunu sözlük formatında döner."""
        with self._lock:
            return {
                "max_items": self._max_items,
                "fundamental_count": len(self._fundamentals),
                "event_count": len(self._events),
                "catalyst_count": len(self._catalysts),
            }

    def to_orjson_bytes(self) -> bytes:
        """Depo durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def get_fundamental_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> list[FundamentalSnapshot]:
        """Tarihe göre sıralı temel analiz snapshot'larını döner."""
        with self._lock:
            clean_sym = ticker.upper().replace(".IS", "").strip()
            date_filter = as_of_date[:10]
            matched = [
                s
                for s in self._fundamentals
                if s.ticker.upper().replace(".IS", "").strip() == clean_sym and s.available_at[:10] <= date_filter
            ]
            return sorted(matched, key=lambda s: s.available_at, reverse=True)

    def get_event_snapshots(
        self,
        ticker: str,
        as_of_date: str,
        event_types: list[str] | None = None,
    ) -> list[EventSnapshot]:
        """Tarihe göre sıralı olay snapshot'larını döner."""
        with self._lock:
            clean_sym = ticker.upper().replace(".IS", "").strip()
            date_filter = as_of_date[:10]
            matched = [
                s
                for s in self._events
                if s.ticker.upper().replace(".IS", "").strip() == clean_sym and s.published_at[:10] <= date_filter
            ]
            if event_types:
                matched = [e for e in matched if e.event_type in event_types]
            return sorted(matched, key=lambda s: s.published_at, reverse=True)

    def get_catalyst_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> list[CatalystSnapshot]:
        """Tarihe göre sıralı katalist snapshot'larını döner."""
        with self._lock:
            clean_sym = ticker.upper().replace(".IS", "").strip()
            date_filter = as_of_date[:10]
            matched = [
                s
                for s in self._catalysts
                if s.ticker.upper().replace(".IS", "").strip() == clean_sym
                and s.announcement_date[:10] <= date_filter
            ]
            return sorted(matched, key=lambda s: s.announcement_date, reverse=True)

    def add_fundamental_snapshot(self, snapshot: FundamentalSnapshot) -> None:
        """Yeni bir temel analiz snapshot'ı ekler."""
        with self._lock:
            self._fundamentals.append(snapshot)
            if len(self._fundamentals) > self._max_items:
                self._fundamentals = self._fundamentals[-self._max_items :]

    def add_event_snapshot(self, snapshot: EventSnapshot) -> None:
        """Yeni bir olay snapshot'ı ekler."""
        with self._lock:
            self._events.append(snapshot)
            if len(self._events) > self._max_items:
                self._events = self._events[-self._max_items :]

    def add_catalyst_snapshot(self, snapshot: CatalystSnapshot) -> None:
        """Yeni bir katalist snapshot'ı ekler."""
        with self._lock:
            self._catalysts.append(snapshot)
            if len(self._catalysts) > self._max_items:
                self._catalysts = self._catalysts[-self._max_items :]

    def clear(self) -> None:
        """Depodaki tüm listeleri sıfırlar."""
        with self._lock:
            self._fundamentals.clear()
            self._events.clear()
            self._catalysts.clear()


# ==============================================================================
# DuckDB Kalıcılık ve Yardımcı Fonksiyonlar
# ==============================================================================


def export_snapshot_to_duckdb(
    snapshot: FundamentalSnapshot | EventSnapshot | CatalystSnapshot,
    db_path: str = DEFAULT_CONTRACTS_AUDIT_DB_PATH,
) -> int:
    """Snapshot verisini DuckDB denetim tablosuna kaydeder.

    Args:
        snapshot: Kaydedilecek sözleşme snapshot nesnesi.
        db_path: DuckDB dosya yolu.

    Returns:
        int: Eklenen kayıt sayısı (1).
    """
    target_file = Path(db_path)
    target_file.parent.mkdir(parents=True, exist_ok=True)

    row_id = uuid.uuid4().hex
    snap_dict = snapshot.to_dict()
    snap_type = snap_dict.get("type", "unknown")
    ticker = snap_dict.get("ticker", "UNKNOWN")

    row = (
        row_id,
        datetime.now(UTC),
        snap_type,
        ticker,
        orjson.dumps(snap_dict, default=str).decode("utf-8"),
    )

    try:
        with duckdb.connect(str(target_file)) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contract_snapshot_audit (
                    id VARCHAR PRIMARY KEY,
                    created_at TIMESTAMP,
                    snapshot_type VARCHAR,
                    ticker VARCHAR,
                    payload_json VARCHAR
                )
                """
            )
            conn.execute(
                """
                INSERT INTO contract_snapshot_audit (
                    id, created_at, snapshot_type, ticker, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                row,
            )
        return 1
    except Exception as exc:
        logger.error("snapshot_duckdb_kayit_hatasi", hisse=ticker, hata=str(exc))
        return 0


def read_contract_audit_from_duckdb(
    db_path: str = DEFAULT_CONTRACTS_AUDIT_DB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Maksimum kayıt sayısı.

    Returns:
        pl.DataFrame: Snapshot denetim geçmişi.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "id": pl.Utf8,
        "created_at": pl.Datetime,
        "snapshot_type": pl.Utf8,
        "ticker": pl.Utf8,
        "payload_json": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'contract_snapshot_audit'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = (
                "SELECT id, created_at, snapshot_type, ticker, payload_json "
                "FROM contract_snapshot_audit ORDER BY created_at DESC LIMIT ?"
            )
            return conn.execute(query, [max(1, int(limit))]).pl()
    except Exception as exc:
        logger.warning("duckdb_contract_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_contract_audit_duckdb(db_path: str = DEFAULT_CONTRACTS_AUDIT_DB_PATH) -> None:
    """DuckDB denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS contract_snapshot_audit;")
    except Exception as exc:
        logger.error("duckdb_contract_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: Final[list[str]] = [
    # Sabitler
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_CONTRACTS_AUDIT_DB_PATH",
    "DEFAULT_MAX_IN_MEMORY_ITEMS",
    "DEFAULT_WAL_SIZE",
    # Modeller
    "CatalystSnapshot",
    "EventSnapshot",
    "FundamentalSnapshot",
    # Depo Arayüzü ve Uygulaması
    "HistoricalDataRepository",
    "InMemoryHistoricalRepository",
    # Yardımcı Fonksiyonlar
    "clear_contract_audit_duckdb",
    "configure_duckdb_wal",
    "export_snapshot_to_duckdb",
    "read_contract_audit_from_duckdb",
    "to_orjson_bytes",
]
