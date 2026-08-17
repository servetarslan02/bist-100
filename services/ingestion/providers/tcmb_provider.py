"""ALPHA BIST - TCMB EVDS (Electronic Data Distribution System) Provider"""

import structlog
from ...core.async_http import get_client
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import structlog

logger = structlog.get_logger()

TCMB_BASE_URL = "https://evds2.tcmb.gov.tr/service/evds"


class TCMBProvider:
    """Fetches macro data from TCMB EVDS API."""

    # Key series codes
    SERIES = {
        "usd_try": "TP.DKUSD.A",
        "eur_try": "TP.DKEUR.A",
        "gbp_try": "TP.DKGBP.A",
        "policy_rate": "TP.PARLAK.ORANI",
        "overnight_rate": "TP.GONORT",
        "cpi": "TP.TUFE1YI1",
        "ppi": "TP.UFE1YI1",
        "current_account": "TP.DB.AB01",
        "industrial_production": "TP.TG2.Y1",
        "unemployment": "TP.TIGJ01",
        "gold_price": "TP.XKUSD.B.A",
        "bist_100": "TP.TUFE1YI1",
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._client = get_client("tcmb", timeout=30.0, max_retries=3)

    async def _make_request(self, series_code: str, start_date: str, end_date: str) -> Optional[List[Dict]]:
        """Make a request to TCMB EVDS API."""
        if not self.api_key:
            logger.warning("TCMB EVDS API key not configured")
            return None

        url = f"{TCMB_BASE_URL}/series={series_code}&startDate={start_date}&endDate={end_date}&type=json&key={self.api_key}"

        try:
            resp = await self._client.get_json(url)
            resp.raise_for_status()
            data = resp

            items = data.get("items", [])
            logger.info("TCMB data fetched", series=series_code, count=len(items))
            return items

        except Exception as e:
            logger.error("TCMB EVDS request failed", series=series_code, error=str(e))
            return None

    async def fetch_usd_try(self, days: int = 30) -> Optional[List[Dict]]:
        """Fetch USD/TRY exchange rate."""
        end_date = datetime.now().strftime("%d-%m-%Y")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
        return self._make_request(self.SERIES["usd_try"], start_date, end_date)

    async def fetch_policy_rate(self, days: int = 365) -> Optional[List[Dict]]:
        """Fetch CBRT policy rate."""
        end_date = datetime.now().strftime("%d-%m-%Y")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
        return self._make_request(self.SERIES["policy_rate"], start_date, end_date)

    async def fetch_inflation(self, days: int = 365) -> Optional[List[Dict]]:
        """Fetch CPI data."""
        end_date = datetime.now().strftime("%d-%m-%Y")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
        return self._make_request(self.SERIES["cpi"], start_date, end_date)

    async def fetch_all_macro(self) -> Dict[str, Any]:
        """Fetch all key macro indicators."""
        result = {}

        for name, series in self.SERIES.items():
            try:
                end_date = datetime.now().strftime("%d-%m-%Y")
                start_date = (datetime.now() - timedelta(days=30)).strftime("%d-%m-%Y")
                data = self._make_request(series, start_date, end_date)

                if data and len(data) > 0:
                    latest = data[-1]
                    result[name] = {
                        "value": latest.get("value", 0),
                        "date": latest.get("date", ""),
                        "series": series,
                    }
                else:
                    result[name] = {"value": None, "date": None, "series": series}

            except Exception as e:
                logger.warning("Failed to fetch macro series", series=name, error=str(e))
                result[name] = {"value": None, "date": None, "series": series}

        return result


# Singleton
tcmb_provider = TCMBProvider()
