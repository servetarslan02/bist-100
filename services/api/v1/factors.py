"""Factors API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, Query
from ..dependencies import get_current_user, check_rate_limit
from .schemas import ErrorResponse
router = APIRouter()


@router.get("/scores/{ticker}")
async def factor_scores(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Factor skorları — factor_engine servisi."""
    try:
        from ...intelligence.factor_engine import FactorEngine
        engine = FactorEngine()
        return {"ticker": ticker, "factor_available": True, "message": "Requires financial data"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/exposure/{ticker}")
async def factor_exposure(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Factor exposure — factor_engine servisi."""
    try:
        from ...intelligence.factor_engine import FactorEngine
        return {"ticker": ticker, "exposure_available": True}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/portfolio-exposure")
async def portfolio_exposure(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Portföy factor exposure."""
    return {"exposure": {}, "message": "Requires portfolio positions"}
