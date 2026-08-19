"""ALPHA BIST - FastAPI Backend (Main Entry Point)"""

import asyncio
import json
from datetime import datetime, timezone
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
        """WebSocket baglantisi kur."""
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = []
        self.active_connections[channel].append(websocket)
        logger.info("WebSocket connected", channel=channel)

    def disconnect(self, websocket: WebSocket, channel: str):
        """WebSocket baglantisi kes."""
        if channel in self.active_connections:
            self.active_connections[channel].remove(websocket)
        logger.info("WebSocket disconnected", channel=channel)

    async def broadcast(self, channel: str, message: dict):
        """Tum connected client'lara mesaj gonder."""
        if channel in self.active_connections:
            for connection in self.active_connections[channel]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    pass  # Intentional: silent error handling


manager = ConnectionManager()


# =====================================================
# Health & Status
# =====================================================

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/status")
async def status():
    """System status endpoint."""
    services = {}

    # Check PostgreSQL
    try:
        pg_ok = await pg_fetchval("SELECT 1") == 1
        services["postgresql"] = "healthy" if pg_ok else "unhealthy"
    except Exception as e:
        services["postgresql"] = "unavailable"

    # Check ClickHouse
    try:
        ch_result = ch_execute("SELECT 1")
        services["clickhouse"] = "healthy" if len(ch_result.result_rows) > 0 else "unhealthy"
    except Exception as e:
        services["clickhouse"] = "unavailable"

    # Check Redis
    try:
        from ..core.database import get_redis
        r = await get_redis()
        redis_ok = await r.ping()
        services["redis"] = "healthy" if redis_ok else "unhealthy"
    except Exception as e:
        services["redis"] = "unavailable"

    return {
        "status": "ok",
        "services": services,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =====================================================
# Market Data
# =====================================================

@app.get("/api/market/state")
async def get_market_state():
    """Get current market state."""
    try:
        state = await redis_get("market_state")
        if state:
            try:
                return json.loads(state)
            except json.JSONDecodeError:
                return {"regime": "UNKNOWN", "message": "Invalid market state data"}
        # Redis yoksa gerçek zamanlı hesapla
        return await _compute_live_market_state()
    except Exception as e:
        return {"regime": "UNKNOWN", "error": str(e)}


async def _compute_live_market_state():
    """Redis yoksa gerçek zamanlı market state hesapla."""
    import yfinance as yf
    from ..ingestion.bist_universe import BIST_STOCKS

    # İlk 50 hisseyi hızlıca tara
    tickers = [f"{t}.IS" for t in BIST_STOCKS[:50]]
    try:
        data = yf.download(tickers, period="2d", group_by="ticker", threads=True, progress=False)

        advancing = 0
        declining = 0
        total = 0

        for t in BIST_STOCKS[:50]:
            try:
                td = data[f"{t}.IS"].dropna()
                if len(td) >= 2:
                    change = (td["Close"].iloc[-1] / td["Close"].iloc[-2] - 1) * 100
                    if change > 0:
                        advancing += 1
                    elif change < 0:
                        declining += 1
                    total += 1
            except Exception as e:
                pass  # Intentional: silent error handling

        breadth = (advancing / total * 100) if total > 0 else 50

        regime = "RANGE"
        if breadth > 65:
            regime = "TRENDING-UP"
        elif breadth < 35:
            regime = "RISK-OFF"
        elif breadth > 70:
            regime = "MOMENTUM-EXPANSION"

        return {
            "regime": regime,
            "breadth_pct": round(breadth, 1),
            "advancing": advancing,
            "declining": declining,
            "total_instruments": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "live_computation",
        }
    except Exception as e:
        return {"regime": "UNKNOWN", "error": str(e)}


@app.get("/api/market/instruments")
async def get_instruments(
    sector: Optional[str] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    """Get list of instruments."""
    try:
        # PostgreSQL yoksa BIST universe'den döndür
        from ..ingestion.bist_universe import BIST_STOCKS, get_sector

        instruments = []
        for ticker in BIST_STOCKS:
            s = get_sector(ticker)
            if sector and s != sector:
                continue
            instruments.append({
                "symbol": ticker,
                "name": ticker,
                "sector": s,
                "active": True,
            })

        return instruments[offset:offset + limit]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/instrument/{ticker}/ohlcv")
async def get_instrument_ohlcv(
    ticker: str,
    period: str = "60d",
    interval: str = "1d"
):
    """Get OHLCV data for chart — ClickHouse'dan oku, yfinance'den değil."""
    try:
        # Önce ClickHouse'dan dene
        try:
            from ..core.database import ch_execute
            result = ch_execute("""
                SELECT timestamp, open, high, low, close, volume
                FROM ohlcv
                WHERE instrument_id = (SELECT id FROM instruments WHERE symbol = %(ticker)s)
                AND timeframe = '1d'
                ORDER BY timestamp DESC LIMIT 60
            """, parameters={"ticker": ticker})

            if result.result_rows and len(result.result_rows) > 0:
                candles = []
                volumes = []
                for row in reversed(result.result_rows):
                    ts = int(row[0].timestamp()) if hasattr(row[0], 'timestamp') else 0
                    candles.append({"time": ts, "open": float(row[1]), "high": float(row[2]),
                                   "low": float(row[3]), "close": float(row[4])})
                    volumes.append({"time": ts, "volume": int(row[5]), "open": float(row[1]), "close": float(row[4])})
                return {"candles": candles, "volumes": volumes}
        except Exception as e:
            pass  # Intentional: silent error handling

        # Fallback: yfinance
        import yfinance as yf
        t = yf.Ticker(f"{ticker}.IS")
        hist = t.history(period=period)
        if hist.empty:
            return {"candles": [], "volumes": []}

        # NaN temizle
        hist = hist.dropna(subset=["Open", "High", "Low", "Close"])

        candles = []
        volumes = []
        for idx, row in hist.iterrows():
            ts = int(idx.timestamp())
            candles.append({"time": ts, "open": round(float(row["Open"]), 2), "high": round(float(row["High"]), 2),
                           "low": round(float(row["Low"]), 2), "close": round(float(row["Close"]), 2)})
            volumes.append({"time": ts, "volume": int(row["Volume"]), "open": round(float(row["Open"]), 2), "close": round(float(row["Close"]), 2)})

        return {"candles": candles, "volumes": volumes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/instrument/{ticker}/full")
async def get_instrument_full(ticker: str):
    """Get full instrument data: price + chart + features + signals."""
    try:
        import yfinance as yf
        from ..features.calculator import FeatureCalculator
        from ..intelligence.spec_engine import spec_engine
        import polars as pl

        # 1. OHLCV data
        t = yf.Ticker(f"{ticker}.IS")
        hist = t.history(period="60d")
        if hist.empty:
            raise HTTPException(status_code=404, detail=f"{ticker} not found")

        # NaN satırları temizle
        hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
        hist = hist.reset_index()

        candles = []
        for _, row in hist.iterrows():
            candles.append({
                "time": int(row["Date"].timestamp()),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })

        # 2. Features
        df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
        df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df = df.drop_nulls(subset=["close"])

        if len(df) < 20:
            raise HTTPException(status_code=404, detail=f"Insufficient data for {ticker}")

        fc = FeatureCalculator()
        features = fc.compute_all_features(df)

        # 3. SPEC score
        asset_state = {
            "volume_zscore": features.get("volume_zscore", 0),
            "price_change_1d_zscore": features.get("return_1d", 0) / 2,
            "volatility_zscore": features.get("volatility_ratio", 1) - 1,
            "bb_position": features.get("bb_position", 0.5),
            "near_20d_high": features.get("near_20d_high", 0),
            "relative_strength_vs_sector": 1.0,
            "kap_sentiment": 0.0,
            "roc_5d": features.get("roc_5d", 0),
            "price_acceleration": features.get("price_acceleration", 0),
            "volatility_regime": "NORMAL",
            "amihud_illiquidity": 0.001,
            "correlation_to_index": 0.75,
            "momentum_20d": features.get("momentum_20d", 0),
            "realized_vol_20d": features.get("realized_vol_20d", 20),
        }
        spec = spec_engine.compute_spec(ticker, asset_state, {"regime": "RANGE"})

        # 4. Current price
        close_list = [x for x in df["close"].to_list() if x is not None]
        current_price = close_list[-1] if close_list else 0

        return {
            "ticker": ticker,
            "price": current_price,
            "candles": candles,
            "features": {k: v for k, v in features.items() if isinstance(v, (int, float))},
            "spec": {
                "score": spec.spec_score,
                "category": spec.category,
                "anomaly": spec.anomaly_score,
                "evidence": spec.evidence_consensus,
                "regime": spec.regime_compatibility,
            },
        }

    except HTTPException:
        raise
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
    """Get active trading signals — gerçek veriyle hesapla."""
    try:
        import yfinance as yf
        from ..ingestion.bist_universe import BIST_STOCKS, get_sector
        from ..features.calculator import FeatureCalculator
        from ..intelligence.spec_engine import spec_engine

        fc = FeatureCalculator()
        signals = []

        # İlk 30 hisseyi tara
        tickers = BIST_STOCKS[:30]
        data = yf.download([f"{t}.IS" for t in tickers], period="60d", group_by="ticker", threads=True, progress=False)

        for ticker in tickers:
            try:
                td = data[f"{ticker}.IS"].dropna()
                if len(td) < 20:
                    continue

                td = td.reset_index()
                df = pl.from_pandas(td[["Date", "Open", "High", "Low", "Close", "Volume"]])
                df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})

                features = fc.compute_all_features(df)
                if not features:
                    continue

                asset_state = {
                    "volume_zscore": features.get("volume_zscore", 0),
                    "price_change_1d_zscore": features.get("return_1d", 0) / 2,
                    "volatility_zscore": features.get("volatility_ratio", 1) - 1,
                    "bb_position": features.get("bb_position", 0.5),
                    "near_20d_high": features.get("near_20d_high", 0),
                    "relative_strength_vs_sector": 1.0,
                    "kap_sentiment": 0.0,
                    "roc_5d": features.get("roc_5d", 0),
                    "price_acceleration": features.get("price_acceleration", 0),
                    "volatility_regime": "NORMAL",
                    "amihud_illiquidity": 0.001,
                    "correlation_to_index": 0.75,
                    "momentum_20d": features.get("momentum_20d", 0),
                    "realized_vol_20d": features.get("realized_vol_20d", 20),
                }

                spec = spec_engine.compute_spec(ticker, asset_state, {"regime": "RANGE"})

                if spec.spec_score >= min_score:
                    signals.append({
                        "ticker": ticker,
                        "name": ticker,
                        "score": round(spec.spec_score, 1),
                        "direction": "LONG" if features.get("momentum_20d", 0) > 0 else "SHORT",
                        "risk_level": "HIGH" if features.get("realized_vol_20d", 20) > 30 else "MEDIUM" if features.get("realized_vol_20d", 20) > 20 else "LOW",
                        "horizon": "1-4W",
                        "expected_return_pct": round(features.get("momentum_20d", 0), 1),
                        "spec_category": spec.category,
                    })
            except Exception as e:
                pass  # Intentional: silent error handling

        signals.sort(key=lambda x: x["score"], reverse=True)
        return signals[:limit]

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
        query += " ORDER BY created_at DESC"
        params.append(limit)
        query += f" LIMIT ${len(params)}"
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

        query += " ORDER BY created_at DESC"
        params.append(limit)
        query += f" LIMIT ${len(params)}"

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
                pass  # Intentional: silent error handling
    except WebSocketDisconnect:
        manager.disconnect(websocket, "live")


@app.get("/api/stream/events")
async def stream_events():
    """SSE endpoint for real-time event streaming."""
    from fastapi.responses import StreamingResponse
    import asyncio

    async def event_generator():
        """Server-sent events generator."""
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
            except Exception as e:
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
