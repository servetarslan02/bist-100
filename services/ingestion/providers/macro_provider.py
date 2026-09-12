"""
ALPHA BIST — Macro Data Provider v2.0 (Async + Detaylı)

Kaynaklar: TCMB EVDS, FRED, ECB, Yahoo Finance
Kullanım: Dünya piyasaları, makro veriler, BIST'e özgü göstergeler

v2.0: Async refactor + detaylı EVDS + BIST'e özgü makro göstergeler
"""

import asyncio
import concurrent.futures
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
import yfinance as yf

from ...core.async_http import get_client

logger = structlog.get_logger()

# Varsayılan sabitler
DEFAULT_MACRO_TIMEOUT: float = 20.0
DEFAULT_TCMB_TIMEOUT: float = 30.0
DEFAULT_MACRO_MAX_RETRIES: int = 3
DEFAULT_MACRO_CACHE_TTL: int = 300
DEFAULT_MACRO_MAX_WORKERS: int = 6
DEFAULT_YAHOO_FETCH_TIMEOUT: int = 15
DEFAULT_HISTORY_DAYS: int = 30
DEFAULT_HISTORY_OBSERVATIONS: int = 5

# VIX eşikleri
DEFAULT_VIX_LOW: float = 15.0
DEFAULT_VIX_HIGH: float = 25.0

# DXY eşikleri
DEFAULT_DXY_MODERATE: float = 100.0
DEFAULT_DXY_STRONG: float = 105.0

# Yahoo Finance sembolleri
DEFAULT_YAHOO_SYMBOLS: dict[str, str] = {
    "USDTRY": "TRY=X",
    "EURTRY": "EURTRY=X",
    "VIX": "^VIX",
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DXY": "DX-Y.NYB",
    "BRENT": "BZ=F",
    "GOLD": "GC=F",
    "US10Y": "^TNX",
    "BTC": "BTC-USD",
    "DAX": "^GDAXI",
    "FTSE": "^FTSE",
    "NIKKEI": "^N225",
}

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
    "foreign_reserves": "TP.REZERV",
    "banking_sector_deposits": "TP.MDDT",
}

# FRED serileri
DEFAULT_FRED_SERIES: dict[str, str] = {
    "US_CPI": "CPIAUCSL",
    "US_UNEMPLOYMENT": "UNRATE",
    "US_GDP": "GDP",
    "US_FED_FUNDS": "FEDFUNDS",
    "US_10Y_YIELD": "DGS10",
    "US_2Y_YIELD": "DGS2",
    "US_PCE": "PCE",
    "US_RETAIL_SALES": "RSAFS",
}


class MacroProvider:
    """Makro veri sağlayıcısı — resmi kaynaklar (async)."""

    def __init__(self) -> None:
        """MacroProvider örneği oluşturur."""
        self._client = get_client("macro", timeout=DEFAULT_MACRO_TIMEOUT, max_retries=DEFAULT_MACRO_MAX_RETRIES)
        self._tcmb_client = get_client("tcmb", timeout=DEFAULT_TCMB_TIMEOUT, max_retries=DEFAULT_MACRO_MAX_RETRIES)
        self._cache: dict[str, Any] = {}
        self._cache_ttl = DEFAULT_MACRO_CACHE_TTL
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=DEFAULT_MACRO_MAX_WORKERS)

    def __repr__(self) -> str:
        """MacroProvider string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return (
            f"MacroProvider(yahoo={len(DEFAULT_YAHOO_SYMBOLS)}, "
            f"tcmb={len(DEFAULT_TCMB_SERIES)}, fred={len(DEFAULT_FRED_SERIES)})"
        )

    async def fetch_yahoo_macro(self) -> dict[str, Any]:
        """Yahoo Finance makro verilerini çeker (async).

        Returns:
            {sembol_adı: veri_sözlüğü} yapısı.
        """
        loop = asyncio.get_event_loop()

        async def _fetch_one(name: str, symbol: str) -> tuple[str, dict[str, Any]]:
            """Tek bir Yahoo sembolü için veri çeker.

            Args:
                name: Sembol adı (örn. USDTRY).
                symbol: Yahoo Finance sembolü.

            Returns:
                (sembol_adı, veri_sözlüğü) demeti.
            """
            try:
                def _get() -> dict[str, Any]:
                    """Yahoo Finance Ticker bilgisini çeker.

                    Returns:
                        Fiyat ve değişim bilgisi sözlüğü.
                    """
                    t = yf.Ticker(symbol)
                    info = t.info
                    return {
                        "price": info.get("regularMarketPrice", 0),
                        "change_pct": info.get("regularMarketChangePercent", 0),
                        "source": "yahoo",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                result = await asyncio.wait_for(
                    loop.run_in_executor(self._executor, _get),
                    timeout=DEFAULT_YAHOO_FETCH_TIMEOUT,
                )
                return name, result
            except Exception as e:
                logger.warning("Yahoo macro fetch failed", symbol=name, error=str(e))
                return name, {"price": None, "change_pct": None, "source": "yahoo", "error": str(e)}

        tasks = [_fetch_one(name, sym) for name, sym in DEFAULT_YAHOO_SYMBOLS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[str, Any] = {}
        for item in results:
            if isinstance(item, Exception):
                continue
            name, data = item
            output[name] = data

        logger.info("Yahoo macro data fetched", count=len(output))
        return output

    async def fetch_tcmb_macro(self, api_key: str | None = None) -> dict[str, Any]:
        """TCMB EVDS makro verilerini çeker (async, detaylı).

        Args:
            api_key: TCMB EVDS API anahtarı.

        Returns:
            {seri_adı: veri_sözlüğü} yapısı.
        """
        if not api_key:
            logger.warning("TCMB EVDS API key not configured")
            return {}

        results: dict[str, Any] = {}
        end_date = datetime.now(UTC).strftime("%d-%m-%Y")
        start_date = (datetime.now(UTC) - timedelta(days=DEFAULT_HISTORY_DAYS)).strftime("%d-%m-%Y")

        async def _fetch_series(name: str, series_code: str) -> tuple[str, dict[str, Any]]:
            """Tek bir TCMB EVDS serisi için veri çeker.

            Args:
                name: Seri adı.
                series_code: EVDS seri kodu.

            Returns:
                (seri_adı, veri_sözlüğü) demeti.
            """
            try:
                url = (
                    f"https://evds2.tcmb.gov.tr/service/evds/series={series_code}"
                    f"&startDate={start_date}&endDate={end_date}&type=json&key={api_key}"
                )
                data = await self._tcmb_client.get_json(url)
                if data and isinstance(data, dict):
                    items = data.get("items", [])
                    if items:
                        latest = items[-1]
                        return name, {
                            "value": latest.get("value"),
                            "date": latest.get("date", ""),
                            "series": series_code,
                            "source": "tcmb",
                            "history": [
                                {"value": i.get("value"), "date": i.get("date")}
                                for i in items[-DEFAULT_HISTORY_OBSERVATIONS:]
                            ],
                        }
                return name, {"value": None, "date": None, "series": series_code, "source": "tcmb"}
            except Exception as e:
                logger.warning("TCMB fetch failed", series=name, error=str(e))
                return name, {"value": None, "date": None, "series": series_code, "source": "tcmb", "error": str(e)}

        tasks = [_fetch_series(name, code) for name, code in DEFAULT_TCMB_SERIES.items()]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for item in results_list:
            if isinstance(item, Exception):
                continue
            name, data = item
            results[name] = data

        logger.info("TCMB macro data fetched", count=len(results))
        return results

    async def fetch_fred_data(self, api_key: str | None = None) -> dict[str, Any]:
        """FRED makro verilerini çeker (async).

        Args:
            api_key: FRED API anahtarı.

        Returns:
            {seri_adı: veri_sözlüğü} yapısı.
        """
        if not api_key:
            logger.warning("FRED API key not configured")
            return {}

        results: dict[str, Any] = {}

        async def _fetch_series(name: str, series_id: str) -> tuple[str, dict[str, Any]]:
            """Tek bir FRED serisi için veri çeker.

            Args:
                name: Seri adı.
                series_id: FRED seri kodu.

            Returns:
                (seri_adı, veri_sözlüğü) demeti.
            """
            try:
                url = "https://api.stlouisfed.org/fred/series/observations"
                params = {
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": DEFAULT_HISTORY_OBSERVATIONS,
                }
                data = await self._client.get_json(url, params=params)
                if data:
                    observations = data.get("observations", [])
                    if observations:
                        latest = observations[0]
                        try:
                            val = float(latest.get("value", 0))
                        except (ValueError, TypeError):
                            val = None
                        history: list[dict[str, Any]] = []
                        for o in observations[:DEFAULT_HISTORY_OBSERVATIONS]:
                            try:
                                h_val = float(o.get("value", 0))
                            except (ValueError, TypeError):
                                h_val = None
                            history.append({"value": h_val, "date": o.get("date")})
                        return name, {
                            "value": val,
                            "date": latest.get("date", ""),
                            "source": "fred",
                            "history": history,
                        }
                return name, {"value": None, "source": "fred"}
            except Exception as e:
                logger.warning("FRED fetch failed", series=name, error=str(e))
                return name, {"value": None, "source": "fred", "error": str(e)}

        tasks = [_fetch_series(name, sid) for name, sid in DEFAULT_FRED_SERIES.items()]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for item in results_list:
            if isinstance(item, Exception):
                continue
            name, data = item
            results[name] = data

        logger.info("FRED data fetched", count=len(results))
        return results

    async def fetch_ecb_data(self) -> dict[str, Any]:
        """ECB makro verilerini çeker (async).

        Returns:
            ECB veri sözlüğü.
        """
        results: dict[str, Any] = {}
        try:
            url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
            params = {"lastNObservations": DEFAULT_HISTORY_OBSERVATIONS, "format": "jsondata"}
            data = await self._client.get_json(url, params=params)
            if data:
                datasets = data.get("dataSets", [{}])
                if datasets:
                    series = datasets[0].get("series", {})
                    obs = series.get("0:0:0:0:0", {}).get("observations", {})
                    if obs:
                        latest_key = sorted(obs.keys())[-1]
                        results["EURUSD"] = {
                            "value": obs[latest_key][0] if obs[latest_key] else None,
                            "source": "ecb",
                        }
        except Exception as e:
            logger.warning("ECB fetch failed", error=str(e))

        return results

    async def fetch_bist_macro_indicators(self) -> dict[str, Any]:
        """BIST'e özgü makro göstergeleri hesaplar (async).

        - BIST 100 volatilite (VIX proxy)
        - USD/TRY trendi (son 5 gün)
        - Altın/USD trendi
        - Petrol fiyatı
        - Tahvil faizi (US 10Y)

        Returns:
            BIST makro göstergeleri sözlüğü.
        """
        yahoo = await self.fetch_yahoo_macro()

        indicators: dict[str, Any] = {
            "usd_try": yahoo.get("USDTRY", {}),
            "eur_try": yahoo.get("EURTRY", {}),
            "gold": yahoo.get("GOLD", {}),
            "oil_brent": yahoo.get("BRENT", {}),
            "vix": yahoo.get("VIX", {}),
            "us_10y": yahoo.get("US10Y", {}),
            "sp500": yahoo.get("SP500", {}),
            "nasdaq": yahoo.get("NASDAQ", {}),
            "dxy": yahoo.get("DXY", {}),
            "btc": yahoo.get("BTC", {}),
            "dax": yahoo.get("DAX", {}),
            "ftse": yahoo.get("FTSE", {}),
            "nikkei": yahoo.get("NIKKEI", {}),
        }

        # Risk appetite hesapla
        vix = indicators.get("vix", {}).get("price", 0)
        if vix:
            if vix < DEFAULT_VIX_LOW:
                indicators["risk_appetite"] = "HIGH"
            elif vix < DEFAULT_VIX_HIGH:
                indicators["risk_appetite"] = "MODERATE"
            else:
                indicators["risk_appetite"] = "LOW"

        # Dolar gücü
        dxy = indicators.get("dxy", {}).get("price", 0)
        if dxy:
            if dxy > DEFAULT_DXY_STRONG:
                indicators["dollar_strength"] = "STRONG"
            elif dxy > DEFAULT_DXY_MODERATE:
                indicators["dollar_strength"] = "MODERATE"
            else:
                indicators["dollar_strength"] = "WEAK"

        indicators["timestamp"] = datetime.now(UTC).isoformat()
        indicators["source"] = "composite"

        logger.info(
            "BIST macro indicators computed",
            risk_appetite=indicators.get("risk_appetite"),
            dollar_strength=indicators.get("dollar_strength"),
        )

        return indicators

    async def fetch_all(self, tcmb_api_key: str | None = None, fred_api_key: str | None = None) -> dict[str, Any]:
        """Tüm makro verileri çeker (async, paralel).

        Args:
            tcmb_api_key: TCMB EVDS API anahtarı.
            fred_api_key: FRED API anahtarı.

        Returns:
            Tüm kaynaklardan birleştirilmiş makro veri sözlüğü.
        """
        tasks = [
            self.fetch_yahoo_macro(),
            self.fetch_tcmb_macro(tcmb_api_key),
            self.fetch_fred_data(fred_api_key),
            self.fetch_ecb_data(),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[str, Any] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Macro fetch task failed", error=str(result))
                continue
            if isinstance(result, dict):
                output.update(result)

        logger.info("All macro data fetched", sources=len(output))
        return output


# Singleton
macro_provider = MacroProvider()


__all__ = ["MacroProvider", "macro_provider"]
