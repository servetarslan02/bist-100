"""
ALPHA BIST — FastAPI Backend v3.0

ROADMAP v3.0 FAZ 7:
- RESTful API endpoints
- WebSocket real-time updates
- Authentication & Rate Limiting
- CORS enabled
- Auto-generated OpenAPI docs

Endpoints:
    GET  /health          → Sistem sağlığı
    GET  /regime          → Mevcut piyasa rejimi
    GET  /opportunities   → Top fırsatlar
    GET  /opportunities/{ticker} → Hisse detayı
    GET  /portfolio       → Portföy önerisi
    GET  /backtest        → Backtest sonuçları
    GET  /learning        → Öğrenme durumu
    GET  /features/{ticker} → Feature vector
    POST /predict         → Tahmin isteği
    WS   /ws              → Real-time updates
"""

import json
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import structlog

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
    signals: Dict

class PortfolioResponse(BaseModel):
    date: str
    total_positions: int
    total_weight: float
    positions: List[Dict]
    risk_metrics: Dict

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    uptime_hours: float
    version: str
    modules: Dict[str, str]

class PredictRequest(BaseModel):
    ticker: str
    features: Optional[Dict] = None

class PredictResponse(BaseModel):
    ticker: str
    score: float
    rank: int
    direction: str
    confidence: float
    feature_importance: Dict[str, float]

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
    title="ALPHA BIST API",
    description="Süper Akıllı Quantitative Trading System API",
    version="3.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production'da kısıtla
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

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Sistem sağlık kontrolü."""
    from services.learning.super_intelligence import super_intelligence

    health = super_intelligence.get_health_status()

    return HealthResponse(
        status=health.overall_status,
        timestamp=datetime.now(timezone.utc).isoformat(),
        uptime_hours=round(health.uptime_hours, 2),
        version="3.0.0",
        modules=health.module_status,
    )

@app.get("/regime", tags=["Market"])
async def get_regime():
    """Mevcut piyasa rejimi."""
    from services.core.regime_detector import regime_detector

    # Son regime bilgisini döndür
    history = regime_detector.get_regime_history()
    if history:
        latest = history[-1]
        return {
            "regime": latest["regime"],
            "confidence": latest["confidence"],
            "timestamp": latest["timestamp"],
            "factors": latest.get("factors", {}),
        }

    return {"regime": "UNKNOWN", "confidence": 0, "timestamp": "", "factors": {}}

@app.get("/opportunities", tags=["Trading"])
async def get_opportunities(
    limit: int = 20,
    regime: Optional[str] = None,
    min_confidence: float = 0.0,
):
    """En iyi fırsatları getir."""
    from services.ml.ranking_model import ranking_model
    from services.core.orchestrator import orchestrator

    report = orchestrator.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No report available")

    opportunities = report.top_opportunities[:limit]

    # Filtrele
    if min_confidence > 0:
        opportunities = [o for o in opportunities if o.get("confidence", 0) >= min_confidence]

    return {
        "date": report.date,
        "regime": report.regime,
        "count": len(opportunities),
        "opportunities": opportunities,
    }

@app.get("/opportunities/{ticker}", tags=["Trading"])
async def get_opportunity_detail(ticker: str):
    """Belirli bir hissenin detaylı analizi."""
    from services.ml.ranking_model import ranking_model

    # TODO: Feature vector'ü getir
    return {
        "ticker": ticker,
        "status": "available",
        "features": {},  # TODO
        "prediction": {},  # TODO
    }

@app.get("/portfolio", response_model=PortfolioResponse, tags=["Trading"])
async def get_portfolio_recommendation():
    """Portföy önerisi."""
    from services.core.orchestrator import orchestrator

    report = orchestrator.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No report available")

    port = report.portfolio_recommendation

    return PortfolioResponse(
        date=report.date,
        total_positions=port.get("total_positions", 0),
        total_weight=port.get("total_weight", 0),
        positions=port.get("positions", []),
        risk_metrics=report.risk_metrics,
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
    from services.learning.continuous_learning import continuous_learning

    return continuous_learning.get_learning_report()

@app.get("/features/{ticker}", tags=["Analysis"])
async def get_features(ticker: str):
    """Hissenin feature vektörü."""
    # TODO: Feature cache'den getir
    return {
        "ticker": ticker,
        "features": {},  # TODO
        "feature_count": 0,
    }

@app.post("/predict", response_model=PredictResponse, tags=["Trading"])
async def predict(request: PredictRequest):
    """Tahmin isteği."""
    from services.ml.ranking_model import ranking_model

    # TODO: Feature'ları hesapla ve tahmin yap
    return PredictResponse(
        ticker=request.ticker,
        score=0.0,
        rank=0,
        direction="UNKNOWN",
        confidence=0.0,
        feature_importance={},
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
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connected", connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info("WebSocket disconnected", connections=len(self.active_connections))

    async def broadcast(self, message: Dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time WebSocket bağlantısı."""
    await manager.connect(websocket)
    try:
        while True:
            # Client'tan mesaj bekle
            data = await websocket.receive_text()
            message = json.loads(data)

            action = message.get("action", "")

            if action == "subscribe":
                # Abonelik başlat
                await websocket.send_json({
                    "type": "subscribed",
                    "channels": message.get("channels", []),
                })

            elif action == "get_opportunities":
                # Fırsatları gönder
                from services.core.orchestrator import orchestrator
                report = orchestrator.get_latest_report()
                if report:
                    await websocket.send_json({
                        "type": "opportunities",
                        "data": report.top_opportunities[:10],
                    })

            elif action == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})

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
            await manager.broadcast({
                "type": "update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "regime": report.regime,
                "top_opportunity": report.top_opportunities[0] if report.top_opportunities else None,
            })

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
