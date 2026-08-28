"""ALPHA BIST — Polars Utility Functions

Polars DataFrame işlemleri için ortak yardımcı fonksiyonlar.
Tekrarlanan kalıpları merkezileştirir.

Kullanım:
    from services.core.polars_utils import yf_to_polars, safe_polars_from_pandas
"""

from __future__ import annotations

from typing import Any

import polars as pl
import structlog
import functools
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.polars_utils")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


@otel_trace("polars_utils.yf_to_polars")
def yf_to_polars(raw_df: Any) -> pl.DataFrame:
    """yfinance pandas DataFrame'ini Polars'a çevir.

    MultiIndex sütunları düzleştirir, Date sütununu parse eder.

    Args:
        raw_df: yfinance'dan dönen pandas DataFrame

    Returns:
        Polars DataFrame
    """
    import pandas as pd

    if raw_df is None or (hasattr(raw_df, "empty") and raw_df.empty):
        return pl.DataFrame()

    # MultiIndex sütun düzleştirme
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df = raw_df.copy()
        raw_df.columns = [c[0] if isinstance(c, tuple) else c for c in raw_df.columns]

    # Index'i reset et (Date genelde index'te)
    if raw_df.index.name or isinstance(raw_df.index, pd.DatetimeIndex):
        raw_df = raw_df.reset_index()

    return pl.from_pandas(raw_df)


@otel_trace("polars_utils.safe_polars_from_pandas")
def safe_polars_from_pandas(df: Any) -> pl.DataFrame | None:
    """Güvenli pandas → Polars dönüşümü. Hata durumunda None döner.

    Args:
        df: pandas DataFrame veya uyumlu nesne

    Returns:
        Polars DataFrame veya None
    """
    if df is None:
        return None
    if isinstance(df, pl.DataFrame):
        return df
    try:
        if hasattr(df, "to_pandas"):
            return pl.from_pandas(df.to_pandas())
        return pl.from_pandas(df)
    except Exception as e:
        logger.warning("pandas → Polars conversion failed", error=str(e))
        return None


@otel_trace("polars_utils.duckdb_to_polars")
def duckdb_to_polars(conn: Any, query: str) -> pl.DataFrame:
    """DuckDB sorgusunu doğrudan Polars DataFrame olarak döndür.

    Args:
        conn: DuckDB connection
        query: SQL sorgusu

    Returns:
        Polars DataFrame
    """
    return conn.execute(query).pl()


@otel_trace("polars_utils.polars_to_duckdb")
def polars_to_duckdb(conn: Any, df: pl.DataFrame, table_name: str, if_exists: str = "replace") -> None:
    """Polars DataFrame'ini DuckDB tablosuna yaz (pandas ara adım yok).

    Args:
        conn: DuckDB connection
        df: Polars DataFrame
        table_name: Hedef tablo adı
        if_exists: 'replace' (drop+create) veya 'append' (insert into)
    """
    if if_exists == "replace":
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

    conn.register(f"_tmp_{table_name}", df)
    if if_exists == "replace":
        conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _tmp_{table_name}")
    else:
        conn.execute(f"INSERT INTO {table_name} SELECT * FROM _tmp_{table_name}")
    conn.unregister(f"_tmp_{table_name}")


@otel_trace("polars_utils.concat_dataframes")
def concat_dataframes(dfs: list[pl.DataFrame]) -> pl.DataFrame:
    """Birden fazla Polars DataFrame'i güvenli şekilde birleştir.

    Farklı sütun yapılarına sahip olabilirler (diagonal concat).

    Args:
        dfs: Polars DataFrame listesi

    Returns:
        Birleştirilmiş Polars DataFrame
    """
    non_empty = [df for df in dfs if df is not None and len(df) > 0]
    if not non_empty:
        return pl.DataFrame()
    if len(non_empty) == 1:
        return non_empty[0]
    return pl.concat(non_empty, how="diagonal")
