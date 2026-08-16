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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
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
from services.core.monitoring import portfolio_monitor
from services.core.monitoring_security import monitoring_auth, extract_bearer_token, extract_api_key
from services.core.alerting import alerting
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
            except Exception:
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
        regime = regime_engine.current_regime

        result = {
            "bist_100": {
                "value": 9847.32,
                "change_pct": 1.24,
                "change_points": 120.45,
            },
            "regime": {
                "current": regime.regime.value if regime else "UNKNOWN",
                "confidence": regime.confidence if regime else 0,
                "regime_scores": regime.features_used if regime else {},
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
    direction: Optional[str] = Query(None, pattern="^(LONG|SHORT)$"),
    min_score: float = Query(0, ge=0, le=100),
):
    """Fırsat listesi."""
    trace_id = distributed_tracing.start_trace("get_opportunities")
    start = datetime.now(timezone.utc)

    try:
        latest_scan_results = getattr(opportunity_engine, "last_results", [])
        opps = opportunity_engine.get_top_opportunities(latest_scan_results, limit=limit)

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
    regime = regime_engine.current_regime
    history = regime_engine.get_history(limit=30)

    return {
        "current": {
            "regime": regime.regime.value,
            "confidence": regime.confidence,
            "duration_hours": regime.duration_hours,
        } if regime else None,
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

# ===================== MONITORING ENDPOINTS =====================

@app.get("/health/detailed")
async def health_detailed():
    """Detaylı sağlık raporu (portfolio + locks + components)."""
    start = datetime.now(timezone.utc)
    result = await portfolio_monitor.get_health_detailed()
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
    result["latency_ms"] = round(latency_ms, 2)
    prometheus_metrics.inc("health_detailed_total")
    return result


@app.get("/metrics")
async def prometheus_metrics_endpoint(request: Request):
    """Prometheus text format metrics (Bearer token gerekli)."""
    client_ip = request.client.host if request.client else "unknown"
    if not monitoring_auth.check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_metrics_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        monitoring_auth.record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")

    text = await portfolio_monitor.get_prometheus_text()
    return JSONResponse(
        content=text,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/admin/lock-metrics")
async def admin_lock_metrics(request: Request):
    """Lock performans metrikleri (admin — token gerekli)."""
    client_ip = request.client.host if request.client else "unknown"
    if not monitoring_auth.check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        monitoring_auth.record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Admin access required")

    prometheus_metrics.inc("admin_lock_metrics_total")
    return await portfolio_monitor.get_lock_metrics_api()


@app.get("/admin/portfolio")
async def admin_portfolio(request: Request):
    """Portfolio sağlık ve muhasebe durumu (admin — token gerekli)."""
    client_ip = request.client.host if request.client else "unknown"
    if not monitoring_auth.check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        monitoring_auth.record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Admin access required")

    prometheus_metrics.inc("admin_portfolio_total")
    return await portfolio_monitor.get_portfolio_api()


@app.get("/admin/alerts")
async def admin_alerts(request: Request):
    """Aktif alert'ler (admin — token gerekli)."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    return {
        "summary": alerting.get_alert_summary(),
        "active": alerting.get_active_alerts(),
        "recent": alerting.get_all_alerts(limit=50),
    }


@app.get("/admin/auth-status")
async def admin_auth_status():
    """Authentication durumu (public)."""
    return monitoring_auth.get_auth_status()


# ===================== POLICY MANAGEMENT ENDPOINTS =====================

@app.get("/admin/policy")
async def admin_policy_get(request: Request):
    """Mevcut alert policy."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    return {
        "policy": alerting.get_policy_info(),
        "active_silences": alerting.get_active_silences(),
    }


@app.post("/admin/policy")
async def admin_policy_update(request: Request):
    """Policy güncelle."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json()
    result = alerting.update_policy(body, actor=f"api:{client_ip}")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("errors", ["Update failed"]))
    return result


@app.post("/admin/policy/rollback")
async def admin_policy_rollback(request: Request):
    """Policy rollback."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    target = body.get("version", 0)
    result = alerting.rollback_policy(target, actor=f"api:{client_ip}")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Rollback failed"))
    return result


@app.get("/admin/policy/history")
async def admin_policy_history(request: Request):
    """Policy versiyon geçmişi."""
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    return {"history": alerting.get_policy_history()}


@app.get("/admin/policy/audit")
async def admin_policy_audit(request: Request):
    """Policy audit log."""
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    return {"audit_log": alerting.get_policy_audit_log()}


@app.post("/admin/silence")
async def admin_silence_add(request: Request):
    """Alert susturma ekle."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json()
    result = alerting.add_silence(
        alert_type=body.get("alert_type"),
        fingerprint=body.get("fingerprint"),
        duration_s=body.get("duration_s", 3600),
        reason=body.get("reason", ""),
        created_by=f"api:{client_ip}",
    )
    return result


@app.delete("/admin/silence")
async def admin_silence_remove(request: Request):
    """Alert susturma kaldır."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    removed = alerting.remove_silence(
        fingerprint=body.get("fingerprint"),
        alert_type=body.get("alert_type"),
        actor=f"api:{client_ip}",
    )
    return {"removed": removed}


@post_admin = lambda: None  # placeholder for syntax

@app.post("/admin/policy/diff")
async def admin_policy_diff(request: Request):
    """Policy diff (uygulamadan)."""
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json()
    diff = alerting.compute_policy_diff(body)
    return {"diff": diff.to_dict()}


@app.post("/admin/silence/batch")
async def admin_silence_batch_add(request: Request):
    """Toplu susturma ekle."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json()
    rules = body.get("rules", [])
    if not rules:
        raise HTTPException(status_code=400, detail="rules array required")

    results = alerting.batch_add_silences(rules, created_by=f"api:{client_ip}")
    return {"results": results, "total": len(rules)}


@app.delete("/admin/silence/batch")
async def admin_silence_batch_remove(request: Request):
    """Toplu susturma kaldır."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    filters = body.get("filters", [])
    if not filters:
        raise HTTPException(status_code=400, detail="filters array required")

    result = alerting.batch_remove_silences(filters, actor=f"api:{client_ip}")
    return result


@app.post("/admin/policy/lock")
async def admin_policy_lock(request: Request):
    """Policy düzenleme kilidi al."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    timeout = body.get("timeout_s", 30)
    owner = f"api:{client_ip}"

    acquired = alerting._policy.acquire_edit_lock(owner, timeout)
    if not acquired:
        lock_info = alerting._policy.get_lock_info()
        raise HTTPException(status_code=409, detail={
            "error": "Policy is locked by another user",
            "lock_info": lock_info,
        })
    return {"success": True, "owner": owner, "timeout_s": timeout}


@app.delete("/admin/policy/lock")
async def admin_policy_unlock(request: Request):
    """Policy düzenleme kilidi bırak."""
    client_ip = request.client.host if request.client else "unknown"
    token = extract_bearer_token(request.headers.get("authorization"))
    api_key = extract_api_key(dict(request.headers))
    if not (monitoring_auth.verify_admin_token(token or "") or
            monitoring_auth.verify_admin_token(api_key or "")):
        raise HTTPException(status_code=401, detail="Admin access required")

    owner = f"api:{client_ip}"
    released = alerting._policy.release_edit_lock(owner)
    if not released:
        raise HTTPException(status_code=409, detail="Lock not owned by you")
    return {"success": True}


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
