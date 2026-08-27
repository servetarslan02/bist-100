"""ALPHA BIST - yfinance Data Provider for BIST"""

from datetime import UTC, datetime
from typing import Any

import polars as pl
import structlog
import yfinance as yf

from ..bist_universe import bist_universe

logger = structlog.get_logger()


def get_yfinance_ticker(ticker: str) -> str:
    """BIST ticker'ını Yahoo Finance formatına çevir.

    THYAO → THYAO.IS
    XU100 → XU100.IS (endeks)
    """
    if ticker.endswith(".IS"):
        return ticker
    return f"{ticker}.IS"


class YFinanceProvider:
    """Fetches BIST market data from yfinance (15min delayed, free)."""

    _FETCH_TIMEOUT = 15  # saniye

    def __init__(self):
        self._cache: dict[str, Any] = {}

    @staticmethod
    def _expand_period(period: str) -> str:
        """Hafta sonu/tatil günlerini telafi etmek için period'u genişlet.

        60d → 90d, 30d → 45d, 1y → 1y (zaten yeterli)
        """
        import re

        m = re.match(r"^(\d+)(d|mo|y)$", period)
        if not m:
            return period
        val, unit = int(m.group(1)), m.group(2)
        if unit == "d":
            # ~1.5x genişlet (hafta sonları + tatiller)
            return f"{int(val * 1.5)}d"
        if unit == "mo":
            return f"{int(val * 1.5)}mo"
        return period  # 1y+ zaten yeterli

    @staticmethod
    def _run_with_timeout(fn, *args, timeout: int = 15, **kwargs):
        """Blocking fonksiyonu timeout ile çalıştır."""
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                logger.warning("yfinance call timed out", timeout=timeout)
                return None

    def fetch_current_price(self, ticker: str) -> dict[str, Any] | None:
        """Fetch current price data for a single ticker."""
        yf_ticker = get_yfinance_ticker(ticker)
        try:
            t = yf.Ticker(yf_ticker)
            info = self._run_with_timeout(lambda t=t: t.info, timeout=self._FETCH_TIMEOUT)
            if info is None:
                return None

            if not info or "regularMarketPrice" not in info:
                return None

            return {
                "ticker": ticker,
                "price": info.get("regularMarketPrice", 0),
                "previous_close": info.get("regularMarketPreviousClose", 0),
                "open": info.get("regularMarketOpen", 0),
                "high": info.get("regularMarketDayHigh", 0),
                "low": info.get("regularMarketDayLow", 0),
                "volume": info.get("regularMarketVolume", 0),
                "market_cap": info.get("marketCap", 0),
                "pe_ratio": info.get("trailingPE"),
                "pb_ratio": info.get("priceToBook"),
                "dividend_yield": info.get("dividendYield"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "avg_volume_20d": info.get("averageVolume"),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.warning("Failed to fetch price", ticker=ticker, error=str(e))
            return None

    def fetch_ohlcv(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pl.DataFrame | None:
        """Fetch OHLCV data for a single ticker."""
        yf_ticker = get_yfinance_ticker(ticker)
        try:
            t = yf.Ticker(yf_ticker)
            # Hafta sonu/tatil günleri için period'u genişlet
            # (60d ≈ 42 trading günü, feature_calculator en az 60 bar ister)
            expanded_period = self._expand_period(period)
            df = self._run_with_timeout(
                lambda: t.history(period=expanded_period, interval=interval),
                timeout=self._FETCH_TIMEOUT,
            )
            if df is None or (hasattr(df, "empty") and df.empty):
                return None

            if df.empty:
                return None

            df = df.reset_index()
            df["Ticker"] = ticker

            # Capitalize columns for feature_calculator compatibility
            df = df.rename(
                columns={
                    "Date": "timestamp",
                    "Open": "Open",
                    "High": "High",
                    "Low": "Low",
                    "Close": "Close",
                    "Volume": "Volume",
                    "Ticker": "Ticker",
                }
            )

            return df[["Ticker", "timestamp", "Open", "High", "Low", "Close", "Volume"]]

        except Exception as e:
            logger.warning("Failed to fetch OHLCV", ticker=ticker, error=str(e))
            return None

    def fetch_batch_ohlcv(
        self,
        tickers: list[str] | None = None,
        period: str = "1y",
        interval: str = "1d",
    ) -> dict[str, pl.DataFrame]:
        """Fetch OHLCV data for multiple tickers."""
        if tickers is None:
            tickers = bist_universe.get_tickers()

        results = {}
        yf_tickers = [get_yfinance_ticker(t) for t in tickers]

        try:
            # Batch download
            data = yf.download(
                yf_tickers,
                period=period,
                interval=interval,
                group_by="ticker",
                threads=True,
                progress=False,
            )

            if data.empty:
                return results

            for ticker in tickers:
                yf_ticker = get_yfinance_ticker(ticker)
                try:
                    # yfinance always returns MultiIndex with group_by='ticker'
                    # Even for single ticker: (ticker, OHLCV)
                    ticker_data = data[yf_ticker].copy()
                    ticker_data = ticker_data.dropna()
                    if ticker_data.empty:
                        continue
                    ticker_data = ticker_data.reset_index()
                    ticker_data["ticker"] = ticker

                    # Normalize column names (case-insensitive)
                    col_map = {}
                    for col in ticker_data.columns:
                        if not isinstance(col, str):
                            col = str(col)
                        cl = col.lower()
                        if cl == "date":
                            col_map[col] = "timestamp"
                        elif cl in ("open", "high", "low", "close", "volume"):
                            col_map[col] = cl
                    ticker_data = ticker_data.rename(columns=col_map)

                    required = ["ticker", "timestamp", "open", "high", "low", "close", "volume"]
                    missing = [c for c in required if c not in ticker_data.columns]
                    if missing:
                        logger.warning("Missing columns", ticker=ticker, missing=missing)
                        continue

                    pl_df = pl.from_pandas(ticker_data[required])
                    results[ticker] = pl_df

                except Exception as e:
                    logger.warning("Failed to process ticker data", ticker=ticker, error=str(e))
                    continue

        except Exception as e:
            logger.error("Batch download failed", error=str(e))

        logger.info("Batch OHLCV fetched", count=len(results))
        return results

    def fetch_index(self, index_symbol: str = "XU100") -> dict[str, Any] | None:
        """Fetch BIST index data."""
        yf_symbol = f"{index_symbol}.IS"
        try:
            t = yf.Ticker(yf_symbol)
            info = self._run_with_timeout(lambda t=t: t.info, timeout=self._FETCH_TIMEOUT)
            if info is None:
                return None

            return {
                "symbol": index_symbol,
                "price": info.get("regularMarketPrice", 0),
                "previous_close": info.get("regularMarketPreviousClose", 0),
                "change_pct": info.get("regularMarketChangePercent", 0),
                "volume": info.get("regularMarketVolume", 0),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.warning("Failed to fetch index", symbol=index_symbol, error=str(e))
            return None

    def fetch_macro(self) -> dict[str, Any]:
        """Fetch macro indicators (USD/TRY, Gold, Oil, VIX).

        Düzeltme: USD/TRY ve EUR/TRY için doğru yfinance symbol'leri kullanılır.
        """
        macro_tickers = {
            "USDTRY=X": "USD/TRY",
            "EURTRY=X": "EUR/TRY",
            "GC=F": "Gold",
            "CL=F": "Oil",
            "^VIX": "VIX",
            "^GSPC": "S&P500",
            "^IXIC": "Nasdaq",
        }

        results = {}
        for yf_symbol, name in macro_tickers.items():
            try:
                t = yf.Ticker(yf_symbol)
                info = self._run_with_timeout(lambda t=t: t.info, timeout=self._FETCH_TIMEOUT)
                if info is None:
                    results[name] = {"price": None, "change_pct": None, "error": "no data"}
                    continue
                results[name] = {
                    "price": info.get("regularMarketPrice", 0),
                    "change_pct": info.get("regularMarketChangePercent", 0),
                }
            except Exception as e:
                results[name] = {"price": None, "change_pct": None, "error": str(e)}

        return results


# Singleton
yfinance_provider = YFinanceProvider()
