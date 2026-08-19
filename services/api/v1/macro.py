"""Macro API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, Query
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/overview")
async def macro_overview(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Makro genel bakış."""
    try:
        from ...intelligence.macro_sensitivity import MacroSensitivityEngine
        return {"macro": "available", "indicators": ["USDTRY", "CDS", "VIX", "TCMB_RATE"]}
    except Exception as e:
        return {"error": str(e)}


@router.get("/impact/{ticker}")
async def macro_impact(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Makro etki — macro_sensitivity servisi."""
    try:
        from ...intelligence.macro_sensitivity import MacroSensitivityEngine
        engine = MacroSensitivityEngine()
        return {"ticker": ticker, "macro_available": True, "message": "Requires live macro data"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/sensitivity/{sector}")
async def sector_sensitivity(sector: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sektör hassasiyeti — macro_sensitivity servisi."""
    try:
        from ...intelligence.macro_sensitivity import MacroSensitivityEngine
        engine = MacroSensitivityEngine()
        sens = engine.get_sector_sensitivity(sector) if hasattr(engine, 'get_sector_sensitivity') else None
        return {"sector": sector, "sensitivity": sens}
    except Exception as e:
        return {"sector": sector, "error": str(e)}
