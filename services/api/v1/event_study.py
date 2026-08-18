"""Event Study API — 4 endpoints."""
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.post("/analyze")
async def analyze(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"status": "started"}

@router.get("/{ticker}")
async def ticker_events(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"ticker": ticker, "events": []}

@router.get("/impact")
async def impact(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"impacts": []}

@router.get("/macro")
async def macro_events(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"macro_events": []}
