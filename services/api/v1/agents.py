"""
Ajanlar API v2.0 — Kurumsal Multi-Agent ve Pipeline Orkestrasyon Uç Noktaları.

Mevcut ve yeni yetenekler:
- /list: Sistemdeki tüm 9 uzman ajan rolünü listeler
- /status: Ajanların anlık çalışma ve sağlık durumunu döndürür
- /run: Tekil bir ajanı tetikler
- /pipeline/run: Çoklu uzman ajanı, çelişki dedektörünü, bull/bear münazarasını ve risk değerlendiricisini içeren tam pipeline'ı çalıştırır
- /pipeline/batch: Birden fazla hisse senedi için tam pipeline analizini toplu olarak çalıştırır
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..dependencies import check_rate_limit, get_current_user

router = APIRouter()


class PipelineRunRequest(BaseModel):
    """Pipeline çalıştırma isteği modeli."""

    ticker: str = Field(..., description="Analiz edilecek BIST hisse kodu (ör. THYAO)")
    context: dict[str, Any] = Field(default_factory=dict, description="Ek piyasa ve analiz bağlamı")
    active_roles: list[str] | None = Field(default=None, description="Aktif çalışacak ajan rolleri")


class BatchPipelineRunRequest(BaseModel):
    """Toplu pipeline çalıştırma isteği modeli."""

    tickers: list[str] = Field(..., description="Analiz edilecek BIST hisse kodları listesi")
    active_roles: list[str] | None = Field(default=None, description="Aktif çalışacak ajan rolleri")


@router.get("/list")
async def list_agents(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> dict[str, Any]:
    """Mevcut ajanların listesini döndürür."""
    try:
        from ...agents.agent_system import AgentRole

        agents = [role.value for role in AgentRole]
        return {"agents": agents, "count": len(agents), "status": "ok"}
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Ajan sistemi mevcut değil") from exc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ajan listesi alınamadı: {e}") from e


@router.get("/status")
async def agent_status(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> dict[str, Any]:
    """Ajanların çalışma durumunu döndürür."""
    try:
        from ...agents.agent_system import agent_system

        return {"agents": agent_system.get_status(), "status": "ok"}
    except ImportError:
        return {"agents": [], "message": "Ajan sistemi başlatılmamış", "status": "unavailable"}
    except Exception as e:
        return {"agents": [], "message": f"Durum alınamadı: {e}", "status": "error"}


@router.post("/run")
async def run_agent(
    agent_name: str = Query(default="researcher", description="Ajan rol adı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Belirtilen ajanı çalıştırır."""
    try:
        from ...agents.agent_system import agent_system

        result = await agent_system.run(agent_name)
        return {"status": "started", "agent": agent_name, "result": result}
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Ajan sistemi mevcut değil") from exc
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"Ajan bulunamadı: {e}") from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ajan çalıştırılamadı: {e}") from e


@router.post("/pipeline/run")
async def run_agent_pipeline(
    req: PipelineRunRequest = Body(...),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Belirtilen hisse için çoklu ajan pipeline'ını tam döngüde çalıştırır.

    Araştırma, Çelişki Tespiti, Münazara, Risk Değerlendirmesi ve Sentez adımlarını işletir.
    """
    sym = req.ticker.upper().strip()
    try:
        from ...agents.agent_pipeline import AgentPipelineOrchestrator

        orchestrator = AgentPipelineOrchestrator()
        result = await orchestrator.run(
            ticker=sym,
            context=req.context,
            active_roles=req.active_roles,
        )
        return {
            "status": "success",
            "ticker": sym,
            "decision": result.final_decision,
            "confidence": result.confidence,
            "trace_id": result.trace_id,
            "result": result.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{sym} için ajan pipeline çalıştırması başarısız oldu: {exc}",
        ) from exc


@router.post("/pipeline/batch")
async def run_batch_agent_pipeline(
    req: BatchPipelineRunRequest = Body(...),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Birden fazla hisse senedi için paralel ajan pipeline analizini çalıştırır."""
    tickers = [t.upper().strip() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="En az bir geçerli hisse sembolü sağlanmalıdır.")

    try:
        from ...agents.agent_pipeline import AgentPipelineOrchestrator

        orchestrator = AgentPipelineOrchestrator()
        batch_results = await orchestrator.run_batch(
            tickers=tickers,
            active_roles=req.active_roles,
        )
        return {
            "status": "success",
            "count": len(batch_results),
            "results": {sym: res.to_dict() for sym, res in batch_results.items()},
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Toplu pipeline çalıştırması başarısız oldu: {exc}",
        ) from exc
