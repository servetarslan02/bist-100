"""
ALPHA BIST — API v2 Yönlendirici & Uç Noktalar (FastAPI APIRouter)

Yeni nesil REST API v2:
  - Anlık canlı piyasa ve derinlik akışı (/api/v2/live/depth/{ticker})
  - Model sinyalleri ve faktör skorları (/api/v2/signals/top)
  - Makro rejim ve piyasa stresi (/api/v2/market/regime)
  - VİOP arbitraj ve taşıma maliyeti tarayıcısı (/api/v2/viop/arbitrage)
  - Sanal portföy performans raporları (/api/v2/portfolio/summary)
  - GraphQL köprüsü (/api/v2/graphql)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.api.graphql_schema import bist_graphql

router = APIRouter(prefix="/v2", tags=["API v2 — Enterprise"])


class GraphQLRequest(BaseModel):
    """GraphQL istek gövdesi."""

    query: str = Field(..., description="GraphQL sorgu metni")
    variables: dict[str, Any] | None = Field(default=None, description="Opsiyonel sorgu değişkenleri")


class OrderSimulationRequest(BaseModel):
    """Sanal emir simülasyon isteği."""

    ticker: str = Field(..., description="BIST hisse kodu")
    side: str = Field(..., description="BUY veya SELL")
    quantity: int = Field(..., gt=0, description="Emir lot adedi")
    limit_price: float | None = Field(default=None, description="Opsiyonel limit fiyat")


@router.get("/health", summary="API v2 Sağlık Kontrolü")
async def get_health_v2() -> dict[str, str]:
    """API v2 durum kontrolü."""
    return {"status": "healthy", "version": "2.0.0"}


@router.get("/market/regime", summary="Aktif Piyasa Rejimi & Stres")
async def get_market_regime_v2() -> dict[str, Any]:
    """Aktif makro rejim ve stres endeksi."""
    regime = bist_graphql.resolve_market_regime()
    return {
        "regime": regime.regime_name,
        "probability": regime.probability,
        "stress_index": regime.stress_index,
        "timestamp": regime.timestamp,
    }


@router.get("/signals/top", summary="En Yüksek Sinyalli Hisseler")
async def get_top_signals_v2(
    top_n: int = Query(default=10, ge=1, le=50, description="Döndürülecek hisse adedi"),
) -> list[dict[str, Any]]:
    """En iyi alım/satım sinyallerini döndürür."""
    signals = bist_graphql.resolve_signals(top_n=top_n)
    return [
        {
            "ticker": s.ticker,
            "action": s.action,
            "score": s.conviction_score,
            "confidence": s.confidence,
            "horizon_days": s.horizon_days,
        }
        for s in signals
    ]


@router.get("/portfolio/summary", summary="Portföy Performans Özeti")
async def get_portfolio_summary_v2(
    portfolio_id: str = Query(default="default", description="Portföy kimliği"),
) -> dict[str, Any]:
    """Sanal portföy büyüklüğü, PnL ve risk metrikleri."""
    port = bist_graphql.resolve_portfolio(portfolio_id)
    return {
        "portfolio_id": port.portfolio_id,
        "total_equity": port.total_equity,
        "cash_balance": port.cash_balance,
        "unrealized_pnl": port.unrealized_pnl,
        "sharpe_ratio": port.sharpe_ratio,
        "max_drawdown_pct": port.max_drawdown_pct,
        "position_count": len(port.positions),
    }


@router.post("/graphql", summary="GraphQL Uç Noktası")
async def handle_graphql(req: GraphQLRequest) -> dict[str, Any]:
    """BIST GraphQL sorgularını çözümler."""
    try:
        return bist_graphql.execute_query(req.query, req.variables)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


__all__ = ["router"]
