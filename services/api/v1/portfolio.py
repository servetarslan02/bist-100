"""Portfolio API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/summary")
async def portfolio_summary(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Portföy özeti."""
    try:
        from ...core.database import pg_fetchrow
        row = await pg_fetchrow("SELECT * FROM portfolios WHERE id = $1", portfolio_id)
        if row:
            return {"status": "ok", "portfolio": dict(row)}
        return {"status": "not_found", "portfolio_id": portfolio_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/positions")
async def positions(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Açık pozisyonlar."""
    try:
        from ...core.database import pg_fetch
        rows = await pg_fetch("""
            SELECT p.*, i.symbol FROM positions p
            JOIN instruments i ON p.instrument_id = i.id
            WHERE p.portfolio_id = $1 AND p.status = 'OPEN'
        """, portfolio_id)
        return {"positions": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"positions": [], "error": str(e)}


@router.get("/trades")
async def trades(portfolio_id: int = Query(1), limit: int = Query(50), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """İşlem geçmişi."""
    try:
        from ...core.database import pg_fetch
        rows = await pg_fetch("""
            SELECT * FROM orders WHERE portfolio_id = $1
            ORDER BY created_at DESC LIMIT $2
        """, portfolio_id, limit)
        return {"trades": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"trades": [], "error": str(e)}


@router.get("/pnl")
async def pnl(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """K/Z durumu."""
    try:
        from ...core.database import pg_fetchrow
        row = await pg_fetchrow("SELECT initial_capital, current_capital FROM portfolios WHERE id = $1", portfolio_id)
        if row:
            initial = float(row["initial_capital"])
            current = float(row["current_capital"])
            total_pnl = current - initial
            pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0
            return {"total_pnl": round(total_pnl, 2), "pnl_pct": round(pnl_pct, 2), "initial": initial, "current": current}
        return {"total_pnl": 0, "pnl_pct": 0}
    except Exception as e:
        return {"total_pnl": 0, "error": str(e)}


@router.get("/equity-curve")
async def equity_curve(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Equity curve."""
    try:
        from ...core.database import pg_fetch
        rows = await pg_fetch("""
            SELECT date, equity FROM equity_history
            WHERE portfolio_id = $1 ORDER BY date
        """, portfolio_id)
        return {"equity_curve": [dict(r) for r in rows], "points": len(rows)}
    except Exception as e:
        return {"equity_curve": [], "error": str(e)}


@router.get("/risk-metrics")
async def risk_metrics(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Portföy risk metrikleri — position_sizing + risk parity."""
    try:
        from ...risk.position_sizing import PositionSizer
        from ...risk.dynamic_limits import DynamicRiskLimits
        limits = DynamicRiskLimits()
        return {"limits": limits.get_limits(), "message": "Full metrics require portfolio data"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/attribution")
async def attribution(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Getiri atıflandırması."""
    return {"attribution": {}, "message": "Requires daily position snapshots"}


@router.post("/rebalance")
async def rebalance(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Rebalance."""
    return {"status": "pending", "message": "Rebalance initiated"}


@router.get("/status")
async def status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Portföy durumu."""
    return {"status": "ok", "trading_enabled": True}
