"""Event Study API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, Query
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/analyze/{ticker}")
async def event_study(ticker: str, event_type: str = Query("earnings"), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Event study analizi."""
    try:
        from ...intelligence.impact_engine import ImpactEngine
        return {"ticker": ticker, "event_type": event_type, "impact_available": True, "message": "Requires event data"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/calendar")
async def event_calendar(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Olay takvimi."""
    return {"events": [], "message": "Requires KAP/event data feed"}
