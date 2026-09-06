"""ALPHA BIST — Yapılandırılmış Loglama Altyapısı (Structured Logging).

Bu modül, platform genelinde yüksek başarımlı ve yapılandırılmış loglamayı sağlar:
- structlog ile asenkron bağlam (contextvars) ve ISO zaman damgası
- Konsol için renkli veya JSON formatında çıktılama
- GEMINI.md standardı: orjson serileştirici zorunluluğu
- SSD yazma limitini korumak için gürültülü kütüphanelerin baskılanması (suppression)
- Windows terminali için UTF-8 karakter kodlaması güvencesi (reconfigure ile güvenli)
- Log istatistiklerinin Polars DataFrame olarak analitik izlenmesi
"""

from __future__ import annotations

import collections
import contextlib
import logging
import os
import sys
import threading
from typing import Any, Final

import orjson
import polars as pl
import structlog

DEFAULT_LOG_LEVEL: Final[str] = os.getenv("ALPHA_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")).upper()

NOISY_LOGGERS: Final[tuple[str, ...]] = (
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "aiohttp",
    "websockets",
    "grpc",
    "opentelemetry",
    "uvicorn.access",
    "uvicorn.error",
    "fastapi",
    "starlette",
    "clickhouse_connect",
    "redis",
    "celery",
    "kombu",
    "billiard",
    "watchfiles",
)

# Seviye bazlı log telemetrisi için sayaçlar, hata halka tamponu ve thread güvenliği
_log_counts_lock = threading.RLock()
_log_counts: dict[str, int] = {
    "debug": 0,
    "info": 0,
    "warning": 0,
    "error": 0,
    "critical": 0,
}
_recent_errors: collections.deque[dict[str, Any]] = collections.deque(maxlen=200)


def _telemetry_processor(
    _logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Her log olayını seviyesine göre telemetri sayacına işler ve kritik hataları tampona alır."""
    level = method_name.lower()
    with _log_counts_lock:
        if level in _log_counts:
            _log_counts[level] += 1
        else:
            _log_counts["info"] += 1

        if level in ("warning", "error", "critical"):
            timestamp = str(event_dict.get("timestamp", ""))
            event_msg = str(event_dict.get("event", ""))
            logger_name = str(getattr(_logger, "name", "root"))
            _recent_errors.append({
                "timestamp": timestamp,
                "log_level": level.upper(),
                "logger": logger_name,
                "message": event_msg,
            })
    return event_dict


def _orjson_serializer(data: dict[str, Any], **kwargs: Any) -> str:
    """GEMINI.md standardı orjson serileştirici fonksiyonu.

    Args:
        data: Log kayıt sözlüğü.
        **kwargs: Ek serileştirme parametreleri.

    Returns:
        UTF-8 formatında serileştirilmiş JSON metni.
    """
    return orjson.dumps(data, default=str).decode("utf-8")


def _ensure_utf8_streams() -> None:
    """sys.stderr ve sys.stdout akışlarını kapatmadan yerinde UTF-8 olarak yapılandırır."""
    for stream in (sys.stderr, sys.stdout):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


def setup_logging(log_level: str = DEFAULT_LOG_LEVEL) -> None:
    """ALPHA BIST için yapılandırılmış (structured) loglama altyapısını kurar.

    Args:
        log_level: Asgari log seviyesi ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
    """
    _ensure_utf8_streams()

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Standart kütüphane loglayıcısını da hizala
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=numeric_level,
        force=True,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        _telemetry_processor,
    ]

    if sys.stderr.isatty():
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.platform != "win32"))
    else:
        processors.append(structlog.processors.JSONRenderer(serializer=_orjson_serializer))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Gürültülü kütüphaneleri baskıla — SSD yazma aşınmasını engelle
    for noisy in NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.ERROR)


def get_log_stats() -> dict[str, int]:
    """Çalışma zamanında üretilen log adedi istatistiklerini döndürür.

    Returns:
        Seviye bazlı log sayıları sözlüğü.
    """
    with _log_counts_lock:
        return dict(_log_counts)


def get_recent_errors(limit: int = 50) -> list[dict[str, Any]]:
    """Son yakalanan uyarı, hata ve kritik log kayıtlarını döndürür (Self-healing teşhis).

    Args:
        limit: Döndürülecek azami kayıt adedi.

    Returns:
        Hata kayıtları sözlük listesi.
    """
    with _log_counts_lock:
        items = list(_recent_errors)
        return items[-limit:] if limit < len(items) else items


def check_error_anomaly(threshold: int = 50) -> bool:
    """Hata ve kritik log adetlerinin belirlenen eşiği aşıp aşmadığını denetler (Kural 6 / Self-healing).

    Args:
        threshold: Alarm üretecek azami hata adedi eşiği.

    Returns:
        Eşik aşıldıysa True, normal ise False.
    """
    with _log_counts_lock:
        total_errors = _log_counts.get("error", 0) + _log_counts.get("critical", 0)
        return total_errors >= threshold


def export_log_stats_to_polars() -> pl.DataFrame:
    """Log seviye dağılımını Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

    Returns:
        Log seviyesi ve adetlerini içeren Polars DataFrame.
    """
    stats = get_log_stats()
    return pl.DataFrame(
        {
            "log_level": list(stats.keys()),
            "count": list(stats.values()),
        },
        schema={"log_level": pl.String, "count": pl.Int64},
    )


def export_recent_errors_to_polars() -> pl.DataFrame:
    """Son hata kayıtlarını analitik inceleme için Polars DataFrame olarak döndürür.

    Returns:
        Hata kayıtlarını içeren Polars DataFrame.
    """
    errors = get_recent_errors()
    if not errors:
        return pl.DataFrame(
            schema={
                "timestamp": pl.String,
                "log_level": pl.String,
                "logger": pl.String,
                "message": pl.String,
            }
        )
    return pl.DataFrame(
        errors,
        schema={
            "timestamp": pl.String,
            "log_level": pl.String,
            "logger": pl.String,
            "message": pl.String,
        },
    )


def export_errors_to_duckdb(db_path: str = "data/log_errors.duckdb") -> int:
    """Son hata tamponundaki kayıtları kalıcı DuckDB denetim tablosuna yazar (Kural 5 & 6).

    Args:
        db_path: Hedef DuckDB dosya yolu.

    Returns:
        Kaydedilen hata kayıt sayısı.
    """
    import duckdb

    errors = get_recent_errors(limit=200)
    if not errors:
        return 0

    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    with _log_counts_lock, duckdb.connect(db_path) as con:
        con.execute("PRAGMA checkpoint_threshold='4MB'")
        con.execute("PRAGMA wal_autocheckpoint='2MB'")
        con.execute("""
            CREATE TABLE IF NOT EXISTS system_error_logs (
                timestamp VARCHAR,
                log_level VARCHAR,
                logger VARCHAR,
                message VARCHAR,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for err in errors:
            con.execute(
                """
                INSERT INTO system_error_logs (timestamp, log_level, logger, message)
                VALUES (?, ?, ?, ?)
            """,
                [err["timestamp"], err["log_level"], err["logger"], err["message"]],
            )
    return len(errors)


# Modül yüklendiğinde varsayılan loglamayı başlat
setup_logging()

# Dışa aktarılan merkezi loglayıcı
logger = structlog.get_logger(__name__)


def get_logger(name: str | None = None) -> Any:
    """Belirtilen ad için yapılandırılmış structlog loglayıcısı döndürür."""
    return structlog.get_logger(name) if name else logger


__all__: Final[list[str]] = [
    "DEFAULT_LOG_LEVEL",
    "NOISY_LOGGERS",
    "check_error_anomaly",
    "export_errors_to_duckdb",
    "export_log_stats_to_polars",
    "export_recent_errors_to_polars",
    "get_log_stats",
    "get_logger",
    "get_recent_errors",
    "logger",
    "setup_logging",
]
