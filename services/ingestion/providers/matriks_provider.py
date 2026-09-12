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

# Varsayılan sabitler
DEFAULT_MATRIKS_BASE_URL: str = "https://www.matriks.com"
DEFAULT_MATRIKS_TIMEOUT: float = 15.0
DEFAULT_MATRIKS_MAX_RETRIES: int = 3
DEFAULT_MATRIKS_SEMAPHORE: int = 5


class MatriksProvider:
    """Matriks veri sağlayıcısı (async, cross-validation)."""

    def __init__(self) -> None:
        """MatriksProvider örneği oluşturur."""
        self._client = get_client(
            "matriks",
            timeout=DEFAULT_MATRIKS_TIMEOUT,
            max_retries=DEFAULT_MATRIKS_MAX_RETRIES,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json, text/html, */*",
            },
        )

    def __repr__(self) -> str:
        """MatriksProvider string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return f"MatriksProvider(base_url={DEFAULT_MATRIKS_BASE_URL!r})"

    async def fetch_stock_price(self, ticker: str) -> dict[str, Any] | None:
        """Tek hisse fiyatı çeker — 15dk gecikmeli (async).

        Args:
            ticker: Hisse sembolü.

        Returns:
            Fiyat verisi sözlüğü veya None.
        """
        logger.warning("Matriks Provider requires institutional API credentials. Endpoint disabled.")
        return None

    async def fetch_batch(self, tickers: list[str]) -> dict[str, dict]:
        """Toplu fiyat çeker (async, paralel).

        Args:
            tickers: Hisse sembolleri listesi.

        Returns:
            {ticker: fiyat_verisi} sözlüğü.
        """
        semaphore = asyncio.Semaphore(DEFAULT_MATRIKS_SEMAPHORE)

        async def _fetch_one(ticker: str) -> tuple[str, dict[str, Any] | None]:
            """Tek hisse için fiyat çeker.

            Args:
                ticker: Hisse sembolü.

            Returns:
                (ticker, fiyat_verisi) demeti.
            """
            async with semaphore:
                data = await self.fetch_stock_price(ticker)
                return ticker, data

        tasks = [_fetch_one(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[str, dict] = {}
        for item in results:
            if isinstance(item, Exception):
                continue
            ticker, data = item
            if data:
                output[ticker] = data

        logger.info("Matriks batch fetched", count=len(output))
        return output

    async def fetch_index(self, symbol: str = "XU100") -> dict[str, Any] | None:
        """Endeks verisi çeker (async).

        Args:
            symbol: Endeks sembolü.

        Returns:
            Endeks verisi sözlüğü veya None.
        """
        try:
            url = f"{DEFAULT_MATRIKS_BASE_URL}/api/index/{symbol}"
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


__all__ = ["MatriksProvider", "matriks_provider"]
