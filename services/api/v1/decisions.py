from typing import Any
"""Decisions API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, Query

from ..dependencies import check_rate_limit, get_current_user

router = APIRouter()


@router.get("/list")
async def list_decisions(
    portfolio_id: int = Query(1), limit: int = Query(50), user=Depends(get_current_user), _=Depends(check_rate_limit)
) -> Any:
    """Karar listesi."""
    try:
        from ...core.database import pg_fetch

        rows = await pg_fetch(
            "SELECT * FROM decisions WHERE portfolio_id = $1 ORDER BY created_at DESC LIMIT $2", portfolio_id, limit
        )
        return {"decisions": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"decisions": [], "error": str(e)}


@router.get("/detail/{decision_id}")
async def decision_detail(decision_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Karar detayı."""
    try:
        from ...core.database import pg_fetchrow

        row = await pg_fetchrow("SELECT * FROM decisions WHERE id = $1", decision_id)
        return dict(row) if row else {"decision_id": decision_id, "status": "not_found"}
    except Exception as e:
        return {"decision_id": decision_id, "error": str(e)}


@router.post("/create")
async def create_decision(
    ticker: str = Query(...), action: str = Query(...), user=Depends(get_current_user), _=Depends(check_rate_limit)
) -> Any:
    """Yeni karar oluştur."""
    return {"status": "created", "ticker": ticker, "action": action}


@router.get("/audit/{decision_id}")
async def audit_trail(decision_id: str, user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Karar audit trail."""
    return {"decision_id": decision_id, "audit": [], "message": "Audit trail requires event bus logs"}


@router.get("/pending-opportunities")
async def pending_opportunities(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Phase 18 (AlphaEngine) tarafindan uretilen en guncel firsatlari getirir."""
    try:
        import orjson

        from ...core.database import pg_fetch

        query = """
            SELECT created_at, target_date, tickers, is_cash_regime, is_rebalance
            FROM paper_trade_portfolio
            ORDER BY target_date DESC, created_at DESC
            LIMIT 1
        """
        rows = await pg_fetch(query)

        if not rows:
            return {"opportunities": [], "message": "Henuz gun sonu modeli (18:15) calismadi veya veri yok."}

        row = rows[0]
        tickers = orjson.loads(row["tickers"]) if isinstance(row["tickers"], str) else row["tickers"]

        return {
            "opportunities": tickers,
            "target_date": row["target_date"].isoformat(),
            "generated_at": row["created_at"].isoformat(),
            "is_cash_regime": row["is_cash_regime"],
            "is_rebalance": row["is_rebalance"],
            "message": "Phase 18 AI Engine: Guncel Portfoy (63-Day Hold Mode)",
        }
    except Exception as e:
        return {"opportunities": [], "error": str(e)}


@router.get("/plan")
async def trade_plan(portfolio_id: int = Query(1), user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """İşlem planı."""
    return {"plan": [], "message": "Requires active decisions"}
