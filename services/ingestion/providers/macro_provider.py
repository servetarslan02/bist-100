"""
ALPHA BIST - Macro Data Provider

Kaynaklar: FRED, ECB, TCMB, Yahoo Finance
Kullanım: Dünya piyasaları, makro veriler
"""

import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class MacroProvider:
    """Makro veri sağlayıcısı — resmi kaynaklar."""

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
    }

    # FRED serisi (Federal Reserve Economic Data)
    FRED_SERIES = {
        "US_CPI": "CPIAUCSL",
        "US_UNEMPLOYMENT": "UNRATE",
        "US_GDP": "GDP",
        "US_FED_FUNDS": "FEDFUNDS",
        "US_10Y_YIELD": "DGS10",
        "US_2Y_YIELD": "DGS2",
    }

    def __init__(self):
        self.session = requests.Session()

    def fetch_yahoo_macro(self) -> Dict[str, Any]:
        """Yahoo Finance makro verileri."""
        import yfinance as yf

        results = {}
        for name, symbol in self.YAHOO_SYMBOLS.items():
            try:
                t = yf.Ticker(symbol)
                info = t.info
                results[name] = {
                    "price": info.get("regularMarketPrice", 0),
                    "change_pct": info.get("regularMarketChangePercent", 0),
                    "source": "yahoo",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            except Exception as e:
                logger.debug("Yahoo macro fetch failed", symbol=name, error=str(e))

        return results

    def fetch_fred_data(self, api_key: Optional[str] = None) -> Dict[str, Any]:
        """FRED makro verileri."""
        if not api_key:
            logger.debug("FRED API key not configured")
            return {}

        results = {}
        for name, series in self.FRED_SERIES.items():
            try:
                url = f"https://api.stlouisfed.org/fred/series/observations"
                params = {
                    "series_id": series,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 5,
                }
                resp = self.session.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    observations = data.get("observations", [])
                    if observations:
                        latest = observations[0]
                        results[name] = {
                            "value": float(latest.get("value", 0)),
                            "date": latest.get("date", ""),
                            "source": "fred",
                        }
            except Exception as e:
                logger.debug("FRED fetch failed", series=name, error=str(e))

        return results

    def fetch_ecb_data(self) -> Dict[str, Any]:
        """ECB makro verileri."""
        results = {}

        try:
            # ECB Euro Exchange Rates
            url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
            params = {"lastNObservations": 1, "format": "jsondata"}
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results["EURUSD"] = {
                    "value": data.get("dataSets", [{}])[0].get("series", {}).get("0:0:0:0:0", {}).get("observations", {}).get("0", [{}])[0],
                    "source": "ecb",
                }
        except Exception as e:
            logger.debug("ECB fetch failed", error=str(e))

        return results

    def fetch_all(self) -> Dict[str, Any]:
        """Tüm makro verileri çek."""
        results = {}

        # Yahoo Finance
        yahoo = self.fetch_yahoo_macro()
        results.update(yahoo)

        # FRED (opsiyonel)
        from ..core.config import settings
        if hasattr(settings, 'fred_api_key') and settings.fred_api_key:
            fred = self.fetch_fred_data(settings.fred_api_key)
            results.update(fred)

        logger.info("Macro data fetched", sources=len(results))
        return results


# Singleton
macro_provider = MacroProvider()
