"""ALPHA BIST — Standardized Point-in-Time Query Helpers

PIT (Point-in-Time) sorguları için standartlaştırılmış yardımcı fonksiyonlar.
Geleceğe sızıntıyı (look-ahead bias) engeller.

Kullanım:
    from services.core.pit_queries import pit_fetch, pit_fetch_latest, pit_fetch_as_of

    # Belirli bir tarihte bilinen veriyi getir
    data = await pit_fetch_as_of(conn, "model_predictions", "AAPL", "2025-06-01")

    # Son N günlük PIT-safe veri
    data = await pit_fetch(conn, "daily_performance", days=30)
"""

from datetime import datetime
from typing import Any

import structlog
import functools
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.pit_queries")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# =====================================================
# PIT-SAFE QUERY TEMPLATES
# =====================================================

# Her tablo için PIT-safe sorgu şablonu
# Kural: Sadece o tarihte bilinen veriyi döndür
PIT_QUERY_TEMPLATES = {
    "model_predictions": {
        "table": "model_predictions",
        "time_column": "prediction_date",
        "created_column": "created_at",
        "identifier_column": "instrument_id",
        "description": "Model tahminleri — prediction_date'den önce oluşturulmuş olmalı",
    },
    "daily_performance": {
        "table": "daily_performance",
        "time_column": "date",
        "created_column": "created_at",
        "identifier_column": "strategy_id",
        "description": "Günlük performans — date'den önce bilinmeli",
    },
    "signals": {
        "table": "signals",
        "time_column": "created_at",
        "created_column": "created_at",
        "identifier_column": "instrument_id",
        "description": "Sinyaller — created_at'te bilinmeli",
    },
    "positions": {
        "table": "positions",
        "time_column": "created_at",
        "created_column": "created_at",
        "identifier_column": "portfolio_id",
        "description": "Pozisyonlar — created_at'te bilinmeli",
    },
    "orders": {
        "table": "orders",
        "time_column": "created_at",
        "created_column": "created_at",
        "identifier_column": "portfolio_id",
        "description": "Emirler — created_at'te bilinmeli",
    },
    "scan_results": {
        "table": "scan_results",
        "time_column": "timestamp",
        "created_column": "timestamp",
        "identifier_column": "ticker",
        "description": "Tarama sonuçları — timestamp'te bilinmeli",
    },
}


# =====================================================
# PIT-SAFE QUERY FUNCTIONS
# =====================================================


@otel_trace("pit_queries.pit_fetch_as_of")
async def pit_fetch_as_of(
    conn,
    table: str,
    identifier: str,
    as_of_date: datetime | str,
    columns: str = "*",
    additional_where: str = "",
) -> list[dict]:
    """Belirli bir tarihte bilinen veriyi getir (PIT-safe).

    Kritik kural: as_of_date'ten ÖNCE oluşturulmuş kayıtları döndürür.
    Bu sayede backtest'te gelecek veri sızıntısı engellenir.

    Args:
        conn: asyncpg connection
        table: Tablo adı
        identifier: Ticker/portfolio/strategy ID
        as_of_date: Bu tarihte bilinen veriyi getir
        columns: Döndürülecek sütunlar (varsayılan: *)
        additional_where: Ek WHERE koşulu

    Returns:
        PIT-safe kayıtlar
    """
    if table not in PIT_QUERY_TEMPLATES:
        raise ValueError(f"Bilinmeyen tablo: {table}. Desteklenen: {list(PIT_QUERY_TEMPLATES.keys())}")

    template = PIT_QUERY_TEMPLATES[table]

    if isinstance(as_of_date, str):
        as_of_date = datetime.fromisoformat(as_of_date)

    # PIT-safe sorgu: created_column <= as_of_date
    query = f"""
        SELECT {columns}
        FROM {template["table"]}
        WHERE {template["identifier_column"]} = $1
            AND {template["created_column"]} <= $2
    """
    params = [identifier, as_of_date]

    if additional_where:
        query += f" AND {additional_where}"

    query += f" ORDER BY {template['created_column']} DESC"

    try:
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(
            "PIT fetch failed",
            table=table,
            identifier=identifier,
            as_of_date=str(as_of_date),
            error=str(e),
        )
        raise


@otel_trace("pit_queries.pit_fetch_latest")
async def pit_fetch_latest(
    conn,
    table: str,
    identifier: str,
    limit: int = 1,
    columns: str = "*",
) -> list[dict]:
    """En son kaydedilen PIT-safe veriyi getir.

    Args:
        conn: asyncpg connection
        table: Tablo adı
        identifier: Ticker/portfolio/strategy ID
        limit: Döndürülecek kayıt sayısı
        columns: Döndürülecek sütunlar

    Returns:
        En son PIT-safe kayıtlar
    """
    if table not in PIT_QUERY_TEMPLATES:
        raise ValueError(f"Bilinmeyen tablo: {table}")

    template = PIT_QUERY_TEMPLATES[table]

    query = f"""
        SELECT {columns}
        FROM {template["table"]}
        WHERE {template["identifier_column"]} = $1
        ORDER BY {template["created_column"]} DESC
        LIMIT $2
    """

    try:
        rows = await conn.fetch(query, identifier, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(
            "PIT fetch latest failed",
            table=table,
            identifier=identifier,
            error=str(e),
        )
        raise


@otel_trace("pit_queries.pit_fetch_range")
async def pit_fetch_range(
    conn,
    table: str,
    identifier: str,
    from_date: datetime | str,
    to_date: datetime | str,
    columns: str = "*",
) -> list[dict]:
    """Belirli bir tarih aralığındaki PIT-safe veriyi getir.

    Args:
        conn: asyncpg connection
        table: Tablo adı
        identifier: Ticker/portfolio/strategy ID
        from_date: Başlangıç tarihi (dahil)
        to_date: Bitiş tarihi (dahil) — PIT-safe: created_at <= to_date
        columns: Döndürülecek sütunlar

    Returns:
        PIT-safe kayıtlar
    """
    if table not in PIT_QUERY_TEMPLATES:
        raise ValueError(f"Bilinmeyen tablo: {table}")

    template = PIT_QUERY_TEMPLATES[table]

    if isinstance(from_date, str):
        from_date = datetime.fromisoformat(from_date)
    if isinstance(to_date, str):
        to_date = datetime.fromisoformat(to_date)

    # PIT-safe: Hem time_column hem created_column kontrolü
    query = f"""
        SELECT {columns}
        FROM {template["table"]}
        WHERE {template["identifier_column"]} = $1
            AND {template["time_column"]} >= $2
            AND {template["time_column"]} <= $3
            AND {template["created_column"]} <= $3
        ORDER BY {template["time_column"]} ASC
    """

    try:
        rows = await conn.fetch(query, identifier, from_date, to_date)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(
            "PIT fetch range failed",
            table=table,
            identifier=identifier,
            error=str(e),
        )
        raise


@otel_trace("pit_queries.pit_validate_no_leakage")
async def pit_validate_no_leakage(
    conn,
    table: str,
    identifier: str,
    check_date: datetime | str,
) -> dict[str, Any]:
    """Veri sızıntısı kontrolü — gelecek veri var mı?

    Args:
        conn: asyncpg connection
        table: Tablo adı
        identifier: Ticker/portfolio/strategy ID
        check_date: Bu tarihten sonraki kayıtlar "sızıntı" sayılır

    Returns:
        Sızıntı kontrolü sonucu
    """
    if table not in PIT_QUERY_TEMPLATES:
        raise ValueError(f"Bilinmeyen tablo: {table}")

    template = PIT_QUERY_TEMPLATES[table]

    if isinstance(check_date, str):
        check_date = datetime.fromisoformat(check_date)

    # check_date'ten SONRA oluşturulmuş ama check_date'ten ÖNCEki veriyi gösteren kayıtlar
    query = f"""
        SELECT COUNT(*) as leak_count
        FROM {template["table"]}
        WHERE {template["identifier_column"]} = $1
            AND {template["created_column"]} > $2
            AND {template["time_column"]} <= $2
    """

    try:
        result = await conn.fetchrow(query, identifier, check_date)
        leak_count = result["leak_count"]

        return {
            "table": table,
            "identifier": identifier,
            "check_date": str(check_date),
            "leak_count": leak_count,
            "has_leakage": leak_count > 0,
            "status": "❌ SIZINTI TESPİT EDİLDİ" if leak_count > 0 else "✅ PIT-safe",
        }
    except Exception as e:
        logger.error(
            "PIT validation failed",
            table=table,
            identifier=identifier,
            error=str(e),
        )
        raise


@otel_trace("pit_queries.pit_fetch_snapshot")
async def pit_fetch_snapshot(
    conn,
    table: str,
    snapshot_date: datetime | str,
    columns: str = "*",
    limit: int = 100,
) -> list[dict]:
    """Belirli bir tarihteki snapshot'ı getir (tüm identifier'lar için).

    Args:
        conn: asyncpg connection
        table: Tablo adı
        snapshot_date: Snapshot tarihi
        columns: Döndürülecek sütunlar
        limit: Maksimum kayıt sayısı

    Returns:
        Snapshot kayıtları
    """
    if table not in PIT_QUERY_TEMPLATES:
        raise ValueError(f"Bilinmeyen tablo: {table}")

    template = PIT_QUERY_TEMPLATES[table]

    if isinstance(snapshot_date, str):
        snapshot_date = datetime.fromisoformat(snapshot_date)

    query = f"""
        SELECT DISTINCT ON ({template["identifier_column"]})
            {columns}
        FROM {template["table"]}
        WHERE {template["created_column"]} <= $1
        ORDER BY {template["identifier_column"]}, {template["created_column"]} DESC
        LIMIT $2
    """

    try:
        rows = await conn.fetch(query, snapshot_date, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(
            "PIT snapshot failed",
            table=table,
            snapshot_date=str(snapshot_date),
            error=str(e),
        )
        raise


# =====================================================
# HELPER: PIT-SAFE DATAFRAME FETCH (Polars)
# =====================================================


@otel_trace("pit_queries.pit_fetch_df")
async def pit_fetch_df(
    conn,
    table: str,
    identifier: str,
    from_date: datetime | str,
    to_date: datetime | str,
):
    """PIT-safe veriyi Polars DataFrame olarak döndür.

    Args:
        conn: asyncpg connection
        table: Tablo adı
        identifier: Ticker/portfolio/strategy ID
        from_date: Başlangıç tarihi
        to_date: Bitiş tarihi

    Returns:
        Polars DataFrame
    """
    import polars as pl

    rows = await pit_fetch_range(conn, table, identifier, from_date, to_date)
    if not rows:
        return pl.DataFrame()
    return pl.from_dicts(rows)


# =====================================================
# PIT AUDIT
# =====================================================


@otel_trace("pit_queries.pit_audit_all_tables")
async def pit_audit_all_tables(
    conn,
    check_date: datetime | str,
) -> list[dict]:
    """Tüm tablolar için PIT sızıntı kontrolü.

    Args:
        conn: asyncpg connection
        check_date: Kontrol tarihi

    Returns:
        Tüm tabloların sızıntı kontrolü sonuçları
    """
    results = []

    for table in PIT_QUERY_TEMPLATES:
        try:
            # Her tablo için örnek identifier'ları al
            template = PIT_QUERY_TEMPLATES[table]
            id_col = template["identifier_column"]

            identifiers = await conn.fetch(f"SELECT DISTINCT {id_col} FROM {table} LIMIT 10")

            for row in identifiers:
                identifier = row[id_col]
                result = await pit_validate_no_leakage(conn, table, identifier, check_date)
                results.append(result)
        except Exception as e:
            results.append(
                {
                    "table": table,
                    "error": str(e),
                    "status": "❌ Kontrol yapılamadı",
                }
            )

    return results
