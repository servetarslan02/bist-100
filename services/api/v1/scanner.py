"""
Scanner API v2.0 â€” TÃ¼m endpoint'ler gerÃ§ek servislere baÄŸlÄ±.

Endpoints:
- GET /scanner/status â€” Tarama durumu (scheduler + dedup + scanner)
- GET /scanner/results â€” Son tarama sonuÃ§larÄ±
- GET /scanner/opportunities â€” En iyi fÄ±rsatlar
- GET /scanner/signals â€” Sinyal listesi
- GET /scanner/tiers â€” Tier bazlÄ± Ã¶zet
- GET /scanner/history/{ticker} â€” Hisse tarama geÃ§miÅŸi
- GET /scanner/performance â€” Performans istatistikleri
- GET /scanner/alerts â€” Son alert'ler
- GET /scanner/filters â€” Filtre listesi
- GET /scanner/dedup â€” Deduplication istatistikleri
- GET /scanner/scheduler â€” Scheduler istatistikleri
- GET /scanner/dashboard â€” Tam dashboard verisi
- POST /scanner/trigger â€” Manuel tarama tetikle
- POST /scanner/event â€” Event bildirimi
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional
from ..dependencies import get_current_user, check_rate_limit
from .schemas import ScannerStatus, OpportunityInfo, ErrorResponse
import structlog

logger = structlog.get_logger()
router = APIRouter()


def _get_scan_api():
    """Scan API singleton'Ä± al."""
    from ...scanner.scan_api import scan_api
    return scan_api


def _get_engine():
    """Alpha engine singleton'Ä± al."""
    from ...scanner.alpha_engine import alpha_engine
    return alpha_engine


@router.get("/signals")
@router.get("/opportunities")
async def scanner_signals(
    limit: int = Query(50, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    try:
        from ...scanner.bist_ml_scanner import bist_ml_scanner
        signals = bist_ml_scanner.scan_all_opportunities(limit=limit)
        return {"signals": signals, "count": len(signals)}
    except Exception as e:
        logger.error(f"bist_ml_scanner error: {e}")
        return {"signals": [], "count": 0}

# =====================================================
# STATUS & DASHBOARD
# =====================================================

@router.get("/status")
async def scan_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tarama durumu â€” scheduler + dedup + scanner Ã¶zeti.

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
    """Tam dashboard verisi â€” tÃ¼m modÃ¼llerin birleÅŸik Ã¶zeti.

    Returns:
        Status + results + tiers + performance + alerts + filters + dedup + scheduler
    """
    try:
        api = _get_scan_api()
        return api.get_full_dashboard()
    except Exception as e:
        raise HTTPException(500, f"Scanner dashboard error: {e}")


@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================
# RESULTS & OPPORTUNITIES
@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================

@router.get("/results")
async def scan_results(
    limit: int = Query(1000, ge=1, le=1000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Son tarama sonuÃ§larÄ±.

    Args:
        limit: Maksimum sonuÃ§ sayÄ±sÄ± (1-200)

    Returns:
        Son tarama sonuÃ§larÄ±: ticker, score, signal, direction, confidence, price, tier
    """
    try:
        api = _get_scan_api()
        return api.get_results(limit=limit)
    except Exception as e:
        raise HTTPException(500, f"Scanner results error: {e}")



@router.get("/opportunities")
async def scan_opportunities(
    limit: int = Query(1000, ge=1, le=1000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return []
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    tickers = [p["ticker"] for p in preds][:limit]
    yf_tickers = [f"{t}.IS" for t in tickers]
    try:
        raw = yf.download(yf_tickers, period="5d", interval="1d", group_by="ticker", auto_adjust=True, progress=False)
    except Exception:
        raw = None
        
    results = []
    for p in preds[:limit]:
        ticker = p["ticker"]
        score = p["score"]
        price = 0.0
        change = 0.0
        
        if raw is not None and ticker + ".IS" in raw.columns.levels[0]:
            df = raw[ticker + ".IS"].dropna()
            if len(df) >= 2:
                price = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                change = ((price - prev) / prev) * 100
                
        if score > 0.03:
            cat = "HIGH_CONVICTION"
            signal = "VOLUME_BREAKOUT"
        elif score > 0.015:
            cat = "MOMENTUM_LEADER"
            signal = "PULLBACK_BOUNCE"
        else:
            cat = "ALL"
            signal = "HOLD"
            
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        
        results.append({
            "symbol": ticker,
            "company_name": names.get(ticker, ticker),
            "price": round(price, 2),
            "change_pct": round(change, 2),
            "signal_type": signal,
            "spec_category": cat,
            "confidence_score": ui_score,
            "spec_reason": f"Phase 18 Otonom Karar (ExpRet: %{round(score*100,2)})",
            "detected_at": "Simdi"
        })
        
    return results



@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================
# TIERS & HISTORY
@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================

@router.get("/tiers")
async def tiers(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tier bazlÄ± Ã¶zet â€” Tier 0-5 daÄŸÄ±lÄ±mÄ± + top opportunities.

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
    """Hisse tarama geÃ§miÅŸi â€” persistence'dan.

    Args:
        ticker: Hisse kodu
        days: Son kaÃ§ gÃ¼n

    Returns:
        Tarama geÃ§miÅŸi + dedup info
    """
    try:
        api = _get_scan_api()
        return api.get_ticker_history(ticker, days=days)
    except Exception as e:
        raise HTTPException(500, f"Ticker history error: {e}")


@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================
# PERFORMANCE & ALERTS
@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================

@router.get("/performance")
async def performance(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Performans istatistikleri â€” hit rate, duration, signal accuracy.

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
    """Son alert'ler â€” scan_alerts servisi.

    Returns:
        Alert listesi + summary (severity/type daÄŸÄ±lÄ±mÄ±)
    """
    try:
        api = _get_scan_api()
        return api.get_alerts(limit=limit)
    except Exception as e:
        raise HTTPException(500, f"Alerts error: {e}")


@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================
# FILTERS & DEDUP & SCHEDULER
@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================

@router.get("/filters")
async def filters(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Filtre listesi â€” custom_filters servisi.

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


@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================
# ACTIONS
@router.get("/signals")
async def scanner_signals(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit)
):
    from ...core.redis_helper import get_cached
    import yfinance as yf
    from ...ingestion.bist_universe import BISTUniverse
    
    preds = get_cached("phase18:predictions")
    if not preds:
        return {"signals": []}
        
    uni = BISTUniverse()
    names = getattr(uni, 'COMPANY_NAMES', {})

    # Top 10 signals from highest score
    top_preds = sorted(preds, key=lambda x: x["score"], reverse=True)[:limit]
    
    signals = []
    for p in top_preds:
        ticker = p["ticker"]
        score = p["score"]
        
        ui_score = min(100, max(0, int((score + 0.05) * 1000)))
        signals.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "score": ui_score,
            "direction": "BUY",
            "risk_level": "Medium",
            "horizon": "Short Term",
            "expected_return_pct": round(score * 100, 2),
            "spec_category": "Phase 18 Otonom",
            "timestamp": "Simdi"
        })
        
    return {"signals": signals}

# =====================================================

@router.post("/trigger")
async def trigger_scan(
    scan_type: str = Query("manual", pattern="^(manual|batch|event)$"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Manuel tarama tetikle.

    Args:
        scan_type: Tarama tÃ¼rÃ¼ (manual, batch, event)

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
    event_type: str = Query(..., description="Event tÃ¼rÃ¼: kap.event, news.event, macro.event"),
    ticker: str = Query("", description="Etkilenen hisse"),
    importance: float = Query(0.5, ge=0, le=1, description="Ã–nem seviyesi"),
    title: str = Query("", description="Event baÅŸlÄ±ÄŸÄ±"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Event bildirimi â€” event_scanner'a gÃ¶nder.

    Args:
        event_type: Event tÃ¼rÃ¼
        ticker: Etkilenen hisse
        importance: Ã–nem seviyesi (0-1)
        title: Event baÅŸlÄ±ÄŸÄ±

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

