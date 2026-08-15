"""ALPHA BIST - yfinance Data Provider for BIST"""

import yfinance as yf
import polars as pl
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import structlog

from ..bist_universe import BIST_STOCKS, get_yfinance_ticker

logger = structlog.get_logger()


class YFinanceProvider:
    """Fetches BIST market data from yfinance (15min delayed, free)."""

    def __init__(self):
        self._cache: Dict[str, Any] = {}

    def fetch_current_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch current price data for a single ticker."""
        yf_ticker = get_yfinance_ticker(ticker)
        try:
            t = yf.Ticker(yf_ticker)
            info = t.info

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
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.warning("Failed to fetch price", ticker=ticker, error=str(e))
            return None

    def fetch_ohlcv(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> Optional[pl.DataFrame]:
        """Fetch OHLCV data for a single ticker."""
        yf_ticker = get_yfinance_ticker(ticker)
        try:
            t = yf.Ticker(yf_ticker)
            df = t.history(period=period, interval=interval)

            if df.empty:
                return None

            df = df.reset_index()
            df["Ticker"] = ticker

            # Convert to Polars
            pl_df = pl.from_pandas(df)

            # Rename columns
            pl_df = pl_df.rename({
                "Date": "timestamp",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
                "Ticker": "ticker",
            })

            return pl_df.select(["ticker", "timestamp", "open", "high", "low", "close", "volume"])

        except Exception as e:
            logger.warning("Failed to fetch OHLCV", ticker=ticker, error=str(e))
            return None

    def fetch_batch_ohlcv(
        self,
        tickers: Optional[List[str]] = None,
        period: str = "1y",
        interval: str = "1d",
    ) -> Dict[str, pl.DataFrame]:
        """Fetch OHLCV data for multiple tickers."""
        if tickers is None:
            tickers = BIST_STOCKS

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
                    if len(tickers) == 1:
                        ticker_data = data.copy()
                    else:
                        ticker_data = data[yf_ticker].copy()

                    ticker_data = ticker_data.dropna()
                    if ticker_data.empty:
                        continue

                    ticker_data = ticker_data.reset_index()
                    ticker_data["ticker"] = ticker

                    pl_df = pl.from_pandas(ticker_data)
                    pl_df = pl_df.rename({
                        "Date": "timestamp",
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Volume": "volume",
                    })

                    results[ticker] = pl_df.select(["ticker", "timestamp", "open", "high", "low", "close", "volume"])

                except Exception as e:
                    logger.warning("Failed to process ticker data", ticker=ticker, error=str(e))
                    continue

        except Exception as e:
            logger.error("Batch download failed", error=str(e))

        logger.info("Batch OHLCV fetched", count=len(results))
        return results

    def fetch_index(self, index_symbol: str = "XU100") -> Optional[Dict[str, Any]]:
        """Fetch BIST index data."""
        yf_symbol = f"{index_symbol}.IS"
        try:
            t = yf.Ticker(yf_symbol)
            info = t.info

            return {
                "symbol": index_symbol,
                "price": info.get("regularMarketPrice", 0),
                "previous_close": info.get("regularMarketPreviousClose", 0),
                "change_pct": info.get("regularMarketChangePercent", 0),
                "volume": info.get("regularMarketVolume", 0),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.warning("Failed to fetch index", symbol=index_symbol, error=str(e))
            return None

    def fetch_macro(self) -> Dict[str, Any]:
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
                info = t.info
                results[name] = {
                    "price": info.get("regularMarketPrice", 0),
                    "change_pct": info.get("regularMarketChangePercent", 0),
                }
            except Exception:
                results[name] = {"price": 0, "change_pct": 0}

        return results


# Singleton
yfinance_provider = YFinanceProvider()
