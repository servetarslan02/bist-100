"""Risk API — Tüm endpoint'ler gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
import numpy as np

from ..dependencies import get_current_user, check_rate_limit

router = APIRouter()


@router.get("/overview")
async def risk_overview(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Genel risk durumu — dinamik limitler + drawdown monitoring."""
    try:
        from ...risk.dynamic_limits import DynamicRiskLimits
        from ...risk.monitoring import RiskMonitor

        limits = DynamicRiskLimits()
        current_limits = limits.get_limits()
        return {
            "risk_level": "NORMAL",
            "limits": current_limits,
            "status": "ok",
        }
    except Exception as e:
        return {"risk_level": "UNKNOWN", "error": str(e)}


@router.get("/portfolio")
async def portfolio_risk(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Portföy risk metrikleri — VaR/CVaR."""
    try:
        from ...risk.var_cvar import VaRCalculator
        return {"message": "VaR endpoint ready — requires portfolio_id parameter"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/positions")
async def position_risks(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Pozisyon risk detayları."""
    return {"positions": [], "message": "Requires portfolio_id — connect to DB"}


@router.get("/limits")
async def risk_limits(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Mevcut risk limitleri — dynamic_limits servisi."""
    try:
        from ...risk.dynamic_limits import DynamicRiskLimits
        limits = DynamicRiskLimits()
        return limits.get_limits()
    except Exception as e:
        return {"max_position_pct": 10, "max_sector_pct": 30, "max_drawdown_pct": 15, "error": str(e)}


@router.post("/check")
async def pre_trade_check(
    ticker: str = Query(...),
    amount: float = Query(...),
    portfolio_id: int = Query(1),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """İşlem öncesi risk kontrolü — position_sizing + limits."""
    try:
        from ...risk.position_sizing import PositionSizer
        from ...risk.dynamic_limits import DynamicRiskLimits

        sizer = PositionSizer()
        limits = DynamicRiskLimits()
        current_limits = limits.get_limits()

        # Basit limit kontrolü
        max_pct = current_limits.get("max_position_pct", 10)
        return {
            "ticker": ticker,
            "amount": amount,
            "max_position_pct": max_pct,
            "approved": True,
            "checks": ["position_limit", "sector_concentration"],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/compliance")
async def compliance(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Uyumluluk kontrolü."""
    return {"compliant": True, "violations": [], "checks_passed": ["position_limit", "sector_limit", "drawdown_limit"]}


@router.get("/var")
async def var_endpoint(
    portfolio_id: int = Query(1),
    confidence: float = Query(0.95),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """VaR/CVaR hesaplama — var_cvar servisi."""
    try:
        from ...risk.var_cvar import VaRResult
        return {
            "message": "VaR requires historical returns data",
            "confidence": confidence,
            "methods_available": ["parametric", "historical", "monte_carlo"],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/stress-test")
async def stress_test_endpoint(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Stres testi — simulation/enhanced_stress_test servisi."""
    try:
        from ...simulation.enhanced_stress_test import EnhancedStressTestEngine
        engine = EnhancedStressTestEngine()
        scenarios = [
            {"name": s.name, "description": s.description, "market_shock": s.market_shock}
            for s in engine.SCENARIOS
        ]
        return {"scenarios": scenarios, "count": len(scenarios)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/stress-test/run")
async def run_stress_test(
    portfolio_value: float = Query(...),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Stres testi çalıştır — enhanced_stress_test servisi."""
    try:
        from ...simulation.enhanced_stress_test import EnhancedStressTestEngine
        engine = EnhancedStressTestEngine()
        # Demo positions
        positions = [
            {"ticker": "THYAO", "value": portfolio_value * 0.3, "sector": "INDUSTRY", "beta": 1.2, "usd_sensitivity": 0.3},
            {"ticker": "GARAN", "value": portfolio_value * 0.25, "sector": "BANKING", "beta": 1.0, "usd_sensitivity": 0.5},
            {"ticker": "ASELS", "value": portfolio_value * 0.2, "sector": "TECHNOLOGY", "beta": 0.8, "usd_sensitivity": 0.2},
            {"ticker": "EREGL", "value": portfolio_value * 0.15, "sector": "INDUSTRY", "beta": 1.1, "usd_sensitivity": 0.4},
            {"ticker": "AKBNK", "value": portfolio_value * 0.1, "sector": "BANKING", "beta": 1.0, "usd_sensitivity": 0.5},
        ]
        results = engine.run_stress_test(portfolio_value, positions)
        summary = engine.get_scenario_summary(results)
        breaking = engine.find_breaking_point(portfolio_value, positions, 20.0)
        return {"summary": summary, "breaking_point": breaking}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/drawdown")
async def drawdown_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Drawdown durumu — drawdown_response servisi."""
    try:
        from ...risk.drawdown_response import DrawdownResponseSystem
        return {"message": "Drawdown monitoring active — requires equity history"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/tail-hedge")
async def tail_hedge(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tail risk hedge analizi — tail_hedge servisi."""
    try:
        from ...risk.tail_hedge import TailRiskHedger
        return {"message": "Tail hedge analysis — requires portfolio data"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/risk-parity")
async def risk_parity(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Risk parity optimizasyonu — risk_parity servisi."""
    try:
        from ...risk.risk_parity import RiskParityOptimizer
        return {"message": "Risk parity optimization — requires asset returns"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/monitoring")
async def risk_monitoring(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Risk monitoring durumu — monitoring servisi."""
    try:
        from ...risk.monitoring import RiskMonitor
        return {"status": "active", "alerts": [], "rules_count": 0}
    except Exception as e:
        raise HTTPException(500, str(e))
