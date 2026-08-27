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


class MacroProvider:
    """Makro veri sağlayıcısı — resmi kaynaklar (async)."""

    # Yahoo Finance sembolleri
    YAHOO_SYMBOLS = {
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
    TCMB_SERIES = {
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
    FRED_SERIES = {
        "US_CPI": "CPIAUCSL",
        "US_UNEMPLOYMENT": "UNRATE",
        "US_GDP": "GDP",
        "US_FED_FUNDS": "FEDFUNDS",
        "US_10Y_YIELD": "DGS10",
        "US_2Y_YIELD": "DGS2",
        "US_PCE": "PCE",
        "US_RETAIL_SALES": "RSAFS",
    }

    def __init__(self):
        self._client = get_client("macro", timeout=20.0, max_retries=3)
        self._tcmb_client = get_client("tcmb", timeout=30.0, max_retries=3)
        self._cache: dict[str, Any] = {}
        self._cache_ttl = 300  # 5 dakika cache

    async def fetch_yahoo_macro(self) -> dict[str, Any]:
        """Yahoo Finance makro verileri (async)."""

        # Use thread pool for sync yfinance calls
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=6)

        async def _fetch_one(name: str, symbol: str) -> tuple:
            try:

                def _get():
                    t = yf.Ticker(symbol)
                    info = t.info
                    return {
                        "price": info.get("regularMarketPrice", 0),
                        "change_pct": info.get("regularMarketChangePercent", 0),
                        "source": "yahoo",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                result = await asyncio.wait_for(
                    loop.run_in_executor(executor, _get),
                    timeout=15,
                )
                return name, result
            except Exception as e:
                logger.debug("Yahoo macro fetch failed", symbol=name, error=str(e))
                return name, {"price": None, "change_pct": None, "source": "yahoo", "error": str(e)}

        tasks = [_fetch_one(name, sym) for name, sym in self.YAHOO_SYMBOLS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for item in results:
            if isinstance(item, Exception):
                continue
            name, data = item
            output[name] = data

        logger.info("Yahoo macro data fetched", count=len(output))
        return output

    async def fetch_tcmb_macro(self, api_key: str | None = None) -> dict[str, Any]:
        """TCMB EVDS makro verileri (async, detaylı)."""
        if not api_key:
            logger.debug("TCMB EVDS API key not configured")
            return {}

        results = {}
        end_date = datetime.now(UTC).strftime("%d-%m-%Y")
        start_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%d-%m-%Y")

        async def _fetch_series(name: str, series_code: str) -> tuple:
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
                                for i in items[-5:]  # Son 5 gözlem
                            ],
                        }
                return name, {"value": None, "date": None, "series": series_code, "source": "tcmb"}
            except Exception as e:
                logger.debug("TCMB fetch failed", series=name, error=str(e))
                return name, {"value": None, "date": None, "series": series_code, "source": "tcmb", "error": str(e)}

        tasks = [_fetch_series(name, code) for name, code in self.TCMB_SERIES.items()]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for item in results_list:
            if isinstance(item, Exception):
                continue
            name, data = item
            results[name] = data

        logger.info("TCMB macro data fetched", count=len(results))
        return results

    async def fetch_fred_data(self, api_key: str | None = None) -> dict[str, Any]:
        """FRED makro verileri (async)."""
        if not api_key:
            logger.debug("FRED API key not configured")
            return {}

        results = {}

        async def _fetch_series(name: str, series_id: str) -> tuple:
            try:
                url = "https://api.stlouisfed.org/fred/series/observations"
                params = {
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 5,
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
                        history = []
                        for o in observations[:5]:
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
                logger.debug("FRED fetch failed", series=name, error=str(e))
                return name, {"value": None, "source": "fred", "error": str(e)}

        tasks = [_fetch_series(name, sid) for name, sid in self.FRED_SERIES.items()]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for item in results_list:
            if isinstance(item, Exception):
                continue
            name, data = item
            results[name] = data

        logger.info("FRED data fetched", count=len(results))
        return results

    async def fetch_ecb_data(self) -> dict[str, Any]:
        """ECB makro verileri (async)."""
        results = {}
        try:
            url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
            params = {"lastNObservations": 5, "format": "jsondata"}
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
            logger.debug("ECB fetch failed", error=str(e))

        return results

    async def fetch_bist_macro_indicators(self) -> dict[str, Any]:
        """BIST'e özgü makro göstergeler (async).

        - BIST 100 volatilite (VIX proxy)
        - USD/TRY trendi (son 5 gün)
        - Altın/USD trendi
        - Petrol fiyatı
        - Tahvil faizi (US 10Y)
        """
        yahoo = await self.fetch_yahoo_macro()

        indicators = {
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
            if vix < 15:
                indicators["risk_appetite"] = "HIGH"
            elif vix < 25:
                indicators["risk_appetite"] = "MODERATE"
            else:
                indicators["risk_appetite"] = "LOW"

        # Dolar gücü
        dxy = indicators.get("dxy", {}).get("price", 0)
        if dxy:
            if dxy > 105:
                indicators["dollar_strength"] = "STRONG"
            elif dxy > 100:
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
        """Tüm makro verileri çek (async, paralel)."""
        tasks = [
            self.fetch_yahoo_macro(),
            self.fetch_tcmb_macro(tcmb_api_key),
            self.fetch_fred_data(fred_api_key),
            self.fetch_ecb_data(),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
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
