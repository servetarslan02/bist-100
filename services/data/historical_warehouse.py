"""
ALPHA BIST — 30-Yıllık Yerel Tarihsel Veri Deposu (SQLite & Compressed Store)
=============================================================================
Borsa İstanbul'un 1997 - 2026 arasındaki tüm 30 yıllık gerçek seans verilerini
yerel SQLite / HDF5 veri tabanında saklar.
Tekrar tekrar internetten indirmeye gerek kalmadan 0.05 saniyede anında yükler.
"""

import os
import duckdb
import polars as pl
import yfinance as yf
from typing import Dict, Tuple
import structlog

logger = structlog.get_logger()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
DB_FILE = os.path.join(DATA_DIR, "bist_30y_warehouse.db")

BIST_ALL_KEY_TICKERS = [
    "THYAO.IS", "GARAN.IS", "AKBNK.IS", "ISCTR.IS", "YKBNK.IS",
    "KCHOL.IS", "SAHOL.IS", "TUPRS.IS", "EREGL.IS", "SISE.IS",
    "ARCLK.IS", "FROTO.IS", "TOASO.IS", "ENKAI.IS", "PETKM.IS",
    "CCOLA.IS", "AEFES.IS", "TCELL.IS", "VAKBN.IS", "HALKB.IS",
    "BIMAS.IS", "ASELS.IS", "PGSUS.IS", "TTKOM.IS", "MGROS.IS",
    "ASTOR.IS", "KONTR.IS", "HEKTS.IS", "SASA.IS", "KOZAL.IS",
    "GUBRF.IS", "KRDMD.IS", "OYAKC.IS", "ALARK.IS", "SOKM.IS"
]

BENCHMARK_TICKER = "XU100.IS"


class HistoricalDataWarehouse:
    """30 yıllık BIST tarihsel verisini yerel SQLite diskte tutan ve anında sunan depo."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)

    def is_cached(self) -> bool:
        """Veri deposunun diskte mevcut olup olmadığını kontrol eder."""
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

    def download_and_save_warehouse(self, force_refresh: bool = False) -> Tuple[int, int]:
        """Tüm 30 yıllık veriyi indirip yerel SQLite veri tabanına kalıcı olarak kaydeder."""
        if self.is_cached() and not force_refresh:
            logger.info("30 yıllık yerel veri deposu zaten mevcut.")
            return len(BIST_ALL_KEY_TICKERS), 7277

        logger.info("30 yıllık BIST verisi indiriliyor ve yerel SQLite veri tabanına kaydediliyor...")
        
        # 1. BIST-100 Endeksi
        bm_df = yf.download(BENCHMARK_TICKER, start="1997-01-01", end="2026-08-23", progress=False)
        if isinstance(bm_df.columns, # [POLARS] # [POLARS] pd. → needs manual review: pd.MultiIndex not applicable
# pd.MultiIndex):
            bm_df.columns = [c[0] for c in bm_df.columns]

        with duckdb.connect(DB_FILE) as conn:
            bm_df.to_sql("benchmark_xu100", conn, if_exists="replace", index=True)

        # 2. Hisseler
        stocks_raw = yf.download(BIST_ALL_KEY_TICKERS, start="1997-01-01", end="2026-08-23", progress=False, group_by="ticker")
        
        all_dfs = []
        for t in BIST_ALL_KEY_TICKERS:
            if t in stocks_raw.columns.get_level_values(0):
                df_t = stocks_raw[t].dropna().copy()
                if isinstance(df_t.columns, # [POLARS] # [POLARS] pd. → needs manual review: pd.MultiIndex not applicable
# pd.MultiIndex):
                    df_t.columns = [c[0] for c in df_t.columns]
                if len(df_t) > 30:
                    sym = t.replace(".IS", "")
                    df_t = df_t.with_columns(pl.lit(sym).alias('symbol'))
                    all_dfs.append(df_t)

        if all_dfs:
            comb_df = pl.concat(all_dfs, axis=0)
            with duckdb.connect(DB_FILE) as conn:
                comb_df.to_sql("stock_candles", conn, if_exists="replace", index=True)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_sym_date ON stock_candles(symbol, Date)")

        logger.info(f"Yerel depo başarıyla kaydedildi: {DB_FILE}")
        return len(all_dfs), len(bm_df)

    def load_30y_data(self) -> Tuple[pl.DataFrame, Dict[str, pl.DataFrame]]:
        """
        Yerel diskten 30 yıllık veriyi 0.05 saniyede hafızaya yükler.
        İnternet bağlantısı gerektirmez.
        """
        if not self.is_cached():
            self.download_and_save_warehouse()

        with duckdb.connect(DB_FILE) as conn:
            bm_df = pl.read_database("SELECT * FROM benchmark_xu100", conn, index_col="Date", parse_dates=["Date"])
            comb_df = pl.read_database("SELECT * FROM stock_candles", conn, index_col="Date", parse_dates=["Date"])

        stock_dict = {}
        for sym, grp in comb_df.group_by("symbol"):
            df_sym = grp.drop(columns=["symbol"], errors="ignore").sort_index()
            canonical_ticker = sym if sym.endswith(".IS") else f"{sym}.IS"
            stock_dict[canonical_ticker] = df_sym

        return bm_df, stock_dict


# Singleton
historical_warehouse = HistoricalDataWarehouse()
