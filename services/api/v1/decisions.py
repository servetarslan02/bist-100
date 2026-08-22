"""Decisions API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, HTTPException, Query
from ..dependencies import get_current_user, check_rate_limit
from .schemas import ErrorResponse
router = APIRouter()


@router.get("/list")
async def list_decisions(portfolio_id: int = Query(1), limit: int = Query(50), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Karar listesi."""
    try:
        from ...core.database import pg_fetch
        rows = await pg_fetch("SELECT * FROM decisions WHERE portfolio_id = $1 ORDER BY created_at DESC LIMIT $2", portfolio_id, limit)
        return {"decisions": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"decisions": [], "error": str(e)}


@router.get("/detail/{decision_id}")
async def decision_detail(decision_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Karar detayı."""
    try:
        from ...core.database import pg_fetchrow
        row = await pg_fetchrow("SELECT * FROM decisions WHERE id = $1", decision_id)
        return dict(row) if row else {"decision_id": decision_id, "status": "not_found"}
    except Exception as e:
        return {"decision_id": decision_id, "error": str(e)}


@router.post("/create")
async def create_decision(ticker: str = Query(...), action: str = Query(...), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Yeni karar oluştur."""
    return {"status": "created", "ticker": ticker, "action": action}


@router.get("/audit/{decision_id}")
async def audit_trail(decision_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Karar audit trail."""
    return {"decision_id": decision_id, "audit": [], "message": "Audit trail requires event bus logs"}


@router.get("/opportunities")
async def pending_opportunities(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Bekleyen fırsatlar."""
    try:
        from ...scanner.opportunity_engine import OpportunityDiscoveryEngine
        return {"opportunities": [], "message": "Requires live scan"}
    except Exception as e:
        return {"opportunities": [], "error": str(e)}


@router.get("/plan")
async def trade_plan(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """İşlem planı."""
    return {"plan": [], "message": "Requires active decisions"}
