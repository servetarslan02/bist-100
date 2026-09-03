"""Kararlar API — Gerçek servislere bağlı uç noktalar."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list")
async def list_decisions(
    portfolio_id: int = Query(1),
    limit: int = Query(50),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Karar listesini döndürür.

    Args:
        portfolio_id: Portföy tanımlayıcısı.
        limit: Maksimum sonuç sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Karar listesi ve sayısı.
    """
    try:
        from ...core.database import pg_fetch

        rows = await pg_fetch(
            "SELECT * FROM decisions WHERE portfolio_id = $1 ORDER BY created_at DESC LIMIT $2",
            portfolio_id,
            limit,
        )
        return {"decisions": [dict(r) for r in rows], "count": len(rows)}
    except Exception as exc:
        logger.error("karar_listesi_hatasi: portfolio_id=%s, hata=%s", portfolio_id, exc)
        return {"decisions": [], "error": str(exc)}


@router.get("/detail/{decision_id}")
async def decision_detail(
    decision_id: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Belirli bir kararın detayını döndürür.

    Args:
        decision_id: Karar tanımlayıcısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Karar detayı veya bulunamadı bilgisi.
    """
    try:
        from ...core.database import pg_fetchrow

        row = await pg_fetchrow("SELECT * FROM decisions WHERE id = $1", decision_id)
        return dict(row) if row else {"decision_id": decision_id, "status": "not_found"}
    except Exception as exc:
        logger.error("karar_detay_hatasi: id=%s, hata=%s", decision_id, exc)
        return {"decision_id": decision_id, "error": str(exc)}


@router.post("/create")
async def create_decision(
    ticker: str = Query(...),
    action: str = Query(...),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Yeni bir yatırım kararı oluşturur ve veritabanına kaydeder.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        action: Karar türü (ör. BUY, SELL, HOLD).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Oluşturulan kararın durum bilgisi.

    Raises:
        HTTPException: Karar oluşturulamazsa 500 hatası döner.
    """
    try:
        from ...core.database import pg_fetchrow

        row = await pg_fetchrow(
            "INSERT INTO decisions (ticker, action, created_by) VALUES ($1, $2, $3) RETURNING id, created_at",
            ticker,
            action,
            user.user_id,
        )
        return {
            "status": "created",
            "decision_id": row["id"],
            "ticker": ticker,
            "action": action,
            "created_at": row["created_at"].isoformat() if row else None,
        }
    except Exception as exc:
        logger.error("karar_olusturma_hatasi: ticker=%s, action=%s, hata=%s", ticker, action, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Karar oluşturulamadı: {exc}",
        ) from exc


@router.get("/audit/{decision_id}")
async def audit_trail(
    decision_id: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Belirli bir kararın audit trail kayıtlarını döndürür.

    Args:
        decision_id: Karar tanımlayıcısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Audit trail kayıtları.
    """
    try:
        from ...core.database import pg_fetch

        rows = await pg_fetch(
            "SELECT * FROM audit_log WHERE entity_type = 'decision' AND entity_id = $1 ORDER BY created_at DESC",
            decision_id,
        )
        if rows:
            return {"decision_id": decision_id, "audit": [dict(r) for r in rows]}
        return {"decision_id": decision_id, "audit": [], "message": "Bu karar için audit kaydı bulunamadı."}
    except Exception as exc:
        logger.error("audit_trail_hatasi: decision_id=%s, hata=%s", decision_id, exc)
        return {"decision_id": decision_id, "audit": [], "error": str(exc)}


@router.get("/pending-opportunities")
async def pending_opportunities(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Phase 18 (AlphaEngine) tarafından üretilen en güncel fırsatları getirir.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Güncel fırsat listesi, hedef tarih ve rejim bilgisi.
    """
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
            return {
                "opportunities": [],
                "message": "Henüz gün sonu modeli (18:15) çalışmadı veya veri yok.",
            }

        row = rows[0]
        tickers = orjson.loads(row["tickers"]) if isinstance(row["tickers"], str) else row["tickers"]

        return {
            "opportunities": tickers,
            "target_date": row["target_date"].isoformat(),
            "generated_at": row["created_at"].isoformat(),
            "is_cash_regime": row["is_cash_regime"],
            "is_rebalance": row["is_rebalance"],
            "message": "Phase 18 AI Engine: Güncel Portföy (63-Day Hold Mode)",
        }
    except Exception as exc:
        logger.error("pending_opportunities_hatasi: hata=%s", exc)
        return {"opportunities": [], "error": str(exc)}


@router.get("/plan")
async def trade_plan(
    portfolio_id: int = Query(1),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Aktif kararlara dayalı işlem planını döndürür.

    Args:
        portfolio_id: Portföy tanımlayıcısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: İşlem planı listesi.
    """
    try:
        from ...core.database import pg_fetch

        rows = await pg_fetch(
            "SELECT * FROM decisions WHERE portfolio_id = $1 AND status = 'pending' ORDER BY created_at DESC",
            portfolio_id,
        )
        if rows:
            return {"plan": [dict(r) for r in rows], "count": len(rows)}
        return {"plan": [], "message": "Aktif karar bulunamadı."}
    except Exception as exc:
        logger.error("islem_plani_hatasi: portfolio_id=%s, hata=%s", portfolio_id, exc)
        return {"plan": [], "error": str(exc)}
