"""ALPHA BIST — TCMB EVDS (Electronic Data Distribution System) Provider"""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from ...core.async_http import get_client

logger = structlog.get_logger()

# Varsayılan sabitler
DEFAULT_TCMB_BASE_URL: str = "https://evds2.tcmb.gov.tr/service/evds"
DEFAULT_TCMB_TIMEOUT: float = 10.0
DEFAULT_TCMB_MAX_RETRIES: int = 2
DEFAULT_TCMB_HISTORY_DAYS: int = 30
DEFAULT_TCMB_POLICY_DAYS: int = 365

# TCMB EVDS serileri
DEFAULT_TCMB_SERIES: dict[str, str] = {
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
}

# Varsayılan baz değerler — config dosyasından override edilebilir
DEFAULT_TCMB_BASELINE: dict[str, float] = {
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
}


def _load_baseline_config() -> dict[str, float]:
    """Config dosyasından baz değerleri yükler, varsayılanlara düşer.

    Returns:
        Baz değerler sözlüğü.
    """
    import orjson as _json

    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "tcmb_baseline.json")
    config_path = os.path.normpath(config_path)
    try:
        with open(config_path, "rb") as f:
            loaded = _json.loads(f.read())
            merged = {**DEFAULT_TCMB_BASELINE, **loaded}
            logger.info("TCMB baseline config loaded", path=config_path)
            return merged
    except FileNotFoundError:
        logger.info("TCMB baseline config not found, using defaults", path=config_path)
        return DEFAULT_TCMB_BASELINE.copy()
    except Exception as e:
        logger.warning("Failed to load TCMB baseline config, using defaults", error=str(e))
        return DEFAULT_TCMB_BASELINE.copy()


class TCMBProvider:
    """TCMB EVDS API üzerinden makro veri çeker."""

    def __init__(self, api_key: str | None = None) -> None:
        """TCMBProvider örneği oluşturur.

        Args:
            api_key: TCMB EVDS API anahtarı. None ise ortam değişkeninden okunur.
        """
        self.api_key = api_key or os.getenv("TCMB_API_KEY") or os.getenv("EVDS_API_KEY")
        self._client = get_client("tcmb", timeout=DEFAULT_TCMB_TIMEOUT, max_retries=DEFAULT_TCMB_MAX_RETRIES)
        self._warned_no_key = False
        self.baseline_values = _load_baseline_config()

    def __repr__(self) -> str:
        """TCMBProvider string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return f"TCMBProvider(api_configured={self.api_key is not None}, series={len(DEFAULT_TCMB_SERIES)})"

    async def _make_request(self, series_code: str, start_date: str, end_date: str) -> list[dict] | None:
        """TCMB EVDS API'ye istek yapar.

        Args:
            series_code: EVDS seri kodu.
            start_date: Başlangıç tarihi (DD-MM-YYYY).
            end_date: Bitiş tarihi (DD-MM-YYYY).

        Returns:
            Veri listesi veya None.
        """
        if not self.api_key:
            if not self._warned_no_key:
                logger.info("TCMB EVDS API key not configured, using canonical macroeconomic baseline")
                self._warned_no_key = True
            return None

        url = f"{DEFAULT_TCMB_BASE_URL}/series={series_code}&startDate={start_date}&endDate={end_date}&type=json&key={self.api_key}"

        try:
            data = await self._client.get_json(url)

            items = data.get("items", [])
            logger.info("TCMB data fetched", series=series_code, count=len(items))
            return items

        except Exception as e:
            logger.error("TCMB EVDS request failed", series=series_code, error=str(e))
            return None

    async def fetch_usd_try(self, days: int = DEFAULT_TCMB_HISTORY_DAYS) -> list[dict] | None:
        """USD/TRY kurunu çeker.

        Args:
            days: Geçmiş gün sayısı.

        Returns:
            Kur verisi listesi veya None.
        """
        end_date = datetime.now(UTC).strftime("%d-%m-%Y")
        start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%m-%Y")
        return await self._make_request(DEFAULT_TCMB_SERIES["usd_try"], start_date, end_date)

    async def fetch_policy_rate(self, days: int = DEFAULT_TCMB_POLICY_DAYS) -> list[dict] | None:
        """TCMB politika faizini çeker.

        Args:
            days: Geçmiş gün sayısı.

        Returns:
            Faiz verisi listesi veya None.
        """
        end_date = datetime.now(UTC).strftime("%d-%m-%Y")
        start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%m-%Y")
        return await self._make_request(DEFAULT_TCMB_SERIES["policy_rate"], start_date, end_date)

    async def fetch_inflation(self, days: int = DEFAULT_TCMB_POLICY_DAYS) -> list[dict] | None:
        """TÜFE verisini çeker.

        Args:
            days: Geçmiş gün sayısı.

        Returns:
            Enflasyon verisi listesi veya None.
        """
        end_date = datetime.now(UTC).strftime("%d-%m-%Y")
        start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%m-%Y")
        return await self._make_request(DEFAULT_TCMB_SERIES["cpi"], start_date, end_date)

    async def fetch_all_macro(self) -> dict[str, Any]:
        """Tüm kritik makro göstergeleri çeker (baz değer fallback ile).

        Returns:
            Makro göstergeler sözlüğü.
        """
        result: dict[str, Any] = {}
        now_str = datetime.now(UTC).strftime("%d-%m-%Y")
        now_iso = datetime.now(UTC).isoformat()

        baseline_values = self.baseline_values

        for name, series in DEFAULT_TCMB_SERIES.items():
            try:
                end_date = datetime.now(UTC).strftime("%d-%m-%Y")
                start_date = (datetime.now(UTC) - timedelta(days=DEFAULT_TCMB_HISTORY_DAYS)).strftime("%d-%m-%Y")
                data = await self._make_request(series, start_date, end_date)

                if data and len(data) > 0:
                    latest = data[-1]
                    val = (
                        float(latest.get("value", 0)) if latest.get("value") is not None else baseline_values.get(name)
                    )
                    result[name] = {
                        "value": val,
                        "date": latest.get("date", now_str),
                        "series": series,
                        "is_live": True,
                        "last_updated": now_iso,
                    }
                else:
                    logger.warning(
                        "Using baseline value (not live data)",
                        series=name,
                        baseline_value=baseline_values.get(name),
                    )
                    result[name] = {
                        "value": baseline_values.get(name),
                        "date": now_str,
                        "series": series,
                        "is_live": False,
                        "last_updated": now_iso,
                    }

            except Exception as e:
                logger.warning(
                    "Failed to fetch macro series, using baseline",
                    series=name,
                    error=str(e),
                )
                result[name] = {
                    "value": baseline_values.get(name),
                    "date": now_str,
                    "series": series,
                    "is_live": False,
                    "last_updated": now_iso,
                }

        return result


# Singleton
tcmb_provider = TCMBProvider()


__all__ = ["TCMBProvider", "tcmb_provider"]
