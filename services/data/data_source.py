"""
ALPHA BIST — Data Source Integration v3.0

ROADMAP v3.0:
- Yahoo Finance entegrasyonu
- BIST veri kaynağı
- Parquet cache (hızlı okuma)
- Multi-source fallback
- Real-time vs batch mode
- Data quality checks

KURAL: Veri = petrol. Kirli veri = kirli petrol.
"""

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import orjson
import polars as pl
import structlog

logger = structlog.get_logger()


class DataSourceManager:
    """Veri kaynağı yöneticisi — multi-source + cache."""

    def __init__(
        self,
        cache_dir: str = "data/cache",
        use_cache: bool = True,
        cache_ttl_hours: int = 24,
    ):
        """Otomatik eklendi."""
        self.cache_dir = Path(cache_dir)
        self.use_cache = use_cache
        self.cache_ttl_hours = cache_ttl_hours

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Veri kaynakları
        self._sources = {
            "warehouse": WarehouseSource(),
            "local": LocalParquetSource(cache_dir),
            "tradingview": TradingViewSource(),
            "yahoo": YahooFinanceSource(),
            "bist": BISTSource(),
        }

        logger.info("DataSourceManager initialized", cache_dir=cache_dir, use_cache=use_cache)

    def get_stock_data(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
        source_priority: list[str] = None,
    ) -> pl.DataFrame:
        """Hisse verisini getir (cache-aware, multi-source).

        Args:
            ticker: Hisse kodu (örn: "THYAO.IS", "GARAN.IS")
            start_date: Başlangıç tarihi (YYYY-MM-DD)
            end_date: Bitiş tarihi (YYYY-MM-DD)
            period: Periyot (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Aralık (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
            source_priority: Kaynak önceliği

        Returns:
            OHLCV DataFrame
        """
        # Önce cache kontrol et
        if source_priority is None:
            source_priority = ["warehouse", "local", "tradingview", "yahoo", "bist"]
        if self.use_cache:
            cached = self._load_from_cache(ticker, interval)
            if cached is not None and not cached.is_empty():
                cache_min_date = cached["Date"].min()
                cache_max_date = cached["Date"].max()
                if isinstance(cache_min_date, str):
                    cache_min_date = cache_min_date[:10]
                    cache_max_date = cache_max_date[:10]
                else:
                    cache_min_date = str(cache_min_date)[:10]
                    cache_max_date = str(cache_max_date)[:10]

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
                        logger.info("Data loaded from cache", ticker=ticker, rows=len(cached))
                        return cached

        # Cache yoksa kaynaklardan dene
        for source_name in source_priority:
            source = self._sources.get(source_name)
            if not source:
                continue

            try:
                df = source.fetch(ticker, start_date, end_date, period, interval)
                if df is not None and not df.is_empty():
                    # NaN ve 0 fiyatlı geçersiz satırları temizle
                    if "Close" in df.columns:
                        df = df.drop_nulls(subset=["Close"])
                        df = df.filter(pl.col("Close") > 0)
                    if df.is_empty():
                        continue

                    # Cache'e kaydet
                    if self.use_cache:
                        self._save_to_cache(ticker, df, interval)

                    logger.info("Data loaded from source", ticker=ticker, source=source_name, rows=len(df))
                    return df

            except Exception as e:
                logger.warning("Source failed", ticker=ticker, source=source_name, error=str(e))
                continue

        logger.error("All sources failed", ticker=ticker)
        return pl.DataFrame()

    def get_multiple_stocks(
        self,
        tickers: list[str],
        max_workers: int = 8,
        **kwargs,
    ) -> dict[str, pl.DataFrame]:
        """Çoklu hisse verisi getir (paralel).

        Args:
            tickers: Hisse kodları listesi
            max_workers: Paralel thread sayısı
            **kwargs: get_stock_data argümanları
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_ticker = {pool.submit(self.get_stock_data, ticker, **kwargs): ticker for ticker in tickers}
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    df = future.result()
                    if df is not None and not df.is_empty():
                        results[ticker] = df
                except Exception as e:
                    logger.warning("Stock fetch failed", ticker=ticker, error=str(e))
        return results

    def get_bist100_universe(self) -> list[str]:
        """BIST 100 hisse listesini getir."""
        cache_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data",
            "bist_universe_cache.json",
        )
        try:
            with open(cache_path) as f:
                cache = orjson.loads(f.read())
            tickers = cache.get("tickers", [])
            if tickers:
                return [f"{t}.IS" for t in tickers]
        except Exception:
            logger.warning("Caught Exception in get_bist100_universe", exc_info=True)
        # Fallback — cache yoksa BIST-30 alt kümesi (geçici, cache yüklenene kadar)
        # Gerçek liste UniverseAutoUpdater tarafından güncellenir
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
        **kwargs,
    ) -> pl.DataFrame:
        """Benchmark verisini getir."""
        return self.get_stock_data(benchmark, **kwargs)

    def _load_from_cache(self, ticker: str, interval: str) -> pl.DataFrame | None:
        """Cache'den veri yukle (Parquet > CSV)."""
        # Parquet cache (tercih)
        parquet_file = self.cache_dir / f"{ticker}_{interval}.parquet"
        csv_file = self.cache_dir / f"{ticker}_{interval}.csv"

        cache_file = parquet_file if parquet_file.exists() else csv_file
        if not cache_file.exists():
            return None

        # TTL kontrolu
        file_age = datetime.now(UTC) - datetime.fromtimestamp(cache_file.stat().st_mtime, tz=UTC)
        if file_age > timedelta(hours=self.cache_ttl_hours):
            logger.info("Cache expired", ticker=ticker)
            return None

        try:
            if cache_file.suffix == ".parquet":
                df = pl.read_parquet(cache_file)
            else:
                df = pl.read_csv(cache_file, try_parse_dates=True)
            if df is not None and not df.is_empty() and "Close" in df.columns:
                df = df.drop_nulls(subset=["Close"])
                df = df.filter(pl.col("Close") > 0)
            logger.info("Cache hit", ticker=ticker, rows=len(df))
            return df
        except Exception as e:
            logger.warning("Cache read failed", ticker=ticker, error=str(e))
            return None

    def _save_to_cache(self, ticker: str, df: pl.DataFrame, interval: str) -> Any:
        """Veriyi cache'e kaydet (Parquet — CSV'den ~10x hızlı)."""
        parquet_file = self.cache_dir / f"{ticker}_{interval}.parquet"

        try:
            df.write_parquet(parquet_file)
            logger.info("Cache saved", ticker=ticker, rows=len(df))
        except Exception as e:
            logger.warning("Cache save failed", ticker=ticker, error=str(e))

    def clear_cache(self) -> Any:
        """Tum cache'i temizle."""
        for f in self.cache_dir.glob("*.parquet"):
            f.unlink()
        for f in self.cache_dir.glob("*.csv"):
            f.unlink()
        logger.info("Cache cleared")

    def get_cache_stats(self) -> dict[str, Any]:
        """Cache istatistikleri."""
        files = list(self.cache_dir.glob("*.parquet")) + list(self.cache_dir.glob("*.csv"))
        total_size = sum(f.stat().st_size for f in files)

        return {
            "files": len(files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "tickers": [f.stem for f in files],
        }


class YahooFinanceSource:
    """Yahoo Finance veri kaynağı."""

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """Yahoo Finance'ten veri çek."""
        try:
            import yfinance as yf

            # Ticker formatını düzelt
            if not ticker.endswith(".IS") and "." not in ticker.split(".")[-1]:
                ticker = f"{ticker}.IS"

            stock = yf.Ticker(ticker)

            logger.debug(f"YFinance fetch: {ticker} start={start_date} end={end_date}")
            if start_date and end_date:
                df = stock.history(start=start_date, end=end_date, interval=interval)
            else:
                df = stock.history(period=period, interval=interval)
            logger.debug(f"YFinance returned: {len(df)} rows")

            if df.empty:
                return None

            # Pandas DataFrame'i Polars'a çevir
            df = pl.from_pandas(df.reset_index())

            # Kolon isimlerini düzelt
            rename_map = {}
            for c in df.columns:
                new_c = c.replace("Stock Splits", "StockSplits").replace("Capital Gains", "CapitalGains")
                if new_c and new_c[0].islower():
                    new_c = new_c[0].upper() + new_c[1:]
                if new_c != c:
                    rename_map[c] = new_c
            if rename_map:
                df = df.rename(rename_map)

            # Date kolonunu datetime'a çevir
            if "Date" in df.columns:
                df = df.with_columns(pl.col("Date").cast(pl.Datetime).alias("Date"))

            return df

        except ImportError:
            logger.warning("yfinance not installed")
            return None
        except Exception as e:
            logger.warning("Yahoo Finance fetch failed", error=str(e))
            return None


class BISTSource:
    """Borsa Istanbul resmi veri kaynagi — web scraping + API."""

    BASE_URL = "https://www.borsaistanbul.com"
    API_URL = "https://www.borsaistanbul.com/api"

    def __init__(self):
        """Otomatik eklendi."""
        self.session = httpx.Client(follow_redirects=True)
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "tr-TR,tr;q=0.9",
            }
        )
        self.timeout = 15

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """Borsa Istanbul'dan veri cek.

        Strateji:
        1. BIST API'den dene
        2. BIST web sitesinden scrape et
        3. Basarisiz olursa None don (fallback: YahooFinance)
        """
        # Ticker formatini duzelt
        ticker_clean = ticker.replace(".IS", "").upper()

        # Yontem 1: BIST API
        try:
            df = self._fetch_from_api(ticker_clean, start_date, end_date)
            if df is not None and not df.is_empty():
                logger.info("BIST API data fetched", ticker=ticker_clean, rows=len(df))
                return df
        except Exception as e:
            logger.debug("BIST API failed", ticker=ticker_clean, error=str(e))

        # Yontem 2: Web scrape (son fiyat)
        try:
            df = self._fetch_from_web(ticker_clean)
            if df is not None and not df.is_empty():
                logger.info("BIST web data fetched", ticker=ticker_clean)
                return df
        except Exception as e:
            logger.debug("BIST web scrape failed", ticker=ticker_clean, error=str(e))

        logger.warning("BIST source failed for ticker", ticker=ticker_clean)
        return None

    def _fetch_from_api(self, ticker: str, start_date: str | None, end_date: str | None) -> pl.DataFrame | None:
        """BIST API'den tarihsel veri cek."""
        # Borsa Istanbul'un hisse detay API'si
        url = f"{self.API_URL}/stock/{ticker}/history"

        params: dict[str, str] = {}
        if start_date:
            params["from"] = start_date
        if end_date:
            params["to"] = end_date

        resp = self.session.get(url, params=params, timeout=self.timeout)
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
                    "Open": float(item.get("open", 0)),
                    "High": float(item.get("high", 0)),
                    "Low": float(item.get("low", 0)),
                    "Close": float(item.get("close", 0)),
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
        """BIST web sitesinden son fiyat bilgisi cek."""
        url = f"{self.BASE_URL}/tr/hisse/{ticker}"
        resp = self.session.get(url, timeout=self.timeout)

        if resp.status_code != 200:
            # Alternatif URL dene
            url = f"{self.BASE_URL}/tr/sirketler/{ticker}"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                return None

        html = resp.text

        # Fiyat bilgilerini regex ile parse et

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

        if close is None:
            return None

        # Hacim
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

        # Degisim
        change = 0
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

        # Onceki kapanis tahmini
        prev_close = close / (1 + change / 100) if change != 0 else close

        # Tek gunluk DataFrame olustur
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        df = pl.DataFrame(
            {
                "Date": [today],
                "Open": [prev_close],
                "High": [max(close, prev_close)],
                "Low": [min(close, prev_close)],
                "Close": [close],
                "Volume": [volume],
            }
        )

        return df

    def fetch_index_data(self, index_code: str = "XU100") -> pl.DataFrame | None:
        """Endeks verisi cek."""
        try:
            url = f"{self.API_URL}/index/{index_code}"
            resp = self.session.get(url, timeout=self.timeout)

            if resp.status_code == 200:
                data = resp.json()
                if data:
                    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                    df = pl.DataFrame(
                        {
                            "Date": [today],
                            "Open": [float(data.get("open", 0))],
                            "High": [float(data.get("high", 0))],
                            "Low": [float(data.get("low", 0))],
                            "Close": [float(data.get("lastPrice", 0))],
                            "Volume": [int(data.get("volume", 0))],
                        }
                    )
                    return df
        except Exception as e:
            logger.debug("BIST index fetch failed", error=str(e))

        return None


class LocalParquetSource:
    """Yerel parquet dosyalarından veri kaynağı."""

    def __init__(self, cache_dir: str):
        """Otomatik eklendi."""
        self.cache_dir = Path(cache_dir)

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """Yerel parquet'ten veri çek."""
        cache_file = self.cache_dir / f"{ticker}_{interval}.parquet"

        if not cache_file.exists():
            return None

        try:
            df = pl.read_parquet(cache_file)

            # Tarih filtresi
            if start_date:
                df = df.filter(pl.col("Date") >= start_date)
            if end_date:
                df = df.filter(pl.col("Date") <= end_date)

            return df
        except Exception as e:
            logger.warning("Local parquet read failed", error=str(e))
            return None


class TradingViewSource:
    """TradingView Scanner API üzerinden canlı ve son seans OHLCV verisi çeker."""

    def __init__(self, timeout: float = 10.0):
        """TradingView kaynak istemcisini başlatır."""
        self.timeout = timeout
        self.url = "https://scanner.tradingview.com/turkey/scan"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def __repr__(self) -> str:
        return f"<TradingViewSource(url='{self.url}', timeout={self.timeout}s)>"

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """TradingView'den hissenin anlık veya son gün OHLCV mumunu çeker.

        Args:
            ticker: Hisse sembolü (örn. THYAO veya THYAO.IS).
            start_date: Başlangıç tarihi filtresi (opsiyonel).
            end_date: Bitiş tarihi filtresi (opsiyonel).
            period: Veri periyodu.
            interval: Bar aralığı.

        Returns:
            pl.DataFrame | None: Tek satırlık canlı bar veya hata durumunda None.
        """
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
            logger.debug("TradingViewSource fetch failed", ticker=sym, error=str(e))
        return None


class WarehouseSource:
    """Tarihsel DuckDB Veri Deposundan (bist_30y_warehouse.duckdb / .db) anlık OHLCV çeker."""

    def __init__(self, db_path: str = "data/bist_30y_warehouse.duckdb") -> None:
        """DuckDB veri deposu yolunu tanımlar."""
        self.db_path = Path(db_path)
        # Geriye dönük uyumluluk: .duckdb yoksa .db yolunu kontrol et
        if not self.db_path.exists():
            legacy_path = Path("data/bist_30y_warehouse.db")
            if legacy_path.exists():
                self.db_path = legacy_path

    def fetch(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """Tarihsel veri deposundan hisse veya endeks OHLCV barlarını Polars DataFrame olarak getirir.

        Args:
            ticker: Hisse veya endeks sembolü (örn. THYAO, XU100).
            start_date: Başlangıç tarihi filtresi (opsiyonel).
            end_date: Bitiş tarihi filtresi (opsiyonel).
            period: Veri periyodu (varsayılan: 2y).
            interval: Bar aralığı (varsayılan: 1d).

        Returns:
            Sıralanmış OHLCV Polars DataFrame veya bulunamazsa None.
        """
        if not self.db_path.exists():
            return None

        import duckdb

        sym = ticker.upper().replace(".IS", "").strip()
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)
            tbl = "benchmark_xu100" if sym in ["XU100", "^XU100", "BIST100"] else "stock_candles"

            if tbl == "benchmark_xu100":
                query = "SELECT Date, Open, High, Low, Close, Volume FROM benchmark_xu100"
                df = conn.execute(query).pl()
            else:
                query = "SELECT Date, Open, High, Low, Close, Volume FROM stock_candles WHERE symbol = ? OR symbol = ?"
                df = conn.execute(query, [sym, f"{sym}.IS"]).pl()
            conn.close()

            if df.is_empty():
                return None

            df = df.sort("Date")

            if start_date:
                df = df.filter(pl.col("Date") >= start_date)
            if end_date:
                df = df.filter(pl.col("Date") <= end_date)
            return df
        except Exception as e:
            logger.warning("WarehouseSource fetch failed", ticker=ticker, error=str(e))
            return None

    def __repr__(self) -> str:
        return f"<WarehouseSource db_path={self.db_path} engine=DuckDB>"


# Singleton
data_source = DataSourceManager()
