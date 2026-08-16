"""
ALPHA BIST — KAP Data Provider (Async)

Kamuyu Aydınlatma Platformu — şirket açıklamaları, KAP bildirimleri.
"""

import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
import structlog

from ...core.async_http import get_client

logger = structlog.get_logger()

KAP_BASE_URL = "https://kap.org.tr"
KAP_API_URL = "https://www.kap.org.tr/tr/api"


class KAPProvider:
    """KAP şirket açıklamaları (async)."""

    def __init__(self):
        self._client = get_client("kap", timeout=15.0, max_retries=3, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "tr-TR,tr;q=0.9",
        })

    async def fetch_disclosures(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """KAP açıklamalarını çek."""
        try:
            params = {"fromDate": from_date or "", "toDate": to_date or "", "limit": str(limit)}
            if ticker:
                params["ticker"] = ticker

            data = await self._client.get_json(f"{KAP_API_URL}/disclosures", params=params)
            if not data:
                return []

            disclosures = []
            for item in data if isinstance(data, list) else []:
                disclosure = {
                    "id": item.get("disclosureId", ""),
                    "ticker": item.get("stockTicker", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "category": item.get("category", ""),
                    "publish_date": item.get("publishDate", ""),
                    "kap_url": f"{KAP_BASE_URL}{item.get('url', '')}",
                    "source": "kap",
                }
                disclosures.append(disclosure)

            logger.info("KAP disclosures fetched", count=len(disclosures))
            return disclosures

        except Exception as e:
            logger.error("KAP fetch failed", error=str(e))
            return []

    async def fetch_company_info(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Şirket bilgisi çek."""
        try:
            data = await self._client.get_json(f"{KAP_API_URL}/company/{ticker}")
            if data:
                return {
                    "ticker": ticker,
                    "name": data.get("name", ""),
                    "sector": data.get("sector", ""),
                    "market_cap": data.get("marketCap", 0),
                    "employees": data.get("employees", 0),
                    "website": data.get("website", ""),
                }
            return None
        except Exception as e:
            logger.warning("KAP company info failed", ticker=ticker, error=str(e))
            return None

    async def fetch_financial_data(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Finansal veri çek."""
        try:
            data = await self._client.get_json(f"{KAP_API_URL}/financial/{ticker}")
            if data:
                return {
                    "ticker": ticker,
                    "revenue": data.get("revenue", 0),
                    "net_income": data.get("netIncome", 0),
                    "total_assets": data.get("totalAssets", 0),
                    "total_equity": data.get("totalEquity", 0),
                    "eps": data.get("eps", 0),
                    "pe_ratio": data.get("peRatio", 0),
                    "report_date": data.get("reportDate", ""),
                }
            return None
        except Exception as e:
            logger.warning("KAP financial data failed", ticker=ticker, error=str(e))
            return None

    async def close(self):
        await self._client.close()


kap_provider = KAPProvider()
