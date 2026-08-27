"""
ALPHA BIST — Matriks Data Provider v2.0 (Async)

Kaynak: Matriks (ücretsiz, 15dk gecikmeli)
Güvenilirlik: 8/10

Kullanım: İkinci doğrulama kaynağı, cross-validation

v2.0: Async refactor + batch support
"""

import asyncio
from typing import Any

import structlog

from ...core.async_http import get_client

logger = structlog.get_logger()


class MatriksProvider:
    """Matriks veri sağlayıcısı (async, cross-validation)."""

    BASE_URL = "https://www.matriks.com"

    def __init__(self):
        self._client = get_client(
            "matriks",
            timeout=15.0,
            max_retries=3,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json, text/html, */*",
            },
        )

    async def fetch_stock_price(self, ticker: str) -> dict[str, Any] | None:
        """Tek hisse fiyatı — 15dk gecikmeli (async)."""
        logger.warning("Matriks Provider requires institutional API credentials. Endpoint disabled.")
        return None

    async def fetch_batch(self, tickers: list[str]) -> dict[str, dict]:
        """Toplu fiyat çekme (async, paralel)."""
        semaphore = asyncio.Semaphore(5)

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

        logger.info("Matriks batch fetched", count=len(output))
        return output

    async def fetch_index(self, symbol: str = "XU100") -> dict[str, Any] | None:
        """Endeks verisi (async)."""
        try:
            url = f"{self.BASE_URL}/api/index/{symbol}"
            data = await self._client.get_json(url)
            if data:
                return {
                    "symbol": symbol,
                    "price": data.get("last", 0),
                    "change_pct": data.get("changePercent", 0),
                    "volume": data.get("volume", 0),
                    "source": "matriks",
                }
            return None
        except Exception as e:
            logger.warning("Matriks index fetch failed", symbol=symbol, error=str(e))
            return None


# Singleton
matriks_provider = MatriksProvider()
