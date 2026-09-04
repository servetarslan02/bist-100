"""
ALPHA BIST — Server-Sent Events (SSE) Router v2.1

Tek yönlü sunucu→istemci push. WebSocket'ten daha basit,
tarayıcıda EventSource API ile çalışır.

En iyi uygulamalar (FastAPI 2026):
- 15 saniyede bir keep-alive ping
- X-Accel-Buffering: no (Nginx proxy buffering kapat)
- Cache-Control: no-cache
- Connection: keep-alive
- Retry: client reconnect süresi
- id: her event'e benzersiz kimlik (reconnect desteği)
- Last-Event-ID: client reconnect'te kaldığı yerden devam eder

Kullanım:
    GET /api/v1/sse/ticks?tickers=THYAO,ASELS
    GET /api/v1/sse/signals
    GET /api/v1/sse/portfolio
    GET /api/v1/sse/alerts
    GET /api/v1/sse/regime
    GET /api/v1/sse/radar
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# SSE en iyi uygulama: 15 saniyede bir keep-alive ping
SSE_KEEPALIVE_INTERVAL = 15


async def _sse_generator(
    request: Request,
    channel: str,
    tickers: list[str] | None = None,
    interval: float = 1.0,
    last_event_id: str | None = None,
) -> AsyncIterator[str]:
    """SSE event generator — sürekli veri akışı + keep-alive ping.

    En iyi uygulamalar:
    - Bağlantı anında `connected` event'i gönder (client doğrulama alır)
    - Her 15 saniyede bir `: ping` comment gönder (bağlantıyı canlı tut)
    - Data değiştiyse event gönder (değişiklik algılama: doğrudan string karşılaştırması)
    - Her event'e `id:` ekle (client reconnect'te kaldığı yerden devam edebilir)
    - Client disconnect detection (CancelledError + request.is_disconnected)

    Args:
        request: FastAPI request nesnesi (disconnect algılama için).
        channel: Veri kanalı (ticks/signals/portfolio/alerts/regime/radar).
        tickers: Hisse kodları listesi (sadece ticks kanalı için gerekli).
        interval: Güncelleme aralığı (saniye).
        last_event_id: Client reconnect'te gönderdiği son event ID'si.

    Yields:
        SSE formatında string event'leri.
    """
    from ...core.redis_helper import get_cached

    last_data: str | None = None
    last_ping_time = time.time()
    event_counter = 0

    # Client reconnect süresi (ms)
    yield "retry: 3000\n\n"

    # İlk bağlantı event'i — client "bağlandım" doğrulaması alır
    event_counter += 1
    yield f"id: {event_counter}\nevent: connected\ndata: {{\"channel\":\"{channel}\",\"ts\":{int(time.time())}}}\n\n"

    # Client reconnect'te last_event_id gönderdiyse bilgilendir
    if last_event_id:
        logger.info("sse_reconnect: kanal=%s son_event_id=%s", channel, last_event_id)

    while True:
        try:
            # Client bağlantıyı kesti mi kontrol et
            if await request.is_disconnected():
                logger.debug("sse_baglanti_kesildi: kanal=%s", channel)
                break

            now = time.time()
            event_data: str | None = None

            if channel == "ticks":
                data = {}
                for ticker in tickers or []:
                    tick = get_cached(f"price:{ticker}")
                    if tick:
                        data[ticker] = tick
                if data:
                    event_data = orjson.dumps(data, default=str).decode()

            elif channel == "signals":
                signals = get_cached("signals:latest") or []
                if signals:
                    event_data = orjson.dumps(signals, default=str).decode()

            elif channel == "portfolio":
                pf = get_cached("portfolio:state")
                if pf:
                    event_data = orjson.dumps(pf, default=str).decode()

            elif channel == "alerts":
                alerts = get_cached("alerts:latest") or []
                if alerts:
                    event_data = orjson.dumps(alerts, default=str).decode()

            elif channel == "regime":
                regime = get_cached("market:regime")
                if regime:
                    event_data = orjson.dumps(regime, default=str).decode()

            elif channel == "radar":
                radar = get_cached("radar:data") or []
                if radar:
                    event_data = orjson.dumps(radar[:50], default=str).decode()

            # Veri değiştiyse gönder (doğrudan string karşılaştırması — hash'ten verimli)
            if event_data is not None and event_data != last_data:
                event_counter += 1
                event_name = {
                    "ticks": "tick",
                    "signals": "signal",
                    "portfolio": "portfolio",
                    "alerts": "alert",
                    "regime": "regime",
                    "radar": "radar",
                }.get(channel, channel)
                yield f"id: {event_counter}\nevent: {event_name}\ndata: {event_data}\n\n"
                last_data = event_data
                last_ping_time = now  # veri gönderildi, ping zamanlayıcısını sıfırla

            # Keep-alive ping: bağımsız olarak 15 saniyede bir gönder
            if now - last_ping_time >= SSE_KEEPALIVE_INTERVAL:
                yield f": ping {int(now)}\n\n"
                last_ping_time = now

            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            # Client disconnect — temiz çık
            logger.debug("sse_baglanti_kesildi: kanal=%s", channel)
            break
        except Exception as e:
            logger.warning("sse_hatasi: kanal=%s hata=%s", channel, str(e))
            await asyncio.sleep(min(interval * 2, 10))


@router.get("/ticks")
async def sse_ticks(
    request: Request,
    tickers: str = Query("", description="Virgülle ayrılmış hisse kodları"),
    interval: float = Query(1.0, ge=0.1, le=10.0, description="Güncelleme aralığı (saniye)"),
) -> Any:
    """SSE: Anlık fiyat akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/ticks?tickers=THYAO,ASELS

        // JavaScript
        const es = new EventSource('/api/v1/sse/ticks?tickers=THYAO,ASELS');
        es.addEventListener('tick', (e) => console.log(JSON.parse(e.data)));
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="tickers parametresi gerekli (virgülle ayrılmış hisse kodları).")

    last_event_id = request.headers.get("Last-Event-ID")

    return StreamingResponse(
        _sse_generator(request, "ticks", tickers=ticker_list, interval=interval, last_event_id=last_event_id),
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
) -> Any:
    """SSE: Sinyal akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/signals
    """
    last_event_id = request.headers.get("Last-Event-ID")

    return StreamingResponse(
        _sse_generator(request, "signals", interval=interval, last_event_id=last_event_id),
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
) -> Any:
    """SSE: Portföy durumu akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/portfolio
    """
    last_event_id = request.headers.get("Last-Event-ID")

    return StreamingResponse(
        _sse_generator(request, "portfolio", interval=interval, last_event_id=last_event_id),
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
) -> Any:
    """SSE: Alarm akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/alerts
    """
    last_event_id = request.headers.get("Last-Event-ID")

    return StreamingResponse(
        _sse_generator(request, "alerts", interval=interval, last_event_id=last_event_id),
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
) -> Any:
    """SSE: Piyasa rejimi akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/regime
    """
    last_event_id = request.headers.get("Last-Event-ID")

    return StreamingResponse(
        _sse_generator(request, "regime", interval=interval, last_event_id=last_event_id),
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
) -> Any:
    """SSE: Radar akışı.

    Kullanım:
        curl -N http://localhost:8000/api/v1/sse/radar
    """
    last_event_id = request.headers.get("Last-Event-ID")

    return StreamingResponse(
        _sse_generator(request, "radar", interval=interval, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
