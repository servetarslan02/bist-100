"""
ALPHA BIST — BIST Official Data Provider v2.0 (Async)

Kaynak: Borsa İstanbul resmi sitesi
Gecikme: 15 dk (ücretsiz)
Güvenilirlik: 10/10

v2.0: Async refactor + detaylı veri + endeks bileşenleri
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import structlog

from ...core.async_http import get_client

logger = structlog.get_logger()


class BISTProvider:
    """Borsa İstanbul resmi veri sağlayıcısı (async)."""

    BASE_URL = "https://www.borsaistanbul.com"

    # BIST endeksleri
    INDICES = {
        "XU100": "BIST 100",
        "XU030": "BIST 30",
        "XU050": "BIST 50",
        "XBANK": "BIST Banka",
        "XUSIN": "BIST Sınai",
        "XUMAL": "BIST Mali",
        "XUTEK": "BIST Teknoloji",
        "XHOLD": "BIST Holding",
    }

    def __init__(self):
        self._client = get_client("bist", timeout=15.0, max_retries=3, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "tr-TR,tr;q=0.9",
        })

    async def fetch_index_data(self) -> Dict[str, Any]:
        """BIST endeks verilerini çek (async)."""
        try:
            url = f"{self.BASE_URL}/api/index"
            data = await self._client.get_json(url)
            if data:
                return self._parse_index_data(data)
            return {}
        except Exception as e:
            logger.warning("BIST index fetch failed", error=str(e))
            return {}

    async def fetch_market_summary(self) -> Dict[str, Any]:
        """Piyasa özeti: yükselen/düşen/hacim (async)."""
        try:
            url = f"{self.BASE_URL}/api/market-summary"
            data = await self._client.get_json(url)
            return data or {}
        except Exception as e:
            logger.warning("BIST market summary failed", error=str(e))
            return {}

    async def fetch_stock_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Tek hisse fiyatı — 15dk gecikmeli (async)."""
        try:
            url = f"{self.BASE_URL}/api/stock/{ticker}"
            data = await self._client.get_json(url)
            if data:
                return {
                    "ticker": ticker,
                    "price": data.get("lastPrice", 0),
                    "change_pct": data.get("changePercent", 0),
                    "volume": data.get("volume", 0),
                    "high": data.get("high", 0),
                    "low": data.get("low", 0),
                    "open": data.get("open", 0),
                    "close": data.get("close", 0),
                    "bid": data.get("bidPrice", 0),
                    "ask": data.get("askPrice", 0),
                    "best_bid_volume": data.get("bidVolume", 0),
                    "best_ask_volume": data.get("askVolume", 0),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "bist_official",
                    "delay_minutes": 15,
                }
            return None
        except Exception as e:
            logger.warning("BIST stock price failed", ticker=ticker, error=str(e))
            return None

    async def fetch_batch_prices(self, tickers: List[str]) -> Dict[str, Dict]:
        """Toplu fiyat çekme (async, paralel)."""
        semaphore = asyncio.Semaphore(5)  # Max 5 paralel

        async def _fetch_one(ticker: str) -> tuple:
            async with semaphore:
                data = await self.fetch_stock_price(ticker)
                return ticker, data

        tasks = [_fetch_one(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for item in results:
            if isinstance(item, Exception):
                continue
            ticker, data = item
            if data:
                output[ticker] = data

        logger.info("BIST batch prices fetched", count=len(output))
        return output

    async def fetch_sector_indices(self) -> Dict[str, Any]:
        """Sektör endeksleri (async)."""
        results = {}
        for symbol, name in self.INDICES.items():
            try:
                url = f"{self.BASE_URL}/api/index/{symbol}"
                data = await self._client.get_json(url)
                if data:
                    results[symbol] = {
                        "name": name,
                        "price": data.get("lastPrice", 0),
                        "change_pct": data.get("changePercent", 0),
                        "volume": data.get("volume", 0),
                    }
            except Exception as e:
                logger.debug("BIST sector index failed", symbol=symbol, error=str(e))

        return results

    def _parse_index_data(self, data: Any) -> Dict[str, Any]:
        indices = {}
        for item in data if isinstance(data, list) else []:
            symbol = item.get("symbol", "")
            indices[symbol] = {
                "name": item.get("name", self.INDICES.get(symbol, "")),
                "price": item.get("lastPrice", 0),
                "change_pct": item.get("changePercent", 0),
                "volume": item.get("volume", 0),
                "high": item.get("high", 0),
                "low": item.get("low", 0),
            }
        return indices

    async def close(self):
        await self._client.close()


# Singleton
bist_provider = BISTProvider()
