"""ALPHA BIST — SSD Write Debounce & DuckDB WAL Utility.

Bu modül, yüksek frekanslı veri akışlarında (order book, tick verisi, portföy durumları,
model ağırlıkları) diske aşırı sık yazma yapılmasını engelleyerek SSD yıpranmasını önler,
yazma sıklığını sınırlar (throttling/debounce) ve DuckDB WAL (Write-Ahead-Log)
ayarlarını optimize eder:

1. SSD Yazma Koruması (Write Throttling):
   - `should_save(key, min_interval_sec)` ile imperatif zaman kontrolü.
   - `@debounced_save(key, min_interval_sec)` ile senkron ve asenkron fonksiyon
     dekoratörü desteği.
2. Saat Kayması ve Zaman Doğruluğu:
   - NTP senkronizasyonlarından veya sistem saati geriye gitmelerinden etkilenmemek
     için `time.monotonic()` kullanılır.
3. Thread & Coroutine Eşzamanlılık Güvenliği:
   - `threading.RLock` ile yarış koşullarına (race condition) karşı tam koruma sağlanır.
4. Güvenli DuckDB WAL Yapılandırması:
   - `wal_autocheckpoint` ve `checkpoint_threshold` değerleri parametre doğrulama
     (regex guard) yapılarak SQL injection riskine karşı korunur.
5. Sıfır Kopyalı Polars İzleme Metrikleri:
   - Debounce anahtarlarının anlık durumu ve engellenen çağrı metrikleri
     `export_debounce_metrics_to_polars()` ile Polars DataFrame olarak raporlanır.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import threading
import time
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable

import duckdb
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# Modül Seviyesi Yapılandırma Sabitleri (GEMINI.md Kural 4)
DEFAULT_MIN_INTERVAL_SEC: Final[float] = 30.0
DEFAULT_WAL_SIZE: Final[str] = "2MB"
DEFAULT_CHECKPOINT_THRESHOLD: Final[str] = "4MB"
DEFAULT_DEBOUNCE_DUCKDB_PATH: Final[str] = "data/debounce_audit.duckdb"
DEFAULT_DEBOUNCE_AUDIT_TABLE: Final[str] = "bist_debounce_audit"

# SQL Injection Koruması için WAL ve Tablo Parametre Doğrulama Deseni
_WAL_PARAM_REGEX: Final[re.Pattern[str]] = re.compile(r"^\d+\s*(?:KB|MB|GB|B)?$", re.IGNORECASE)
_TABLE_NAME_REGEX: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Thread-safe reentrant kilit
_debounce_lock: Final[threading.RLock] = threading.RLock()

# Global debounce durumu: key → last_write_timestamp (time.monotonic)
# Geriye dönük uyumluluk için modül seviyesinde tutulur
_last_writes: dict[str, float] = {}
_write_counts: dict[str, int] = {}
_debounced_counts: dict[str, int] = {}


def debounced_save(
    key: str,
    min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Dekoratör: Dosya veya veritabanı kayıt fonksiyonlarını debounce eder.

    Hem senkron (`def`) hem de asenkron (`async def`) fonksiyonları şeffaf bir şekilde
    destekler. Süre dolmadıysa `None` döner ve fonksiyon yürütülmez.

    Args:
        key: İşlemi tanımlayan benzersiz anahtar.
        min_interval_sec: İki kayıt arasındaki zorunlu asgari süre (saniye).

    Returns:
        Callable[[Callable[..., Any]], Callable[..., Any]]: Dekore edilmiş sarmalayıcı.

    Example:
        @debounced_save("virtual_portfolio_save", min_interval_sec=30.0)
        async def save_state(self):
            ...  # Gerçek asenkron kayıt
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with _debounce_lock:
                    now = time.monotonic()
                    last = _last_writes.get(key, 0.0)
                    if now - last < min_interval_sec:
                        _debounced_counts[key] = _debounced_counts.get(key, 0) + 1
                        logger.debug(
                            "debounced_save_atlandi",
                            key=key,
                            gecen_sure=round(now - last, 2),
                            min_aralik=min_interval_sec,
                        )
                        return None
                    _last_writes[key] = now
                    _write_counts[key] = _write_counts.get(key, 0) + 1

                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with _debounce_lock:
                now = time.monotonic()
                last = _last_writes.get(key, 0.0)
                if now - last < min_interval_sec:
                    _debounced_counts[key] = _debounced_counts.get(key, 0) + 1
                    logger.debug(
                        "debounced_save_atlandi",
                        key=key,
                        gecen_sure=round(now - last, 2),
                        min_aralik=min_interval_sec,
                    )
                    return None
                _last_writes[key] = now
                _write_counts[key] = _write_counts.get(key, 0) + 1

            return func(*args, **kwargs)

        return sync_wrapper

    return decorator


def should_save(key: str, min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC) -> bool:
    """İmperatif kullanım: Son yazmadan min_interval_sec süre geçtiyse True döner.

    Süre geçtiyse zaman damgasını günceller ve izni onaylar. Süre dolmadıysa
    False döner ve yazma işlemini engeller.

    Args:
        key: İzlenen servis, depo veya işlem anahtarı.
        min_interval_sec: İki kayıt arasındaki zorunlu asgari süre (saniye).

    Returns:
        bool: Yazma işlemine izin veriliyorsa True, debounce edilmişse False.

    Example:
        if should_save("order_history_save", 10.0):
            _do_actual_save()
    """
    with _debounce_lock:
        now = time.monotonic()
        last = _last_writes.get(key, 0.0)
        if now - last < min_interval_sec:
            _debounced_counts[key] = _debounced_counts.get(key, 0) + 1
            return False
        _last_writes[key] = now
        _write_counts[key] = _write_counts.get(key, 0) + 1
        return True


def get_remaining_debounce_time(key: str, min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC) -> float:
    """Belirtilen anahtar için bir sonraki yazma işlemine kalan süreyi döner.

    Args:
        key: Denetlenen anahtar.
        min_interval_sec: Minimum bekleme aralığı (saniye).

    Returns:
        float: Kalan süre (saniye). Yazmaya hazırsa 0.0 döner.
    """
    with _debounce_lock:
        last = _last_writes.get(key, 0.0)
        if last == 0.0:
            return 0.0
        elapsed = time.monotonic() - last
        remaining = min_interval_sec - elapsed
        return max(0.0, remaining)


def reset_debounce(key: str | None = None) -> None:
    """Belirtilen anahtarın veya tüm debounce durumlarının geçmişini sıfırlar.

    Args:
        key: Sıfırlanacak anahtar (None verilirse tüm durumlar sıfırlanır).
    """
    with _debounce_lock:
        if key is None:
            _last_writes.clear()
            _write_counts.clear()
            _debounced_counts.clear()
        else:
            _last_writes.pop(key, None)
            _write_counts.pop(key, None)
            _debounced_counts.pop(key, None)


def get_debounce_stats() -> dict[str, dict[str, Any]]:
    """Tüm aktif debounce anahtarlarının anlık istatistiklerini döner.

    Returns:
        dict[str, dict[str, Any]]: Anahtar bazlı istatistik sözlüğü.
    """
    now = time.monotonic()
    with _debounce_lock:
        result: dict[str, dict[str, Any]] = {}
        for k, last_ts in _last_writes.items():
            result[k] = {
                "key": k,
                "elapsed_seconds": round(now - last_ts, 3),
                "allowed_writes": _write_counts.get(k, 0),
                "debounced_calls": _debounced_counts.get(k, 0),
            }
        return result


def export_debounce_metrics_to_polars() -> pl.DataFrame:
    """Debounce sayaç ve süre metriklerini sıfır kopyalı Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

    Returns:
        pl.DataFrame: Debounce analitik tablosu.
    """
    stats = get_debounce_stats()
    schema = {
        "key": pl.Utf8,
        "elapsed_seconds": pl.Float64,
        "allowed_writes": pl.Int64,
        "debounced_calls": pl.Int64,
    }
    if not stats:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(list(stats.values()), schema=schema)


def export_debounce_to_orjson_bytes() -> bytes:
    """Debounce istatistiklerini orjson formatında serileştirir."""
    return orjson.dumps(get_debounce_stats(), default=str)


def export_debounce_to_duckdb(
    db_path: str | Path | None = None,
    table_name: str = DEFAULT_DEBOUNCE_AUDIT_TABLE,
) -> int:
    """Debounce metriklerini yerel DuckDB tablosuna aktarır.

    Args:
        db_path: DuckDB veritabanı yolu.
        table_name: Hedef tablo adı.

    Returns:
        int: Eklenen kayıt sayısı.
    """
    cleaned_table = str(table_name).strip()
    if not _TABLE_NAME_REGEX.match(cleaned_table):
        raise ValueError(f"Geçersiz tablo adı: {table_name!r}")

    df = export_debounce_metrics_to_polars()
    if df.is_empty():
        return 0

    path_obj = Path(db_path or DEFAULT_DEBOUNCE_DUCKDB_PATH)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if path_obj.exists() and path_obj.stat().st_size == 0:
        with contextlib.suppress(OSError):
            path_obj.unlink()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            with contextlib.suppress(Exception):
                configure_duckdb_wal(conn)
            conn.register("df_debounce", df.to_arrow())
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {cleaned_table} AS SELECT * FROM df_debounce WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {cleaned_table} SELECT * FROM df_debounce")
            with contextlib.suppress(Exception):
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{cleaned_table}_key ON {cleaned_table}(key)")
        return len(df)
    except Exception as e:
        logger.error("export_debounce_to_duckdb_basarisiz", error=str(e))
        return 0


def query_debounce_duckdb(
    db_path: str | Path | None = None,
    table_name: str = DEFAULT_DEBOUNCE_AUDIT_TABLE,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş debounce kayıtlarını sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        table_name: Tablo adı.

    Returns:
        pl.DataFrame: Sorgu neticesi Polars tablosu.
    """
    cleaned_table = str(table_name).strip()
    if not _TABLE_NAME_REGEX.match(cleaned_table):
        raise ValueError(f"Geçersiz tablo adı: {table_name!r}")

    path_obj = Path(db_path or DEFAULT_DEBOUNCE_DUCKDB_PATH)
    if not path_obj.exists() or path_obj.stat().st_size == 0:
        return pl.DataFrame()

    try:
        with duckdb.connect(str(path_obj), read_only=True) as conn:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                [cleaned_table],
            ).fetchall()
            if not tables:
                return pl.DataFrame()

            arrow_res = conn.execute(f"SELECT * FROM {cleaned_table}").arrow()
            return pl.from_arrow(arrow_res)
    except Exception as e:
        logger.error("query_debounce_duckdb_basarisiz", error=str(e))
        return pl.DataFrame()


def configure_duckdb_wal(
    conn: Any,
    wal_size: str = DEFAULT_WAL_SIZE,
    checkpoint: str = DEFAULT_CHECKPOINT_THRESHOLD,
) -> None:
    """DuckDB bağlantısına SSD-dostu WAL ayarları uygular.

    Dosya sisteminde aşırı I/O ve disk yıpranmasını önlemek için WAL autocheckpoint
    ve checkpoint_threshold parametrelerini optimize eder.

    Args:
        conn: DuckDB bağlantı nesnesi (duckdb.DuckDBPyConnection veya DuckDB cursor).
        wal_size: WAL otomatik denetim noktası eşiği (örn: '2MB').
        checkpoint: Denetim noktası yazma eşiği (örn: '4MB').

    Raises:
        ValueError: Parametre formatı geçersizse veya güvenlik denetimini geçemezse.
    """
    cleaned_wal = wal_size.strip()
    cleaned_cp = checkpoint.strip()

    if not _WAL_PARAM_REGEX.match(cleaned_wal):
        raise ValueError(f"Geçersiz wal_size parametresi: {wal_size!r}")
    if not _WAL_PARAM_REGEX.match(cleaned_cp):
        raise ValueError(f"Geçersiz checkpoint parametresi: {checkpoint!r}")

    try:
        conn.execute(f"SET wal_autocheckpoint = '{cleaned_wal}'")
        conn.execute(f"SET checkpoint_threshold = '{cleaned_cp}'")
        logger.debug(
            "duckdb_wal_yapilandirildi",
            wal_size=cleaned_wal,
            checkpoint=cleaned_cp,
        )
    except Exception as exc:
        logger.debug(
            "duckdb_wal_yapilandirma_atlandi",
            hata=str(exc),
            aciklama="Salt okunur bağlantı veya desteklenmeyen parametre",
        )


class DebounceManager:
    """Nesne yönelimli (OOP) SSD Yazma Debounce ve Hız Sınırlama Yöneticisi.

    Bağımsız durum yönetimi gereken izole servisler ve test ortamları için
    ayrı durum alanı (state scope) sunar.
    """

    def __init__(self, default_interval: float = DEFAULT_MIN_INTERVAL_SEC) -> None:
        """DebounceManager yöneticisini başlatır.

        Args:
            default_interval: Varsayılan asgari bekleme süresi (saniye).
        """
        self._default_interval = max(0.0, default_interval)
        self._lock = threading.RLock()
        self._local_last_writes: dict[str, float] = {}
        self._local_writes: dict[str, int] = {}
        self._local_debounced: dict[str, int] = {}

    def should_save(self, key: str, min_interval_sec: float | None = None) -> bool:
        """Yazma iznini yerel durum üzerinde kontrol eder.

        Args:
            key: Denetlenen işlem anahtarı.
            min_interval_sec: İsteğe bağlı özel süre (belirtilmezse varsayılan kullanılır).

        Returns:
            bool: İzin verildiyse True, engellendiyse False.
        """
        interval = self._default_interval if min_interval_sec is None else max(0.0, min_interval_sec)
        with self._lock:
            now = time.monotonic()
            last = self._local_last_writes.get(key, 0.0)
            if now - last < interval:
                self._local_debounced[key] = self._local_debounced.get(key, 0) + 1
                return False
            self._local_last_writes[key] = now
            self._local_writes[key] = self._local_writes.get(key, 0) + 1
            return True

    def reset(self, key: str | None = None) -> None:
        """Yerel debounce geçmişini sıfırlar.

        Args:
            key: Sıfırlanacak anahtar (None verilirse tümü sıfırlanır).
        """
        with self._lock:
            if key is None:
                self._local_last_writes.clear()
                self._local_writes.clear()
                self._local_debounced.clear()
            else:
                self._local_last_writes.pop(key, None)
                self._local_writes.pop(key, None)
                self._local_debounced.pop(key, None)

    def to_polars(self) -> pl.DataFrame:
        """Yerel debounce metriklerini Polars DataFrame olarak döner.

        Returns:
            pl.DataFrame: Sıfır kopyalı analitik veri tablosu.
        """
        schema = {
            "key": pl.Utf8,
            "elapsed_seconds": pl.Float64,
            "allowed_writes": pl.Int64,
            "debounced_calls": pl.Int64,
        }
        now = time.monotonic()
        with self._lock:
            if not self._local_last_writes:
                return pl.DataFrame(schema=schema)
            rows = [
                {
                    "key": k,
                    "elapsed_seconds": round(now - last_ts, 3),
                    "allowed_writes": self._local_writes.get(k, 0),
                    "debounced_calls": self._local_debounced.get(k, 0),
                }
                for k, last_ts in self._local_last_writes.items()
            ]
            return pl.DataFrame(rows, schema=schema)

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Yerel durum istatistiklerini sözlük formatında döner."""
        now = time.monotonic()
        with self._lock:
            return {
                k: {
                    "key": k,
                    "elapsed_seconds": round(now - last_ts, 3),
                    "allowed_writes": self._local_writes.get(k, 0),
                    "debounced_calls": self._local_debounced.get(k, 0),
                }
                for k, last_ts in self._local_last_writes.items()
            }

    def to_orjson_bytes(self) -> bytes:
        """Yerel istatistikleri orjson bayt dizisi olarak serileştirir."""
        return orjson.dumps(self.get_stats(), default=str)

    def export_to_duckdb(
        self,
        db_path: str | Path | None = None,
        table_name: str = DEFAULT_DEBOUNCE_AUDIT_TABLE,
    ) -> int:
        """Yerel metrikleri DuckDB tablosuna aktarır."""
        cleaned_table = str(table_name).strip()
        if not _TABLE_NAME_REGEX.match(cleaned_table):
            raise ValueError(f"Geçersiz tablo adı: {table_name!r}")

        df = self.to_polars()
        if df.is_empty():
            return 0

        path_obj = Path(db_path or DEFAULT_DEBOUNCE_DUCKDB_PATH)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        if path_obj.exists() and path_obj.stat().st_size == 0:
            with contextlib.suppress(OSError):
                path_obj.unlink()

        try:
            with duckdb.connect(str(path_obj)) as conn:
                with contextlib.suppress(Exception):
                    configure_duckdb_wal(conn)
                conn.register("df_local_debounce", df.to_arrow())
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {cleaned_table} AS SELECT * FROM df_local_debounce WHERE 1=0"
                )
                conn.execute(f"INSERT INTO {cleaned_table} SELECT * FROM df_local_debounce")
                with contextlib.suppress(Exception):
                    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{cleaned_table}_key ON {cleaned_table}(key)")
            return len(df)
        except Exception as e:
            logger.error("export_to_duckdb_basarisiz", error=str(e))
            return 0

    def __repr__(self) -> str:
        """Yönetici nesnesinin durum temsili."""
        with self._lock:
            return (
                f"DebounceManager(default_interval={self._default_interval}s, "
                f"active_keys={len(self._local_last_writes)})"
            )


__all__: Final[list[str]] = [
    # Yapılandırma Sabitleri
    "DEFAULT_CHECKPOINT_THRESHOLD",
    "DEFAULT_DEBOUNCE_AUDIT_TABLE",
    "DEFAULT_DEBOUNCE_DUCKDB_PATH",
    "DEFAULT_MIN_INTERVAL_SEC",
    "DEFAULT_WAL_SIZE",
    # Ana Fonksiyonlar & Dekoratörler
    "configure_duckdb_wal",
    "debounced_save",
    "export_debounce_metrics_to_polars",
    "export_debounce_to_duckdb",
    "export_debounce_to_orjson_bytes",
    "get_debounce_stats",
    "get_remaining_debounce_time",
    "query_debounce_duckdb",
    "reset_debounce",
    "should_save",
    # Nesne Yönelimli Sınıf
    "DebounceManager",
    # Global Durum (Geriye Dönük Uyumluluk)
    "_last_writes",
]
