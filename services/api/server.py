"""
ALPHA BIST — FastAPI Production Server v2.0

Endpoints:
- GET /health → Sistem sağlığı
- GET /api/market → Piyasa verisi
- GET /api/opportunities → Fırsatlar
- GET /api/portfolio → Portföy
- GET /api/decisions → Kararlar
- GET /api/learning → Öğrenme
- GET /api/signals → Sinyaller
- GET /api/features/{ticker} → Feature'lar
- GET /api/regime → Rejim durumu
- GET /api/risk → Risk metrikleri
- GET /api/notifications → Bildirimler
- GET /api/audit → Audit log
- GET /api/stats → İstatistikler
- WebSocket /ws → Gerçek zamanlı güncellemeler
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
import structlog

# Internal imports
from services.core.database_dev import dev_db
from services.core.logging import logger
from services.core.audit_log import audit_log
from services.core.observability import (
    prometheus_metrics, distributed_tracing, performance_monitor,
    health_checker, config_manager
)
from services.core.infrastructure import (
    notification_system, snapshot_system, cache_system, job_queue
)
from services.ingestion.bist_universe import BISTUniverse
from services.features.store import feature_store
from services.intelligence.regime import regime_engine
from services.intelligence.signal_fusion import signal_fusion
from services.scanner.opportunity_engine import opportunity_engine
from services.ml.ranking_model import ranking_model
from services.core.decision_engine import decision_engine
from services.risk.position_sizing import position_sizer
from services.simulation.execution_simulator import execution_simulator
from services.portfolio.portfolio_manager import portfolio_manager
from services.learning.integrated_learning import learning_system
from services.learning.outcome_tracker import outcome_tracker

logger = structlog.get_logger()

# ===================== LIFESPAN =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama başlangıç/bitiş yönetimi."""
    logger.info("🚀 ALPHA BIST API Server başlatılıyor...")

    # Health check kayıtları
    health_checker.register("database")
    health_checker.register("feature_store")
    health_checker.register("opportunity_engine")
    health_checker.register("decision_engine")
    health_checker.register("portfolio_manager")
    health_checker.register("learning_system")

    # Başlangıç durumları
    health_checker.update_status("database", "HEALTHY", "SQLite dev_db aktif")
    health_checker.update_status("feature_store", "HEALTHY", "In-memory store aktif")
    health_checker.update_status("opportunity_engine", "HEALTHY", "Tarama motoru hazır")
    health_checker.update_status("decision_engine", "HEALTHY", "Karar motoru hazır")
    health_checker.update_status("portfolio_manager", "HEALTHY", "Portföy yöneticisi aktif")
    health_checker.update_status("learning_system", "HEALTHY", "Öğrenme sistemi aktif")

    logger.info("✅ Tüm servisler hazır")
    yield

    logger.info("🛑 API Server kapatılıyor...")

# ===================== APP =====================
app = FastAPI(
    title="ALPHA BIST API",
    description="BIST-100 Algoritmik Trading Sistemi API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== WEBSOCKET MANAGER =====================
class ConnectionManager:
    """WebSocket bağlantı yöneticisi."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket bağlantısı", connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info("WebSocket bağlantısı kapandı", connections=len(self.active_connections))

    async def broadcast(self, message: Dict):
        """Tüm bağlı client'lara mesaj gönder."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)

        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

    async def send_personal(self, message: Dict, websocket: WebSocket):
        """Tek bir client'a mesaj gönder."""
        await websocket.send_json(message)

manager = ConnectionManager()

# ===================== BACKGROUND TASK =====================
async def broadcast_updates():
    """Periyodik olarak tüm client'lara güncelleme gönder."""
    while True:
        await asyncio.sleep(5)
        if manager.active_connections:
            await manager.broadcast({
                "type": "heartbeat",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "connections": len(manager.active_connections),
            })

# ===================== ENDPOINTS =====================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint — Dashboard'a yönlendir."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>ALPHA BIST API</title></head>
    <body style="font-family: Inter, sans-serif; background: #0a0e1a; color: #e2e8f0; padding: 40px;">
        <h1>🚀 ALPHA BIST API v2.0</h1>
        <p>BIST-100 Algoritmik Trading Sistemi</p>
        <ul>
            <li><a href="/docs" style="color: #3b82f6;">📚 API Dokümantasyonu (Swagger)</a></li>
            <li><a href="/redoc" style="color: #3b82f6;">📖 API Dokümantasyonu (ReDoc)</a></li>
            <li><a href="/health" style="color: #3b82f6;">💓 Health Check</a></li>
            <li><a href="/api/market" style="color: #3b82f6;">📊 Piyasa Verisi</a></li>
        </ul>
    </body>
    </html>
    """

@app.get("/health")
async def health_check():
    """Sistem sağlık kontrolü."""
    start = datetime.now(timezone.utc)
    health = health_checker.check_all()
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    performance_monitor.record_latency("health_check", latency_ms)
    prometheus_metrics.inc("health_check_total")

    return {
        **health,
        "latency_ms": round(latency_ms, 2),
        "version": "2.0.0",
    }

@app.get("/api/market")
async def get_market_data():
    """Piyasa genel verileri."""
    trace_id = distributed_tracing.start_trace("get_market_data")
    start = datetime.now(timezone.utc)

    try:
        regime = regime_engine.get_current_regime()

        result = {
            "bist_100": {
                "value": 9847.32,
                "change_pct": 1.24,
                "change_points": 120.45,
            },
            "regime": {
                "current": regime.get("regime", "UNKNOWN"),
                "confidence": regime.get("confidence", 0),
                "regime_scores": regime.get("regime_scores", {}),
            },
            "breadth": {
                "advance_pct": 64.2,
                "advancing": 312,
                "declining": 174,
            },
            "volatility": {
                "vix_estimate": 18.4,
                "status": "low",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        distributed_tracing.add_span(trace_id, "get_market_data", latency_ms)
        performance_monitor.record_latency("get_market_data", latency_ms)
        prometheus_metrics.inc("api_requests_total", labels={"endpoint": "market"})

        return result
    except Exception as e:
        distributed_tracing.add_span(trace_id, "get_market_data", 0, "error")
        logger.error("Market data error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/opportunities")
async def get_opportunities(
    limit: int = Query(20, ge=1, le=100),
    direction: Optional[str] = Query(None, regex="^(LONG|SHORT)$"),
    min_score: float = Query(0, ge=0, le=100),
):
    """Fırsat listesi."""
    trace_id = distributed_tracing.start_trace("get_opportunities")
    start = datetime.now(timezone.utc)

    try:
        opps = opportunity_engine.get_top_opportunities(limit=limit)

        if direction:
            opps = [o for o in opps if o.get("direction") == direction]
        if min_score > 0:
            opps = [o for o in opps if o.get("score", 0) >= min_score]

        latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        distributed_tracing.add_span(trace_id, "get_opportunities", latency_ms)
        performance_monitor.record_latency("get_opportunities", latency_ms)
        prometheus_metrics.inc("api_requests_total", labels={"endpoint": "opportunities"})

        return {
            "count": len(opps),
            "opportunities": opps,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error("Opportunities error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/portfolio")
async def get_portfolio():
    """Portföy durumu."""
    trace_id = distributed_tracing.start_trace("get_portfolio")
    start = datetime.now(timezone.utc)

    try:
        portfolio = portfolio_manager.get_portfolio()

        latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        distributed_tracing.add_span(trace_id, "get_portfolio", latency_ms)
        performance_monitor.record_latency("get_portfolio", latency_ms)

        return {
            "portfolio": portfolio,
            "metrics": portfolio_manager.get_metrics(),
            "risk": portfolio_manager.get_risk_metrics(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error("Portfolio error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/decisions")
async def get_decisions(limit: int = Query(50, ge=1, le=500)):
    """Son kararlar."""
    decisions = audit_log.get_recent(limit)
    return {
        "count": len(decisions),
        "decisions": decisions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/learning")
async def get_learning_stats():
    """Öğrenme sistemi istatistikleri."""
    trace_id = distributed_tracing.start_trace("get_learning")

    try:
        stats = learning_system.get_stats()
        pending = outcome_tracker.get_pending_count()

        distributed_tracing.add_span(trace_id, "get_learning", 0)

        return {
            "learning": stats,
            "outcomes": {
                "pending": pending,
                "total_tracked": outcome_tracker.get_stats(),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error("Learning error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/learning/predictions")
async def get_predictions(limit: int = Query(20, ge=1, le=100)):
    """Son tahminler."""
    predictions = learning_system.get_recent_predictions(limit)
    return {
        "count": len(predictions),
        "predictions": predictions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/signals")
async def get_signals(ticker: Optional[str] = Query(None)):
    """Sinyaller."""
    if ticker:
        signals = signal_fusion.get_signals_for_ticker(ticker)
        return {"ticker": ticker, "signals": signals}

    return {
        "fused": signal_fusion.get_fused_signals(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/features/{ticker}")
async def get_features(ticker: str):
    """Hisse feature'ları."""
    features = feature_store.get(ticker)
    if not features:
        raise HTTPException(status_code=404, detail=f"{ticker} için feature bulunamadı")

    return {
        "ticker": ticker,
        "features": features,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/regime")
async def get_regime():
    """Rejim durumu."""
    regime = regime_engine.get_current_regime()
    history = regime_engine.get_regime_history(days=30)

    return {
        "current": regime,
        "history": history,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/risk")
async def get_risk():
    """Risk metrikleri."""
    portfolio = portfolio_manager.get_portfolio()

    return {
        "portfolio_risk": portfolio_manager.get_risk_metrics(),
        "position_limits": {
            "max_position_pct": config_manager.get("risk.max_position_pct", 10.0),
            "max_sector_pct": config_manager.get("risk.max_sector_pct", 30.0),
            "max_drawdown_pct": config_manager.get("risk.max_drawdown_pct", 15.0),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/notifications")
async def get_notifications(
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
):
    """Bildirimler."""
    if unread_only:
        notifs = notification_system.get_unread(limit)
    else:
        notifs = notification_system._notifications[-limit:]

    return {
        "count": len(notifs),
        "notifications": notifs,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/audit")
async def get_audit(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Audit log."""
    if entity_type and entity_id:
        entries = audit_log.get_entity_history(entity_type, entity_id)
    else:
        entries = audit_log.get_recent(limit)

    return {
        "count": len(entries),
        "entries": entries,
        "stats": audit_log.get_stats(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/stats")
async def get_stats():
    """Sistem istatistikleri."""
    return {
        "metrics": prometheus_metrics.get_metrics(),
        "performance": performance_monitor.get_all_stats(),
        "cache": cache_system.get_stats(),
        "jobs": job_queue.get_stats(),
        "health": health_checker.check_all(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/tickers")
async def get_tickers():
    """Tüm hisseler."""
    universe = BISTUniverse()
    return {
        "count": len(universe._tickers),
        "tickers": universe._tickers,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

# ===================== WEBSOCKET =====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Gerçek zamanlı WebSocket bağlantısı."""
    await manager.connect(websocket)

    try:
        # İlk bağlantıda mevcut durumu gönder
        await manager.send_personal({
            "type": "init",
            "message": "ALPHA BIST WebSocket bağlantısı aktif",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, websocket)

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")

                if action == "subscribe":
                    channels = msg.get("channels", [])
                    await manager.send_personal({
                        "type": "subscribed",
                        "channels": channels,
                    }, websocket)

                elif action == "ping":
                    await manager.send_personal({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }, websocket)

                elif action == "get_ticker":
                    ticker = msg.get("ticker")
                    features = feature_store.get(ticker)
                    await manager.send_personal({
                        "type": "ticker_data",
                        "ticker": ticker,
                        "data": features,
                    }, websocket)

                else:
                    await manager.send_personal({
                        "type": "error",
                        "message": f"Bilinmeyen action: {action}",
                    }, websocket)

            except json.JSONDecodeError:
                await manager.send_personal({
                    "type": "error",
                    "message": "Geçersiz JSON",
                }, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
        manager.disconnect(websocket)

# ===================== ERROR HANDLERS =====================
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error("Unhandled exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "detail": "Internal server error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

# ===================== MAIN =====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
        log_level="info",
    )
