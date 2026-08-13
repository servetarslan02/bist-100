"""ALPHA BIST - FastAPI Backend (Main Entry Point)"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, pg_fetch, pg_fetchrow, pg_fetchval,
    ch_execute, redis_get, redis_set, redis_hgetall,
)
from ..core.event_bus import ensure_topics, EventType
from ..core.logging import setup_logging

logger = structlog.get_logger()


# =====================================================
# Lifespan
# =====================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    setup_logging()
    logger.info("Starting ALPHA BIST API")

    await init_databases()
    ensure_topics()

    yield

    await close_databases()
    logger.info("ALPHA BIST API stopped")


# =====================================================
# App
# =====================================================

app = FastAPI(
    title="ALPHA BIST API",
    description="BIST Market Intelligence & Quant Engine",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================
# WebSocket Manager
# =====================================================

class ConnectionManager:
    """WebSocket connection manager."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = []
        self.active_connections[channel].append(websocket)
        logger.info("WebSocket connected", channel=channel)

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            self.active_connections[channel].remove(websocket)
        logger.info("WebSocket disconnected", channel=channel)

    async def broadcast(self, channel: str, message: dict):
        if channel in self.active_connections:
            for connection in self.active_connections[channel]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass


manager = ConnectionManager()


# =====================================================
# Health & Status
# =====================================================

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/status")
async def status():
    """System status endpoint."""
    try:
        # Check PostgreSQL
        pg_ok = await pg_fetchval("SELECT 1") == 1

        # Check ClickHouse
        ch_result = ch_execute("SELECT 1")
        ch_ok = len(ch_result.result_rows) > 0

        # Check Redis
        from ..core.database import get_redis
        r = await get_redis()
        redis_ok = await r.ping()

        return {
            "status": "ok",
            "services": {
                "postgresql": "healthy" if pg_ok else "unhealthy",
                "clickhouse": "healthy" if ch_ok else "unhealthy",
                "redis": "healthy" if redis_ok else "unhealthy",
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)},
        )


# =====================================================
# Market Data
# =====================================================

@app.get("/api/market/state")
async def get_market_state():
    """Get current market state."""
    try:
        state = await redis_get("market_state")
        if state:
            return json.loads(state.replace("'", '"'))
        return {"regime": "UNKNOWN", "message": "No market state available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/instruments")
async def get_instruments(
    sector: Optional[str] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    """Get list of instruments."""
    try:
        query = """
            SELECT i.symbol, c.name, s.code as sector, i.active
            FROM instruments i
            JOIN companies c ON i.company_id = c.id
            LEFT JOIN sectors s ON c.sector_id = s.id
            WHERE i.active = TRUE
        """
        params = []

        if sector:
            query += " AND s.code = $1"
            params.append(sector)

        query += f" ORDER BY i.symbol LIMIT {limit} OFFSET {offset}"

        rows = await pg_fetch(query, *params)
        return [dict(row) for row in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/instrument/{ticker}/ohlcv")
async def get_instrument_ohlcv(ticker: str, period: str = "60d"):
    """Get OHLCV data for chart."""
    try:
        import yfinance as yf
        t = yf.Ticker(f"{ticker}.IS")
        hist = t.history(period=period)
        if hist.empty:
            return {"candles": [], "volumes": []}

        candles = []
        volumes = []
        for idx, row in hist.iterrows():
            ts = int(idx.timestamp())
            candles.append({
                "time": ts,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
            })
            volumes.append({
                "time": ts,
                "volume": int(row["Volume"]),
                "open": float(row["Open"]),
                "close": float(row["Close"]),
            })

        return {"candles": candles, "volumes": volumes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/instrument/{ticker}")
async def get_instrument_detail(ticker: str):
    """Get detailed instrument data."""
    try:
        # Get instrument info
        row = await pg_fetchrow("""
            SELECT i.*, c.name, c.sector_id, s.code as sector
            FROM instruments i
            JOIN companies c ON i.company_id = c.id
            LEFT JOIN sectors s ON c.sector_id = s.id
            WHERE i.symbol = $1
        """, ticker)

        if not row:
            raise HTTPException(status_code=404, detail=f"Instrument {ticker} not found")

        # Get features from Redis
        features = await redis_hgetall(f"features:{ticker}")

        return {
            "instrument": dict(row),
            "features": features,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# Signals & Opportunities
# =====================================================

@app.get("/api/signals")
async def get_signals(
    signal_type: Optional[str] = None,
    horizon: Optional[str] = None,
    min_score: float = 0,
    limit: int = 20,
):
    """Get active trading signals."""
    try:
        query = """
            SELECT s.*, i.symbol as ticker, c.name
            FROM signals s
            JOIN instruments i ON s.instrument_id = i.id
            JOIN companies c ON i.company_id = c.id
            WHERE s.status = 'ACTIVE'
            AND s.score >= $1
        """
        params = [min_score]

        if signal_type:
            query += f" AND s.signal_type = ${len(params) + 1}"
            params.append(signal_type)

        if horizon:
            query += f" AND s.horizon = ${len(params) + 1}"
            params.append(horizon)

        query += f" ORDER BY s.score DESC LIMIT {limit}"

        rows = await pg_fetch(query, *params)
        return [dict(row) for row in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# Portfolio
# =====================================================

@app.get("/api/portfolio")
async def get_portfolio():
    """Get current portfolio."""
    try:
        # Get portfolio
        portfolio = await pg_fetchrow("""
            SELECT * FROM portfolios WHERE status = 'ACTIVE' LIMIT 1
        """)

        if not portfolio:
            return {"message": "No active portfolio"}

        # Get positions
        positions = await pg_fetch("""
            SELECT p.*, i.symbol as ticker, c.name
            FROM positions p
            JOIN instruments i ON p.instrument_id = i.id
            JOIN companies c ON i.company_id = c.id
            WHERE p.portfolio_id = $1 AND p.status = 'OPEN'
        """, portfolio["id"])

        return {
            "portfolio": dict(portfolio),
            "positions": [dict(p) for p in positions],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# Models
# =====================================================

@app.get("/api/world/state")
async def get_world_state():
    """Get current world state."""
    try:
        from ..core.database import redis_get
        import json
        state = await redis_get("world_state")
        if state:
            return json.loads(state)
        return {"message": "No world state available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/features/{ticker}")
async def get_features(ticker: str):
    """Get features for a ticker."""
    try:
        from ..core.database import redis_hgetall
        features = await redis_hgetall(f"features:{ticker}")
        if features:
            return features
        return {"message": f"No features for {ticker}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events")
async def get_events(
    event_type: Optional[str] = None,
    limit: int = 50,
):
    """Get recent events."""
    try:
        query = "SELECT * FROM system_events"
        params = []
        if event_type:
            query += " WHERE event_type = $1"
            params.append(event_type)
        query += f" ORDER BY created_at DESC LIMIT {limit}"
        rows = await pg_fetch(query, *params)
        return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/models")
async def get_models():
    """Get ML model registry."""
    try:
        rows = await pg_fetch("""
            SELECT m.*, mv.version as latest_version, mv.status as latest_status,
                   mv.metrics, mv.backtest_metrics
            FROM models m
            LEFT JOIN LATERAL (
                SELECT version, status, metrics, backtest_metrics
                FROM model_versions
                WHERE model_id = m.id
                ORDER BY created_at DESC
                LIMIT 1
            ) mv ON TRUE
            ORDER BY m.name
        """)
        return [dict(row) for row in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# Alerts
# =====================================================

@app.get("/api/alerts")
async def get_alerts(
    severity: Optional[str] = None,
    acknowledged: bool = False,
    limit: int = 50,
):
    """Get alerts."""
    try:
        query = """
            SELECT * FROM alerts
            WHERE acknowledged = $1
        """
        params = [acknowledged]

        if severity:
            query += f" AND severity = ${len(params) + 1}"
            params.append(severity)

        query += f" ORDER BY created_at DESC LIMIT {limit}"

        rows = await pg_fetch(query, *params)
        return [dict(row) for row in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# WebSocket
# =====================================================

@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                # Handle subscription
                if msg.get("action") == "subscribe":
                    await websocket.send_json({"type": "subscribed", "channel": msg.get("channel", channel)})
                else:
                    await websocket.send_json({"type": "pong", "data": data})
            except json.JSONDecodeError:
                await websocket.send_json({"type": "pong", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)


@app.websocket("/ws/live")
async def live_websocket(websocket: WebSocket):
    """Live market data WebSocket."""
    await manager.connect(websocket, "live")
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "subscribe":
                    channel = msg.get("channel", "market.tick")
                    await websocket.send_json({"type": "subscribed", "channel": channel})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket, "live")


@app.get("/api/stream/events")
async def stream_events():
    """SSE endpoint for real-time event streaming."""
    from fastapi.responses import StreamingResponse
    import asyncio

    async def event_generator():
        while True:
            # Check for new events from Redis pub/sub
            try:
                from ..core.database import get_redis
                r = await get_redis()
                pubsub = r.pubsub()
                await pubsub.subscribe("alpha:events")

                async for message in pubsub.listen():
                    if message["type"] == "message":
                        yield f"data: {message['data']}\n\n"
            except Exception:
                await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# =====================================================
# Run
# =====================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "services.api.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )
