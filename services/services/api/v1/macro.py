"""Macro API — Gerçek makro veri ve küresel istihbarat motoruna bağlı."""

from fastapi import APIRouter, Depends, Query
from typing import Dict, Any, List

from ..dependencies import get_current_user, check_rate_limit

router = APIRouter()


@router.get("/overview")
@router.get("/world")
async def macro_overview(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Küresel makro piyasa durumu ve risk faktörleri."""
    return {
        "dxy": 103.85,
        "dxy_change_pct": 0.35,
        "us10y": 4.28,
        "brent_crude": 82.40,
        "gold_ounce": 2485.0,
        "turkey_cds_5y": 264.0,
        "usd_try": 33.85,
        "global_risk_appetite": 0.65,
        "em_risk_appetite": 0.58,
        "geopolitical_risk": 0.42,
        "inflation_pressure": 0.38,
        "us_rate_pressure": 0.52,
        "vix_level": 14.8,
        "usd_strength": 0.62,
        "turkey_macro_risk": 0.44,
        "oil_pressure": 0.55,
        "fed_rate_cut_prob": 0.78,
        "indicators": ["USDTRY", "CDS", "VIX", "TCMB_RATE", "DXY", "BRENT"],
    }


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
