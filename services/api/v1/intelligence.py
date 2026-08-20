"""Intelligence API — Servis bağlantısı olmayan endpoint'ler 501 döndürür."""

from fastapi import APIRouter, Depends, HTTPException, Query
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/analysis/{ticker}")
async def analysis(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tam analiz — spec_engine + factor_engine."""
    raise HTTPException(
        status_code=501,
        detail=f"Full analysis for {ticker} not yet implemented. Intelligence pipeline not connected.",
    )


@router.get("/features/{ticker}")
async def features(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Feature'lar — factor_engine servisi."""
    raise HTTPException(
        status_code=501,
        detail=f"Feature computation for {ticker} not yet implemented. Run feature pipeline first.",
    )


@router.get("/forecast/{ticker}")
async def forecast(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tahmin — forecasting + ensemble_forecast servisleri."""
    raise HTTPException(
        status_code=501,
        detail=f"Forecast for {ticker} not yet implemented. Forecasting engine not connected.",
    )


@router.get("/simulation/{ticker}")
async def simulation(ticker: str, num_sims: int = Query(10000), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Monte Carlo simülasyonu — monte_carlo_enhanced servisi."""
    raise HTTPException(
        status_code=501,
        detail=f"Monte Carlo simulation for {ticker} not yet implemented. Simulation engine not connected.",
    )


@router.get("/scenarios/{ticker}")
async def scenarios(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Senaryo analizi — scenario servisi."""
    raise HTTPException(
        status_code=501,
        detail=f"Scenario analysis for {ticker} not yet implemented. Scenario engine not connected.",
    )


@router.get("/spec/{ticker}")
async def spec_score(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """SPEC skoru — spec_engine servisi."""
    raise HTTPException(
        status_code=501,
        detail=f"SPEC score for {ticker} not yet implemented. SPEC engine not connected.",
    )


@router.get("/probability/{ticker}")
async def probability(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Olasılık dağılımı — probability servisi."""
    raise HTTPException(
        status_code=501,
        detail=f"Probability distribution for {ticker} not yet implemented. Probability engine not connected.",
    )


@router.get("/valuation/{ticker}")
async def valuation(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Değerleme."""
    raise HTTPException(
        status_code=501,
        detail=f"Valuation for {ticker} not yet implemented. Fundamental data source not connected.",
    )


@router.get("/regime")
async def regime(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Piyasa rejimi — regime servisi."""
    try:
        from ...intelligence.regime import regime_engine
        current = regime_engine.get_current_regime() if hasattr(regime_engine, 'get_current_regime') else None
        if current is None:
            raise HTTPException(status_code=501, detail="Regime engine not initialized. Connect data source first.")
        return {"regime": current}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=501, detail=f"Regime engine not available: {e}")


@router.get("/macro-impact/{ticker}")
async def macro_impact(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Makro etki — macro_sensitivity servisi."""
    raise HTTPException(
        status_code=501,
        detail=f"Macro impact analysis for {ticker} not yet implemented. Macro data source not connected.",
    )
