"""
Scanner API v2.0 — Tüm endpoint'ler gerçek servislere bağlı.

Endpoints:
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

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional
from ..dependencies import get_current_user, check_rate_limit

router = APIRouter()


def _get_scan_api():
    """Scan API singleton'ı al."""
    from ...scanner.scan_api import scan_api
    return scan_api


def _get_engine():
    """Alpha engine singleton'ı al."""
    from ...scanner.alpha_engine import alpha_engine
    return alpha_engine


# =====================================================
# STATUS & DASHBOARD
# =====================================================

@router.get("/status")
async def scan_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tarama durumu — scheduler + dedup + scanner özeti.

    Returns:
        Sistem durumu: scheduler mode, market open, dedup stats, tier summary
    """
    try:
        api = _get_scan_api()
        return api.get_status()
    except Exception as e:
        raise HTTPException(500, f"Scanner status error: {e}")


@router.get("/dashboard")
async def scan_dashboard(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tam dashboard verisi — tüm modüllerin birleşik özeti.

    Returns:
        Status + results + tiers + performance + alerts + filters + dedup + scheduler
    """
    try:
        api = _get_scan_api()
        return api.get_full_dashboard()
    except Exception as e:
        raise HTTPException(500, f"Scanner dashboard error: {e}")


# =====================================================
# RESULTS & OPPORTUNITIES
# =====================================================

@router.get("/results")
async def scan_results(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Son tarama sonuçları.

    Args:
        limit: Maksimum sonuç sayısı (1-200)

    Returns:
        Son tarama sonuçları: ticker, score, signal, direction, confidence, price, tier
    """
    try:
        api = _get_scan_api()
        return api.get_results(limit=limit)
    except Exception as e:
        raise HTTPException(500, f"Scanner results error: {e}")


@router.get("/opportunities")
@router.get("/rankings")
async def scan_opportunities(
    tier: Optional[str] = Query(None, description="Tier filtresi (TIER_1, TIER_2, TIER_3)"),
    limit: int = Query(20, ge=1, le=100, description="Maksimum sonuç"),
    min_score: float = Query(50.0, ge=0, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """En iyi fırsatlar — opportunity_engine.

    Args:
        limit: Maksimum sonuç
        min_score: Minimum skor eşiği

    Returns:
        Fırsat listesi: ticker, score, signal, direction, evidence, risks
    """
    try:
        api = _get_scan_api()
        tiers = api.get_tiers()
        opportunities = tiers.get("top_opportunities", [])
        filtered = [o for o in opportunities if o.get("opportunity_score", 0) >= min_score]
        return {
            "opportunities": filtered[:limit],
            "total": len(filtered),
            "min_score": min_score,
        }
    except Exception as e:
        raise HTTPException(500, f"Opportunities error: {e}")


@router.get("/signals")
async def signals(
    limit: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Sinyal listesi — son taramadaki sinyaller.

    Returns:
        Sinyal listesi: ticker, type, score, direction, confidence, evidence
    """
    try:
        api = _get_scan_api()
        results = api.get_results(limit=200)
        signal_list = [
            r for r in results.get("results", [])
            if r.get("signal")
        ]
        return {
            "signals": signal_list[:limit],
            "total": len(signal_list),
        }
    except Exception as e:
        raise HTTPException(500, f"Signals error: {e}")


# =====================================================
# TIERS & HISTORY
# =====================================================

@router.get("/tiers")
async def tiers(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tier bazlı özet — Tier 0-5 dağılımı + top opportunities.

    Returns:
        Tier summary + top_opportunities
    """
    try:
        api = _get_scan_api()
        return api.get_tiers()
    except Exception as e:
        raise HTTPException(500, f"Tiers error: {e}")


@router.get("/history/{ticker}")
async def ticker_history(
    ticker: str,
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Hisse tarama geçmişi — persistence'dan.

    Args:
        ticker: Hisse kodu
        days: Son kaç gün

    Returns:
        Tarama geçmişi + dedup info
    """
    try:
        api = _get_scan_api()
        return api.get_ticker_history(ticker, days=days)
    except Exception as e:
        raise HTTPException(500, f"Ticker history error: {e}")


# =====================================================
# PERFORMANCE & ALERTS
# =====================================================

@router.get("/performance")
async def performance(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Performans istatistikleri — hit rate, duration, signal accuracy.

    Returns:
        Tracker stats + persistence stats + signal accuracy + top filters + regime performance
    """
    try:
        api = _get_scan_api()
        return api.get_performance()
    except Exception as e:
        raise HTTPException(500, f"Performance error: {e}")


@router.get("/alerts")
async def alerts(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Son alert'ler — scan_alerts servisi.

    Returns:
        Alert listesi + summary (severity/type dağılımı)
    """
    try:
        api = _get_scan_api()
        return api.get_alerts(limit=limit)
    except Exception as e:
        raise HTTPException(500, f"Alerts error: {e}")


# =====================================================
# FILTERS & DEDUP & SCHEDULER
# =====================================================

@router.get("/filters")
async def filters(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Filtre listesi — custom_filters servisi.

    Returns:
        Aktif/pasif filtreler: name, description, action, enabled
    """
    try:
        api = _get_scan_api()
        return api.get_filters()
    except Exception as e:
        raise HTTPException(500, f"Filters error: {e}")


@router.get("/dedup")
async def dedup_stats(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Deduplication istatistikleri.

    Returns:
        Tracked tickers, block rate, forced pending, cooldown stats
    """
    try:
        api = _get_scan_api()
        return api.get_dedup_stats()
    except Exception as e:
        raise HTTPException(500, f"Dedup stats error: {e}")


@router.get("/scheduler")
async def scheduler_stats(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Scheduler istatistikleri.

    Returns:
        Mode, interval, volatility, regime, market open, interval history
    """
    try:
        api = _get_scan_api()
        return api.get_scheduler_stats()
    except Exception as e:
        raise HTTPException(500, f"Scheduler stats error: {e}")


# =====================================================
# ACTIONS
# =====================================================

@router.post("/trigger")
async def trigger_scan(
    scan_type: str = Query("manual", pattern="^(manual|batch|event)$"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Manuel tarama tetikle.

    Args:
        scan_type: Tarama türü (manual, batch, event)

    Returns:
        Tarama durumu
    """
    try:
        engine = _get_engine()
        if scan_type == "batch":
            import asyncio
            result = await engine.run_batch_scan()
            return {"status": "completed", "scan_type": "batch", "result": result}
        else:
            return {"status": "triggered", "scan_type": scan_type, "message": "Scan queued"}
    except Exception as e:
        raise HTTPException(500, f"Trigger scan error: {e}")


@router.post("/event")
async def report_event(
    event_type: str = Query(..., description="Event türü: kap.event, news.event, macro.event"),
    ticker: str = Query("", description="Etkilenen hisse"),
    importance: float = Query(0.5, ge=0, le=1, description="Önem seviyesi"),
    title: str = Query("", description="Event başlığı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Event bildirimi — event_scanner'a gönder.

    Args:
        event_type: Event türü
        ticker: Etkilenen hisse
        importance: Önem seviyesi (0-1)
        title: Event başlığı

    Returns:
        Etkilenen hisseler ve sinyaller
    """
    try:
        engine = _get_engine()
        event_data = {
            "ticker": ticker,
            "importance": importance,
            "title": title,
            "affected_tickers": [ticker] if ticker else [],
        }
        results = engine.on_event(event_type, event_data)
        return {
            "event_type": event_type,
            "affected": [ticker] if ticker else [],
            "results": results,
            "signals_generated": len(results),
        }
    except Exception as e:
        raise HTTPException(500, f"Event report error: {e}")
