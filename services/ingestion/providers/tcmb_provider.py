"""ALPHA BIST - TCMB EVDS (Electronic Data Distribution System) Provider"""

import structlog
from ...core.async_http import get_client
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

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
        import os
        self.api_key = api_key or os.getenv("TCMB_API_KEY") or os.getenv("EVDS_API_KEY")
        self._client = get_client("tcmb", timeout=10.0, max_retries=2)
        self._warned_no_key = False

    async def _make_request(self, series_code: str, start_date: str, end_date: str) -> Optional[List[Dict]]:
        """Make a request to TCMB EVDS API."""
        if not self.api_key:
            if not self._warned_no_key:
                logger.info("TCMB EVDS API key not configured, using canonical macroeconomic baseline")
                self._warned_no_key = True
            return None

        url = f"{TCMB_BASE_URL}/series={series_code}&startDate={start_date}&endDate={end_date}&type=json&key={self.api_key}"

        try:
            data = await self._client.get_json(url)

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
        return await self._make_request(self.SERIES["usd_try"], start_date, end_date)

    async def fetch_policy_rate(self, days: int = 365) -> Optional[List[Dict]]:
        """Fetch CBRT policy rate."""
        end_date = datetime.now().strftime("%d-%m-%Y")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
        return await self._make_request(self.SERIES["policy_rate"], start_date, end_date)

    async def fetch_inflation(self, days: int = 365) -> Optional[List[Dict]]:
        """Fetch CPI data."""
        end_date = datetime.now().strftime("%d-%m-%Y")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
        return await self._make_request(self.SERIES["cpi"], start_date, end_date)

    async def fetch_all_macro(self) -> Dict[str, Any]:
        """Fetch all key macro indicators (with canonical baseline fallback)."""
        result = {}
        now_str = datetime.now().strftime("%d-%m-%Y")

        # Canonical baseline values used when EVDS API key is not present
        baseline_values = {
            "policy_rate": 50.0,
            "overnight_rate": 50.0,
            "cpi": 48.5,
            "ppi": 41.2,
            "usd_try": 36.5,
            "eur_try": 38.2,
            "gbp_try": 45.8,
            "current_account": -1500.0,
            "industrial_production": 2.5,
            "unemployment": 8.5,
            "gold_price": 2850.0,
            "bist_100": 9850.0,
        }

        for name, series in self.SERIES.items():
            try:
                end_date = datetime.now().strftime("%d-%m-%Y")
                start_date = (datetime.now() - timedelta(days=30)).strftime("%d-%m-%Y")
                data = await self._make_request(series, start_date, end_date)

                if data and len(data) > 0:
                    latest = data[-1]
                    val = float(latest.get("value", 0)) if latest.get("value") is not None else baseline_values.get(name)
                    result[name] = {
                        "value": val,
                        "date": latest.get("date", now_str),
                        "series": series,
                        "is_live": True,
                    }
                else:
                    result[name] = {
                        "value": baseline_values.get(name),
                        "date": now_str,
                        "series": series,
                        "is_live": False,
                    }

            except Exception as e:
                logger.debug("Failed to fetch macro series, using baseline", series=name, error=str(e))
                result[name] = {
                    "value": baseline_values.get(name),
                    "date": now_str,
                    "series": series,
                    "is_live": False,
                }

        return result


# Singleton
tcmb_provider = TCMBProvider()
