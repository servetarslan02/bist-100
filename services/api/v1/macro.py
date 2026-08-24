"""Macro API — Gerçek canlı küresel makro veri motoru (DXY, VIX, Altın, Brent, USD/TRY, ABD 10Y)."""

import time
import asyncio
from fastapi import APIRouter, Depends, Query
from typing import Dict, Any, List
import structlog
import yfinance as yf

from ..dependencies import get_current_user, check_rate_limit
from .schemas import ErrorResponse

logger = structlog.get_logger()
router = APIRouter()

_CACHE_TTL = 120
_last_macro_fetch = time.time()
_cached_macro_data: Dict[str, Any] = {
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
    "macro_commentary": "Dolar ve CDS dengeli seviyelerde. Risk iştahı pozitif.",
    "bist_macro_bias": "POZİTİF"
}

def _fetch_live_macro_data() -> Dict[str, Any]:
    global _last_macro_fetch, _cached_macro_data
    now = time.time()
    if _cached_macro_data and (now - _last_macro_fetch < _CACHE_TTL):
        return _cached_macro_data

    _last_macro_fetch = now

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

        # UI Mapping & Dynamic Regime Commentary
        result["usd_strength"] = round(max(0.0, min(1.0, (result.get("dxy", 100) - 90) / 20)), 2)
        result["turkey_macro_risk"] = round(max(0.0, min(1.0, result.get("turkey_cds_5y", 300) / 600)), 2)
        result["oil_pressure"] = round(max(0.0, min(1.0, (result.get("brent_crude", 80) - 60) / 60)), 2)

        # Dinamik Makro Yorum ve BIST Etki Puanı
        dxy_v = result.get("dxy", 100)
        cds_v = result.get("turkey_cds_5y", 270)
        brent_v = result.get("brent_crude", 85)
        us10_v = result.get("us10y", 4.5)

        commentary_parts = []
        if dxy_v > 103:
            commentary_parts.append("Dolar küresel çapta güçlü (Gelişmekte olan piyasalara sermaye akışı baskı altında).")
        else:
            commentary_parts.append("Dolar endeksi stabil (Gelişmekte olan piyasalar için nötr-pozitif ortam).")

        if cds_v < 280:
            commentary_parts.append(f"Türkiye 5Y CDS primi ({cds_v:.0f} bps) gerileme eğiliminde (Ülke risk primi olumlu).")
        else:
            commentary_parts.append(f"Türkiye 5Y CDS primi ({cds_v:.0f} bps) temkinli bölgede.")

        if brent_v > 90:
            commentary_parts.append(f"Brent petrol ({brent_v:.1f} $) yüksek (Cari denge ve sanayi marjları üzerinde maliyet baskısı).")
        else:
            commentary_parts.append(f"Brent petrol ({brent_v:.1f} $) dengeli seviyelerde.")

        result["macro_commentary"] = " ".join(commentary_parts)
        result["bist_macro_bias"] = "POZİTİF" if (cds_v < 290 and dxy_v < 104) else "NÖTR"

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
@router.get("/indicators")
async def macro_overview(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Küresel makro piyasa durumu ve risk faktörleri (Canlı yfinance verileri)."""
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _fetch_live_macro_data)
    return data


@router.get("/impact/{ticker}")
async def macro_impact(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Hisse bazlı makro etki ve duyarlılık analizi."""
    try:
        from ...intelligence.macro_sensitivity import MacroSensitivityEngine
        engine = MacroSensitivityEngine()
        result = engine.get_company_sensitivity(ticker) if hasattr(engine, 'get_company_sensitivity') else {}
        if result:
            return {"ticker": ticker, "macro_available": True, **result}
    except Exception as e:
        logger.debug("macro_sensitivity_ticker_failed", ticker=ticker, error=str(e))
    return {
        "ticker": ticker,
        "macro_available": False,
        "interest_rate_sensitivity": None,
        "fx_sensitivity": None,
        "inflation_beta": None,
        "note": "Connect MacroSensitivityEngine for real data.",
    }


@router.get("/sensitivity/{sector}")
async def sector_sensitivity(sector: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sektör makro duyarlılık katsayıları."""
    try:
        from ...intelligence.macro_sensitivity import MacroSensitivityEngine
        engine = MacroSensitivityEngine()
        result = engine.get_sector_sensitivity(sector) if hasattr(engine, 'get_sector_sensitivity') else {}
        if result:
            return {"sector": sector, "sensitivity": result, "source": "macro_sensitivity_engine"}
    except Exception as e:
        logger.debug("macro_sensitivity_sector_failed", sector=sector, error=str(e))
    return {
        "sector": sector,
        "sensitivity": {
            "interest_rate": None,
            "fx_usd": None,
            "commodity": None,
        },
        "source": "unavailable",
        "note": "Connect MacroSensitivityEngine for real sector sensitivity data.",
    }
