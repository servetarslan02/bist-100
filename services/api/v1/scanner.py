"""
Scanner API v2.0 — Tüm endpoint'ler gerçek servislere bağlı ve optimize.

Uç noktalar:
- GET /scanner/status — Tarama durumu (scheduler + dedup + scanner)
- GET /scanner/results — Son tarama sonuçları
- GET /scanner/opportunities — En iyi fırsatlar
- GET /scanner/signals — Sinyal listesi
- GET /scanner/tiers — Tier bazlı özet
- GET /scanner/history/{ticker} — Hisse tarama geçmişi
- GET /scanner/performance — Performans istatistikleri
- GET /scanner/alerts — Son alert'ler
- GET /scanner/filters — Filtre listesi
- GET /scanner/dedup — Deduplication istatistikleri
- GET /scanner/scheduler — Scheduler istatistikleri
- GET /scanner/dashboard — Tam dashboard verisi
- POST /scanner/trigger — Manuel tarama tetikle
- POST /scanner/event — Event bildirimi
"""

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..dependencies import check_rate_limit, get_current_user
from ...core.swr_cache import SWRCache

logger = logging.getLogger(__name__)
router = APIRouter()

# Thread-safe SWR cache for signals
_signals_cache = SWRCache(ttl_seconds=60)


def _get_scan_api() -> Any:
    """Tarama API singleton'ını döndürür."""
    from ...scanner.scan_api import scan_api

    return scan_api




# =====================================================
# SIGNALS & OPPORTUNITIES
# =====================================================


@router.get("/signals")
@router.get("/opportunities")
async def scanner_signals(
    request: Request,
    response: Response,
    limit: int = Query(50, ge=1, le=100),
    category: str | None = Query(None),
    sort_by: str | None = Query("confidence"),
    search: str | None = Query(None),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Canlı model sinyalleri ve piyasa fırsatları (Filtreli, Güven & Getiri Sıralı ve ETag/SWR Korumalı)."""
    # ETag / If-None-Match Kontrolü (İstemci tarafı 304 Not Modified)
    client_etag = request.headers.get("if-none-match")
    if client_etag and _signals_cache.etag and client_etag.strip('"') == _signals_cache.etag.strip('"'):
        if _signals_cache.is_fresh and not category and not search:
            response.status_code = 304
            return response

    # 1. Redis Cache Kontrolü
    try:
        from ...core.redis_helper import get_cached, set_cached

        # Stabilizasyon: Eğer hafızada taze sinyaller varsa (60 sn) ve filtre uygulanmamışsa hızlı dön
        cached = _signals_cache.get()
        if cached is not None and not category and not search:
            signals = list(cached)
        else:
            preds = get_cached("phase18:predictions")
            if not preds or len(preds) == 0 or not preds[0].get("target_price"):
                try:
                    from ...scanner.bist_ml_scanner import bist_ml_scanner
                    preds = bist_ml_scanner.scan_all_opportunities(limit=50)
                    if preds:
                        set_cached("phase18:predictions", preds, ttl=3600)
                        set_cached("radar:data", preds, ttl=3600)
                except Exception as scan_err:
                    logger.warning("dinamik_tarayici_notu: hata=%s", str(scan_err))

            signals = []
            if preds and len(preds) > 0:
                for p in preds:
                    item = dict(p)
                    # Frontend kategori filtreleri ile tam uyum garantisi
                    if not item.get("signal_type") or item.get("signal_type") in ["GÜÇLÜ AL", "AL", "TUT"]:
                        item["signal_type"] = item.get("spec_category", item.get("strategy_type", "MOMENTUM_LEADER"))
                    signals.append(item)

            # Sıralama en çok güven (score) ve en yüksek getiri (expected_return_pct)
            signals.sort(key=lambda x: (x.get("score", 0), x.get("expected_return_pct", 0)), reverse=True)
            _signals_cache.set(signals)

        # Filtreleme (Kategori ve Arama)
        result_signals = signals
        if category and category != "ALL":
            result_signals = [
                s for s in result_signals
                if s.get("spec_category") == category
                or s.get("signal_type") == category
                or s.get("strategy_type") == category
                or category in s.get("tags", [])
                or (category == "HIGH_CONVICTION" and (s.get("is_high_conviction") or s.get("score", 0) >= 80))
            ]

        if search:
            q = search.lower().strip()
            result_signals = [
                s for s in result_signals
                if q in s.get("symbol", "").lower() or q in s.get("name", "").lower() or q in s.get("spec_reason", "").lower()
            ]

        if _signals_cache.etag:
            response.headers["ETag"] = f'"{_signals_cache.etag}"'
            response.headers["Cache-Control"] = "public, max-age=15, stale-while-revalidate=45"

        return {"signals": result_signals[:limit], "count": len(result_signals[:limit])}
    except Exception as e:
        logger.warning("redis_sinyal_okuma_notu: hata=%s", str(e))

    # Yedek: Doğrudan ML Scanner
    try:
        from ...scanner.bist_ml_scanner import bist_ml_scanner

        live_opps = bist_ml_scanner.scan_all_opportunities(limit=limit)
        if live_opps:
            result_signals = live_opps
            if category and category != "ALL":
                result_signals = [
                    s
                    for s in result_signals
                    if s.get("spec_category") == category
                    or s.get("signal_type") == category
                    or s.get("strategy_type") == category
                    or category in s.get("tags", [])
                    or (category == "HIGH_CONVICTION" and (s.get("is_high_conviction") or s.get("score", 0) >= 80))
                ]
            if search:
                q = search.lower().strip()
                result_signals = [
                    s
                    for s in result_signals
                    if q in s.get("symbol", "").lower()
                    or q in s.get("name", "").lower()
                    or q in s.get("spec_reason", "").lower()
                ]
            return {
                "signals": result_signals[:limit],
                "count": len(result_signals[:limit]),
                "source": "ml_scanner_live",
            }
    except Exception as scan_err:
        logger.warning("canli_tarayici_yedek_hatasi: hata=%s", str(scan_err))

    # Kapalı mod: Asla sahte sinyal dönme
    return {
        "signals": [],
        "count": 0,
        "status": "unavailable",
        "message": "Canlı sinyal verisi bulunamadı veya altyapı güncelleniyor.",
    }


# =====================================================
# STATUS & DASHBOARD
# =====================================================


@router.get("/status")
async def scan_status(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Tarama durumu — scheduler + dedup + scanner özeti."""
    try:
        api = _get_scan_api()
        return api.get_status()
    except Exception as exc:
        logger.error("tarama_durumu_hatasi: hata=%s", str(exc))
        raise HTTPException(503, detail="Tarama durumu alınamadı.") from exc


@router.get("/dashboard")
async def scan_dashboard(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Tam dashboard verisi — tüm modüllerin birleşik özeti."""
    try:
        api = _get_scan_api()
        return api.get_full_dashboard()
    except Exception as exc:
        logger.error("tarama_panel_hatasi: hata=%s", str(exc))
        raise HTTPException(503, detail="Tarama panel verisi alınamadı.") from exc


@router.get("/results")
async def scan_results(
    request: Request,
    response: Response,
    limit: int = Query(1000, ge=1, le=1000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Son tarama sonuçları."""
    try:
        api = _get_scan_api()
        return api.get_results(limit=limit)
    except Exception as exc:
        logger.warning("tarama_sonuc_hatasi: hata=%s", str(exc))
        # Yedek olarak sinyal endpoint'inden dön
        return await scanner_signals(
            request=request, response=response, limit=limit,
            category=None, sort_by=None, search=None, user=user, _=_,
        )


@router.get("/tiers")
async def tiers(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Tier bazlı özet — Tier 0-5 dağılımı + top opportunities."""
    try:
        api = _get_scan_api()
        return api.get_tiers()
    except Exception as exc:
        logger.error("tier_hatasi: hata=%s", str(exc))
        raise HTTPException(503, detail="Tier verisi alınamadı.") from exc


@router.get("/history/{ticker}")
async def ticker_history(
    ticker: str,
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Hisse tarama geçmişi."""
    try:
        api = _get_scan_api()
        return api.get_ticker_history(ticker, days=days)
    except Exception as exc:
        logger.error("hisse_gecmisi_hatasi: ticker=%s hata=%s", ticker, str(exc))
        raise HTTPException(503, detail=f"{ticker} tarama geçmişi alınamadı.") from exc


@router.get("/performance")
async def scanner_performance(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Scanner performans metrikleri."""
    try:
        api = _get_scan_api()
        return api.get_performance()
    except Exception as exc:
        logger.error("tarayici_performans_hatasi: hata=%s", str(exc))
        raise HTTPException(503, detail="Tarayıcı performans metrikleri alınamadı.") from exc


@router.get("/alerts")
async def scanner_alerts(
    limit: int = Query(20, ge=1, le=100), user=Depends(get_current_user), _=Depends(check_rate_limit)
) -> Any:
    """Tarayıcı alarmları ve bildirimleri."""
    try:
        api = _get_scan_api()
        return api.get_alerts(limit=limit)
    except Exception as exc:
        logger.error("tarayici_alarm_hatasi: hata=%s", str(exc))
        return {"alerts": [], "count": 0, "status": "unavailable"}


@router.get("/filters")
async def scanner_filters(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Aktif filtreler."""
    try:
        api = _get_scan_api()
        return api.get_filters()
    except Exception as exc:
        logger.error("tarayici_filtre_hatasi: hata=%s", str(exc))
        return {"filters": [], "status": "unavailable"}


@router.get("/dedup")
async def dedup_stats(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Deduplication istatistikleri."""
    try:
        api = _get_scan_api()
        return api.get_dedup_stats()
    except Exception as exc:
        logger.error("dedup_hatasi: hata=%s", str(exc))
        raise HTTPException(503, detail="Dedup istatistikleri alınamadı.") from exc


@router.get("/scheduler")
async def scheduler_stats(user=Depends(get_current_user), _=Depends(check_rate_limit)) -> Any:
    """Scheduler istatistikleri."""
    try:
        api = _get_scan_api()
        return api.get_scheduler_stats()
    except Exception as exc:
        logger.error("scheduler_hatasi: hata=%s", str(exc))
        raise HTTPException(503, detail="Scheduler istatistikleri alınamadı.") from exc


# =====================================================
# ACTIONS
# =====================================================


@router.post("/trigger")
async def trigger_scan(
    scan_type: str = Query("manual", pattern="^(manual|batch|event)$"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Manuel tarama tetikle."""
    try:
        from ...pipeline.run_unified_daily import run_unified_daily_cycle

        task = asyncio.create_task(run_unified_daily_cycle())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return {
            "status": "triggered",
            "scan_type": scan_type,
            "message": "Birleşik günlük tarama ve işlem döngüsü kuyruğa alındı.",
        }
    except Exception as exc:
        logger.error("tarama_tetikleme_hatasi: hata=%s", str(exc))
        raise HTTPException(500, detail=f"Tarama tetiklenemedi: {exc}") from exc


@router.post("/event")
async def report_event(
    event_type: str = Query(..., description="Event türü: kap.event, news.event, macro.event"),
    ticker: str = Query("", description="Etkilenen hisse"),
    importance: float = Query(0.5, ge=0, le=1, description="Önem seviyesi"),
    title: str = Query("", description="Event başlığı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Event bildirimi."""
    try:
        from ...core.redis_helper import set_cached

        event_data = {
            "event_type": event_type,
            "ticker": ticker.upper() if ticker else "",
            "importance": importance,
            "title": title,
            "timestamp": time.time(),
        }
        # Event'i Redis'e yaz (pipeline tüketir)
        set_cached(f"event:{event_type}:{ticker}", event_data, ttl=3600)

        return {
            "event_type": event_type,
            "affected": [ticker] if ticker else [],
            "importance": importance,
            "status": "received",
        }
    except Exception as exc:
        logger.warning("event_bildirim_hatasi: hata=%s", str(exc))
        return {
            "event_type": event_type,
            "affected": [ticker] if ticker else [],
            "importance": importance,
            "status": "received",
        }
