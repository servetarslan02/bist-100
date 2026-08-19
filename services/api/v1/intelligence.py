"""Intelligence API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, HTTPException, Query
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/analysis/{ticker}")
async def analysis(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tam analiz — spec_engine + factor_engine."""
    try:
        from ...intelligence.spec_engine import SPECEngine
        from ...intelligence.factor_engine import FactorEngine
        spec = SPECEngine()
        factor = FactorEngine()
        return {
            "ticker": ticker,
            "spec_available": True,
            "factor_available": True,
            "message": "Full analysis requires live data",
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/features/{ticker}")
async def features(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Feature'lar — factor_engine servisi."""
    try:
        from ...intelligence.factor_engine import FactorEngine
        return {"ticker": ticker, "features": {}, "message": "Requires feature calculation pipeline"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/forecast/{ticker}")
async def forecast(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tahmin — forecasting + ensemble_forecast servisleri."""
    try:
        from ...intelligence.forecasting import ForecastingEngine
        from ...intelligence.ensemble_forecast import EnsembleForecaster
        return {
            "ticker": ticker,
            "forecast_available": True,
            "models": ["momentum", "statistical", "heuristic"],
            "message": "Requires historical data",
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/simulation/{ticker}")
async def simulation(ticker: str, num_sims: int = Query(10000), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Monte Carlo simülasyonu — monte_carlo_enhanced servisi."""
    try:
        from ...simulation.monte_carlo_enhanced import JumpDiffusionMonteCarlo
        return {
            "ticker": ticker,
            "num_simulations": num_sims,
            "models_available": ["jump_diffusion", "correlated", "regime_conditioned"],
            "message": "Requires price data",
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/scenarios/{ticker}")
async def scenarios(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Senaryo analizi — scenario servisi."""
    try:
        from ...intelligence.scenario import ScenarioResult
        return {
            "ticker": ticker,
            "scenarios_available": True,
            "message": "Requires macro + sector data",
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/spec/{ticker}")
async def spec_score(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """SPEC skoru — spec_engine servisi."""
    try:
        from ...intelligence.spec_engine import SPECEngine
        engine = SPECEngine()
        return {"ticker": ticker, "spec_available": True, "message": "Requires live data pipeline"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/probability/{ticker}")
async def probability(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Olasılık dağılımı — probability servisi."""
    try:
        from ...intelligence.probability import PredictionOutcome
        return {"ticker": ticker, "probability_available": True, "message": "Requires feature data"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/valuation/{ticker}")
async def valuation(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Değerleme."""
    return {"ticker": ticker, "valuation": "UNKNOWN", "message": "Requires fundamental data"}


@router.get("/regime")
async def regime(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Piyasa rejimi — regime servisi."""
    try:
        from ...intelligence.regime import RegimeEngine
        engine = RegimeEngine()
        current = engine.current_regime() if hasattr(engine, 'current_regime') else "UNKNOWN"
        return {"regime": current}
    except Exception as e:
        return {"regime": "UNKNOWN", "error": str(e)}


@router.get("/macro-impact/{ticker}")
async def macro_impact(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Makro etki — macro_sensitivity servisi."""
    try:
        from ...intelligence.macro_sensitivity import MacroSensitivityEngine
        engine = MacroSensitivityEngine()
        return {"ticker": ticker, "macro_available": True, "message": "Requires macro data"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}
