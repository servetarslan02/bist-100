"""
ALPHA BIST — Server-Sent Events (SSE) Router v2.0

Tek yönlü server→client push. WebSocket'ten daha basit,
tarayıcıda EventSource API ile çalışır.

Best Practices (FastAPI 2026):
- 15 saniyede bir keep-alive ping
- X-Accel-Buffering: no (Nginx proxy buffering kapat)
- Cache-Control: no-cache
- Connection: keep-alive
- Retry: client reconnect süresi

Kullanım:
    GET /api/v1/sse/ticks?tickers=THYAO,ASELS
    GET /api/v1/sse/signals
    GET /api/v1/sse/portfolio
    GET /api/v1/sse/alerts
"""

import asyncio
import time
from collections.abc import AsyncIterator

import orjson
import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

logger = structlog.get_logger()

router = APIRouter()

# SSE best practice: 15 saniyede bir keep-alive ping
SSE_KEEPALIVE_INTERVAL = 15


async def _sse_generator(
    channel: str,
    tickers: list = None,
    interval: float = 1.0,
) -> AsyncIterator[str]:
    """SSE event generator — sürekli veri akışı + keep-alive ping.

    Best Practices:
    - Her 15 saniyede bir `: ping` comment gönder (bağlantıyı canlı tut)
    - Data değiştiğinde event gönder
    - Client disconnect detection (CancelledError)
    """
    from ...core.redis_helper import get_cached

    last_data_hash = None
    last_ping_time = time.time()
    retry_count = 0
    max_retries = 100

    # Client reconnect süresi (ms)
    yield "retry: 3000\n\n"

    while retry_count < max_retries:
        try:
            now = time.time()

            if channel == "ticks":
                data = {}
                for ticker in tickers or []:
                    tick = get_cached(f"price:{ticker}")
                    if tick:
                        data[ticker] = tick
                if data:
                    event_data = orjson.dumps(data, default=str).decode()
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: tick\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "signals":
                signals = get_cached("signals:latest") or []
                if signals:
                    event_data = orjson.dumps(signals, default=str).decode()
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: signal\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "portfolio":
                pf = get_cached("portfolio:state")
                if pf:
                    event_data = orjson.dumps(pf, default=str).decode()
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: portfolio\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "alerts":
                alerts = get_cached("alerts:latest") or []
                if alerts:
                    event_data = orjson.dumps(alerts, default=str).decode()
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: alert\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "regime":
                regime = get_cached("market:regime")
                if regime:
                    event_data = orjson.dumps(regime, default=str).decode()
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: regime\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            elif channel == "radar":
                radar = get_cached("radar:data") or []
                if radar:
                    event_data = orjson.dumps(radar[:50], default=str).decode()
                    current_hash = hash(event_data)
                    if current_hash != last_data_hash:
                        yield f"event: radar\ndata: {event_data}\n\n"
                        last_data_hash = current_hash

            # Keep-alive ping: 15 saniyede bir (bağlantıyı canlı tut)
            if now - last_ping_time >= SSE_KEEPALIVE_INTERVAL:
                yield f": ping {int(now)}\n\n"
                last_ping_time = now

            retry_count = 0
            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            # Client disconnect — temiz çık
            logger.debug(f"SSE {channel} client disconnected")
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

        // JavaScript
        const es = new EventSource('/api/v1/sse/ticks?tickers=THYAO,ASELS');
        es.addEventListener('tick', (e) => console.log(JSON.parse(e.data)));
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        ticker_list = ["THYAO", "ASELS", "TUPRS", "FROTO", "KCHOL"]

    return StreamingResponse(
        _sse_generator("ticks", tickers=ticker_list, interval=interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
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
            "Cache-Control": "no-cache, no-transform",
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
            "Cache-Control": "no-cache, no-transform",
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
            "Cache-Control": "no-cache, no-transform",
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
            "Cache-Control": "no-cache, no-transform",
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
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
