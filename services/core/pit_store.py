from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Modül Sabitleri
DEFAULT_PIT_STORE_DUCKDB_PATH: Final[str] = "data/pit_store.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(
    conn: duckdb.DuckDBPyConnection,
    checkpoint_threshold: str = DEFAULT_CHECKPOINT_SIZE,
    wal_autocheckpoint: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB WAL boyutunu optimize eder."""
    try:
        conn.execute(f"SET checkpoint_threshold = '{checkpoint_threshold}';")
        conn.execute(f"SET wal_autocheckpoint = '{wal_autocheckpoint}';")
    except Exception as e:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(e))


def _ensure_utc_datetime(dt_val: datetime | str) -> datetime:
    """Tarih girdisini doğrular ve UTC farkındalıklı datetime nesnesine çevirir."""
    if isinstance(dt_val, str):
        parsed = datetime.fromisoformat(dt_val)
    else:
        parsed = dt_val
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


@dataclass(slots=True)
class PITRecord:
    """Point-in-Time kayıt veri modeli.

    Attributes:
        ticker: Hisse/enstrüman sembolü.
        field_name: Alan adı (fiyat, ciro, f/k vb.).
        value: Kaydedilen değer.
        valid_from: Verinin açıklandığı / bilindiği başlangıç anı (UTC).
        valid_until: Verinin düzeltildiği veya geçerliliğini yitirdiği an (UTC).
        source: Veri kaynağı (KAP, Finnet, Matriks vb.).
        revision: Bu alan için kaçıncı revizyon olduğu.
    """

    ticker: str
    field_name: str
    value: Any
    valid_from: datetime
    valid_until: datetime | None = None
    source: str = ""
    revision: int = 0

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        v_until = self.valid_until.isoformat() if self.valid_until else "None"
        return (
            f"PITRecord(ticker={self.ticker!r}, field={self.field_name!r}, "
            f"value={self.value!r}, rev={self.revision}, from={self.valid_from.isoformat()}, until={v_until})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "ticker": self.ticker,
            "field_name": self.field_name,
            "value": self.value,
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "source": self.source,
            "revision": self.revision,
        }

    def to_orjson_bytes(self) -> bytes:
        """Kayıt verilerini yüksek hızlı orjson bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)


class PointInTimeStore:
    """Point-in-Time veri deposu.

    Kritik kural: Backtest'te sadece o tarihte bilinen veri kullanılır.
    Sonradan düzeltilmiş bilanço veya revizyon geçmişe sızamaz (Look-ahead bias engellenir).
    Tüm işlemler thread-safe reentrant kilit (RLock) ile korunur.
    DuckDB üzerinden kalıcı durum saklama ve kurtarma (self-healing) yeteneği mevcuttur.
    """

    def __init__(self, duckdb_path: str = DEFAULT_PIT_STORE_DUCKDB_PATH) -> None:
        self._lock = threading.RLock()
        self._duckdb_path = duckdb_path
        # ticker → field_name → [PITRecord] (zaman sıralı)
        self._store: dict[str, dict[str, list[PITRecord]]] = {}

    @otel_trace("pit_store.insert")
    def insert(
        self,
        ticker: str,
        field_name: str,
        value: Any,
        valid_from: datetime | str,
        source: str = "",
    ) -> PITRecord:
        """Yeni veri kaydet (veya mevcut kaydı güncelle).

        Args:
            ticker: Hisse/enstrüman sembolü.
            field_name: Alan adı (örn. 'pe_ratio', 'net_income').
            value: Kaydedilecek değer.
            valid_from: Verinin bilindiği/açıklandığı başlangıç tarihi.
            source: Veri kaynağı (KAP, Finnet, vb.).

        Returns:
            Oluşturulan PITRecord nesnesi.
        """
        valid_from_dt = _ensure_utc_datetime(valid_from)

        with self._lock:
            if ticker not in self._store:
                self._store[ticker] = {}
            if field_name not in self._store[ticker]:
                self._store[ticker][field_name] = []

            records = self._store[ticker][field_name]

            # Mevcut kaydın valid_until'ünü güncelle
            if records:
                last = records[-1]
                if last.valid_until is None and last.valid_from <= valid_from_dt:
                    last.valid_until = valid_from_dt

            # Yeni kayıt ekle
            new_record = PITRecord(
                ticker=ticker,
                field_name=field_name,
                value=value,
                valid_from=valid_from_dt,
                source=source,
                revision=len(records),
            )
            records.append(new_record)
            # Zaman sıralamasını garanti et
            records.sort(key=lambda r: r.valid_from)
            logger.debug(
                "pit_kaydi_eklendi",
                hisse=ticker,
                alan=field_name,
                revizyon=new_record.revision,
                gecerli_tarih=str(valid_from_dt),
            )
            return new_record

    @otel_trace("pit_store.get_as_of")
    def get_as_of(
        self,
        ticker: str,
        field_name: str,
        as_of_date: datetime | str,
    ) -> Any | None:
        """Belirli bir tarihte bilinen en güncel değeri döndür.

        Kritik kural: Sadece as_of_date'ten ÖNCE bilinen veriyi döndürür.

        Args:
            ticker: Hisse sembolü.
            field_name: Alan adı.
            as_of_date: Sorgulanan referans tarihi.

        Returns:
            O tarihte bilinen değer veya None.
        """
        as_of_dt = _ensure_utc_datetime(as_of_date)

        with self._lock:
            records = self._store.get(ticker, {}).get(field_name, [])
            # as_of_date'ten önceki en son kayıt (tersten tarama)
            for record in reversed(records):
                if record.valid_from <= as_of_dt:
                    return record.value
            return None

    @otel_trace("pit_store.get_latest")
    def get_latest(self, ticker: str, field_name: str) -> Any | None:
        """En son kaydedilen değeri döndürür.

        Args:
            ticker: Hisse sembolü.
            field_name: Alan adı.

        Returns:
            En son kayıt değeri veya None.
        """
        with self._lock:
            records = self._store.get(ticker, {}).get(field_name, [])
            return records[-1].value if records else None

    @otel_trace("pit_store.get_history")
    def get_history(
        self,
        ticker: str,
        field_name: str,
        from_date: datetime | str | None = None,
        to_date: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """Değer revizyon geçmişini döndürür.

        Args:
            ticker: Hisse sembolü.
            field_name: Alan adı.
            from_date: Başlangıç tarihi filtresi (dahil).
            to_date: Bitiş tarihi filtresi (dahil).

        Returns:
            Revizyon sözlükleri listesi.
        """
        from_dt = _ensure_utc_datetime(from_date) if from_date is not None else None
        to_dt = _ensure_utc_datetime(to_date) if to_date is not None else None

        with self._lock:
            records = self._store.get(ticker, {}).get(field_name, [])
            result: list[dict[str, Any]] = []

            for r in records:
                if from_dt and r.valid_from < from_dt:
                    continue
                if to_dt and r.valid_from > to_dt:
                    continue
                result.append(r.to_dict())

            return result

    def get_history_df(
        self,
        ticker: str,
        field_name: str,
        from_date: datetime | str | None = None,
        to_date: datetime | str | None = None,
    ) -> pl.DataFrame:
        """Değer geçmişini Polars DataFrame olarak döndürür.

        Args:
            ticker: Hisse sembolü.
            field_name: Alan adı.
            from_date: Başlangıç tarihi.
            to_date: Bitiş tarihi.

        Returns:
            Polars DataFrame.
        """
        history = self.get_history(ticker, field_name, from_date, to_date)
        if not history:
            return pl.DataFrame(
                schema={
                    "ticker": pl.String,
                    "field_name": pl.String,
                    "value": pl.String,
                    "valid_from": pl.String,
                    "valid_until": pl.String,
                    "source": pl.String,
                    "revision": pl.Int64,
                }
            )
        # Değer alanını tip güvenliği için string normalizasyonundan geçir
        normalized = []
        for h in history:
            item = dict(h)
            item["value"] = str(item["value"]) if item["value"] is not None else None
            normalized.append(item)
        return pl.from_dicts(normalized)

    @otel_trace("pit_store.get_revisions")
    def get_revisions(self, ticker: str, field_name: str) -> int:
        """Toplam revizyon sayısını döndürür."""
        with self._lock:
            return len(self._store.get(ticker, {}).get(field_name, []))

    @otel_trace("pit_store.bulk_insert")
    def bulk_insert(
        self,
        ticker: str,
        data: dict[str, Any],
        valid_from: datetime | str,
        source: str = "",
    ) -> int:
        """Toplu veri kaydetme.

        Args:
            ticker: Hisse sembolü.
            data: Alan adı ve değer sözlüğü.
            valid_from: Başlangıç geçerlilik tarihi.
            source: Kaynak bilgisi.

        Returns:
            Eklenen kayıt sayısı.
        """
        count = 0
        with self._lock:
            for field_name, value in data.items():
                self.insert(ticker, field_name, value, valid_from, source)
                count += 1
        return count

    @otel_trace("pit_store.get_stats")
    def get_stats(self) -> dict[str, Any]:
        """Depo istatistiklerini döndürür."""
        with self._lock:
            total_records = sum(len(records) for fields in self._store.values() for records in fields.values())
            return {
                "tickers": len(self._store),
                "total_records": total_records,
                "duckdb_path": self._duckdb_path,
            }

    def export_store_to_polars(self) -> pl.DataFrame:
        """Tüm PIT deposunu Polars DataFrame olarak dışa aktarır."""
        rows: list[dict[str, Any]] = []
        with self._lock:
            for fields in self._store.values():
                for records in fields.values():
                    for r in records:
                        item = r.to_dict()
                        item["value"] = str(item["value"]) if item["value"] is not None else None
                        rows.append(item)
        if not rows:
            return pl.DataFrame(
                schema={
                    "ticker": pl.String,
                    "field_name": pl.String,
                    "value": pl.String,
                    "valid_from": pl.String,
                    "valid_until": pl.String,
                    "source": pl.String,
                    "revision": pl.Int64,
                }
            )
        return pl.from_dicts(rows)

    def to_orjson_bytes(self) -> bytes:
        """Tüm depo verilerini yüksek hızlı orjson bayt dizisine dönüştürür."""
        rows: list[dict[str, Any]] = []
        with self._lock:
            for fields in self._store.values():
                for records in fields.values():
                    for r in records:
                        rows.append(r.to_dict())
        return orjson.dumps(rows, default=str)

    # =====================================================
    # DUCKDB PERSISTENCE & SELF-HEALING RECOVERY
    # =====================================================

    def save_to_duckdb(self, db_path: str | None = None) -> int:
        """Depodaki tüm PIT kayıtlarını DuckDB tablosuna kaydeder.

        Args:
            db_path: İsteğe bağlı hedef DuckDB yolu (varsayılan: self._duckdb_path).

        Returns:
            Kaydedilen toplam kayıt sayısı.
        """
        target_path = db_path or self._duckdb_path
        path_obj = Path(target_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        df = self.export_store_to_polars()
        if df.is_empty():
            return 0

        conn = duckdb.connect(str(path_obj))
        try:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pit_store_records (
                    ticker VARCHAR,
                    field_name VARCHAR,
                    value VARCHAR,
                    valid_from VARCHAR,
                    valid_until VARCHAR,
                    source VARCHAR,
                    revision BIGINT,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, field_name, revision)
                )
                """
            )
            conn.register("tmp_pit_store_df", df.to_arrow())
            conn.execute(
                """
                INSERT INTO pit_store_records (ticker, field_name, value, valid_from, valid_until, source, revision)
                SELECT ticker, field_name, value, valid_from, valid_until, source, revision
                FROM tmp_pit_store_df
                ON CONFLICT (ticker, field_name, revision) DO UPDATE SET
                    value = EXCLUDED.value,
                    valid_from = EXCLUDED.valid_from,
                    valid_until = EXCLUDED.valid_until,
                    source = EXCLUDED.source,
                    synced_at = now()
                """
            )
            logger.info("pit_store_duckdb_kaydedildi", kayit_sayisi=df.height, db_path=str(path_obj))
            return df.height
        finally:
            conn.close()

    def load_from_duckdb(self, db_path: str | None = None) -> int:
        """DuckDB'den kalıcı PIT kayıtlarını hafızaya geri yükler (Zero-Touch Self-Healing).

        Args:
            db_path: İsteğe bağlı hedef DuckDB yolu (varsayılan: self._duckdb_path).

        Returns:
            Yüklenen toplam kayıt sayısı.
        """
        target_path = db_path or self._duckdb_path
        path_obj = Path(target_path)
        if not path_obj.exists():
            return 0

        conn = duckdb.connect(str(path_obj), read_only=True)
        loaded_count = 0
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "pit_store_records" not in tables:
                return 0

            rows = conn.execute(
                """
                SELECT ticker, field_name, value, valid_from, valid_until, source, revision
                FROM pit_store_records
                ORDER BY ticker, field_name, revision ASC
                """
            ).fetchall()

            with self._lock:
                for row in rows:
                    ticker, f_name, val, v_from_str, v_until_str, src, rev = row
                    v_from_dt = _ensure_utc_datetime(v_from_str)
                    v_until_dt = _ensure_utc_datetime(v_until_str) if v_until_str else None

                    if ticker not in self._store:
                        self._store[ticker] = {}
                    if f_name not in self._store[ticker]:
                        self._store[ticker][f_name] = []

                    record = PITRecord(
                        ticker=ticker,
                        field_name=f_name,
                        value=val,
                        valid_from=v_from_dt,
                        valid_until=v_until_dt,
                        source=src or "",
                        revision=int(rev),
                    )
                    self._store[ticker][f_name].append(record)
                    loaded_count += 1

            logger.info("pit_store_duckdb_yuklendi", yuklenen_kayit=loaded_count, db_path=str(path_obj))
            return loaded_count
        except Exception as e:
            logger.error("pit_store_duckdb_yukleme_hatasi", hata=str(e))
            return 0
        finally:
            conn.close()

    def repair_inconsistencies(self) -> int:
        """Zaman sıralaması veya revizyon bozukluklarını otomatik onarır (Self-Healing).

        Returns:
            Onarılan kayıt sayısı.
        """
        repaired = 0
        with self._lock:
            for fields in self._store.values():
                for records in fields.values():
                    # Zaman sırasına göre yeniden sırala
                    records.sort(key=lambda r: r.valid_from)
                    for i, r in enumerate(records):
                        # Revizyon indeksini düzelt
                        if r.revision != i:
                            r.revision = i
                            repaired += 1
                        # valid_until tutarlılığı
                        if i < len(records) - 1:
                            next_from = records[i + 1].valid_from
                            if r.valid_until != next_from:
                                r.valid_until = next_from
                                repaired += 1
        if repaired > 0:
            logger.info("pit_store_tutarsizliklari_onarildi", onarilan_alan_sayisi=repaired)
        return repaired

    def clear(self) -> None:
        """Hafızadaki tüm kayıtları temizler."""
        with self._lock:
            self._store.clear()

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        with self._lock:
            total_records = sum(len(records) for fields in self._store.values() for records in fields.values())
            return f"PointInTimeStore(tickers={len(self._store)}, total_records={total_records}, duckdb={self._duckdb_path!r})"


# Singleton
pit_store = PointInTimeStore()


def export_pit_store_to_polars(store: PointInTimeStore = pit_store) -> pl.DataFrame:
    """PointInTimeStore verisini Polars DataFrame olarak dışa aktarır."""
    return store.export_store_to_polars()


def save_pit_store_to_duckdb(
    store: PointInTimeStore = pit_store,
    db_path: str = DEFAULT_PIT_STORE_DUCKDB_PATH,
) -> int:
    """Singleton veya belirtilen depoyu DuckDB'ye kalıcı yazar."""
    return store.save_to_duckdb(db_path=db_path)


def load_pit_store_from_duckdb(
    store: PointInTimeStore = pit_store,
    db_path: str = DEFAULT_PIT_STORE_DUCKDB_PATH,
) -> int:
    """DuckDB'den kayıtları depoya geri yükler."""
    return store.load_from_duckdb(db_path=db_path)


__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_PIT_STORE_DUCKDB_PATH",
    "DEFAULT_WAL_SIZE",
    "PITRecord",
    "PointInTimeStore",
    "configure_duckdb_wal",
    "export_pit_store_to_polars",
    "load_pit_store_from_duckdb",
    "pit_store",
    "save_pit_store_to_duckdb",
]

