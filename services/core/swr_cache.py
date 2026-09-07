"""
ALPHA BIST — Thread-safe SWR (Stale-While-Revalidate) In-Memory Cache v2.0

API Uç Noktaları ve Gerçek Zamanlı Servisler İçin Yüksek Performanslı Önbellek:
- Stale-While-Revalidate (SWR) Mimarisi: Bayat veri anında istemciye sunulurken arka planda asenkron yenileme.
- Hem tekil (singleton) hem de anahtarlı (multi-key / ticker bazlı) önbellek desteği.
- Deterministic ETag Üretimi (SHA-256 tabanlı yüksek hızlı orjson serileştirme).
- İş Parçacığı Güvenliği: threading.RLock() ile korunan veri ve metrik erişimi.
- DuckDB >= 1.3.0 denetim izi: Hit/Miss ve geçersiz kılma olayları yerel DuckDB tablosunda arşivlenir.
- Polars >= 1.30.0 analitik sorgulama ve orjson serileştirme desteği.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

DEFAULT_SWR_CACHE_DB: Final[str] = "data/swr_cache_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

logger = structlog.get_logger(__name__)


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("DuckDB WAL pragma uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli byte dizisine serileştirir."""
    if hasattr(val, "to_dict"):
        return orjson.dumps(val.to_dict(), default=str)
    return orjson.dumps(val, default=str)


@dataclass(slots=True)
class CacheEntry:
    """Tekil önbellek girdisi veri modeli.

    Attributes:
        data: Saklanan önbellek verisi.
        timestamp: Verinin kaydedildiği anlık zaman damgası (monotonic saniye).
        created_at: ISO formatında UTC oluşturulma zamanı.
        etag: SHA-256 tabanlı 16 karakterlik içerik parmak izi.
        hit_count: Bu girdiye yapılan başarılı erişim sayısı.
        stale_hit_count: Bayat durumdayken yapılan erişim sayısı.
    """

    data: Any
    timestamp: float
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    etag: str = ""
    hit_count: int = 0
    stale_hit_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Girdi meta verilerini sözlük olarak döndürür (büyük veriler hariç özetlenir)."""
        return {
            "etag": self.etag,
            "created_at": self.created_at.isoformat(),
            "hit_count": self.hit_count,
            "stale_hit_count": self.stale_hit_count,
        }

    def __repr__(self) -> str:
        return f"CacheEntry(etag={self.etag!r}, hits={self.hit_count}, stale_hits={self.stale_hit_count})"


@dataclass(slots=True)
class SWRCacheStats:
    """SWR Önbellek performans istatistikleri veri modeli."""

    total_keys: int
    total_hits: int
    total_misses: int
    total_stale_hits: int
    hit_ratio: float
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """İstatistikleri standart Python sözlüğüne dönüştürür."""
        data = asdict(self)
        data["updated_at"] = self.updated_at.isoformat()
        return data

    def to_orjson_bytes(self) -> bytes:
        """İstatistikleri orjson ikili baytlarına serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"SWRCacheStats(keys={self.total_keys}, hits={self.total_hits}, "
            f"misses={self.total_misses}, stale_hits={self.total_stale_hits}, ratio={self.hit_ratio:.2%})"
        )


class SWRCache:
    """Thread-safe Stale-While-Revalidate (SWR) in-memory önbellek motoru.

    Global değişkenler (_CACHE, _TIME, _ETAG) yerine kurumsal ve izlenebilir durum yönetimi sağlar.
    """

    def __init__(
        self,
        ttl_seconds: int = 60,
        stale_ttl_seconds: int = 300,
        duckdb_path: str = DEFAULT_SWR_CACHE_DB,
    ) -> None:
        """SWRCache başlatıcısı.

        Args:
            ttl_seconds: Verinin taze (fresh) kabul edildiği süre (saniye).
            stale_ttl_seconds: Verinin bayat (stale) kabul edilip sunulabileceği maksimum ek süre.
            duckdb_path: Önbellek denetim günlüğü için DuckDB dosya yolu veya ':memory:'.
        """
        self._ttl = max(1, ttl_seconds)
        self._stale_ttl = max(self._ttl, stale_ttl_seconds)
        self._lock = threading.RLock()
        self._entries: dict[str, CacheEntry] = {}
        self._total_hits = 0
        self._total_misses = 0
        self._total_stale_hits = 0
        self._duckdb_path = duckdb_path

        # DuckDB denetim tablosu kurulumu
        if self._duckdb_path != ":memory:":
            try:
                Path(self._duckdb_path).parent.mkdir(parents=True, exist_ok=True)
                self._duckdb_con = duckdb.connect(self._duckdb_path)
            except Exception as e:
                logger.warning(
                    "DuckDB disk baglantisi kurulamadi, bellege donuluyor",
                    yol=self._duckdb_path,
                    hata=str(e),
                )
                self._duckdb_con = duckdb.connect(":memory:")
        else:
            self._duckdb_con = duckdb.connect(":memory:")

        configure_duckdb_wal(self._duckdb_con)
        self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """DuckDB denetim tablosunu ve dizisini oluşturur."""
        with self._lock:
            try:
                self._duckdb_con.execute("""
                    CREATE SEQUENCE IF NOT EXISTS seq_swr_audit_id START 1;
                    CREATE TABLE IF NOT EXISTS swr_cache_audit (
                        id BIGINT DEFAULT nextval('seq_swr_audit_id') PRIMARY KEY,
                        cache_key VARCHAR NOT NULL,
                        event_type VARCHAR NOT NULL,
                        etag VARCHAR NOT NULL,
                        hit_count BIGINT NOT NULL,
                        stale_hit_count BIGINT NOT NULL,
                        recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            except Exception as exc:
                logger.error("SWRCache DuckDB schema init failed", error=str(exc))

    def _record_audit(self, key: str, event_type: str, etag: str = "") -> None:
        """Önbellek olayını yerel DuckDB tablosuna kaydeder."""
        with self._lock:
            try:
                self._duckdb_con.execute(
                    """
                    INSERT INTO swr_cache_audit
                    (cache_key, event_type, etag, hit_count, stale_hit_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [key, event_type, etag, self._total_hits, self._total_stale_hits],
                )
            except Exception as exc:
                logger.debug("SWRCache audit recording skipped", error=str(exc))

    def _generate_etag(self, data: Any) -> str:
        """Veri için SHA-256 tabanlı yüksek hızlı ETag parmak izi üretir."""
        try:
            raw_bytes = orjson.dumps(data, default=str)
        except Exception:
            raw_bytes = str(data).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()[:16]

    def is_fresh(self, key: str = "default") -> bool:
        """Belirtilen anahtarın verisi hâlâ taze mi?"""
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return False
            return (time.monotonic() - entry.timestamp) < self._ttl

    def is_stale(self, key: str = "default") -> bool:
        """Veri taze değil ancak hâlâ bayat (stale) penceresi içinde sunulabilir mi?"""
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return False
            elapsed = time.monotonic() - entry.timestamp
            return self._ttl <= elapsed < self._stale_ttl

    def etag(self, key: str = "default") -> str:
        """Mevcut anahtar için ETag değerini döndürür."""
        with self._lock:
            entry = self._entries.get(key)
            return entry.etag if entry else ""

    def get(self, key: str = "default") -> Any | None:
        """Sadece taze veri varsa döndürür, aksi takdirde None döner (Strict Cache)."""
        with self._lock:
            entry = self._entries.get(key)
            if entry and (time.monotonic() - entry.timestamp) < self._ttl:
                entry.hit_count += 1
                self._total_hits += 1
                return entry.data

            self._total_misses += 1
            return None

    def get_swr(self, key: str = "default") -> tuple[Any | None, bool, str]:
        """Stale-While-Revalidate deseni ile veri çeker.

        Returns:
            tuple[data, is_stale, etag]:
                - data: Önbellekteki veri (taze veya bayat) ya da None.
                - is_stale: Verinin bayat olup olmadığı (True ise arka planda revalidate edilmeli).
                - etag: İlgili ETag değeri.
        """
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                self._total_misses += 1
                return None, True, ""

            elapsed = time.monotonic() - entry.timestamp

            # 1. Taze Durum (Fresh)
            if elapsed < self._ttl:
                entry.hit_count += 1
                self._total_hits += 1
                return entry.data, False, entry.etag

            # 2. Bayat Durum (Stale-While-Revalidate penceresi)
            if elapsed < self._stale_ttl:
                entry.stale_hit_count += 1
                self._total_stale_hits += 1
                return entry.data, True, entry.etag

            # 3. Süresi Tamamen Dolmuş (Expired)
            self._total_misses += 1
            return None, True, entry.etag

    def set(self, data: Any, key: str = "default") -> str:
        """Önbelleği günceller ve yeni ETag değerini döndürür."""
        new_etag = self._generate_etag(data)
        now_mono = time.monotonic()

        with self._lock:
            entry = self._entries.get(key)
            if entry:
                entry.data = data
                entry.timestamp = now_mono
                entry.etag = new_etag
                entry.created_at = datetime.now(UTC)
            else:
                self._entries[key] = CacheEntry(
                    data=data,
                    timestamp=now_mono,
                    etag=new_etag,
                )

        self._record_audit(key, "SET", new_etag)
        return new_etag

    def invalidate(self, key: str | None = None) -> None:
        """Belirtilen anahtarı veya None ise tüm önbelleği temizler."""
        with self._lock:
            if key is None:
                self._entries.clear()
                self._record_audit("ALL", "INVALIDATE_ALL")
            elif key in self._entries:
                del self._entries[key]
                self._record_audit(key, "INVALIDATE")

    def get_stats(self) -> SWRCacheStats:
        """Önbellek istatistiklerini hesaplar."""
        with self._lock:
            total_requests = self._total_hits + self._total_stale_hits + self._total_misses
            hit_ratio = (
                (self._total_hits + self._total_stale_hits) / total_requests
                if total_requests > 0
                else 0.0
            )

            return SWRCacheStats(
                total_keys=len(self._entries),
                total_hits=self._total_hits,
                total_misses=self._total_misses,
                total_stale_hits=self._total_stale_hits,
                hit_ratio=hit_ratio,
            )

    def export_cache_entries_to_polars(self) -> pl.DataFrame:
        """Mevcut önbellek anahtar durumlarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            if not self._entries:
                return pl.DataFrame(
                    schema={
                        "key": pl.Utf8,
                        "etag": pl.Utf8,
                        "is_fresh": pl.Boolean,
                        "is_stale": pl.Boolean,
                        "hits": pl.Int64,
                        "stale_hits": pl.Int64,
                        "age_seconds": pl.Float64,
                    }
                )

            now_mono = time.monotonic()
            rows: list[dict[str, Any]] = []
            for k, entry in self._entries.items():
                age = now_mono - entry.timestamp
                rows.append({
                    "key": k,
                    "etag": entry.etag,
                    "is_fresh": bool(age < self._ttl),
                    "is_stale": bool(self._ttl <= age < self._stale_ttl),
                    "hits": int(entry.hit_count),
                    "stale_hits": int(entry.stale_hit_count),
                    "age_seconds": round(float(age), 3),
                })
            return pl.DataFrame(rows)

    def export_audit_to_polars(self) -> pl.DataFrame:
        """DuckDB denetim kayıtlarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            try:
                return self._duckdb_con.execute("""
                    SELECT id, cache_key, event_type, etag, hit_count, stale_hit_count, recorded_at
                    FROM swr_cache_audit
                    ORDER BY id ASC
                """).pl()
            except Exception as exc:
                logger.error("Failed to export SWR audit to Polars", error=str(exc))
                return pl.DataFrame()

    def clear_audit_duckdb(self) -> None:
        """DuckDB önbellek denetim tablosunu temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM swr_cache_audit")
            except Exception as exc:
                logger.warning("DuckDB swr audit tablosu temizlenemedi", hata=str(exc))

    def close(self) -> None:
        """DuckDB bağlantısını güvenli şekilde kapatır."""
        with self._lock:
            try:
                self._duckdb_con.close()
            except Exception as exc:
                logger.debug("DuckDB baglantisi kapatilirken hata", hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"SWRCache(keys={len(self._entries)}, ttl={self._ttl}s, "
                f"stale_ttl={self._stale_ttl}s, hits={self._total_hits}, misses={self._total_misses})"
            )


def read_swr_audit_from_duckdb(
    duckdb_path: str = DEFAULT_SWR_CACHE_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan SWR denetim kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            return conn.execute(
                """
                SELECT id, cache_key, event_type, etag, hit_count, stale_hit_count, recorded_at
                FROM swr_cache_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan SWR denetim kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_swr_audit_duckdb(duckdb_path: str = DEFAULT_SWR_CACHE_DB) -> None:
    """Belirtilen DuckDB dosyasındaki SWR denetim tablosunu sıfırlar."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            conn.execute("DELETE FROM swr_cache_audit")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB SWR denetim tablosu temizlenemedi", hata=str(exc))


# Küresel Singleton Nesnesi
swr_cache = SWRCache()

__all__ = [
    "CacheEntry",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_SWR_CACHE_DB",
    "DEFAULT_WAL_SIZE",
    "SWRCache",
    "SWRCacheStats",
    "clear_swr_audit_duckdb",
    "configure_duckdb_wal",
    "read_swr_audit_from_duckdb",
    "swr_cache",
    "to_orjson_bytes",
]
