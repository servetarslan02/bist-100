"""Zekâ API — Yapay zeka, rejim tespiti ve karar modellerine bağlı uç noktalar."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/regime")
async def get_market_regime(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Piyasa rejimi ve oynaklık durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Rejim türü, oynaklık, güven skoru ve trend bilgisi.

    Raises:
        HTTPException: Rejim tespiti yapılamazsa 503 hatası döner.
    """
    try:
        from ...intelligence.regime import regime_detector

        regime = regime_detector.detect_regime() if hasattr(regime_detector, "detect_regime") else None
        if regime:
            return regime
    except Exception as exc:
        logger.warning("regime_detector_hatasi: hata=%s", exc)

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
    except Exception as exc:
        logger.error("rejim_tespiti_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Piyasa rejimi tespit edilemedi: {exc}",
        ) from exc


@router.get("/decisions")
async def get_decisions(
    limit: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Yapay zeka çoklu model füzyonu ile üretilen güncel kararları döndürür.

    Args:
        limit: Maksimum karar sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Karar listesi ve sayısı.
    """
    try:
        from ...scanner.alpha_scanner import alpha_scanner as alpha_engine

        results = alpha_engine.get_latest_results(limit=limit) if hasattr(alpha_engine, "get_latest_results") else []
        return {
            "decisions": results if results else [],
            "count": len(results) if results else 0,
            "message": "Henüz karar üretilmedi. Pipeline çalıştırılmalı." if not results else None,
        }
    except Exception as exc:
        logger.error("karar_getirme_hatasi: hata=%s", exc)
        return {"decisions": [], "error": str(exc)}


@router.get("/simulation/{ticker}")
async def simulation(
    ticker: str,
    horizon_days: int = Query(20, ge=5, le=252),
    n_sims: int = Query(5000, ge=100, le=20000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Monte Carlo simülasyonu çalıştırır.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        horizon_days: Simülasyon ufku (gün).
        n_sims: Simülasyon sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Beklenen fiyat, medyan, percentiller, kâr olasılığı ve risk metrikleri.

    Raises:
        HTTPException: Fiyat bulunamazsa veya simülasyon başarısız olursa hata döner.
    """
    try:
        from ...intelligence.advanced_monte_carlo import AdvancedMonteCarloEngine
        from ...core.redis_helper import get_cached

        mc = AdvancedMonteCarloEngine()

        live_price = get_cached(f"price:{ticker}")
        current_price = float(live_price.get("price", 0)) if live_price else 0
        if current_price <= 0:
            raise HTTPException(
                status_code=404,
                detail=f"{ticker} için canlı fiyat bulunamadı.",
            )

        # Tarihsel volatilite ve getiri — gerçek veriden hesaplanmalı
        import yfinance as yf
        import numpy as np

        sym_is = f"{ticker.upper()}.IS" if not ticker.upper().endswith(".IS") else ticker.upper()
        data = yf.download(sym_is, period="3mo", interval="1d", auto_adjust=True, progress=False)
        if data.empty or "Close" not in data:
            raise HTTPException(
                status_code=503,
                detail=f"{ticker} için tarihsel veri bulunamadı.",
            )

        close = data["Close"].dropna()
        if len(close) < 20:
            raise HTTPException(
                status_code=503,
                detail=f"{ticker} için yeterli tarihsel veri yok.",
            )

        daily_returns = close.pct_change().dropna()
        mu = float(daily_returns.mean() * 252)  # Yıllık getiri
        sigma = float(daily_returns.std() * np.sqrt(252))  # Yıllık volatilite

        res = mc.gbm_sim(
            ticker=ticker,
            current_price=current_price,
            mu=mu,
            sigma=sigma,
            horizon_days=horizon_days,
            n_sims=n_sims,
            seed=42,
        )
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
            "mu_annual": round(mu, 4),
            "sigma_annual": round(sigma, 4),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("simulasyon_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Monte Carlo simülasyonu başarısız: {exc}",
        ) from exc


@router.get("/analysis/{ticker}")
async def analysis(
    ticker: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Hisse kantitatif analizini döndürür.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sentiment, bileşik skor, tavsiye ve temel oranlar.

    Raises:
        HTTPException: Analiz yapılamazsa hata döner.
    """
    try:
        from ...core.redis_helper import get_cached

        radar = get_cached("radar:data") or []
        item = next((x for x in radar if x.get("symbol") == ticker.upper()), None)

        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"{ticker} için analiz verisi bulunamadı.",
            )

        score = item.get("score", 50.0)
        change = item.get("change", 0.0)

        if score >= 80:
            recommendation = "STRONG_BUY"
            sentiment = "BULLISH"
        elif score >= 65:
            recommendation = "BUY"
            sentiment = "BULLISH"
        elif score >= 50:
            recommendation = "HOLD"
            sentiment = "NEUTRAL"
        elif score >= 35:
            recommendation = "SELL"
            sentiment = "BEARISH"
        else:
            recommendation = "STRONG_SELL"
            sentiment = "BEARISH"

        return {
            "ticker": ticker.upper(),
            "sentiment": sentiment,
            "composite_score": round(score, 1),
            "recommendation": recommendation,
            "change_pct": round(change, 2),
            "source": "radar_cache",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analiz_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Analiz yapılamadı: {exc}",
        ) from exc


@router.post("/ask_gemini")
async def ask_gemini_endpoint(
    body: dict[str, Any],
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Google Gemini ile canlı araştırma ve analiz yapar.

    Args:
        body: İstek gövdesi (prompt alanı).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Gemini yanıtı, model adı ve durum.

    Raises:
        HTTPException: Gemini çağrısı başarısız olursa hata döner.
    """
    prompt = body.get("prompt", "Borsa İstanbul piyasa durumu hakkında özet ver.")
    try:
        from ...intelligence.gemini_service import call_gemini

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, call_gemini, prompt)
        return {"response": response, "model": "gemini-3.7-flash", "status": "ok"}
    except Exception as exc:
        logger.error("gemini_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Gemini servisi yanıt vermedi: {exc}",
        ) from exc


@router.get("/gemini_report/{ticker}")
async def gemini_report(
    ticker: str,
    price: float = 100.0,
    sector: str = "BIST",
    rsi: float | None = None,
    pe: float | None = None,
    pb: float | None = None,
    support: float | None = None,
    resistance: float | None = None,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Belirli bir hisse için Gemini araştırma raporu üretir.

    Args:
        ticker: Hisse sembolü.
        price: Güncel fiyat.
        sector: Sektör.
        rsi: RSI değeri.
        pe: F/K oranı.
        pb: PD/DD oranı.
        support: Destek seviyesi.
        resistance: Direnç seviyesi.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Araştırma raporu, model adı ve durum.

    Raises:
        HTTPException: Rapor üretilemezse hata döner.
    """
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
            ),
        )
        return {"ticker": ticker, "report": report, "model": "gemini-3.7-flash", "status": "ok"}
    except Exception as exc:
        logger.error("gemini_rapor_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Gemini raporu üretilemedi: {exc}",
        ) from exc
