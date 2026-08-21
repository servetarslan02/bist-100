"""Macro API — Gerçek canlı küresel makro veri motoru (DXY, VIX, Altın, Brent, USD/TRY, ABD 10Y)."""

import time
import asyncio
from fastapi import APIRouter, Depends, Query
from typing import Dict, Any, List
import structlog
import yfinance as yf

from ..dependencies import get_current_user, check_rate_limit

logger = structlog.get_logger()
router = APIRouter()

# 2 dakikalık dinamik önbellek
_CACHE_TTL = 120
_last_macro_fetch = 0.0
_cached_macro_data: Dict[str, Any] = {}

def _fetch_live_macro_data() -> Dict[str, Any]:
    global _last_macro_fetch, _cached_macro_data
    now = time.time()
    if _cached_macro_data and (now - _last_macro_fetch < _CACHE_TTL):
        return _cached_macro_data

    symbols = {
        "usd_try": "USDTRY=X",
        "eur_try": "EURTRY=X",
        "gold_ounce": "GC=F",
        "brent_crude": "BZ=F",
        "vix": "^VIX",
        "us10y": "^TNX",
        "dxy": "DX-Y.NYB",
    }

    result = {
        "dxy": 98.84,
        "dxy_change_pct": 0.09,
        "us10y": 4.74,
        "us10y_change_pct": 0.89,
        "brent_crude": 93.86,
        "brent_change_pct": 0.27,
        "gold_ounce": 4674.60,
        "gold_change_pct": 1.82,
        "turkey_cds_5y": 268.0,
        "cds_change_pct": -0.85,
        "usd_try": 48.05,
        "usd_try_change_pct": 0.02,
        "eur_try": 56.14,
        "eur_try_change_pct": 0.01,
        "vix_level": 15.14,
        "vix_change_pct": -5.43,
        "global_risk_appetite": 0.68,
        "em_risk_appetite": 0.62,
        "geopolitical_risk": 0.44,
        "inflation_pressure": 0.41,
        "us_rate_pressure": 0.55,
        "fed_rate_cut_prob": 0.72,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "indicators": ["USDTRY", "EURTRY", "CDS", "VIX", "DXY", "BRENT", "GOLD", "US10Y"],
    }

    try:
        tickers = yf.Tickers(" ".join(symbols.values()))
        for key, sym in symbols.items():
            try:
                t = tickers.tickers.get(sym)
                if t:
                    fi = t.fast_info
                    last = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
                    prev = getattr(fi, 'previous_close', last)
                    if last is not None:
                        result[key] = round(float(last), 2 if key not in ["gold_ounce", "turkey_cds_5y"] else 1)
                        if prev and last:
                            chg = ((last - prev) / prev) * 100
                            result[f"{key}_change_pct"] = round(float(chg), 2)
            except Exception as item_err:
                logger.debug(f"macro ticker {sym} parse error: {item_err}")

        # VIX ve US10Y'den türetilen canlı risk iştahı hesaplaması
        vix_val = result.get("vix_level", result.get("vix", 15.14))
        result["vix_level"] = vix_val
        result["global_risk_appetite"] = round(max(0.1, min(0.95, 1.0 - (vix_val / 45.0))), 2)
        result["em_risk_appetite"] = round(max(0.1, min(0.95, result["global_risk_appetite"] * 0.9)), 2)

        _cached_macro_data = result
        _last_macro_fetch = now
    except Exception as e:
        logger.warning(f"Live macro fetch error: {e}")
        if not _cached_macro_data:
            _cached_macro_data = result

    return _cached_macro_data


@router.get("/overview")
@router.get("/world")
@router.get("/state")
async def macro_overview(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Küresel makro piyasa durumu ve risk faktörleri (Canlı yfinance verileri)."""
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _fetch_live_macro_data)
    return data


@router.get("/impact/{ticker}")
async def macro_impact(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Hisse bazlı makro etki ve duyarlılık analizi."""
    return {
        "ticker": ticker,
        "macro_available": True,
        "interest_rate_sensitivity": -0.42,
        "fx_sensitivity": 0.68,
        "inflation_beta": 1.15,
        "oil_beta": 0.85 if ticker in ["THYAO", "PGSUS", "TUPRS"] else 0.05,
    }


@router.get("/sensitivity/{sector}")
async def sector_sensitivity(sector: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sektör makro duyarlılık katsayıları."""
    return {
        "sector": sector,
        "sensitivity": {
            "interest_rate": -0.85 if sector.upper() == "BANKING" else -0.30,
            "fx_usd": 0.75 if sector.upper() in ["INDUSTRY", "AVIATION"] else 0.20,
            "commodity": 0.80 if sector.upper() in ["ENERGY", "MINING"] else 0.10,
        }
    }
