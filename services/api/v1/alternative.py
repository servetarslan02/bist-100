"""Alternative Data API — 4 endpoints."""
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()

@router.get("/{ticker}")
async def ticker_alternative(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"ticker": ticker, "features": {}}

@router.get("/sources")
async def sources(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    from ...alternative.base import adapter_registry
    return {"sources": adapter_registry.list_adapters()}

@router.get("/features")
async def feature_names(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    from ...alternative.feature_engine import alt_feature_engine
    return {"features": alt_feature_engine.get_feature_names()}

@router.get("/social")
async def social(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    return {"social": {}}
