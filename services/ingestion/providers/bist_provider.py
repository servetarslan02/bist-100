"""
ALPHA BIST — BIST Official Data Provider v2.0 (Async)

Kaynak: Borsa İstanbul resmi sitesi
Gecikme: 15 dk (ücretsiz)
Güvenilirlik: 10/10

v2.0: Async refactor + detaylı veri + endeks bileşenleri
"""

import asyncio
from typing import Any

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
        """Otomatik eklendi."""
        self._client = get_client(
            "bist",
            timeout=15.0,
            max_retries=3,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "tr-TR,tr;q=0.9",
            },
        )

    async def fetch_index_data(self) -> dict[str, Any]:
        """BIST endeks verilerini çek (async)."""
        logger.warning("BIST Provider requires institutional VERDA API credentials. Endpoint disabled.")
        return {}

    async def fetch_market_summary(self) -> dict[str, Any]:
        """Piyasa özeti: yükselen/düşen/hacim (async)."""
        logger.warning("BIST Provider requires institutional VERDA API credentials. Endpoint disabled.")
        return {}

    async def fetch_stock_price(self, ticker: str) -> dict[str, Any] | None:
        """Tek hisse fiyatı — 15dk gecikmeli (async)."""
        logger.warning("BIST Provider requires institutional VERDA API credentials. Endpoint disabled.")
        return None

    async def fetch_batch_prices(self, tickers: list[str]) -> dict[str, dict]:
        """Toplu fiyat çekme (async, paralel)."""
        semaphore = asyncio.Semaphore(5)  # Max 5 paralel

        async def _fetch_one(ticker: str) -> tuple:
            """Otomatik eklendi."""
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

    async def fetch_sector_indices(self) -> dict[str, Any]:
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

    def _parse_index_data(self, data: Any) -> dict[str, Any]:
        """Otomatik eklendi."""
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

    async def close(self) -> Any:
        """Otomatik eklendi."""
        await self._client.close()


# Singleton
bist_provider = BISTProvider()
