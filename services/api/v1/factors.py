"""Factors API — 4 endpoints."""
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("/{ticker}")
async def ticker_factors(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"ticker": ticker, "factors": {}}

@router.get("/ranking")
async def ranking(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"ranking": []}

@router.get("/performance")
async def performance(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"performance": {}}

@router.get("/anomalies")
async def anomalies(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"anomalies": []}
