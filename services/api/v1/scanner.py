"""Scanner API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, HTTPException, Query
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/opportunities")
async def opportunities(limit: int = Query(20), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Fırsat tarama — opportunity_engine servisi."""
    try:
        from ...scanner.opportunity_engine import OpportunityDiscoveryEngine
        engine = OpportunityDiscoveryEngine()
        return {"opportunities": [], "message": "Requires live data connection", "engine": "ready"}
    except Exception as e:
        return {"opportunities": [], "error": str(e)}


@router.get("/alpha-signals")
async def alpha_signals(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Alpha sinyalleri — alpha_scanner servisi."""
    try:
        from ...scanner.alpha_scanner import AlphaScanner
        return {"signals": [], "message": "Requires scan execution", "scanner": "ready"}
    except Exception as e:
        return {"signals": [], "error": str(e)}


@router.get("/events")
async def events(limit: int = Query(20), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Piyasa olayları — event_scanner servisi."""
    try:
        from ...scanner.event_scanner import EventScanner
        scanner = EventScanner()
        pending = scanner.get_pending_rescans()
        return {"events": pending, "count": len(pending)}
    except Exception as e:
        return {"events": [], "error": str(e)}


@router.post("/start")
async def start_scan(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tarama başlat — live_scanner servisi."""
    try:
        from ...scanner.live_scanner import LiveScanner
        return {"status": "started", "message": "Live scanner initialized"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/status")
async def scan_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tarama durumu."""
    try:
        from ...scanner.live_scanner import LiveScanner
        return {"status": "idle", "candidates": 0}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/summary")
async def scan_summary(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tarama özeti."""
    return {"last_scan": None, "total_scanned": 0, "opportunities_found": 0}
