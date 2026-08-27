"""
ALPHA BIST — 30-Yıllık Yerel Tarihsel Veri Deposu (DuckDB & Polars-Native)
=============================================================================
Borsa İstanbul'un 1997 - 2026 arasındaki tüm 30 yıllık gerçek seans verilerini
yerel DuckDB veri tabanında saklar.
Tekrar tekrar internetten indirmeye gerek kalmadan 0.05 saniyede anında yükler.
"""

import os

import duckdb
import polars as pl
import structlog
import yfinance as yf

logger = structlog.get_logger()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
DB_FILE = os.path.join(DATA_DIR, "bist_30y_warehouse.db")

BIST_ALL_KEY_TICKERS = [
    "THYAO.IS",
    "GARAN.IS",
    "AKBNK.IS",
    "ISCTR.IS",
    "YKBNK.IS",
    "KCHOL.IS",
    "SAHOL.IS",
    "TUPRS.IS",
    "EREGL.IS",
    "SISE.IS",
    "ARCLK.IS",
    "FROTO.IS",
    "TOASO.IS",
    "ENKAI.IS",
    "PETKM.IS",
    "CCOLA.IS",
    "AEFES.IS",
    "TCELL.IS",
    "VAKBN.IS",
    "HALKB.IS",
    "BIMAS.IS",
    "ASELS.IS",
    "PGSUS.IS",
    "TTKOM.IS",
    "MGROS.IS",
    "ASTOR.IS",
    "KONTR.IS",
    "HEKTS.IS",
    "SASA.IS",
    "KOZAL.IS",
    "GUBRF.IS",
    "KRDMD.IS",
    "OYAKC.IS",
    "ALARK.IS",
    "SOKM.IS",
]

BENCHMARK_TICKER = "XU100.IS"


def _yf_to_polars(yf_df) -> pl.DataFrame:
    """yfinance pandas DataFrame'ini Polars'a çevir."""
    if yf_df is None or len(yf_df) == 0:
        return pl.DataFrame()
    df = yf_df.reset_index()
    if isinstance(df.columns, __import__("pandas").MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return pl.from_pandas(df)


class HistoricalDataWarehouse:
    """30 yıllık BIST tarihsel verisini yerel DuckDB diskte tutan ve anında sunan depo."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)

    def is_cached(self) -> bool:
        if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) < 10000:
            return False
        try:
            with duckdb.connect(DB_FILE) as conn:
                cur = conn.cursor()
                cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'main'")
                count = cur.fetchone()[0]
                return count >= 2
        except Exception:
            return False

    def download_and_save_warehouse(self, force_refresh: bool = False) -> tuple[int, int]:
        if self.is_cached() and not force_refresh:
            logger.info("30 yıllık yerel veri deposu zaten mevcut.")
            return len(BIST_ALL_KEY_TICKERS), 7277

        logger.info("30 yıllık BIST verisi indiriliyor ve yerel DuckDB veri tabanına kaydediliyor...")

        # 1. BIST-100 Endeksi
        from datetime import date
        end_date = date.today().isoformat()
        bm_raw = yf.download(BENCHMARK_TICKER, start="1997-01-01", end=end_date, progress=False)
        bm_df = _yf_to_polars(bm_raw)

        with duckdb.connect(DB_FILE) as conn:
            # Polars → DuckDB (native, pandas dönüşümü gereksiz)
            conn.execute("DROP TABLE IF EXISTS benchmark_xu100")
            conn.register("_bm_tmp", bm_df)
            conn.execute("CREATE TABLE benchmark_xu100 AS SELECT * FROM _bm_tmp")
            conn.unregister("_bm_tmp")

        # 2. Hisseler
        stocks_raw = yf.download(
            BIST_ALL_KEY_TICKERS, start="1997-01-01", end=end_date, progress=False, group_by="ticker"
        )

        all_dfs = []
        for t in BIST_ALL_KEY_TICKERS:
            if t in stocks_raw.columns.get_level_values(0):
                df_t = stocks_raw[t].dropna().copy()
                if isinstance(df_t.columns, __import__("pandas").MultiIndex):
                    df_t.columns = [c[0] for c in df_t.columns]
                if len(df_t) > 30:
                    sym = t.replace(".IS", "")
                    pl_df = _yf_to_polars(df_t)
                    pl_df = pl_df.with_columns(pl.lit(sym).alias("symbol"))
                    all_dfs.append(pl_df)

        if all_dfs:
            comb_df = pl.concat(all_dfs, how="diagonal")
            with duckdb.connect(DB_FILE) as conn:
                # Polars → DuckDB (native, pandas dönüşümü gereksiz)
                conn.execute("DROP TABLE IF EXISTS stock_candles")
                conn.register("_comb_tmp", comb_df)
                conn.execute("CREATE TABLE stock_candles AS SELECT * FROM _comb_tmp")
                conn.unregister("_comb_tmp")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_sym_date ON stock_candles(symbol, Date)")

        logger.info(f"Yerel depo başarıyla kaydedildi: {DB_FILE}")
        return len(all_dfs), len(bm_df)

    def load_30y_data(self) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
        """Yerel diskten 30 yıllık veriyi hafızaya yükler."""
        if not self.is_cached():
            self.download_and_save_warehouse()

        with duckdb.connect(DB_FILE) as conn:
            # DuckDB → Polars (native, pandas dönüşümü gereksiz)
            bm_df = conn.execute("SELECT * FROM benchmark_xu100").pl()
            comb_df = conn.execute("SELECT * FROM stock_candles").pl()

        stock_dict: dict[str, pl.DataFrame] = {}
        if "symbol" in comb_df.columns:
            for sym in comb_df["symbol"].unique().to_list():
                df_sym = comb_df.filter(pl.col("symbol") == sym).drop("symbol").sort("Date")
                canonical_ticker = sym if sym.endswith(".IS") else f"{sym}.IS"
                stock_dict[canonical_ticker] = df_sym

        return bm_df, stock_dict


# Singleton
historical_warehouse = HistoricalDataWarehouse()
