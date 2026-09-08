"""ALPHA BIST — Veri Kaynağı Entegrasyonu ve Yönetim Motoru (Data Source Integration).

Bu modül, Borsa İstanbul (BIST) pay piyasası ve endeks verileri için çok kaynaklı
(Yahoo Finance, BIST Web/API, TradingView Scanner, Yerel Parquet ve Tarihsel DuckDB Warehouse)
veri toplama, tamponlama (cache-aware) ve arıza durumunda otomatik kaynak değiştirme
(multi-source fallback) mimarisi sunar.

Temel Yetenekler:
1. Çok Kaynaklı Veri Çekme (Warehouse -> Local Parquet -> TradingView -> Yahoo -> BIST).
2. Yüksek Performanslı Parquet ve DuckDB Önbellekleme.
3. Otomatik Veri Temizliği (Hacim ve sıfır fiyat ayıklama, null filtreleme).
4. Eşzamanlı Çoklu Hisse İndirme (ThreadPoolExecutor).
5. DuckDB WAL ve Checkpoint optimizasyonları ile Point-In-Time uyumluluğu.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import duckdb
import httpx
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# ==============================================================================
# Yapılandırma ve WAL Sabitleri
# ==============================================================================

DEFAULT_CACHE_DIR: Final[str] = "data/cache"
DEFAULT_WAREHOUSE_DB_PATH: Final[str] = "data/bist_30y_warehouse.duckdb"
DEFAULT_CACHE_TTL_HOURS: Final[int] = 24
DEFAULT_MAX_WORKERS: Final[int] = 8
DEFAULT_HTTP_TIMEOUT_SEC: Final[float] = 15.0
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

DEFAULT_SOURCE_PRIORITY: Final[list[str]] = [
    "warehouse",
    "local",
    "tradingview",
    "yahoo",
    "bist",
]


# ==============================================================================
# Yardımcı Fonksiyonlar
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


# ==============================================================================
# Veri Kaynağı Alt Sınıfları
# ==============================================================================


class YahooFinanceSource:
    """Yahoo Finance API üzerinden tarihsel ve anlık veri çeken adaptör."""

    def __init__(self) -> None:
        """YahooFinanceSource başlatıcı."""
        self._name = "yahoo"

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return "YahooFinanceSource(kaynak='yahoo')"

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """Yahoo Finance üzerinden hisse verisi çeker."""
        try:
            import yfinance as yf

            # Ticker formatını BIST için standartlaştır (.IS eki)
            clean_ticker = ticker.strip().upper()
            if not clean_ticker.endswith(".IS") and "." not in clean_ticker.split(".")[-1]:
                clean_ticker = f"{clean_ticker}.IS"

            stock = yf.Ticker(clean_ticker)
            if start_date and end_date:
                pdf = stock.history(start=start_date, end=end_date, interval=interval)
            else:
                pdf = stock.history(period=period, interval=interval)

            if pdf is None or pdf.empty:
                return None

            df = pl.from_pandas(pdf.reset_index())

            rename_map = {}
            for c in df.columns:
                new_c = c.replace("Stock Splits", "StockSplits").replace("Capital Gains", "CapitalGains")
                if new_c and new_c[0].islower():
                    new_c = new_c[0].upper() + new_c[1:]
                if new_c != c:
                    rename_map[c] = new_c
            if rename_map:
                df = df.rename(rename_map)

            if "Date" in df.columns:
                df = df.with_columns(pl.col("Date").cast(pl.Datetime).alias("Date"))

            return df

        except ImportError:
            logger.warning("yfinance_paketi_yuklu_degil")
            return None
        except Exception as e:
            logger.warning("yahoo_finance_veri_cekme_hatasi", hisse=ticker, hata=str(e))
            return None


class BISTSource:
    """Borsa İstanbul resmi web sitesi ve veri uç noktaları adaptörü."""

    BASE_URL: Final[str] = "https://www.borsaistanbul.com"
    API_URL: Final[str] = "https://www.borsaistanbul.com/api"

    def __init__(self, timeout: float = DEFAULT_HTTP_TIMEOUT_SEC) -> None:
        """BISTSource başlatıcı.

        Args:
            timeout: HTTP istek zaman aşımı süresi (saniye).
        """
        self.timeout = timeout
        self.session = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "tr-TR,tr;q=0.9",
            },
        )

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return f"BISTSource(api_url='{self.API_URL}', timeout={self.timeout}s)"

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """BIST kaynaklarından hisse OHLCV verisi çeker."""
        ticker_clean = ticker.replace(".IS", "").upper().strip()

        # 1. Aşama: API uç noktası denemesi
        try:
            df = self._fetch_from_api(ticker_clean, start_date, end_date)
            if df is not None and not df.is_empty():
                return df
        except Exception as e:
            logger.debug("bist_api_basarisiz", hisse=ticker_clean, hata=str(e))

        # 2. Aşama: Web kazıma (scraping) denemesi
        try:
            df = self._fetch_from_web(ticker_clean)
            if df is not None and not df.is_empty():
                return df
        except Exception as e:
            logger.debug("bist_web_scrape_basarisiz", hisse=ticker_clean, hata=str(e))

        return None

    def _fetch_from_api(self, ticker: str, start_date: str | None, end_date: str | None) -> pl.DataFrame | None:
        """BIST API'den tarihsel veri çeker."""
        url = f"{self.API_URL}/stock/{ticker}/history"
        params: dict[str, str] = {}
        if start_date:
            params["from"] = start_date
        if end_date:
            params["to"] = end_date

        resp = self.session.get(url, params=params)
        if resp.status_code != 200:
            return None

        data = resp.json()
        if not data or "data" not in data:
            return None

        rows = []
        for item in data.get("data", []):
            rows.append(
                {
                    "Date": item.get("date", ""),
                    "Open": float(item.get("open", 0.0)),
                    "High": float(item.get("high", 0.0)),
                    "Low": float(item.get("low", 0.0)),
                    "Close": float(item.get("close", 0.0)),
                    "Volume": int(item.get("volume", 0)),
                }
            )

        if not rows:
            return None

        df = pl.DataFrame(rows)
        if "Date" in df.columns:
            df = df.sort("Date")
        return df

    def _fetch_from_web(self, ticker: str) -> pl.DataFrame | None:
        """BIST web sayfasından son güncel seans verisini kazır."""
        url = f"{self.BASE_URL}/tr/hisse/{ticker}"
        resp = self.session.get(url)

        if resp.status_code != 200:
            url = f"{self.BASE_URL}/tr/sirketler/{ticker}"
            resp = self.session.get(url)
            if resp.status_code != 200:
                return None

        html = resp.text

        price_patterns = [
            r'class="[^"]*last-price[^"]*"[^>]*>([0-9.,]+)<',
            r'class="[^"]*price[^"]*"[^>]*>([0-9.,]+)<',
            r'data-last-price="([0-9.,]+)"',
            r'<span[^>]*class="[^"]*value[^"]*"[^>]*>([0-9.,]+)</span>',
        ]

        close = None
        for pattern in price_patterns:
            match = re.search(pattern, html)
            if match:
                close_str = match.group(1).replace(".", "").replace(",", ".")
                try:
                    close = float(close_str)
                    break
                except ValueError:
                    continue

        if close is None or close <= 0:
            return None

        volume = 0
        vol_patterns = [
            r'class="[^"]*volume[^"]*"[^>]*>([0-9.,]+)<',
            r"Hacim[\s:]*</[^>]*>\s*<[^>]*>([0-9.,]+)<",
        ]
        for pattern in vol_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                vol_str = match.group(1).replace(".", "").replace(",", "")
                try:
                    volume = int(vol_str)
                    break
                except ValueError:
                    continue

        change = 0.0
        change_patterns = [
            r'class="[^"]*change[^"]*"[^>]*>([+-]?[0-9.,]+)<',
            r"Degisim[\s:]*</[^>]*>\s*<[^>]*>([+-]?[0-9.,]+)<",
        ]
        for pattern in change_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                change_str = match.group(1).replace(",", ".")
                try:
                    change = float(change_str)
                    break
                except ValueError:
                    continue

        prev_close = close / (1 + change / 100) if change != 0 else close
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        return pl.DataFrame(
            {
                "Date": [today],
                "Open": [prev_close],
                "High": [max(close, prev_close)],
                "Low": [min(close, prev_close)],
                "Close": [close],
                "Volume": [volume],
            }
        )

    def fetch_index_data(self, index_code: str = "XU100") -> pl.DataFrame | None:
        """BIST endeks verisini çeker."""
        try:
            url = f"{self.API_URL}/index/{index_code}"
            resp = self.session.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                    return pl.DataFrame(
                        {
                            "Date": [today],
                            "Open": [float(data.get("open", 0.0))],
                            "High": [float(data.get("high", 0.0))],
                            "Low": [float(data.get("low", 0.0))],
                            "Close": [float(data.get("lastPrice", 0.0))],
                            "Volume": [int(data.get("volume", 0))],
                        }
                    )
        except Exception as e:
            logger.debug("bist_endeks_cekme_hatasi", endeks=index_code, hata=str(e))
        return None


class LocalParquetSource:
    """Yerel Parquet önbellek dosyalarından veri okuyan adaptör."""

    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> None:
        """LocalParquetSource başlatıcı.

        Args:
            cache_dir: Parquet dosyalarının bulunduğu dizin.
        """
        self.cache_dir = Path(cache_dir)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return f"LocalParquetSource(cache_dir='{self.cache_dir}')"

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """Yerel Parquet dosyasından hisse verisini okur."""
        clean_sym = ticker.replace(".IS", "").upper().strip()
        cache_file = self.cache_dir / f"{clean_sym}_{interval}.parquet"
        if not cache_file.exists():
            cache_file = self.cache_dir / f"{ticker}_{interval}.parquet"
            if not cache_file.exists():
                return None

        try:
            df = pl.read_parquet(cache_file)
            if df.is_empty():
                return None
            if start_date and "Date" in df.columns:
                df = df.filter(pl.col("Date") >= start_date)
            if end_date and "Date" in df.columns:
                df = df.filter(pl.col("Date") <= end_date)
            return df
        except Exception as e:
            logger.warning("yerel_parquet_okuma_hatasi", hisse=ticker, dosya=str(cache_file), hata=str(e))
            return None


class TradingViewSource:
    """TradingView Scanner API üzerinden anlık ve son seans barlarını çeken adaptör."""

    def __init__(self, timeout: float = 10.0) -> None:
        """TradingView kaynak istemcisini başlatır.

        Args:
            timeout: HTTP istek zaman aşımı.
        """
        self.timeout = timeout
        self.url = "https://scanner.tradingview.com/turkey/scan"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return f"TradingViewSource(url='{self.url}', timeout={self.timeout}s)"

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """TradingView üzerinden son gün mum verisini çeker."""
        sym = ticker.upper().replace(".IS", "").strip()
        payload = {
            "filter": [{"left": "name", "operation": "match", "right": sym}],
            "options": {"lang": "tr"},
            "symbols": {"query": {"types": []}},
            "columns": ["name", "open", "high", "low", "close", "volume"],
            "range": [0, 1],
        }
        try:
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                resp = client.post(self.url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    rows = data.get("data", [])
                    if not rows:
                        return None
                    d = rows[0].get("d", [])
                    if len(d) >= 6 and d[4] is not None and float(d[4]) > 0:
                        today = datetime.now(UTC).strftime("%Y-%m-%d")
                        close = float(d[4])
                        open_p = float(d[1]) if d[1] is not None else close
                        high = float(d[2]) if d[2] is not None else close
                        low = float(d[3]) if d[3] is not None else close
                        vol = int(d[5]) if d[5] is not None else 0

                        return pl.DataFrame(
                            {
                                "Date": [today],
                                "Open": [open_p],
                                "High": [high],
                                "Low": [low],
                                "Close": [close],
                                "Volume": [vol],
                            }
                        )
        except Exception as e:
            logger.debug("tradingview_veri_cekme_hatasi", hisse=sym, hata=str(e))
        return None


class WarehouseSource:
    """Tarihsel DuckDB Veri Deposundan (bist_30y_warehouse.duckdb) anlık OHLCV çeker."""

    def __init__(self, db_path: str = DEFAULT_WAREHOUSE_DB_PATH) -> None:
        """WarehouseSource başlatıcı.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            legacy_path = Path("data/bist_30y_warehouse.db")
            if legacy_path.exists():
                self.db_path = legacy_path

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return f"WarehouseSource(db_path='{self.db_path}')"

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """Tarihsel depodan hisse veya endeks OHLCV barlarını Polars DataFrame olarak getirir."""
        if not self.db_path.exists():
            return None

        sym = ticker.upper().replace(".IS", "").strip()
        try:
            with duckdb.connect(str(self.db_path)) as conn:
                configure_duckdb_wal(conn)
                tbl = "benchmark_xu100" if sym in ["XU100", "^XU100", "BIST100"] else "stock_candles"

                # Tablo mevcudiyet kontrolü
                tbl_check = conn.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [tbl]
                ).fetchone()
                if not tbl_check or tbl_check[0] == 0:
                    return None

                if tbl == "benchmark_xu100":
                    query = "SELECT Date, Open, High, Low, Close, Volume FROM benchmark_xu100"
                    df = conn.execute(query).pl()
                else:
                    query = (
                        "SELECT Date, Open, High, Low, Close, Volume "
                        "FROM stock_candles WHERE symbol = ? OR symbol = ?"
                    )
                    df = conn.execute(query, [sym, f"{sym}.IS"]).pl()

            if df is None or df.is_empty():
                return None

            df = df.sort("Date")
            if start_date and "Date" in df.columns:
                df = df.filter(pl.col("Date") >= start_date)
            if end_date and "Date" in df.columns:
                df = df.filter(pl.col("Date") <= end_date)
            return df

        except Exception as e:
            logger.warning("warehouse_veri_cekme_hatasi", hisse=ticker, hata=str(e))
            return None


# ==============================================================================
# Veri Kaynağı Yöneticisi (DataSourceManager / DataSource)
# ==============================================================================


class DataSourceManager:
    """Veri kaynağı yöneticisi — çoklu kaynak fallback ve önbellek mimarisi."""

    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        use_cache: bool = True,
        cache_ttl_hours: int = DEFAULT_CACHE_TTL_HOURS,
    ) -> None:
        """DataSourceManager başlatıcı.

        Args:
            cache_dir: Önbellek dizini.
            use_cache: Önbelleğin aktif olup olmadığı.
            cache_ttl_hours: Önbellek geçerlilik süresi (saat).
        """
        self.cache_dir = Path(cache_dir)
        self.use_cache = use_cache
        self.cache_ttl_hours = cache_ttl_hours
        self._lock = threading.RLock()

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._sources: dict[str, Any] = {
            "warehouse": WarehouseSource(),
            "local": LocalParquetSource(self.cache_dir),
            "tradingview": TradingViewSource(),
            "yahoo": YahooFinanceSource(),
            "bist": BISTSource(),
        }

        logger.info("veri_kaynagi_yoneticisi_baslatildi", cache_dir=str(self.cache_dir), use_cache=use_cache)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"DataSourceManager(cache_dir='{self.cache_dir}', "
                f"use_cache={self.use_cache}, ttl={self.cache_ttl_hours}h)"
            )

    def to_dict(self) -> dict[str, Any]:
        """Yönetici yapılandırmasını sözlük formatında döner."""
        with self._lock:
            return {
                "cache_dir": str(self.cache_dir),
                "use_cache": self.use_cache,
                "cache_ttl_hours": self.cache_ttl_hours,
                "sources": list(self._sources.keys()),
            }

    def to_orjson_bytes(self) -> bytes:
        """Yönetici yapılandırmasını ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def get_stock_data(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
        source_priority: list[str] | None = None,
    ) -> pl.DataFrame:
        """Hisse verisini getirir (önbellek kontrollü, çok kaynaklı fallback).

        Args:
            ticker: Hisse kodu (örn: "THYAO.IS", "GARAN.IS").
            start_date: Başlangıç tarihi (YYYY-MM-DD).
            end_date: Bitiş tarihi (YYYY-MM-DD).
            period: Periyot (1d, 5d, 1mo, 1y, 2y, 5y, max).
            interval: Bar aralığı (1m, 5m, 1h, 1d vb.).
            source_priority: Kaynak deneme öncelik sıralaması.

        Returns:
            pl.DataFrame: OHLCV Polars DataFrame.
        """
        priority = source_priority or DEFAULT_SOURCE_PRIORITY

        if self.use_cache:
            with self._lock:
                cached = self._load_from_cache(ticker, interval)
            if cached is not None and not cached.is_empty():
                cache_min_date = str(cached["Date"].min())[:10]
                cache_max_date = str(cached["Date"].max())[:10]

                cache_is_valid = True
                if start_date and start_date < cache_min_date:
                    cache_is_valid = False
                if end_date and end_date > cache_max_date:
                    cache_is_valid = False

                if cache_is_valid:
                    if start_date:
                        cached = cached.filter(pl.col("Date") >= start_date)
                    if end_date:
                        cached = cached.filter(pl.col("Date") <= end_date)
                    if not cached.is_empty():
                        logger.info("veri_onbellekten_yuklendi", hisse=ticker, satir=len(cached))
                        return cached

        for source_name in priority:
            source = self._sources.get(source_name)
            if not source:
                continue

            try:
                df = source.fetch(ticker, start_date, end_date, period, interval)
                if df is not None and not df.is_empty():
                    if "Close" in df.columns:
                        df = df.drop_nulls(subset=["Close"]).filter(pl.col("Close") > 0)
                    if df.is_empty():
                        continue

                    if self.use_cache:
                        with self._lock:
                            self._save_to_cache(ticker, df, interval)

                    logger.info("veri_kaynaktan_alindi", hisse=ticker, kaynak=source_name, satir=len(df))
                    return df

            except Exception as e:
                logger.warning("veri_kaynagi_hata_verdi", hisse=ticker, kaynak=source_name, hata=str(e))
                continue

        logger.error("tum_veri_kaynaklari_basarisiz", hisse=ticker)
        return pl.DataFrame()

    def get_multiple_stocks(
        self,
        tickers: list[str],
        max_workers: int = DEFAULT_MAX_WORKERS,
        **kwargs: Any,
    ) -> dict[str, pl.DataFrame]:
        """Çoklu hisse verisini paralel olarak getirir.

        Args:
            tickers: Hisse kodları listesi.
            max_workers: Maksimum iş parçacığı sayısı.
            **kwargs: get_stock_data fonksiyonuna aktarılacak parametreler.

        Returns:
            dict[str, pl.DataFrame]: Hisse sembolü -> OHLCV DataFrame sözlüğü.
        """
        results: dict[str, pl.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            future_to_ticker = {pool.submit(self.get_stock_data, ticker, **kwargs): ticker for ticker in tickers}
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    df = future.result()
                    if df is not None and not df.is_empty():
                        results[ticker] = df
                except Exception as e:
                    logger.warning("paralel_hisse_yukleme_hatasi", hisse=ticker, hata=str(e))
        return results

    def get_bist100_universe(self) -> list[str]:
        """BIST 100 hisse evren listesini getirir."""
        cache_path = Path("data/bist_universe_cache.json")
        try:
            if cache_path.exists():
                with open(cache_path, "rb") as f:
                    cache = orjson.loads(f.read())
                tickers = cache.get("tickers", [])
                if tickers:
                    return [f"{t}.IS" if not t.endswith(".IS") else t for t in tickers]
        except Exception as exc:
            logger.warning("bist_evren_onbellek_okuma_hatasi", hata=str(exc))

        # Fallback: Güvenilir BIST-30 çekirdek hisse listesi
        return [
            "THYAO.IS",
            "GARAN.IS",
            "ISCTR.IS",
            "AKBNK.IS",
            "YKBNK.IS",
            "BIMAS.IS",
            "KCHOL.IS",
            "SAHOL.IS",
            "TUPRS.IS",
            "EREGL.IS",
            "ASELS.IS",
            "SISE.IS",
            "TOASO.IS",
            "ARCLK.IS",
            "KRDMD.IS",
            "PETKM.IS",
            "PGSUS.IS",
            "TAVHL.IS",
            "TKFEN.IS",
            "VAKBN.IS",
        ]

    def get_benchmark_data(
        self,
        benchmark: str = "XU100.IS",
        **kwargs: Any,
    ) -> pl.DataFrame:
        """Endeks benchmark verisini getirir."""
        return self.get_stock_data(benchmark, **kwargs)

    def _load_from_cache(self, ticker: str, interval: str) -> pl.DataFrame | None:
        """Önbellekten veriyi yükler (Parquet öncelikli)."""
        clean_sym = ticker.replace(".IS", "").upper().strip()
        parquet_file = self.cache_dir / f"{clean_sym}_{interval}.parquet"
        csv_file = self.cache_dir / f"{clean_sym}_{interval}.csv"

        cache_file = parquet_file if parquet_file.exists() else csv_file
        if not cache_file.exists():
            return None

        file_age = datetime.now(UTC) - datetime.fromtimestamp(cache_file.stat().st_mtime, tz=UTC)
        if file_age > timedelta(hours=self.cache_ttl_hours):
            logger.info("onbellek_suresi_doldu", hisse=ticker)
            return None

        try:
            if cache_file.suffix == ".parquet":
                df = pl.read_parquet(cache_file)
            else:
                df = pl.read_csv(cache_file, try_parse_dates=True)
            if df is not None and not df.is_empty() and "Close" in df.columns:
                df = df.drop_nulls(subset=["Close"]).filter(pl.col("Close") > 0)
            return df
        except Exception as e:
            logger.warning("onbellek_okuma_hatasi", hisse=ticker, hata=str(e))
            return None

    def _save_to_cache(self, ticker: str, df: pl.DataFrame, interval: str) -> None:
        """Veriyi Parquet önbelleğine kaydeder."""
        clean_sym = ticker.replace(".IS", "").upper().strip()
        parquet_file = self.cache_dir / f"{clean_sym}_{interval}.parquet"
        try:
            df.write_parquet(parquet_file)
            logger.info("onbellek_kaydedildi", hisse=ticker, satir=len(df))
        except Exception as e:
            logger.warning("onbellek_kaydetme_hatasi", hisse=ticker, hata=str(e))

    def clear_cache(self) -> None:
        """Önbellekteki tüm Parquet ve CSV dosyalarını temizler."""
        with self._lock:
            for f in self.cache_dir.glob("*.parquet"):
                f.unlink(missing_ok=True)
            for f in self.cache_dir.glob("*.csv"):
                f.unlink(missing_ok=True)
        logger.info("onbellek_temizlendi")

    def get_cache_stats(self) -> dict[str, Any]:
        """Önbellek istatistiklerini döner."""
        with self._lock:
            files = list(self.cache_dir.glob("*.parquet")) + list(self.cache_dir.glob("*.csv"))
            total_size = sum(f.stat().st_size for f in files)
            return {
                "files": len(files),
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "tickers": [f.stem for f in files],
            }


# Alias for backward and package compatibility
DataSource = DataSourceManager

# Global Singleton
data_source: DataSourceManager = DataSourceManager()


# ==============================================================================
# DuckDB Yardımcı Fonksiyonları
# ==============================================================================


def read_stock_candles_from_duckdb(
    db_path: str = DEFAULT_WAREHOUSE_DB_PATH,
    ticker: str | None = None,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB veri ambarından hisse barlarını doğrudan Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: İsteğe bağlı hisse filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Okunan hisse barları.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "Date": pl.Datetime,
        "Open": pl.Float64,
        "High": pl.Float64,
        "Low": pl.Float64,
        "Close": pl.Float64,
        "Volume": pl.Int64,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl = "stock_candles"
            tbl_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [tbl]
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = "SELECT Date, Open, High, Low, Close, Volume FROM stock_candles WHERE 1=1"
            params: list[Any] = []
            if ticker:
                sym = ticker.upper().replace(".IS", "").strip()
                query += " AND (symbol = ? OR symbol = ?)"
                params.extend([sym, f"{sym}.IS"])

            query += " ORDER BY Date DESC LIMIT ?"
            params.append(max(1, int(limit)))

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_stock_candles_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_stock_candles_duckdb(db_path: str = DEFAULT_WAREHOUSE_DB_PATH) -> None:
    """DuckDB veri ambarındaki hisse mum tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS stock_candles;")
    except Exception as exc:
        logger.error("duckdb_stock_candles_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: Final[list[str]] = [
    # Yapılandırma Sabitleri
    "DEFAULT_CACHE_DIR",
    "DEFAULT_CACHE_TTL_HOURS",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_HTTP_TIMEOUT_SEC",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_SOURCE_PRIORITY",
    "DEFAULT_WAL_SIZE",
    "DEFAULT_WAREHOUSE_DB_PATH",
    # Kaynak Adaptörleri ve Yönetici
    "BISTSource",
    "DataSource",
    "DataSourceManager",
    "LocalParquetSource",
    "TradingViewSource",
    "WarehouseSource",
    "YahooFinanceSource",
    # Singleton
    "data_source",
    # Yardımcı Fonksiyonlar
    "clear_stock_candles_duckdb",
    "configure_duckdb_wal",
    "read_stock_candles_from_duckdb",
    "to_orjson_bytes",
]
