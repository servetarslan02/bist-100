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

import re
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
DEFAULT_PIT_LATEST_LIMIT: Final[int] = 1
DEFAULT_PIT_SNAPSHOT_LIMIT: Final[int] = 100
DEFAULT_PIT_DUCKDB_PATH: Final[str] = "data/pit_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

_SAFE_COLUMNS_PATTERN = re.compile(r"^[a-zA-Z0-9_,\s\.\*\(\)]+$")


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


@dataclass(slots=True)
class PITQueryTemplate:
    """Nokta-zamanı (Point-in-Time) sorgu şablonu tanımı.

    Attributes:
        table: Sorgulanacak PostgreSQL / DuckDB tablo adı.
        time_column: Olayın gerçekleştiği zaman damgası sütunu.
        created_column: Kaydın sisteme girildiği oluşturulma zaman damgası.
        identifier_column: Varlık anahtarı sütun adı (ticker, portfolio_id vb.).
        description: Şablonun işlevsel açıklaması.
    """

    table: str
    time_column: str
    created_column: str
    identifier_column: str
    description: str

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"PITQueryTemplate(table={self.table!r}, id_col={self.identifier_column!r}, "
            f"time_col={self.time_column!r}, created_col={self.created_column!r})"
        )

    def __getitem__(self, key: str) -> str:
        """Geriye dönük sözlük erişim uyumluluğu sağlar."""
        return getattr(self, key)

    def to_dict(self) -> dict[str, str]:
        """Sözlük formatına dönüştürür."""
        return {
            "table": self.table,
            "time_column": self.time_column,
            "created_column": self.created_column,
            "identifier_column": self.identifier_column,
            "description": self.description,
        }

    def to_orjson_bytes(self) -> bytes:
        """Model verilerini yüksek hızlı orjson bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())


def _validate_columns(columns: str) -> str:
    """Sütun isimlerinin SQL güvenliğini denetler."""
    cleaned = columns.strip()
    if not cleaned or not _SAFE_COLUMNS_PATTERN.match(cleaned) or ";" in cleaned or "--" in cleaned or "/*" in cleaned:
        raise ValueError(f"Geçersiz veya güvensiz sütun parametresi: {columns!r}")
    return cleaned


def _ensure_utc_datetime(dt_val: datetime | str) -> datetime:
    """Tarih girdisini doğrular ve UTC farkındalıklı datetime nesnesine çevirir."""
    if isinstance(dt_val, str):
        parsed = datetime.fromisoformat(dt_val)
    else:
        parsed = dt_val
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


# Her tablo için PIT-safe sorgu şablonu
# Kural: Sadece o tarihte bilinen veriyi döndür
PIT_QUERY_TEMPLATES: Final[dict[str, PITQueryTemplate]] = {
    "model_predictions": PITQueryTemplate(
        table="model_predictions",
        time_column="prediction_date",
        created_column="created_at",
        identifier_column="instrument_id",
        description="Model tahminleri — prediction_date'den önce oluşturulmuş olmalı",
    ),
    "daily_performance": PITQueryTemplate(
        table="daily_performance",
        time_column="date",
        created_column="created_at",
        identifier_column="strategy_id",
        description="Günlük performans — date'den önce bilinmeli",
    ),
    "signals": PITQueryTemplate(
        table="signals",
        time_column="created_at",
        created_column="created_at",
        identifier_column="instrument_id",
        description="Sinyaller — created_at'te bilinmeli",
    ),
    "positions": PITQueryTemplate(
        table="positions",
        time_column="created_at",
        created_column="created_at",
        identifier_column="portfolio_id",
        description="Pozisyonlar — created_at'te bilinmeli",
    ),
    "orders": PITQueryTemplate(
        table="orders",
        time_column="created_at",
        created_column="created_at",
        identifier_column="portfolio_id",
        description="Emirler — created_at'te bilinmeli",
    ),
    "scan_results": PITQueryTemplate(
        table="scan_results",
        time_column="timestamp",
        created_column="timestamp",
        identifier_column="ticker",
        description="Tarama sonuçları — timestamp'te bilinmeli",
    ),
}


# =====================================================
# PIT-SAFE QUERY FUNCTIONS (POSTGRESQL)
# =====================================================


@otel_trace("pit_queries.pit_fetch_as_of")
async def pit_fetch_as_of(
    conn: Any,
    table: str,
    identifier: str,
    as_of_date: datetime | str,
    columns: str = "*",
    additional_where: str = "",
) -> list[dict[str, Any]]:
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
    validated_columns = _validate_columns(columns)
    utc_as_of = _ensure_utc_datetime(as_of_date)

    # PIT-safe sorgu: created_column <= as_of_date
    query = f"""
        SELECT {validated_columns}
        FROM {template.table}
        WHERE {template.identifier_column} = $1
            AND {template.created_column} <= $2
    """
    params: list[Any] = [identifier, utc_as_of]

    if additional_where:
        query += f" AND {additional_where}"

    query += f" ORDER BY {template.created_column} DESC"

    try:
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(
            "pit_sorgusu_hatasi",
            tablo=table,
            kimlik=identifier,
            as_of_tarihi=str(utc_as_of),
            hata=str(e),
        )
        raise


@otel_trace("pit_queries.pit_fetch_latest")
async def pit_fetch_latest(
    conn: Any,
    table: str,
    identifier: str,
    limit: int = DEFAULT_PIT_LATEST_LIMIT,
    columns: str = "*",
) -> list[dict[str, Any]]:
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
    validated_columns = _validate_columns(columns)

    query = f"""
        SELECT {validated_columns}
        FROM {template.table}
        WHERE {template.identifier_column} = $1
        ORDER BY {template.created_column} DESC
        LIMIT $2
    """

    try:
        rows = await conn.fetch(query, identifier, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(
            "pit_son_kayit_sorgusu_hatasi",
            tablo=table,
            kimlik=identifier,
            hata=str(e),
        )
        raise


@otel_trace("pit_queries.pit_fetch_range")
async def pit_fetch_range(
    conn: Any,
    table: str,
    identifier: str,
    from_date: datetime | str,
    to_date: datetime | str,
    columns: str = "*",
) -> list[dict[str, Any]]:
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
    validated_columns = _validate_columns(columns)
    utc_from = _ensure_utc_datetime(from_date)
    utc_to = _ensure_utc_datetime(to_date)

    # PIT-safe: Hem time_column hem created_column kontrolü
    query = f"""
        SELECT {validated_columns}
        FROM {template.table}
        WHERE {template.identifier_column} = $1
            AND {template.time_column} >= $2
            AND {template.time_column} <= $3
            AND {template.created_column} <= $3
        ORDER BY {template.time_column} ASC
    """

    try:
        rows = await conn.fetch(query, identifier, utc_from, utc_to)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(
            "pit_aralik_sorgusu_hatasi",
            tablo=table,
            kimlik=identifier,
            hata=str(e),
        )
        raise


@otel_trace("pit_queries.pit_validate_no_leakage")
async def pit_validate_no_leakage(
    conn: Any,
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
    utc_check = _ensure_utc_datetime(check_date)

    # check_date'ten SONRA oluşturulmuş ama check_date'ten ÖNCEki veriyi gösteren kayıtlar
    query = f"""
        SELECT COUNT(*) as leak_count
        FROM {template.table}
        WHERE {template.identifier_column} = $1
            AND {template.created_column} > $2
            AND {template.time_column} <= $2
    """

    try:
        result = await conn.fetchrow(query, identifier, utc_check)
        leak_count = int(result["leak_count"] if result is not None else 0)

        return {
            "table": table,
            "identifier": identifier,
            "check_date": str(utc_check),
            "leak_count": leak_count,
            "has_leakage": leak_count > 0,
            "status": "❌ SIZINTI TESPİT EDİLDİ" if leak_count > 0 else "✅ PIT-safe",
        }
    except Exception as e:
        logger.error(
            "pit_sizinti_denetimi_hatasi",
            tablo=table,
            kimlik=identifier,
            hata=str(e),
        )
        raise


@otel_trace("pit_queries.pit_fetch_snapshot")
async def pit_fetch_snapshot(
    conn: Any,
    table: str,
    snapshot_date: datetime | str,
    columns: str = "*",
    limit: int = DEFAULT_PIT_SNAPSHOT_LIMIT,
) -> list[dict[str, Any]]:
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
    validated_columns = _validate_columns(columns)
    utc_snapshot = _ensure_utc_datetime(snapshot_date)

    query = f"""
        SELECT DISTINCT ON ({template.identifier_column})
            {validated_columns}
        FROM {template.table}
        WHERE {template.created_column} <= $1
        ORDER BY {template.identifier_column}, {template.created_column} DESC
        LIMIT $2
    """

    try:
        rows = await conn.fetch(query, utc_snapshot, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(
            "pit_anlik_goruntu_sorgusu_hatasi",
            tablo=table,
            as_of_tarihi=str(utc_snapshot),
            hata=str(e),
        )
        raise


# =====================================================
# DUCKDB PIT-SAFE QUERY SUPPORT
# =====================================================


def pit_fetch_duckdb(
    duck_conn: duckdb.DuckDBPyConnection,
    table: str,
    identifier: str,
    as_of_date: datetime | str,
    columns: str = "*",
) -> pl.DataFrame:
    """DuckDB üzerinden sıfır kopyalı ve PIT-safe Polars DataFrame sorgular.

    Args:
        duck_conn: Aktif DuckDB bağlantısı.
        table: Tablo adı.
        identifier: Enstrüman veya varlık kimliği.
        as_of_date: Referans nokta-zamanı tarihi.
        columns: İstenen sütunlar.

    Returns:
        Sorgu sonucu Polars DataFrame.
    """
    if table not in PIT_QUERY_TEMPLATES:
        raise ValueError(f"Bilinmeyen tablo: {table}. Desteklenen: {list(PIT_QUERY_TEMPLATES.keys())}")

    template = PIT_QUERY_TEMPLATES[table]
    validated_columns = _validate_columns(columns)
    utc_as_of = _ensure_utc_datetime(as_of_date)

    query = f"""
        SELECT {validated_columns}
        FROM {template.table}
        WHERE {template.identifier_column} = ?
            AND {template.created_column} <= ?
        ORDER BY {template.created_column} DESC
    """
    try:
        arrow_table = duck_conn.execute(query, [identifier, utc_as_of]).arrow()
        return pl.from_arrow(arrow_table)  # type: ignore[return-value]
    except Exception as e:
        logger.error(
            "pit_duckdb_sorgu_hatasi",
            tablo=table,
            kimlik=identifier,
            as_of_tarihi=str(utc_as_of),
            hata=str(e),
        )
        raise


# =====================================================
# ZERO-TOUCH & SELF-HEALING DATA GUARD
# =====================================================


def sanitize_pit_polars(
    df: pl.DataFrame,
    time_column: str,
    created_column: str,
    as_of_date: datetime | str,
) -> pl.DataFrame:
    """Polars DataFrame içindeki geleceğe sızıntılı verileri otomatik temizler (Self-Healing).

    Args:
        df: Filtrelenecek ham Polars DataFrame.
        time_column: Olay zamanı sütun adı.
        created_column: Kayıt oluşturulma zamanı sütun adı.
        as_of_date: Bu tarihten sonra oluşturulmuş kayıtları süzer.

    Returns:
        Sızıntısız temizlenmiş Polars DataFrame.
    """
    if df.is_empty():
        return df

    utc_as_of = _ensure_utc_datetime(as_of_date)

    if created_column not in df.columns:
        logger.warning("pit_filtreleme_sutun_bulunamadi", aranan=created_column)
        return df

    # created_column <= as_of_date filtresi uygula
    return df.filter(pl.col(created_column) <= utc_as_of)


# =====================================================
# HELPER: PIT-SAFE DATAFRAME FETCH (Polars)
# =====================================================


@otel_trace("pit_queries.pit_fetch_df")
async def pit_fetch_df(
    conn: Any,
    table: str,
    identifier: str,
    from_date: datetime | str,
    to_date: datetime | str,
) -> pl.DataFrame:
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
    rows = await pit_fetch_range(conn, table, identifier, from_date, to_date)
    if not rows:
        return pl.DataFrame()
    return pl.from_dicts(rows)


# =====================================================
# PIT AUDIT & DUCKDB PERSISTENCE
# =====================================================


@otel_trace("pit_queries.pit_audit_all_tables")
async def pit_audit_all_tables(
    conn: Any,
    check_date: datetime | str,
) -> list[dict[str, Any]]:
    """Tüm tablolar için PIT sızıntı kontrolü.

    Args:
        conn: asyncpg connection
        check_date: Kontrol tarihi

    Returns:
        Tüm tabloların sızıntı kontrolü sonuçları
    """
    results: list[dict[str, Any]] = []

    for table, template in PIT_QUERY_TEMPLATES.items():
        try:
            id_col = template.identifier_column
            identifiers = await conn.fetch(f"SELECT DISTINCT {id_col} FROM {template.table} LIMIT 10")

            for row in identifiers:
                identifier = str(row[id_col])
                result = await pit_validate_no_leakage(conn, table, identifier, check_date)
                results.append(result)
        except Exception as e:
            results.append(
                {
                    "table": table,
                    "identifier": "UNKNOWN",
                    "check_date": str(_ensure_utc_datetime(check_date)),
                    "leak_count": -1,
                    "has_leakage": False,
                    "status": f"❌ Kontrol yapılamadı: {e}",
                    "error": str(e),
                }
            )

    return results


def export_pit_audit_to_polars(audit_results: list[dict[str, Any]]) -> pl.DataFrame:
    """PIT sızıntı denetim sonuçlarını Polars DataFrame formatına dönüştürür.

    Args:
        audit_results: Denetim sonuç sözlükleri listesi.

    Returns:
        Katı tip şemalı Polars DataFrame.
    """
    if not audit_results:
        return pl.DataFrame(
            schema={
                "table": pl.String,
                "identifier": pl.String,
                "check_date": pl.String,
                "leak_count": pl.Int64,
                "has_leakage": pl.Boolean,
                "status": pl.String,
            }
        )

    # Sözlük alanlarını şemaya uygun normalize et
    normalized_rows = []
    for r in audit_results:
        normalized_rows.append(
            {
                "table": str(r.get("table", "")),
                "identifier": str(r.get("identifier", "")),
                "check_date": str(r.get("check_date", "")),
                "leak_count": int(r.get("leak_count", 0)),
                "has_leakage": bool(r.get("has_leakage", False)),
                "status": str(r.get("status", "")),
            }
        )

    return pl.DataFrame(
        normalized_rows,
        schema={
            "table": pl.String,
            "identifier": pl.String,
            "check_date": pl.String,
            "leak_count": pl.Int64,
            "has_leakage": pl.Boolean,
            "status": pl.String,
        },
    )


def export_pit_results_to_orjson(results: Any) -> bytes:
    """PIT sorgu sonuçlarını C hızında orjson bayt dizisine dönüştürür.

    Args:
        results: Serileştirilecek veri (liste, sözlük veya model).

    Returns:
        JSON baytları.
    """
    return orjson.dumps(results, default=str)


def to_orjson_bytes(results: Any) -> bytes:
    """export_pit_results_to_orjson için takma ad."""
    return export_pit_results_to_orjson(results)


def save_pit_audit_to_duckdb(
    audit_results: list[dict[str, Any]],
    db_path: str = DEFAULT_PIT_DUCKDB_PATH,
) -> None:
    """PIT denetim sonuçlarını DuckDB kalıcı tablosuna kaydeder.

    Args:
        audit_results: Kaydedilecek sızıntı denetim kayıtları.
        db_path: DuckDB veritabanı dosya yolu.
    """
    if not audit_results:
        return

    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    df = export_pit_audit_to_polars(audit_results)

    conn = duckdb.connect(str(path_obj))
    try:
        configure_duckdb_wal(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pit_leakage_audit (
                table_name VARCHAR,
                identifier VARCHAR,
                check_date VARCHAR,
                leak_count BIGINT,
                has_leakage BOOLEAN,
                status VARCHAR,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.register("tmp_pit_df", df.to_arrow())
        try:
            conn.execute(
                """
                INSERT INTO pit_leakage_audit (table_name, identifier, check_date, leak_count, has_leakage, status)
                SELECT "table", identifier, check_date, leak_count, has_leakage, status
                FROM tmp_pit_df
                """
            )
        finally:
            conn.unregister("tmp_pit_df")
        conn.commit()
        logger.info("pit_denetim_sonuclari_duckdb_kaydedildi", kayit_sayisi=df.height, db_path=str(path_obj))
    finally:
        conn.close()


def read_pit_audit_from_duckdb(
    db_path: str = DEFAULT_PIT_DUCKDB_PATH,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB içindeki PIT denetim geçmişini Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        limit: Döndürülecek maksimum kayıt sayısı.

    Returns:
        PIT sızıntı denetim kayıtlarını içeren Polars DataFrame.
    """
    path = Path(db_path)
    schema = {
        "table_name": pl.String,
        "identifier": pl.String,
        "check_date": pl.String,
        "leak_count": pl.Int64,
        "has_leakage": pl.Boolean,
        "status": pl.String,
        "recorded_at": pl.String,
    }
    if not path.exists():
        return pl.DataFrame(schema=schema)

    conn = duckdb.connect(str(path), read_only=True)
    try:
        configure_duckdb_wal(conn)
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
        if "pit_leakage_audit" not in tables:
            return pl.DataFrame(schema=schema)
        arrow_table = conn.execute(
            f"SELECT table_name, identifier, check_date, leak_count, has_leakage, status, CAST(recorded_at AS VARCHAR) AS recorded_at "
            f"FROM pit_leakage_audit ORDER BY recorded_at DESC LIMIT {int(limit)}"
        ).arrow()
        return pl.from_arrow(arrow_table)  # type: ignore[return-value]
    finally:
        conn.close()


def clear_pit_audit_duckdb(
    db_path: str = DEFAULT_PIT_DUCKDB_PATH,
) -> None:
    """DuckDB tablosundaki PIT sızıntı denetim kayıtlarını temizler.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
    """
    path = Path(db_path)
    if not path.exists():
        return
    conn = duckdb.connect(str(path))
    try:
        configure_duckdb_wal(conn)
        conn.execute("DROP TABLE IF EXISTS pit_leakage_audit")
        conn.commit()
        logger.info("pit_audit_duckdb_temizlendi", db_path=str(path))
    finally:
        conn.close()


__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_PIT_DUCKDB_PATH",
    "DEFAULT_PIT_LATEST_LIMIT",
    "DEFAULT_PIT_SNAPSHOT_LIMIT",
    "DEFAULT_WAL_SIZE",
    "PIT_QUERY_TEMPLATES",
    "PITQueryTemplate",
    "clear_pit_audit_duckdb",
    "configure_duckdb_wal",
    "export_pit_audit_to_polars",
    "export_pit_results_to_orjson",
    "pit_audit_all_tables",
    "pit_fetch_as_of",
    "pit_fetch_df",
    "pit_fetch_duckdb",
    "pit_fetch_latest",
    "pit_fetch_range",
    "pit_fetch_snapshot",
    "pit_validate_no_leakage",
    "read_pit_audit_from_duckdb",
    "sanitize_pit_polars",
    "save_pit_audit_to_duckdb",
    "to_orjson_bytes",
]

