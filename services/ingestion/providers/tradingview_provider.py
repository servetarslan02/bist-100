"""
ALPHA BIST — TradingView Scanner Data Provider v1.0

TradingView Türkiye Tarayıcısı (Scanner API) ile tüm BIST hisselerini
tek bir HTTP POST isteğiyle (~150ms) anlık, gecikmesiz ve zengin
teknik/temel indikatörlerle toplu olarak çeker.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

TRADINGVIEW_SCANNER_URL = "https://scanner.tradingview.com/turkey/scan"

# İstenen metrikler ve indikatör sütunları
SCANNER_COLUMNS = [
    "name",
    "description",
    "close",
    "change",
    "change_abs",
    "volume",
    "Value.Traded",
    "open",
    "high",
    "low",
    "RSI",
    "MACD.macd",
    "MACD.signal",
    "SMA50",
    "SMA200",
    "market_cap_basic",
    "price_earnings_ttm",
    "price_book_fq",
    "Recommend.All",
    "Volatility.D",
]


class TradingViewProvider:
    """TradingView Scanner API üzerinden yüksek performanslı BIST veri sağlayıcısı."""

    def __init__(self, timeout: float = 10.0):
        self._timeout = timeout
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_fetch_time: datetime | None = None
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def fetch_all_bist_stocks(self) -> dict[str, dict[str, Any]]:
        """Tüm BIST hisselerini tek bir istekte çeker ve sözlük olarak döner.

        Returns:
            dict[ticker, dict]: Hisse sembolüne göre yapılandırılmış piyasa verileri.
        """
        payload = {
            "filter": [],
            "options": {"lang": "tr"},
            "symbols": {"query": {"types": []}},
            "columns": SCANNER_COLUMNS,
            "sort": {"sortBy": "Value.Traded", "sortOrder": "desc"},
            "range": [0, 800],
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    TRADINGVIEW_SCANNER_URL,
                    json=payload,
                    headers=self._headers,
                )

                if response.status_code != 200:
                    logger.warning(
                        "TradingView scanner returned non-200 status",
                        status_code=response.status_code,
                    )
                    return self._cache

                raw_data = response.json()
                rows = raw_data.get("data", [])
                result: dict[str, dict[str, Any]] = {}
                now_str = datetime.now(UTC).isoformat()

                for row in rows:
                    cols = row.get("d", [])
                    if not cols or len(cols) < len(SCANNER_COLUMNS):
                        continue

                    raw_item = dict(zip(SCANNER_COLUMNS, cols, strict=False))
                    ticker = raw_item.get("name")
                    if not ticker or not isinstance(ticker, str):
                        continue

                    ticker = ticker.strip().upper()
                    close_price = raw_item.get("close")
                    if close_price is None or not isinstance(close_price, int | float) or close_price <= 0:
                        continue

                    result[ticker] = {
                        "ticker": ticker,
                        "name": raw_item.get("description", ""),
                        "price": float(close_price),
                        "close": float(close_price),
                        "change_pct": float(raw_item.get("change") or 0.0),
                        "change_abs": float(raw_item.get("change_abs") or 0.0),
                        "volume": float(raw_item.get("volume") or 0.0),
                        "value_traded": float(raw_item.get("Value.Traded") or 0.0),
                        "open": float(raw_item.get("open") or close_price),
                        "high": float(raw_item.get("high") or close_price),
                        "low": float(raw_item.get("low") or close_price),
                        "rsi": float(raw_item.get("RSI") or 0.0) if raw_item.get("RSI") is not None else None,
                        "macd": float(raw_item.get("MACD.macd") or 0.0)
                        if raw_item.get("MACD.macd") is not None
                        else None,
                        "macd_signal": float(raw_item.get("MACD.signal") or 0.0)
                        if raw_item.get("MACD.signal") is not None
                        else None,
                        "sma50": float(raw_item.get("SMA50") or 0.0)
                        if raw_item.get("SMA50") is not None
                        else None,
                        "sma200": float(raw_item.get("SMA200") or 0.0)
                        if raw_item.get("SMA200") is not None
                        else None,
                        "market_cap": float(raw_item.get("market_cap_basic") or 0.0)
                        if raw_item.get("market_cap_basic") is not None
                        else None,
                        "pe_ratio": float(raw_item.get("price_earnings_ttm") or 0.0)
                        if raw_item.get("price_earnings_ttm") is not None
                        else None,
                        "pb_ratio": float(raw_item.get("price_book_fq") or 0.0)
                        if raw_item.get("price_book_fq") is not None
                        else None,
                        "recommendation": float(raw_item.get("Recommend.All") or 0.0)
                        if raw_item.get("Recommend.All") is not None
                        else None,
                        "volatility_daily": float(raw_item.get("Volatility.D") or 0.0)
                        if raw_item.get("Volatility.D") is not None
                        else None,
                        "source": "tradingview",
                        "timestamp": now_str,
                    }

                self._cache = result
                self._last_fetch_time = datetime.now(UTC)
                logger.info("TradingView BIST scan completed", count=len(result))
                return result

        except Exception as exc:
            logger.warning("TradingView BIST scan failed", error=str(exc))
            return self._cache

    def get_cached_stock(self, ticker: str) -> dict[str, Any] | None:
        """Önbellekten tek bir hissenin verisini döner."""
        return self._cache.get(ticker.strip().upper())


# Global singleton
tradingview_provider = TradingViewProvider()
