"""
ALPHA BIST - BIST Official Data Provider (Async)

Kaynak: Borsa İstanbul resmi sitesi
Gecikme: 15 dk (ücretsiz)
Güvenilirlik: 10/10
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import structlog

from ...core.async_http import get_client

logger = structlog.get_logger()


class BISTProvider:
    """Borsa İstanbul resmi veri sağlayıcısı (async)."""

    BASE_URL = "https://www.borsaistanbul.com"

    def __init__(self):
        self._client = get_client("bist", timeout=15.0, max_retries=3)

    async def fetch_index_data(self) -> Dict[str, Any]:
        """BIST endeks verilerini çek."""
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
        """Piyasa özeti: yükselen/düşen/hacim."""
        try:
            url = f"{self.BASE_URL}/api/market-summary"
            data = await self._client.get_json(url)
            return data or {}
        except Exception as e:
            logger.warning("BIST market summary failed", error=str(e))
            return {}

    async def fetch_stock_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Tek hisse fiyatı (15dk gecikmeli)."""
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "bist_official",
                    "delay_minutes": 15,
                }
            return None
        except Exception as e:
            logger.warning("BIST stock price failed", ticker=ticker, error=str(e))
            return None

    def _parse_index_data(self, data: Any) -> Dict[str, Any]:
        indices = {}
        for item in data if isinstance(data, list) else []:
            indices[item.get("symbol", "")] = {
                "name": item.get("name", ""),
                "price": item.get("lastPrice", 0),
                "change_pct": item.get("changePercent", 0),
                "volume": item.get("volume", 0),
            }
        return indices

    async def close(self):
        await self._client.close()


bist_provider = BISTProvider()
