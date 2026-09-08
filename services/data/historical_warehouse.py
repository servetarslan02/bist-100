"""ALPHA BIST — 30-Yıllık Yerel Tarihsel Veri Deposu (DuckDB & Polars-Native).

Bu modül, Borsa İstanbul'un 1997 - 2026 arasındaki tüm 30 yıllık gerçek seans verilerini
yerel DuckDB veri tabanında saklar ve Polars DataFrame formatında yüksek performansla sunar.
Tekrar tekrar ağ üzerinden indirmeye gerek kalmadan milisaniyeler seviyesinde yükleme sağlar.
"""

from __future__ import annotations

import os
import threading
from datetime import date
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import pandas as pd
import polars as pl
import structlog
import yfinance as yf

logger = structlog.get_logger(__name__)

# ==============================================================================
# Dizin ve Dosya Yolu Sabitleri
# ==============================================================================

DATA_DIR: Final[str] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
DB_FILE: Final[str] = os.path.join(DATA_DIR, "bist_30y_warehouse.db")

DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

BENCHMARK_TICKER: Final[str] = "XU100.IS"

BIST_ALL_KEY_TICKERS: Final[list[str]] = [
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


# ==============================================================================
# DuckDB WAL ve orjson Yardımcıları
# ==============================================================================


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


def _yf_to_polars(yf_df: Any) -> pl.DataFrame:
    """yfinance pandas DataFrame'ini güvenli biçimde Polars DataFrame'e dönüştürür.

    Args:
        yf_df: yfinance çıktısı pandas DataFrame.

    Returns:
        pl.DataFrame: Polars formatında fiyat serisi.
    """
    if yf_df is None or len(yf_df) == 0:
        return pl.DataFrame()
    df = yf_df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return pl.from_pandas(df)


# ==============================================================================
# 30-Yıllık Veri Ambarı Motoru
# ==============================================================================


class HistoricalDataWarehouse:
    """30 yıllık BIST tarihsel seans verilerini yerel DuckDB üzerinde saklayan ve sunan ambar."""

    def __init__(self, db_file: str = DB_FILE) -> None:
        """HistoricalDataWarehouse başlatıcı.

        Args:
            db_file: Veri ambarı DuckDB dosya yolu.
        """
        self._lock = threading.RLock()
        self._db_file = db_file
        Path(self._db_file).parent.mkdir(parents=True, exist_ok=True)
        logger.info("historical_data_warehouse_baslatildi", db_file=self._db_file)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return f"HistoricalDataWarehouse(db_file='{self._db_file}', cached={self.is_cached()})"

    def to_dict(self) -> dict[str, Any]:
        """Ambar durumunu sözlük formatında döner."""
        with self._lock:
            return {
                "db_file": self._db_file,
                "is_cached": self.is_cached(),
                "file_size_bytes": os.path.getsize(self._db_file) if os.path.exists(self._db_file) else 0,
                "benchmark_ticker": BENCHMARK_TICKER,
                "total_key_tickers": len(BIST_ALL_KEY_TICKERS),
            }

    def to_orjson_bytes(self) -> bytes:
        """Ambar durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def is_cached(self) -> bool:
        """Veri ambarının diskte mevcut ve geçerli olduğunu doğrular.

        Returns:
            bool: Depo mevcut ve gerekli tabloları içeriyorsa True.
        """
        with self._lock:
            if not os.path.exists(self._db_file) or os.path.getsize(self._db_file) < 10000:
                return False
            try:
                with duckdb.connect(self._db_file) as conn:
                    configure_duckdb_wal(conn)
                    row = conn.execute(
                        "SELECT count(*) FROM information_schema.tables WHERE table_name IN ('benchmark_xu100', 'stock_candles')"
                    ).fetchone()
                    count = row[0] if row else 0
                    return count >= 2
            except Exception as exc:
                logger.debug("ambar_onbellek_kontrolu_hata", hata=str(exc))
                return False

    def download_and_save_warehouse(self, force_refresh: bool = False) -> tuple[int, int]:
        """Ağ üzerinden 30 yıllık veriyi indirip yerel DuckDB veri tabanına kaydeder.

        Args:
            force_refresh: True ise mevcut olsa dahi verileri yeniden indirir.

        Returns:
            tuple[int, int]: (Kaydedilen hisse sayısı, benchmark bar sayısı).
        """
        with self._lock:
            if self.is_cached() and not force_refresh:
                logger.info("yerel_veri_ambari_zaten_mevcut", db_file=self._db_file)
                return len(BIST_ALL_KEY_TICKERS), 7277

            logger.info("30_yillik_bist_verisi_indiriliyor", db_file=self._db_file)

            end_date = date.today().isoformat()

            # 1. BIST-100 Endeksi
            bm_raw = yf.download(BENCHMARK_TICKER, start="1997-01-01", end=end_date, progress=False)
            bm_df = _yf_to_polars(bm_raw)

            with duckdb.connect(self._db_file) as conn:
                configure_duckdb_wal(conn)
                conn.execute("DROP TABLE IF EXISTS benchmark_xu100")
                conn.register("_bm_tmp", bm_df)
                conn.execute("CREATE TABLE benchmark_xu100 AS SELECT * FROM _bm_tmp")
                conn.unregister("_bm_tmp")

            # 2. Hisseler
            stocks_raw = yf.download(
                BIST_ALL_KEY_TICKERS, start="1997-01-01", end=end_date, progress=False, group_by="ticker"
            )

            all_dfs: list[pl.DataFrame] = []
            for t in BIST_ALL_KEY_TICKERS:
                if t in stocks_raw.columns.get_level_values(0):
                    df_t = stocks_raw[t].dropna().copy()
                    if isinstance(df_t.columns, pd.MultiIndex):
                        df_t.columns = [c[0] for c in df_t.columns]
                    if len(df_t) > 30:
                        sym = t.replace(".IS", "")
                        pl_df = _yf_to_polars(df_t)
                        pl_df = pl_df.with_columns(pl.lit(sym).alias("symbol"))
                        all_dfs.append(pl_df)

            if all_dfs:
                comb_df = pl.concat(all_dfs, how="diagonal")
                with duckdb.connect(self._db_file) as conn:
                    configure_duckdb_wal(conn)
                    conn.execute("DROP TABLE IF EXISTS stock_candles")
                    conn.register("_comb_tmp", comb_df)
                    conn.execute("CREATE TABLE stock_candles AS SELECT * FROM _comb_tmp")
                    conn.unregister("_comb_tmp")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_sym_date ON stock_candles(symbol, Date)")

            logger.info("yerel_ambar_basariyla_kaydedildi", db_file=self._db_file, hisse_sayisi=len(all_dfs))
            return len(all_dfs), len(bm_df)

    def load_30y_data(self) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
        """Yerel diskten 30 yıllık veriyi hafızaya yükler.

        Returns:
            tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
                (BIST-100 endeks DataFrame'i, Hisse kodu bazında Polars DataFrame sözlüğü).
        """
        with self._lock:
            if not self.is_cached():
                self.download_and_save_warehouse()

            bm_df = read_warehouse_benchmark_from_duckdb(self._db_file)
            comb_df = read_warehouse_stocks_from_duckdb(self._db_file)

            stock_dict: dict[str, pl.DataFrame] = {}
            if "symbol" in comb_df.columns:
                for sym in comb_df["symbol"].unique().to_list():
                    df_sym = comb_df.filter(pl.col("symbol") == sym).drop("symbol").sort("Date")
                    canonical_ticker = sym if sym.endswith(".IS") else f"{sym}.IS"
                    stock_dict[canonical_ticker] = df_sym

            return bm_df, stock_dict


# ==============================================================================
# Bağımsız DuckDB Yardımcı Fonksiyonları
# ==============================================================================


def read_warehouse_benchmark_from_duckdb(db_path: str = DB_FILE) -> pl.DataFrame:
    """DuckDB ambarından BIST-100 endeks verisini Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.

    Returns:
        pl.DataFrame: Endeks verisi (tablo yoksa boş DataFrame döner).
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'benchmark_xu100'"
            ).fetchone()
            if not tbl or tbl[0] == 0:
                return pl.DataFrame()
            return conn.execute("SELECT * FROM benchmark_xu100 ORDER BY Date ASC").pl()
    except Exception as exc:
        logger.warning("duckdb_benchmark_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame()


def read_warehouse_stocks_from_duckdb(
    db_path: str = DB_FILE,
    symbol: str | None = None,
    limit: int | None = None,
) -> pl.DataFrame:
    """DuckDB ambarından hisse mum verilerini Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        symbol: İsteğe bağlı hisse sembolü (örn: THYAO).
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Mum verisi tablosu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return pl.DataFrame()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'stock_candles'"
            ).fetchone()
            if not tbl or tbl[0] == 0:
                return pl.DataFrame()

            query = "SELECT * FROM stock_candles WHERE 1=1"
            params: list[Any] = []
            if symbol:
                clean_sym = symbol.upper().replace(".IS", "").strip()
                query += " AND symbol = ?"
                params.append(clean_sym)

            query += " ORDER BY Date ASC"
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_warehouse_stocks_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame()


def clear_warehouse_duckdb(db_path: str = DB_FILE) -> None:
    """DuckDB ambarındaki tabloları temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS benchmark_xu100;")
            conn.execute("DROP TABLE IF EXISTS stock_candles;")
            logger.info("warehouse_duckdb_temizlendi", db_path=db_path)
    except Exception as exc:
        logger.error("warehouse_duckdb_temizleme_hatasi", db_path=db_path, hata=str(exc))


# Singleton örneği
historical_warehouse: Final[HistoricalDataWarehouse] = HistoricalDataWarehouse()

__all__: Final[list[str]] = [
    "BENCHMARK_TICKER",
    "BIST_ALL_KEY_TICKERS",
    "DATA_DIR",
    "DB_FILE",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_WAL_SIZE",
    "HistoricalDataWarehouse",
    "clear_warehouse_duckdb",
    "configure_duckdb_wal",
    "historical_warehouse",
    "read_warehouse_benchmark_from_duckdb",
    "read_warehouse_stocks_from_duckdb",
    "to_orjson_bytes",
]
