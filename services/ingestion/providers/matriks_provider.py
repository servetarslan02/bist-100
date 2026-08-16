"""
ALPHA BIST - Matriks Data Provider

Kaynak: Matriks (ücretsiz, 15dk gecikmeli)
Güvenilirlik: 8/10

Kullanım: İkinci doğrulama kaynağı, cross-validation
"""

import structlog
from ...core.async_http import get_client
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class MatriksProvider:
    """Matriks veri sağlayıcısı (cross-validation)."""

    BASE_URL = "https://www.matriks.com"

    async def __init__(self):
        self._client = get_client("matriks", timeout=15.0, max_retries=3)
        # Headers set in client config
        pass  #
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })

    async def fetch_stock_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Tek hisse fiyatı (15dk gecikmeli)."""
        try:
            url = f"{self.BASE_URL}/api/stock/{ticker}"
            resp = await self._client.get_json(url)

            if resp is not None:
                data = resp
                return {
                    "ticker": ticker,
                    "price": data.get("last", 0),
                    "change_pct": data.get("changePercent", 0),
                    "volume": data.get("volume", 0),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "matriks",
                    "delay_minutes": 15,
                }

            return None

        except Exception as e:
            logger.warning("Matriks fetch failed", ticker=ticker, error=str(e))
            return None

    async def fetch_batch(self, tickers: List[str]) -> Dict[str, Dict]:
        """Toplu fiyat çekme."""
        results = {}
        for ticker in tickers:
            data = self.fetch_stock_price(ticker)
            if data:
                results[ticker] = data
        return results


# Singleton
matriks_provider = MatriksProvider()
