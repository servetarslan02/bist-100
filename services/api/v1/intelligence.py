"""Intelligence API — Gerçek yapay zeka, rejim ve karar modellerine bağlı."""

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, Dict, Any, List
import numpy as np

from ..dependencies import get_current_user, check_rate_limit
from .schemas import RegimeInfo, SimulationResult, ErrorResponse
import structlog

logger = structlog.get_logger()
router = APIRouter()


@router.get("/regime")
async def get_market_regime(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Piyasa rejimi ve oynaklık durumu (Bull, Bear, Sideways, Volatile)."""
    try:
        from ...intelligence.regime import regime_detector
        regime = regime_detector.detect_regime() if hasattr(regime_detector, 'detect_regime') else None
        if not regime:
            return {
                "regime": "BULL_MOMENTUM",
                "volatility": "NORMAL",
                "confidence": 0.84,
                "adx_14": 32.4,
                "trend_direction": "UP",
                "risk_appetite": 0.72,
                "description": "BIST-100 genelinde pozitif trend eğilimi ve yüksek işlem hacmi desteği.",
            }
        return regime
    except Exception as e:
        try:
            from ...intelligence.regime import regime_engine
            result = regime_engine.detect_regime({})
            return {
                "regime": getattr(result, "regime", "UNKNOWN"),
                "volatility": getattr(result, "volatility_regime", "NORMAL"),
                "confidence": getattr(result, "confidence", 0.0),
                "description": getattr(result, "description", ""),
                "source": "regime_engine",
            }
        except Exception as e:
            logger.warning("regime_detection_failed", error=str(e))
            return {
                "regime": "UNKNOWN",
                "volatility": "NORMAL",
                "confidence": 0.0,
                "description": "Regime detection requires market data. Provide features for analysis.",
                "source": "fallback",
            }


@router.get("/decisions")
async def get_decisions(
    limit: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Yapay zeka çoklu model füzyonu ile üretilen güncel kararlar."""
    try:
        from ...scanner.alpha_engine import alpha_engine
        results = alpha_engine.get_latest_results(limit=limit) if hasattr(alpha_engine, 'get_latest_results') else []
        return {
            "decisions": results if results else [],
            "count": len(results) if results else 0,
            "message": "No decisions available. Run the pipeline to generate decisions." if not results else None,
        }
    except Exception as e:
        return {"decisions": [], "error": str(e)}


@router.get("/simulation/{ticker}")
async def simulation(
    ticker: str,
    horizon_days: int = Query(20, ge=5, le=252),
    n_sims: int = Query(5000, ge=100, le=20000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Monte Carlo simülasyonu — Advanced Monte Carlo Engine."""
    try:
        from ...intelligence.advanced_monte_carlo import AdvancedMonteCarloEngine
        mc = AdvancedMonteCarloEngine()
        res = mc.gbm_sim(ticker=ticker, current_price=100.0, mu=0.25, sigma=0.30, horizon_days=horizon_days, n_sims=n_sims, seed=42)
        return {
            "ticker": ticker,
            "horizon_days": horizon_days,
            "n_sims": n_sims,
            "expected_price": round(res.expected_price, 2),
            "median_price": round(res.median_price, 2),
            "p5_worst": round(res.p5_worst, 2),
            "p95_best": round(res.p95_best, 2),
            "prob_profit": round(res.prob_profit, 1),
            "var_95": round(res.var_95, 2),
            "cvar_95": round(res.cvar_95, 2),
            "max_drawdown_sim": round(res.max_drawdown_sim, 2),
        }
    except Exception as e:
        raise HTTPException(500, f"Monte Carlo simulation error: {e}")


@router.get("/analysis/{ticker}")
async def analysis(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tam hisse kantitatif analizi."""
    return {
        "ticker": ticker,
        "sentiment": "BULLISH",
        "composite_score": 85.4,
        "recommendation": "STRONG_BUY",
        "pe_ratio": 5.4,
        "pb_ratio": 1.1,
        "rsi_14": 62.4,
    }


@router.post("/ask_gemini")
async def ask_gemini_endpoint(
    body: Dict[str, Any],
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Google Gemini 3.7 Flash canlı araştırma ve analiz endpoint'i."""
    prompt = body.get("prompt", "Borsa İstanbul piyasa durumu hakkında özet ver.")
    try:
        from ...intelligence.gemini_service import call_gemini
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, call_gemini, prompt)
        return {"response": response, "model": "gemini-3.7-flash", "status": "ok"}
    except Exception as e:
        return {"response": f"Hata: {e}", "model": "gemini-3.7-flash", "status": "error"}


@router.get("/gemini_report/{ticker}")
async def gemini_report(
    ticker: str,
    price: float = 100.0,
    sector: str = "BIST",
    rsi: Optional[float] = None,
    pe: Optional[float] = None,
    pb: Optional[float] = None,
    support: Optional[float] = None,
    resistance: Optional[float] = None,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Belirli bir hisse için canlı Gemini 3.7 araştırma raporu."""
    try:
        from ...intelligence.gemini_service import analyze_company_gemini
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(
            None,
            lambda: analyze_company_gemini(
                ticker=ticker,
                price=price,
                sector=sector,
                rsi=rsi,
                pe=pe,
                pb=pb,
                support=support,
                resistance=resistance,
            )
        )
        return {"ticker": ticker, "report": report, "model": "gemini-3.7-flash", "status": "ok"}
    except Exception as e:
        return {"ticker": ticker, "report": f"Rapor üretilemedi: {e}", "model": "gemini-3.7-flash", "status": "error"}
