"""ALPHA BIST — Polars Utility Functions

Polars DataFrame işlemleri için ortak ve yüksek performanslı yardımcı fonksiyonlar.
Tekrarlanan kalıpları merkezileştirir, veri sızıntılarını ve tip bozulmalarını önler.

Kullanım:
    from services.core.polars_utils import (
        yf_to_polars,
        safe_polars_from_pandas,
        duckdb_to_polars,
        polars_to_duckdb,
        clean_numeric_extremes,
        export_polars_to_orjson,
        polars_from_orjson,
    )
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

if TYPE_CHECKING:
    import duckdb

logger = structlog.get_logger(__name__)

# Modül Sabitleri
DEFAULT_IF_EXISTS: Final[str] = "replace"
VALID_IF_EXISTS_MODES: Final[set[str]] = {"replace", "append"}
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

_SAFE_TABLE_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


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


def _validate_table_name(table_name: str) -> str:
    """Tablo isminin SQL güvenliğini denetler."""
    cleaned = table_name.strip()
    if not cleaned or not _SAFE_TABLE_PATTERN.match(cleaned):
        raise ValueError(f"Geçersiz veya güvensiz tablo adı: {table_name!r}")
    return cleaned


@otel_trace("polars_utils.yf_to_polars")
def yf_to_polars(raw_df: Any) -> pl.DataFrame:
    """yfinance pandas DataFrame'ini Polars'a çevirir.

    MultiIndex sütunları düzleştirir, Date sütununu parse eder.

    Args:
        raw_df: yfinance'dan dönen pandas DataFrame.

    Returns:
        Polars DataFrame.
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
        df: pandas DataFrame veya uyumlu nesne.

    Returns:
        Polars DataFrame veya None.
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
        logger.warning("pandas_polars_donusum_hatasi", hata=str(e))
        return None


@otel_trace("polars_utils.duckdb_to_polars")
def duckdb_to_polars(conn: Any, query: str) -> pl.DataFrame:
    """DuckDB sorgusunu sıfır kopyalı Arrow üzerinden Polars DataFrame olarak döndürür.

    Args:
        conn: DuckDB bağlantısı.
        query: SQL sorgusu.

    Returns:
        Polars DataFrame.
    """
    try:
        return pl.from_arrow(conn.execute(query).arrow())  # type: ignore[return-value]
    except AttributeError:
        # Eski DuckDB fallback
        return conn.execute(query).pl()


@otel_trace("polars_utils.polars_to_duckdb")
def polars_to_duckdb(
    conn: Any,
    df: pl.DataFrame,
    table_name: str,
    if_exists: str = DEFAULT_IF_EXISTS,
) -> None:
    """Polars DataFrame'ini DuckDB tablosuna güvenle ve sıfır kopyayla yazar.

    Args:
        conn: DuckDB bağlantısı.
        df: Kaydedilecek Polars DataFrame.
        table_name: Hedef tablo adı.
        if_exists: 'replace' (yeniden oluştur) veya 'append' (ekle).
    """
    safe_table = _validate_table_name(table_name)
    mode = if_exists.lower().strip()
    if mode not in VALID_IF_EXISTS_MODES:
        raise ValueError(f"Geçersiz if_exists kipi: {if_exists!r}. İzin verilenler: {VALID_IF_EXISTS_MODES}")

    temp_view = f"_tmp_{safe_table}"
    try:
        conn.register(temp_view, df.to_arrow())
        if mode == "replace":
            conn.execute(f"CREATE OR REPLACE TABLE {safe_table} AS SELECT * FROM {temp_view}")
        else:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {safe_table} AS SELECT * FROM {temp_view} WHERE 1=0")
            conn.execute(f"INSERT INTO {safe_table} SELECT * FROM {temp_view}")
    finally:
        conn.unregister(temp_view)


@otel_trace("polars_utils.concat_dataframes")
def concat_dataframes(dfs: list[pl.DataFrame]) -> pl.DataFrame:
    """Birden fazla Polars DataFrame'i güvenli şekilde birleştirir.

    Farklı sütun yapılarına sahip olabilirler (diagonal concat).

    Args:
        dfs: Polars DataFrame listesi.

    Returns:
        Birleştirilmiş Polars DataFrame.
    """
    non_empty = [df for df in dfs if df is not None and not df.is_empty()]
    if not non_empty:
        return pl.DataFrame()
    if len(non_empty) == 1:
        return non_empty[0]
    return pl.concat(non_empty, how="diagonal")


# =====================================================
# QUANT & SAYISAL GÜVENLİK YARDIMCILARI (KURAL 2)
# =====================================================


def clean_numeric_extremes(
    df: pl.DataFrame,
    columns: list[str] | None = None,
    replace_val: float = 0.0,
) -> pl.DataFrame:
    """Sayısal sütunlardaki NaN, Null ve Sonsuz (Inf/-Inf) değerleri güvenli değere dönüştürür.

    Args:
        df: İşlenecek Polars DataFrame.
        columns: Temizlenecek sütunlar (None ise tüm sayısal sütunlar).
        replace_val: Aşırı/bozuk değerlerin yerine yazılacak sayı (varsayılan: 0.0).

    Returns:
        Temizlenmiş Polars DataFrame.
    """
    if df.is_empty():
        return df

    target_cols = columns or [c for c, dtype in df.schema.items() if dtype.is_numeric()]
    if not target_cols:
        return df

    exprs = []
    for col in target_cols:
        if col in df.columns:
            # NaN, Null veya Sonsuz (is_finite değil) ise replace_val ata
            expr = (
                pl.when(pl.col(col).is_finite())
                .then(pl.col(col))
                .otherwise(pl.lit(replace_val))
                .alias(col)
            )
            exprs.append(expr)

    return df.with_columns(exprs) if exprs else df


def slice_pit_dataframe(
    df: pl.DataFrame,
    date_column: str,
    as_of_date: datetime | str,
) -> pl.DataFrame:
    """Point-in-Time güvenliği için as_of_date sonrasındaki kayıtları keser (Look-Ahead engeli).

    Args:
        df: Kaynak Polars DataFrame.
        date_column: Zaman sütunu adı.
        as_of_date: Referans kesim tarihi.

    Returns:
        PIT-safe Polars DataFrame.
    """
    if df.is_empty() or date_column not in df.columns:
        return df

    if isinstance(as_of_date, str):
        cutoff = datetime.fromisoformat(as_of_date)
    else:
        cutoff = as_of_date
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)

    return df.filter(pl.col(date_column) <= cutoff)


# =====================================================
# ORJSON SERİLEŞTİRME YARDIMCILARI (KURAL 5)
# =====================================================


def export_polars_to_orjson(df: pl.DataFrame) -> bytes:
    """Polars DataFrame'ini C hızında orjson bayt dizisine dönüştürür.

    Args:
        df: Serileştirilecek Polars DataFrame.

    Returns:
        JSON baytları.
    """
    return orjson.dumps(df.to_dicts(), default=str)


def polars_from_orjson(json_bytes: bytes | str) -> pl.DataFrame:
    """orjson bayt veya metninden Polars DataFrame oluşturur.

    Args:
        json_bytes: JSON veri baytları veya metni.

    Returns:
        Polars DataFrame.
    """
    data = orjson.loads(json_bytes)
    if not data:
        return pl.DataFrame()
    return pl.from_dicts(data)


__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_IF_EXISTS",
    "DEFAULT_WAL_SIZE",
    "VALID_IF_EXISTS_MODES",
    "clean_numeric_extremes",
    "concat_dataframes",
    "configure_duckdb_wal",
    "duckdb_to_polars",
    "export_polars_to_orjson",
    "polars_from_orjson",
    "polars_to_duckdb",
    "safe_polars_from_pandas",
    "slice_pit_dataframe",
    "yf_to_polars",
]

