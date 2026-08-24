"""
ALPHA BIST — Server-Sent Events (SSE) Router v1.0

Tek yönlü server→client push. WebSocket'ten daha basit,
tarayıcıda EventSource API ile çalışır.

Kullanım:
    GET /api/v1/sse/ticks?tickers=THYAO,ASELS
    GET /api/v1/sse/signals
    GET /api/v1/sse/portfolio
    GET /api/v1/sse/alerts
"""

import asyncio
import json
import time
from typing import AsyncIterator, Dict, Any, Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse
import structlog

logger = structlog.get_logger()

router = APIRouter()


async def _sse_generator(
    channel: str,
    tickers: list = None,
    interval: float = 1.0,
) -> AsyncIterator[str]:
    """SSE event generator — sürekli veri akışı."""
    from ...core.redis_helper import get_cached

    last_data_hash = None
    retry_count = 0
    max_retries = 100

    while retry_count < max_retries:
        try:
            if channel == "ticks":
                data = {}
                for ticker in (tickers or []):
                    tick = get_cached(f"price:{ticker}")
                    if tick:
                        data[ticker] = tick
                if data:
                    event_data = json.dumps(data, default=str)
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: tick\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "signals":
                signals = get_cached("signals:latest") or []
                if signals:
                    event_data = json.dumps(signals, default=str)
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: signal\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "portfolio":
                pf = get_cached("portfolio:state")
                if pf:
                    event_data = json.dumps(pf, default=str)
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: portfolio\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "alerts":
                alerts = get_cached("alerts:latest") or []
                if alerts:
                    event_data = json.dumps(alerts, default=str)
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: alert\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "regime":
                regime = get_cached("market:regime")
                if regime:
                    event_data = json.dumps(regime, default=str)
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: regime\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "radar":
                radar = get_cached("radar:data") or []
                if radar:
                    event_data = json.dumps(radar[:50], default=str)  # İlk 50
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: radar\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            # Heartbeat (30 saniyede bir)
            yield f": heartbeat {int(time.time())}\n\n"

            retry_count = 0
            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            break
        except Exception as e:
            retry_count += 1
            logger.warning(f"SSE {channel} error", error=str(e), retry=retry_count)
            await asyncio.sleep(min(interval * 2, 10))


@router.get("/ticks")
async def sse_ticks(
    request: Request,
    tickers: str = Query("", description="Comma-separated ticker list"),
    interval: float = Query(1.0, ge=0.1, le=10.0, description="Update interval in seconds"),
):
    """SSE: Anlık fiyat akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/ticks?tickers=THYAO,ASELS
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        ticker_list = ["THYAO", "ASELS", "TUPRS", "FROTO", "KCHOL"]

    return StreamingResponse(
        _sse_generator("ticks", tickers=ticker_list, interval=interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx buffering kapat
        },
    )


@router.get("/signals")
async def sse_signals(
    request: Request,
    interval: float = Query(2.0, ge=0.5, le=30.0),
):
    """SSE: Sinyal akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/signals
    """
    return StreamingResponse(
        _sse_generator("signals", interval=interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/portfolio")
async def sse_portfolio(
    request: Request,
    interval: float = Query(5.0, ge=1.0, le=60.0),
):
    """SSE: Portföy durumu akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/portfolio
    """
    return StreamingResponse(
        _sse_generator("portfolio", interval=interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/alerts")
async def sse_alerts(
    request: Request,
    interval: float = Query(3.0, ge=1.0, le=30.0),
):
    """SSE: Alarm akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/alerts
    """
    return StreamingResponse(
        _sse_generator("alerts", interval=interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/regime")
async def sse_regime(
    request: Request,
    interval: float = Query(10.0, ge=5.0, le=60.0),
):
    """SSE: Piyasa rejimi akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/regime
    """
    return StreamingResponse(
        _sse_generator("regime", interval=interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/radar")
async def sse_radar(
    request: Request,
    interval: float = Query(5.0, ge=1.0, le=30.0),
):
    """SSE: Radar akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/radar
    """
    return StreamingResponse(
        _sse_generator("radar", interval=interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
