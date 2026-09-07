"""ALPHA BIST — Paper Trading Veritabanı Kurulum Modülü.

Sanal işlem (paper trading) portföy ve defter (ledger) tablolarının
PostgreSQL ve yerel DuckDB üzerinde otomatik oluşturulmasını sağlar.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)


@otel_trace("setup_paper_db.setup_tables")
async def setup_tables() -> None:
    """PostgreSQL üzerinde paper trading tablolarını oluşturur."""
    from services.core.database import init_databases, pg_execute

    await init_databases()

    query = """
    CREATE TABLE IF NOT EXISTS paper_trade_portfolio (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        target_date DATE NOT NULL,
        tickers JSONB NOT NULL,
        is_cash_regime BOOLEAN DEFAULT FALSE,
        is_rebalance BOOLEAN DEFAULT FALSE
    );

    CREATE TABLE IF NOT EXISTS paper_trade_ledger (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        portfolio_value NUMERIC NOT NULL,
        cash_ratio NUMERIC NOT NULL,
        cagr NUMERIC
    );
    """

    await pg_execute(query)
    logger.info("paper_trade_tablolari_olusturuldu", hedef="postgresql")


@otel_trace("setup_paper_db.setup_duckdb_tables")
def setup_duckdb_tables(db_path: str = "data/paper_trade.duckdb") -> None:
    """Yerel DuckDB veritabanında paper trading tablolarını ve indekslerini oluşturur.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
    """
    import duckdb

    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(db_path) as conn:
        conn.execute("SET checkpoint_threshold = '64MB';")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_trade_portfolio (
                id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                target_date VARCHAR,
                tickers VARCHAR,
                is_cash_regime BOOLEAN DEFAULT FALSE,
                is_rebalance BOOLEAN DEFAULT FALSE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pt_portfolio_date ON paper_trade_portfolio (target_date);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_trade_ledger (
                id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                period_start VARCHAR,
                period_end VARCHAR,
                portfolio_value DOUBLE,
                cash_ratio DOUBLE,
                cagr DOUBLE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pt_ledger_period ON paper_trade_ledger (period_start, period_end);")

    logger.info("paper_trade_tablolari_olusturuldu", hedef="duckdb", db_path=db_path)


def clear_paper_trade_duckdb(db_path: str = "data/paper_trade.duckdb") -> None:
    """DuckDB üzerindeki paper trading tablolarını temizler."""
    import duckdb

    target = Path(db_path)
    if not target.exists():
        return
    with duckdb.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS paper_trade_portfolio")
        conn.execute("DROP TABLE IF EXISTS paper_trade_ledger")


def export_paper_db_schema_to_polars() -> pl.DataFrame:
    """Paper trade tablo şema tanımlarını Polars DataFrame olarak döndürür."""
    schema_info: list[dict[str, Any]] = [
        {"table_name": "paper_trade_portfolio", "column_name": "id", "data_type": "BIGINT", "is_nullable": False},
        {"table_name": "paper_trade_portfolio", "column_name": "created_at", "data_type": "TIMESTAMP", "is_nullable": False},
        {"table_name": "paper_trade_portfolio", "column_name": "target_date", "data_type": "VARCHAR/DATE", "is_nullable": False},
        {"table_name": "paper_trade_portfolio", "column_name": "tickers", "data_type": "JSONB/VARCHAR", "is_nullable": False},
        {"table_name": "paper_trade_portfolio", "column_name": "is_cash_regime", "data_type": "BOOLEAN", "is_nullable": True},
        {"table_name": "paper_trade_portfolio", "column_name": "is_rebalance", "data_type": "BOOLEAN", "is_nullable": True},
        {"table_name": "paper_trade_ledger", "column_name": "id", "data_type": "BIGINT", "is_nullable": False},
        {"table_name": "paper_trade_ledger", "column_name": "created_at", "data_type": "TIMESTAMP", "is_nullable": False},
        {"table_name": "paper_trade_ledger", "column_name": "period_start", "data_type": "VARCHAR/DATE", "is_nullable": False},
        {"table_name": "paper_trade_ledger", "column_name": "period_end", "data_type": "VARCHAR/DATE", "is_nullable": False},
        {"table_name": "paper_trade_ledger", "column_name": "portfolio_value", "data_type": "DOUBLE/NUMERIC", "is_nullable": False},
        {"table_name": "paper_trade_ledger", "column_name": "cash_ratio", "data_type": "DOUBLE/NUMERIC", "is_nullable": False},
        {"table_name": "paper_trade_ledger", "column_name": "cagr", "data_type": "DOUBLE/NUMERIC", "is_nullable": True},
    ]
    return pl.DataFrame(schema_info)


def export_paper_db_schema_to_orjson_bytes() -> bytes:
    """Paper trade tablo şema tanımlarını orjson ikili serileştirilmiş bayt olarak döndürür."""
    df = export_paper_db_schema_to_polars()
    return orjson.dumps(df.to_dicts(), default=str)


__all__: list[str] = [
    "clear_paper_trade_duckdb",
    "export_paper_db_schema_to_orjson_bytes",
    "export_paper_db_schema_to_polars",
    "setup_duckdb_tables",
    "setup_tables",
]


if __name__ == "__main__":
    setup_duckdb_tables()
    with contextlib.suppress(Exception):
        asyncio.run(setup_tables())

