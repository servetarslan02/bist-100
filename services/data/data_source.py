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
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
from pathlib import Path
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
        self.cache_dir = Path(cache_dir)
        self.use_cache = use_cache
        self.cache_ttl_hours = cache_ttl_hours

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Veri kaynakları
        self._sources = {
            "yahoo": YahooFinanceSource(),
            "bist": BISTSource(),
            "local": LocalParquetSource(cache_dir),
        }

        logger.info("DataSourceManager initialized",
                   cache_dir=cache_dir, use_cache=use_cache)

    def get_stock_data(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "2y",
        interval: str = "1d",
        source_priority: List[str] = ["local", "yahoo", "bist"],
    ) -> pd.DataFrame:
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
        if self.use_cache:
            cached = self._load_from_cache(ticker, interval)
            if cached is not None and not cached.empty:
                # Tarih filtresi uygula
                if start_date:
                    cached = cached[cached.index >= start_date]
                if end_date:
                    cached = cached[cached.index <= end_date]

                if not cached.empty:
                    logger.info("Data loaded from cache", ticker=ticker, rows=len(cached))
                    return cached

        # Cache yoksa kaynaklardan dene
        for source_name in source_priority:
            source = self._sources.get(source_name)
            if not source:
                continue

            try:
                df = source.fetch(ticker, start_date, end_date, period, interval)
                if df is not None and not df.empty:
                    # Cache'e kaydet
                    if self.use_cache:
                        self._save_to_cache(ticker, df, interval)

                    logger.info("Data loaded from source",
                              ticker=ticker, source=source_name, rows=len(df))
                    return df

            except Exception as e:
                logger.warning("Source failed",
                             ticker=ticker, source=source_name, error=str(e))
                continue

        logger.error("All sources failed", ticker=ticker)
        return pd.DataFrame()

    def get_multiple_stocks(
        self,
        tickers: List[str],
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        """Çoklu hisse verisi getir."""
        results = {}
        for ticker in tickers:
            df = self.get_stock_data(ticker, **kwargs)
            if not df.empty:
                results[ticker] = df
        return results

    def get_bist100_universe(self) -> List[str]:
        """BIST 100 hisse listesini getir."""
        # TODO: Gerçek BIST 100 listesi
        # Şimdilik örnek liste
        return [
            "THYAO.IS", "GARAN.IS", "ISCTR.IS", "AKBNK.IS", "YKBNK.IS",
            "BIMAS.IS", "KCHOL.IS", "SAHOL.IS", "TUPRS.IS", "EREGL.IS",
            "ASELS.IS", "SISE.IS", "TOASO.IS", "ARCLK.IS", "KRDMD.IS",
            "PETKM.IS", "PGSUS.IS", "TAVHL.IS", "TKFEN.IS", "VAKBN.IS",
        ]

    def get_benchmark_data(
        self,
        benchmark: str = "XU100.IS",
        **kwargs,
    ) -> pd.DataFrame:
        """Benchmark verisini getir."""
        return self.get_stock_data(benchmark, **kwargs)

    def _load_from_cache(self, ticker: str, interval: str) -> Optional[pd.DataFrame]:
        """Cache'den veri yükle."""
        cache_file = self.cache_dir / f"{ticker}_{interval}.parquet"

        if not cache_file.exists():
            return None

        # TTL kontrolü
        file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if file_age > timedelta(hours=self.cache_ttl_hours):
            logger.info("Cache expired", ticker=ticker)
            return None

        try:
            df = pd.read_parquet(cache_file)
            logger.info("Cache hit", ticker=ticker, rows=len(df))
            return df
        except Exception as e:
            logger.warning("Cache read failed", ticker=ticker, error=str(e))
            return None

    def _save_to_cache(self, ticker: str, df: pd.DataFrame, interval: str):
        """Veriyi cache'e kaydet."""
        cache_file = self.cache_dir / f"{ticker}_{interval}.parquet"

        try:
            df.to_parquet(cache_file, compression="zstd")
            logger.info("Cache saved", ticker=ticker, rows=len(df))
        except Exception as e:
            logger.warning("Cache save failed", ticker=ticker, error=str(e))

    def clear_cache(self):
        """Tüm cache'i temizle."""
        for f in self.cache_dir.glob("*.parquet"):
            f.unlink()
        logger.info("Cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Cache istatistikleri."""
        files = list(self.cache_dir.glob("*.parquet"))
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
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """Yahoo Finance'ten veri çek."""
        try:
            import yfinance as yf

            # Ticker formatını düzelt
            if not ticker.endswith(".IS") and not "." in ticker.split(".")[-1]:
                ticker = f"{ticker}.IS"

            stock = yf.Ticker(ticker)

            if start_date and end_date:
                df = stock.history(start=start_date, end=end_date, interval=interval)
            else:
                df = stock.history(period=period, interval=interval)

            if df.empty:
                return None

            # Kolon isimlerini düzelt
            df.columns = [c.replace("Stock Splits", "StockSplits").replace("Capital Gains", "CapitalGains") for c in df.columns]
            df.columns = [c[0].upper() + c[1:].lower() if c else c for c in df.columns]

            return df

        except ImportError:
            logger.warning("yfinance not installed")
            return None
        except Exception as e:
            logger.warning("Yahoo Finance fetch failed", error=str(e))
            return None


class BISTSource:
    """BIST resmi veri kaynağı."""

    def fetch(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """BIST'ten veri çek.

        Not: BIST API entegrasyonu gerekiyor.
        Şimdilik placeholder.
        """
        # TODO: BIST API entegrasyonu
        logger.info("BIST source not yet implemented")
        return None


class LocalParquetSource:
    """Yerel parquet dosyalarından veri kaynağı."""

    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)

    def fetch(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "2y",
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """Yerel parquet'ten veri çek."""
        cache_file = self.cache_dir / f"{ticker}_{interval}.parquet"

        if not cache_file.exists():
            return None

        try:
            df = pd.read_parquet(cache_file)

            # Tarih filtresi
            if start_date:
                df = df[df.index >= start_date]
            if end_date:
                df = df[df.index <= end_date]

            return df
        except Exception as e:
            logger.warning("Local parquet read failed", error=str(e))
            return None


# Singleton
data_source = DataSourceManager()
