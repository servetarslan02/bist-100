"""
ALPHA BIST — PostgreSQL Replication Health Monitor
==================================================
TimescaleDB / PostgreSQL Streaming Replication İzleme Motoru:
- Primary ve Read-Replica arasındaki veri gecikmesini (lag) LSN ve saniye bazında ölçer.
- Replikasyon bağlantı durumunu (streaming, catchup, disconnected) denetler.
- Polars analitik DataFrame formatında metrik üretir (GEMINI.md Kural 2).
- Fail-closed ve yapısal Türkçe structlog loglama sağlar.
"""

from __future__ import annotations

import functools
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import trace

from .database import get_pg_pool, get_pg_replica_pool

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.pg_replication_health")

# Eşik değerler
DEFAULT_MAX_LAG_BYTES: Final[int] = 1_048_576  # 1 MB
DEFAULT_MAX_LAG_SECONDS: Final[float] = 60.0  # 60 saniye
DEFAULT_PG_HEALTH_DB_PATH: Final[str] = "data/pg_replication_health.duckdb"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için SSD koruyucu ve optimize WAL parametrelerini ayarlar."""
    try:
        conn.execute("PRAGMA checkpoint_threshold='4MB'")
        conn.execute("PRAGMA wal_autocheckpoint='2MB'")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def otel_trace(span_name: str) -> Any:
    """Metot veya fonksiyonu OpenTelemetry span içine alan dekoratör.

    Args:
        span_name: Span adı.

    Returns:
        Sarmalayıcı fonksiyon.
    """

    def decorator(func: Any) -> Any:
        """Hedef fonksiyonu OTel span ile sarmalar."""

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Asenkron çağrıyı span içinde icra eder."""
            with tracer.start_as_current_span(span_name):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


@otel_trace("pg_replication_health.check_replication_health")
async def check_replication_health() -> dict[str, Any]:
    """PostgreSQL birincil ve ikincil replika sağlık durumunu ve gecikmesini denetler.

    Returns:
        Replikasyon sağlık durumu, lag bayt/saniye ve hata listesi özeti.
    """
    health: dict[str, Any] = {
        "primary": {"status": "unknown"},
        "replica": {"status": "unknown"},
        "lag_bytes": 0,
        "lag_seconds": 0.0,
        "errors": [],
        "checked_at": datetime.now(UTC).isoformat(),
    }

    # 1. Primary durumu kontrolü
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    client_addr,
                    state,
                    sent_lsn,
                    write_lsn,
                    flush_lsn,
                    replay_lsn,
                    pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes
                FROM pg_stat_replication
                LIMIT 1
            """)

            if row:
                health["primary"]["status"] = "streaming"
                health["primary"]["replica_addr"] = str(row["client_addr"])
                health["primary"]["state"] = str(row["state"])
                raw_lag = row["lag_bytes"]
                health["lag_bytes"] = int(raw_lag) if raw_lag is not None else 0

                if health["lag_bytes"] > DEFAULT_MAX_LAG_BYTES:
                    lag_mb = health["lag_bytes"] / DEFAULT_MAX_LAG_BYTES
                    msg = f"Replikasyon bayt gecikmesi yüksek: {lag_mb:.2f} MB"
                    health["errors"].append(msg)
                    logger.warning("pg_replikasyon_bayt_gecikmesi_yuksek", lag_mb=lag_mb)
            else:
                health["primary"]["status"] = "no_replica_connected"
                health["errors"].append("Bağlı PostgreSQL replikası bulunamadı")
                logger.warning("pg_bagli_replika_bulunamadi")

    except Exception as e:
        health["primary"]["status"] = "error"
        hata_mesaji = f"Birincil PostgreSQL bağlantı hatası: {str(e)[:150]}"
        health["errors"].append(hata_mesaji)
        logger.error("pg_birincil_denetim_hatasi", hata=str(e))

    # 2. Replica durumu kontrolü
    try:
        replica_pool = await get_pg_replica_pool()
        async with replica_pool.acquire() as conn:
            is_recovery = await conn.fetchval("SELECT pg_is_in_recovery()")

            if is_recovery:
                health["replica"]["status"] = "in_recovery"

                lag = await conn.fetchval("""
                    SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))
                """)
                health["lag_seconds"] = round(float(lag), 2) if lag is not None else 0.0

                if health["lag_seconds"] > DEFAULT_MAX_LAG_SECONDS:
                    msg = f"Replika zaman gecikmesi yüksek: {health['lag_seconds']:.1f} saniye"
                    health["errors"].append(msg)
                    logger.warning("pg_replika_zaman_gecikmesi_yuksek", lag_saniye=health["lag_seconds"])
            else:
                health["replica"]["status"] = "not_in_recovery"
                health["errors"].append("Replika recovery (okuma) modunda değil")
                logger.warning("pg_replika_recovery_modunda_degil")

    except Exception as e:
        health["replica"]["status"] = "error"
        hata_mesaji = f"İkincil replika bağlantı hatası: {str(e)[:150]}"
        health["errors"].append(hata_mesaji)
        logger.error("pg_ikincil_denetim_hatasi", hata=str(e))

    # 3. Genel Durum Sınıflandırması
    if not health["errors"]:
        health["status"] = "healthy"
    else:
        health["status"] = "degraded"

    return health


@otel_trace("pg_replication_health.get_replication_metrics")
async def get_replication_metrics() -> dict[str, Any]:
    """Prometheus ve telemetri sistemleri için replikasyon metriklerini üretir."""
    health = await check_replication_health()
    primary_info = health.get("primary", {})
    return {
        "pg_replica_lag_bytes": int(health.get("lag_bytes", 0) or 0),
        "pg_replica_lag_seconds": float(health.get("lag_seconds", 0.0) or 0.0),
        "pg_replica_connected": 1 if primary_info.get("state") == "streaming" else 0,
        "pg_replication_healthy": 1 if health.get("status") == "healthy" else 0,
    }


def should_fallback_to_primary(health_data: dict[str, Any]) -> bool:
    """Okuma işlemlerinin replikadan birincil veritabanına aktarılması gerekip gerekmediğini denetler.

    Self-healing failover koruması sağlar. Replikasyon gecikmesi yüksekse veya
    replika çökmüşse True dönerek sorguların Primary'ye yönlendirilmesini sağlar.

    Args:
        health_data: check_replication_health() sağlık denetim çıktısı.

    Returns:
        Birincile yönlendirme gerekliyse True, replika sağlıklıysa False.
    """
    if not health_data:
        return True

    replica_info = health_data.get("replica", {})
    if replica_info.get("status") != "in_recovery":
        return True

    lag_sec = float(health_data.get("lag_seconds", 0.0) or 0.0)
    if lag_sec > DEFAULT_MAX_LAG_SECONDS:
        return True

    lag_bytes = int(health_data.get("lag_bytes", 0) or 0)
    if lag_bytes > DEFAULT_MAX_LAG_BYTES:
        return True

    return health_data.get("status") != "healthy"


def export_pg_replication_to_polars(health_data: dict[str, Any] | None = None) -> pl.DataFrame:
    """Replikasyon durumunu Polars DataFrame olarak dışa aktarır.

    Args:
        health_data: check_replication_health() çıktısı. Verilmezse varsayılan şema döner.

    Returns:
        pl.DataFrame: Replikasyon sağlık tablosu.
    """
    schema = {
        "primary_status": pl.String,
        "replica_status": pl.String,
        "lag_bytes": pl.Int64,
        "lag_seconds": pl.Float64,
        "overall_status": pl.String,
        "error_count": pl.Int64,
        "checked_at": pl.String,
    }
    if not health_data:
        return pl.DataFrame(schema=schema)

    record = {
        "primary_status": str(health_data.get("primary", {}).get("status", "unknown")),
        "replica_status": str(health_data.get("replica", {}).get("status", "unknown")),
        "lag_bytes": int(health_data.get("lag_bytes", 0) or 0),
        "lag_seconds": float(health_data.get("lag_seconds", 0.0) or 0.0),
        "overall_status": str(health_data.get("status", "unknown")),
        "error_count": len(health_data.get("errors", [])),
        "checked_at": str(health_data.get("checked_at", datetime.now(UTC).isoformat())),
    }
    return pl.DataFrame([record], schema=schema)


def export_pg_replication_to_orjson(health_data: dict[str, Any]) -> bytes:
    """Replikasyon durumunu C seviyesinde orjson bayt dizisine dönüştürür."""
    return orjson.dumps(health_data, option=orjson.OPT_SORT_KEYS)


def save_replication_health_to_duckdb(
    health_data: dict[str, Any],
    db_path: str = DEFAULT_PG_HEALTH_DB_PATH,
) -> None:
    """Replikasyon sağlık durumunu DuckDB geçmiş tablosuna atomik olarak kaydeder.

    SSD koruması ve optimize WAL parametreleri ile çalışır.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    try:
        configure_duckdb_wal(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pg_replication_history (
                primary_status VARCHAR,
                replica_status VARCHAR,
                lag_bytes BIGINT,
                lag_seconds DOUBLE,
                overall_status VARCHAR,
                error_count BIGINT,
                checked_at VARCHAR
            )
        """)
        df_health = export_pg_replication_to_polars(health_data)
        if df_health.height > 0:
            conn.register("tmp_pg_rep", df_health.to_arrow())
            conn.execute("""
                INSERT INTO pg_replication_history
                SELECT primary_status, replica_status, lag_bytes, lag_seconds, overall_status, error_count, checked_at
                FROM tmp_pg_rep
            """)
            conn.unregister("tmp_pg_rep")
        conn.commit()
        logger.info("pg_replikasyon_durumu_duckdb_kaydedildi", db_path=str(path))
    finally:
        conn.close()


__all__: Final[list[str]] = [
    "DEFAULT_MAX_LAG_BYTES",
    "DEFAULT_MAX_LAG_SECONDS",
    "DEFAULT_PG_HEALTH_DB_PATH",
    "check_replication_health",
    "configure_duckdb_wal",
    "export_pg_replication_to_orjson",
    "export_pg_replication_to_polars",
    "get_replication_metrics",
    "otel_trace",
    "save_replication_health_to_duckdb",
    "should_fallback_to_primary",
]
