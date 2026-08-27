"""
ALPHA BIST — FastAPI Backend v3.0 (STANDALONE)

⚠️  Bu dosya BAĞIMSIZ bir servistir.
    Canonical production server: services/api/app.py (port 8000)
    Bu dosya port 8001'de çalışır ve farklı endpoint prefix'leri kullanır.

ROADMAP v3.0 FAZ 7:
- RESTful API endpoints
- WebSocket real-time updates
- Authentication & Rate Limiting
- CORS enabled
- Auto-generated OpenAPI docs

Endpoints:
    GET  /health              → Sistem sağlığı
    GET  /regime              → Mevcut piyasa rejimi
    GET  /opportunities       → Top fırsatlar
    GET  /opportunities/{ticker} → Hisse detayı
    GET  /portfolio           → Portföy önerisi
    GET  /backtest            → Backtest sonuçları
    GET  /learning            → Öğrenme durumu
    GET  /features/{ticker}   → Feature vector
    POST /predict             → Tahmin isteği
    WS   /ws                  → Real-time updates (token gerekli)
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import orjson
import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = structlog.get_logger()

# =====================================================
# PYDANTIC MODELLER
# =====================================================


class OpportunityResponse(BaseModel):
    ticker: str
    rank: int
    score: float
    direction: str
    confidence: float
    regime: str
    signals: dict


class PortfolioResponse(BaseModel):
    date: str
    total_positions: int
    total_weight: float
    positions: list[dict]
    risk_metrics: dict


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    uptime_hours: float
    version: str
    modules: dict[str, str]


class PredictRequest(BaseModel):
    ticker: str
    features: dict | None = None


class PredictResponse(BaseModel):
    ticker: str
    score: float
    rank: int
    direction: str
    confidence: float
    feature_importance: dict[str, float]


# =====================================================
# FASTAPI UYGULAMASI
# =====================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü."""
    logger.info("ALPHA BIST API starting up")
    yield
    logger.info("ALPHA BIST API shutting down")


app = FastAPI(
    title="ALPHA BIST API v3.0 (Standalone)",
    description="Süper Akıllı Quantitative Trading System API — Standalone service (port 8001)",
    version="3.0.0",
    lifespan=lifespan,
)

# CORS — ortam değişkeninden okunur, varsayılan olarak sadece localhost
_allowed = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:8001").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# ENDPOINT'LER
# =====================================================


@app.get("/", tags=["Root"])
async def root():
    """API bilgisi."""
    return {
        "name": "ALPHA BIST API",
        "version": "3.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["System"])
async def health_check():
    """Sistem sağlık kontrolü — standart format."""
    try:
        from services.learning.super_intelligence import super_intelligence

        health = super_intelligence.get_health_status()
        return {
            "status": health.overall_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": "3.0.0",
            "server": "standalone (apps/api/main.py)",
            "services": health.module_status,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "version": "3.0.0",
            "server": "standalone (apps/api/main.py)",
            "error": str(e),
        }


@app.get("/regime", tags=["Market"])
async def get_regime():
    """Mevcut piyasa rejimi."""
    raise HTTPException(
        status_code=301,
        detail="This endpoint has moved. Use GET /api/v1/market/regime instead.",
    )


@app.get("/opportunities", tags=["Trading"])
async def get_opportunities(
    limit: int = 20,
    regime: str | None = None,
    min_confidence: float = 0.0,
):
    """En iyi fırsatları getir."""
    raise HTTPException(
        status_code=301,
        detail="This endpoint has moved. Use GET /api/v1/scanner/opportunities instead.",
    )


@app.get("/opportunities/{ticker}", tags=["Trading"])
async def get_opportunity_detail(ticker: str):
    """Belirli bir hissenin detaylı analizi."""
    raise HTTPException(
        status_code=501,
        detail=f"Detail analysis for {ticker} not yet implemented. Run feature pipeline first.",
    )


@app.get("/portfolio", response_model=PortfolioResponse, tags=["Trading"])
async def get_portfolio_recommendation():
    """Portföy önerisi."""
    raise HTTPException(
        status_code=301,
        detail="This endpoint has moved. Use GET /api/v1/portfolio/summary instead.",
    )


@app.get("/backtest", tags=["Analysis"])
async def get_backtest_results():
    """Backtest sonuçları."""
    from services.core.orchestrator import orchestrator

    report = orchestrator.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No report available")

    return {
        "date": report.date,
        "backtest": report.backtest_summary,
    }


@app.get("/learning", tags=["System"])
async def get_learning_status():
    """Sürekli öğrenme durumu."""
    raise HTTPException(
        status_code=301,
        detail="This endpoint has moved. Use GET /api/v1/learning/ instead.",
    )


@app.get("/features/{ticker}", tags=["Analysis"])
async def get_features(ticker: str):
    """Hissenin feature vektörü."""
    raise HTTPException(
        status_code=301,
        detail=f"This endpoint has moved. Use GET /api/v1/intelligence/features/{ticker} instead.",
    )


@app.post("/predict", response_model=PredictResponse, tags=["Trading"])
async def predict(request: PredictRequest):
    """Prediction endpoint — not yet implemented."""
    raise HTTPException(
        status_code=501,
        detail="Prediction engine not yet connected. Run training pipeline first.",
    )


@app.get("/pipeline/stats", tags=["System"])
async def get_pipeline_stats():
    """Pipeline istatistikleri."""
    from services.core.orchestrator import orchestrator

    return orchestrator.get_pipeline_stats()


@app.get("/reports/latest", tags=["System"])
async def get_latest_report():
    """Son günlük rapor."""
    from services.core.orchestrator import orchestrator

    report = orchestrator.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No report available")

    return {
        "date": report.date,
        "timestamp": report.timestamp,
        "regime": report.regime,
        "opportunities": report.top_opportunities,
        "portfolio": report.portfolio_recommendation,
        "risk": report.risk_metrics,
        "learning": report.learning_status,
        "health": report.system_health,
        "alerts": report.alerts,
    }


# =====================================================
# WEBSOCKET
# =====================================================


class ConnectionManager:
    """WebSocket bağlantı yöneticisi."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connected", connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info("WebSocket disconnected", connections=len(self.active_connections))

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                logger.error("Unexpected error in broadcast", exc_info=True)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time WebSocket bağlantısı — Authorization header ile token doğrulama."""
    # Token'ı header'dan al (URL'de taşınmaz — güvenlik)
    auth_header = websocket.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header else ""
    if not token:
        await websocket.close(code=4001, reason="Authentication required: set Authorization: Bearer <token> header")
        return

    # Token doğrulama
    try:
        from services.api.auth import jwt_handler

        payload = jwt_handler.verify_token(token)
        if not payload:
            await websocket.close(code=4003, reason="Invalid or expired token")
            return
    except Exception:
        await websocket.close(code=4003, reason="Token verification failed")
        return

    await manager.connect(websocket)
    try:
        # İlk bağlantıda mevcut durumu gönder
        await websocket.send_json(
            {
                "type": "init",
                "message": f"Connected as {payload.username}",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        while True:
            data = await websocket.receive_text()
            message = orjson.loads(data)

            action = message.get("action", "")

            if action == "subscribe":
                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "channels": message.get("channels", []),
                    }
                )

            elif action == "get_opportunities":
                from services.core.orchestrator import orchestrator

                report = orchestrator.get_latest_report()
                if report:
                    await websocket.send_json(
                        {
                            "type": "opportunities",
                            "data": report.top_opportunities[:10],
                        }
                    )

            elif action == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now(UTC).isoformat()})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
        manager.disconnect(websocket)


# =====================================================
# BACKGROUND TASKS
# =====================================================


async def broadcast_updates():
    """Periyodik güncellemeleri broadcast et."""
    while True:
        await asyncio.sleep(60)  # Her 60 saniye

        from services.core.orchestrator import orchestrator

        report = orchestrator.get_latest_report()

        if report:
            await manager.broadcast(
                {
                    "type": "update",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "regime": report.regime,
                    "top_opportunity": report.top_opportunities[0] if report.top_opportunities else None,
                }
            )


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
