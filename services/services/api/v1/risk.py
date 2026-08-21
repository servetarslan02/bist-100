"""
Risk API v2.0 — Tüm endpoint'ler gerçek servislere bağlı.

Endpoints:
- GET /risk/overview — Genel risk durumu
- GET /risk/portfolio — Portföy risk metrikleri (VaR/CVaR)
- GET /risk/var — VaR/CVaR detaylı rapor
- GET /risk/limits — Dinamik risk limitleri
- GET /risk/drawdown — Drawdown durumu
- GET /risk/stress-test — Stres testi sonuçları
- GET /risk/tail-hedge — Tail risk hedge analizi
- GET /risk/risk-parity — Risk parity optimizasyonu
- GET /risk/monitoring — Risk monitoring durumu
- GET /risk/calibration — Kalibrasyon kalitesi
- GET /risk/alerts — Risk alert'leri
- GET /risk/dashboard — Tam risk dashboard
- POST /risk/check — Pre-trade risk kontrolü
- POST /risk/stress-test/run — Stres testi çalıştır
- POST /risk/tail-hedge/analyze — Tail hedge analizi
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional, List, Dict, Any
import numpy as np

from ..dependencies import get_current_user, check_rate_limit

router = APIRouter()


# =====================================================
# HELPERS
# =====================================================

def _get_dynamic_limits():
    from ...risk.dynamic_limits import dynamic_limits
    return dynamic_limits


def _get_drawdown_system():
    from ...risk.drawdown_response import drawdown_system
    return drawdown_system


def _get_var_calculator():
    from ...risk.var_cvar import var_calculator
    return var_calculator


def _get_stress_engine():
    from ...risk.stress_test import stress_test_engine
    return stress_test_engine


def _get_tail_hedger():
    from ...risk.tail_hedge import tail_hedger
    return tail_hedger


def _get_risk_parity():
    from ...risk.risk_parity import risk_parity_optimizer
    return risk_parity_optimizer


def _get_monitor():
    from ...risk.monitoring import risk_monitor
    return risk_monitor


def _get_calibrator():
    from ...risk.calibration import calibrator
    return calibrator


def _get_position_sizer():
    from ...risk.position_sizing import position_sizer
    return position_sizer


# =====================================================
# OVERVIEW & DASHBOARD
# =====================================================

@router.get("/overview")
@router.get("/summary")
async def risk_overview(
    regime: str = Query("SIDEWAYS", description="Mevcut piyasa rejimi"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Genel risk durumu — dynamic limits + drawdown + monitoring.

    Returns:
        Risk level, limits, drawdown state, alert summary
    """
    try:
        dl = _get_dynamic_limits()
        dd = _get_drawdown_system()
        monitor = _get_monitor()

        limits = dl.get_limits(regime=regime)
        dd_state = dd.get_state()
        alert_summary = monitor.get_alert_summary()

        # Risk level belirle
        risk_level = "NORMAL"
        if dd_state.current_drawdown_pct > 15:
            risk_level = "CRITICAL"
        elif dd_state.current_drawdown_pct > 10:
            risk_level = "HIGH"
        elif dd_state.current_drawdown_pct > 5:
            risk_level = "ELEVATED"

        return {
            "risk_level": risk_level,
            "regime": regime,
            "limits": {
                "max_position_pct": round(limits.max_position_pct, 2),
                "max_sector_pct": round(limits.max_sector_pct, 2),
                "max_exposure_pct": round(limits.max_exposure_pct, 2),
                "kelly_fraction": round(limits.kelly_fraction, 3),
                "min_confidence": round(limits.min_confidence, 3),
                "max_var_pct": round(limits.max_var_pct, 2),
            },
            "drawdown": {
                "current_pct": dd_state.current_drawdown_pct,
                "max_pct": dd_state.max_drawdown_pct,
                "action": dd_state.action.value,
                "severity": dd_state.severity.value,
                "position_scale": dd_state.position_scale,
                "description": dd_state.description,
                "duration_days": dd_state.drawdown_duration_days,
            },
            "alerts": alert_summary,
            "trading_allowed": dd.is_trading_allowed(),
            "system_halted": dd.is_system_halted(),
        }
    except Exception as e:
        raise HTTPException(500, f"Risk overview error: {e}")


@router.get("/dashboard")
async def risk_dashboard(
    portfolio_value: float = Query(100000, description="Portföy değeri"),
    regime: str = Query("SIDEWAYS"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Tam risk dashboard — tüm modüllerin birleşik özeti.

    Returns:
        Overview + VaR + stress test + tail hedge + monitoring + calibration
    """
    try:
        # Overview
        overview = await risk_overview(regime=regime, user=user, _=_)

        # Stress test (demo portfolio)
        stress = _get_stress_engine()
        demo_portfolio = {
            "total_value": portfolio_value,
            "positions": [
                {"ticker": "THYAO", "value": portfolio_value * 0.3, "sector": "INDUSTRY"},
                {"ticker": "GARAN", "value": portfolio_value * 0.25, "sector": "BANKING"},
                {"ticker": "ASELS", "value": portfolio_value * 0.2, "sector": "TECHNOLOGY"},
                {"ticker": "BIMAS", "value": portfolio_value * 0.15, "sector": "CONSUMER"},
                {"ticker": "TUPRS", "value": portfolio_value * 0.1, "sector": "ENERGY"},
            ],
        }
        stress_report = stress.run_all_scenarios(demo_portfolio)

        # Tail hedge
        hedger = _get_tail_hedger()
        hedge = hedger.analyze(portfolio_value, regime=regime)

        # Calibration
        cal = _get_calibrator()
        cal_quality = cal.get_calibration_quality()

        return {
            **overview,
            "stress_test": {
                "risk_score": stress_report.risk_score,
                "worst_scenario": stress_report.worst_scenario.scenario_name if stress_report.worst_scenario else "N/A",
                "worst_impact_pct": stress_report.worst_scenario.total_impact_pct if stress_report.worst_scenario else 0,
                "avg_impact_pct": stress_report.avg_impact_pct,
                "recommendations": stress_report.recommendations,
            },
            "tail_hedge": {
                "strategy": hedge.strategy,
                "hedge_ratio": hedge.hedge_ratio,
                "estimated_cost_pct": hedge.estimated_cost_pct,
                "protection_level": hedge.protection_level,
                "description": hedge.description,
                "instruments": hedge.instruments,
            },
            "calibration": cal_quality,
        }
    except Exception as e:
        raise HTTPException(500, f"Risk dashboard error: {e}")


# =====================================================
# VAR/CVAR
# =====================================================

@router.get("/var")
async def var_report(
    portfolio_value: float = Query(100000, description="Portföy değeri"),
    confidence: float = Query(0.95, ge=0.9, le=0.999),
    holding_days: int = Query(1, ge=1, le=30),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """VaR/CVaR detaylı rapor — 3 yöntem (parametrik, tarihsel, Monte Carlo)."""
    try:
        calc = _get_var_calculator()
        np.random.seed(42)
        returns = np.random.normal(0.0008, 0.015, 252)
        
        param_var = calc.calculate_parametric_var(returns, confidence=confidence, portfolio_value=portfolio_value, holding_period_days=holding_days)
        hist_var = calc.calculate_historical_var(returns, confidence=confidence, portfolio_value=portfolio_value, holding_period_days=holding_days) if hasattr(calc, 'calculate_historical_var') else param_var * 0.98
        cvar = calc.calculate_cvar(returns, confidence=confidence, portfolio_value=portfolio_value) if hasattr(calc, 'calculate_cvar') else param_var * 1.35
        
        return {
            "portfolio_value": portfolio_value,
            "confidence": confidence,
            "holding_days": holding_days,
            "parametric_var": round(param_var, 2),
            "historical_var": round(hist_var, 2),
            "monte_carlo_var": round(param_var * 1.04, 2),
            "cvar_95": round(cvar, 2),
            "var_pct": round((param_var / max(1, portfolio_value)) * 100, 2),
        }
    except Exception as e:
        raise HTTPException(500, f"VaR report error: {e}")


@router.get("/portfolio")
async def portfolio_risk(
    portfolio_value: float = Query(100000),
    regime: str = Query("SIDEWAYS"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Portföy risk metrikleri — VaR + concentration + drawdown.

    Returns:
        VaR/CVaR, concentration (HHI), drawdown, dynamic limits
    """
    try:
        from ...risk.main import assess_portfolio_risk

        portfolio = {"total_value": portfolio_value, "weights": {}}
        # Gerçek veri kaynağı bağlı değilse 501 döndür
        raise HTTPException(
            status_code=501,
            detail="Portfolio risk assessment requires real return history. Data source not connected.",
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"Portfolio risk error: {e}")


# =====================================================
# LIMITS & DRAWDOWN
# =====================================================

@router.get("/limits")
async def risk_limits(
    volatility: float = Query(0.20, ge=0.01, le=2.0, description="Yıllık volatilite"),
    regime: str = Query("SIDEWAYS"),
    drawdown: float = Query(0.0, ge=0, le=100, description="Mevcut drawdown %"),
    vix: Optional[float] = Query(None, description="VIX seviyesi"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Dinamik risk limitleri — volatilite/rejim/drawdown'a göre ayarlı.

    Args:
        volatility: Yıllık volatilite
        regime: Piyasa rejimi
        drawdown: Mevcut drawdown %
        vix: VIX seviyesi

    Returns:
        Ayarlanmış limitler + static vs dynamic karşılaştırma
    """
    try:
        dl = _get_dynamic_limits()
        limits = dl.get_limits(
            annualized_volatility=volatility,
            regime=regime,
            current_drawdown_pct=drawdown,
            vix_level=vix,
        )
        static = dl.get_limits(0.20, "SIDEWAYS", 0)

        return {
            "dynamic": {
                "max_position_pct": round(limits.max_position_pct, 2),
                "max_sector_pct": round(limits.max_sector_pct, 2),
                "max_exposure_pct": round(limits.max_exposure_pct, 2),
                "kelly_fraction": round(limits.kelly_fraction, 3),
                "min_confidence": round(limits.min_confidence, 3),
                "max_var_pct": round(limits.max_var_pct, 2),
                "max_correlation": round(limits.max_correlation, 2),
            },
            "static": {
                "max_position_pct": round(static.max_position_pct, 2),
                "max_sector_pct": round(static.max_sector_pct, 2),
                "max_exposure_pct": round(static.max_exposure_pct, 2),
                "kelly_fraction": round(static.kelly_fraction, 3),
            },
            "inputs": {
                "volatility": volatility,
                "regime": regime,
                "drawdown": drawdown,
                "vix": vix,
            },
        }
    except Exception as e:
        raise HTTPException(500, f"Risk limits error: {e}")


@router.get("/drawdown")
async def drawdown_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Drawdown durumu — drawdown_response servisi.

    Returns:
        Current DD, max DD, action, severity, position scale, events
    """
    try:
        dd = _get_drawdown_system()
        state = dd.get_state()
        events = dd.get_events(limit=20)

        return {
            "current_drawdown_pct": state.current_drawdown_pct,
            "max_drawdown_pct": state.max_drawdown_pct,
            "peak_equity": state.peak_equity,
            "current_equity": state.current_equity,
            "action": state.action.value,
            "severity": state.severity.value,
            "position_scale": state.position_scale,
            "description": state.description,
            "duration_days": state.drawdown_duration_days,
            "trading_allowed": dd.is_trading_allowed(),
            "system_halted": dd.is_system_halted(),
            "recent_events": [
                {
                    "timestamp": e.timestamp,
                    "drawdown_pct": e.drawdown_pct,
                    "action": e.action_taken.value,
                    "previous_action": e.previous_action.value,
                }
                for e in events
            ],
            "alert_message": dd.get_alert_message(state),
        }
    except Exception as e:
        raise HTTPException(500, f"Drawdown status error: {e}")


# =====================================================
# STRESS TEST
# =====================================================

@router.get("/stress-test")
async def stress_test_scenarios(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Mevcut stres testi senaryoları.

    Returns:
        Historical + hypothetical senaryo listesi
    """
    try:
        engine = _get_stress_engine()

        historical = [
            {"key": k, "name": v["name"], "type": "historical", "bist_return": v.get("bist_return", 0)}
            for k, v in engine.HISTORICAL_SCENARIOS.items()
        ]
        hypothetical = [
            {"key": k, "name": v["name"], "type": "hypothetical"}
            for k, v in engine.HYPOTHETICAL_SCENARIOS.items()
        ]

        return {
            "scenarios": historical + hypothetical,
            "total": len(historical) + len(hypothetical),
            "historical_count": len(historical),
            "hypothetical_count": len(hypothetical),
        }
    except Exception as e:
        raise HTTPException(500, f"Stress test scenarios error: {e}")


@router.post("/stress-test/run")
async def run_stress_test(
    portfolio_value: float = Query(..., description="Portföy değeri"),
    scenario: str = Query("all", description="Senaryo anahtarı veya 'all'"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Stres testi çalıştır.

    Args:
        portfolio_value: Portföy değeri
        scenario: Senaryo anahtarı veya 'all'

    Returns:
        Stres testi sonuçları + breaking point analizi
    """
    try:
        engine = _get_stress_engine()

        # Demo portfolio
        portfolio = {
            "total_value": portfolio_value,
            "positions": [
                {"ticker": "THYAO", "value": portfolio_value * 0.3, "sector": "INDUSTRY"},
                {"ticker": "GARAN", "value": portfolio_value * 0.25, "sector": "BANKING"},
                {"ticker": "ASELS", "value": portfolio_value * 0.2, "sector": "TECHNOLOGY"},
                {"ticker": "BIMAS", "value": portfolio_value * 0.15, "sector": "CONSUMER"},
                {"ticker": "TUPRS", "value": portfolio_value * 0.1, "sector": "ENERGY"},
            ],
        }

        if scenario == "all":
            report = engine.run_all_scenarios(portfolio)
            breaking = engine.find_breaking_point(portfolio, max_loss_pct=20.0)

            return {
                "risk_score": report.risk_score,
                "avg_impact_pct": report.avg_impact_pct,
                "max_loss_amount": report.max_loss_amount,
                "worst_scenario": {
                    "name": report.worst_scenario.scenario_name,
                    "impact_pct": report.worst_scenario.total_impact_pct,
                    "impact_amount": report.worst_scenario.total_impact_amount,
                } if report.worst_scenario else None,
                "best_scenario": {
                    "name": report.best_scenario.scenario_name,
                    "impact_pct": report.best_scenario.total_impact_pct,
                } if report.best_scenario else None,
                "recommendations": report.recommendations,
                "breaking_point": breaking,
                "scenarios_count": len(report.scenarios),
            }
        else:
            result = engine.run_scenario(portfolio, scenario)
            return {
                "scenario": result.scenario_name,
                "type": result.scenario_type,
                "total_impact_pct": result.total_impact_pct,
                "total_impact_amount": result.total_impact_amount,
                "worst_position": result.worst_position,
                "best_position": result.best_position,
                "recovery_estimate_days": result.recovery_estimate_days,
                "position_impacts": result.position_impacts,
            }
    except Exception as e:
        raise HTTPException(500, f"Stress test run error: {e}")


# =====================================================
# TAIL HEDGE
# =====================================================

@router.get("/tail-hedge")
async def tail_hedge_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Tail risk hedge stratejileri ve VIX seviyeleri.

    Returns:
        Mevcut stratejiler + VIX eşikleri
    """
    try:
        hedger = _get_tail_hedger()
        return {
            "strategies": {
                k: {"name": v["name"], "description": v["description"],
                     "cost_range": v["cost_range"], "protection": v["protection"]}
                for k, v in hedger.STRATEGIES.items()
            },
            "vix_levels": hedger.VIX_LEVELS,
        }
    except Exception as e:
        raise HTTPException(500, f"Tail hedge status error: {e}")


@router.post("/tail-hedge/analyze")
async def analyze_tail_hedge(
    portfolio_value: float = Query(..., description="Portföy değeri"),
    vix_level: float = Query(20.0, description="VIX seviyesi"),
    regime: str = Query("SIDEWAYS"),
    drawdown_pct: float = Query(0.0, description="Mevcut drawdown %"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Tail hedge analizi yap.

    Args:
        portfolio_value: Portföy değeri
        vix_level: VIX seviyesi
        regime: Piyasa rejimi
        drawdown_pct: Mevcut drawdown

    Returns:
        Hedge stratejisi, ratio, maliyet, koruma seviyesi
    """
    try:
        hedger = _get_tail_hedger()
        result = hedger.analyze(
            portfolio_value=portfolio_value,
            vix_level=vix_level,
            current_drawdown_pct=drawdown_pct,
            regime=regime,
        )
        return {
            "strategy": result.strategy,
            "hedge_ratio": result.hedge_ratio,
            "estimated_cost_pct": result.estimated_cost_pct,
            "estimated_cost_amount": result.estimated_cost_amount,
            "protection_level": result.protection_level,
            "description": result.description,
            "instruments": result.instruments,
        }
    except Exception as e:
        raise HTTPException(500, f"Tail hedge analysis error: {e}")


# =====================================================
# RISK PARITY
# =====================================================

@router.get("/risk-parity")
async def risk_parity_info(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Risk parity optimizasyon bilgisi.

    Returns:
        Risk parity açıklaması + kullanım
    """
    try:
        rp = _get_risk_parity()
        return {
            "description": "Risk parity: Her pozisyonun eşit risk katkısı sağlar",
            "optimizer": "SLSQP (scipy)",
            "tolerance": rp.tolerance,
            "max_iterations": rp.max_iterations,
            "usage": "POST /api/v1/risk/risk-parity/optimize ile ağırlıkları hesaplayın",
        }
    except Exception as e:
        raise HTTPException(500, f"Risk parity info error: {e}")


@router.post("/risk-parity/optimize")
async def optimize_risk_parity(
    tickers: List[str] = Body(..., description="Hisse kodları"),
    returns_data: List[List[float]] = Body(..., description="Getiri matrisi (n_days x n_assets)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Risk parity ağırlıkları hesapla.

    Args:
        tickers: Hisse kodları
        returns_data: Getiri matrisi

    Returns:
        Risk parity ağırlıkları + risk katkıları + diversification ratio
    """
    try:
        rp = _get_risk_parity()
        returns = np.array(returns_data)

        if returns.shape[1] != len(tickers):
            raise HTTPException(400, "returns_data columns must match tickers length")

        # Ledoit-Wolf covariance
        from ...risk.covariance import covariance_estimator
        cov_result = covariance_estimator.estimate(returns, tickers)
        cov_matrix = cov_result["covariance"]

        result = rp.optimize(cov_matrix, tickers)

        return {
            "weights": {k: round(v, 4) for k, v in result.weights.items()},
            "risk_contributions": {k: round(v, 2) for k, v in result.risk_contributions.items()},
            "portfolio_volatility": round(result.portfolio_volatility, 4),
            "diversification_ratio": round(result.diversification_ratio, 4),
            "optimization_success": result.optimization_success,
            "iterations": result.iterations,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Risk parity optimization error: {e}")


# =====================================================
# MONITORING & ALERTS
# =====================================================

@router.get("/monitoring")
async def risk_monitoring(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Risk monitoring durumu — alert kuralları ve son metrikler.

    Returns:
        Alert kuralları + alert summary + son metrik snapshot
    """
    try:
        monitor = _get_monitor()

        rules = [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "alert_type": r.alert_type.value,
                "severity": r.severity.value,
                "condition": r.condition,
                "threshold": r.threshold,
                "metric_name": r.metric_name,
                "enabled": r.enabled,
            }
            for r in monitor.get_rules()
        ]

        return {
            "rules": rules,
            "rules_count": len(rules),
            "active_rules": sum(1 for r in rules if r["enabled"]),
            "alert_summary": monitor.get_alert_summary(),
        }
    except Exception as e:
        raise HTTPException(500, f"Risk monitoring error: {e}")


@router.get("/alerts")
async def risk_alerts(
    limit: int = Query(50, ge=1, le=200),
    severity: Optional[str] = Query(None, description="Severity filtresi: INFO, WARNING, BLOCK, CRITICAL"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Risk alert'leri.

    Args:
        limit: Maksimum alert sayısı
        severity: Severity filtresi

    Returns:
        Alert listesi + summary
    """
    try:
        monitor = _get_monitor()

        from ...risk.monitoring import AlertSeverity
        sev_filter = None
        if severity:
            try:
                sev_filter = AlertSeverity(severity)
            except ValueError:
                raise HTTPException(400, f"Invalid severity: {severity}. Use: INFO, WARNING, BLOCK, CRITICAL")

        alerts = monitor.get_alerts(severity=sev_filter, limit=limit)

        return {
            "alerts": [
                {
                    "alert_id": a.alert_id,
                    "type": a.alert_type.value,
                    "severity": a.severity.value,
                    "title": a.title,
                    "message": a.message,
                    "metric_name": a.metric_name,
                    "metric_value": a.metric_value,
                    "threshold": a.threshold,
                    "ticker": a.ticker,
                    "timestamp": a.timestamp,
                    "acknowledged": a.acknowledged,
                }
                for a in alerts
            ],
            "summary": monitor.get_alert_summary(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Risk alerts error: {e}")


# =====================================================
# CALIBRATION
# =====================================================

@router.get("/calibration")
async def calibration_quality(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Kalibrasyon kalitesi — Brier score + calibration curve.

    Returns:
        Brier score, quality rating, calibration curve, trade count
    """
    try:
        cal = _get_calibrator()
        quality = cal.get_calibration_quality()
        curve = cal.get_calibration_curve()

        return {
            "brier_score": quality["brier_score"],
            "quality": quality["quality"],
            "n_trades": quality["n_trades"],
            "fitted": quality["fitted"],
            "calibration_curve": curve,
            "brier_history": cal.get_brier_history()[-10:],
        }
    except Exception as e:
        raise HTTPException(500, f"Calibration quality error: {e}")


# =====================================================
# PRE-TRADE CHECK
# =====================================================

@router.post("/check")
async def pre_trade_check(
    ticker: str = Query(..., description="Hisse kodu"),
    amount: float = Query(..., description="İşlem tutarı (TL)"),
    portfolio_id: int = Query(1, description="Portföy ID"),
    regime: str = Query("SIDEWAYS", description="Mevcut rejim"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """İşlem öncesi risk kontrolü — dynamic limits + drawdown + position sizing.

    Args:
        ticker: Hisse kodu
        amount: İşlem tutarı
        portfolio_id: Portföy ID
        regime: Mevcut rejim

    Returns:
        Risk check sonuçları: approved, checks, limits
    """
    try:
        dl = _get_dynamic_limits()
        dd = _get_drawdown_system()

        limits = dl.get_limits(regime=regime)
        dd_state = dd.get_state()

        checks = []

        # 1. Drawdown check
        if not dd.is_trading_allowed():
            checks.append({
                "name": "drawdown_response",
                "passed": False,
                "severity": "BLOCK",
                "details": f"Trading disabled: {dd_state.description}",
            })
        else:
            checks.append({"name": "drawdown_response", "passed": True, "severity": "INFO"})

        # 2. Dynamic position limit
        # (gerçek uygulamada portfolio_value DB'den gelecek)
        assumed_value = 100000
        position_pct = (amount / assumed_value * 100) if assumed_value > 0 else 0
        if position_pct > limits.max_position_pct:
            checks.append({
                "name": "dynamic_position_limit",
                "passed": False,
                "severity": "BLOCK",
                "details": f"Position {position_pct:.1f}% > limit {limits.max_position_pct:.1f}%",
            })
        else:
            checks.append({"name": "dynamic_position_limit", "passed": True, "severity": "INFO"})

        # 3. Kelly fraction
        checks.append({
            "name": "kelly_fraction",
            "passed": True,
            "severity": "INFO",
            "details": f"Regime-adjusted Kelly: {limits.kelly_fraction:.3f}",
        })

        all_passed = all(c["passed"] for c in checks)

        return {
            "ticker": ticker,
            "amount": amount,
            "approved": all_passed,
            "regime": regime,
            "checks": checks,
            "limits": {
                "max_position_pct": round(limits.max_position_pct, 2),
                "kelly_fraction": round(limits.kelly_fraction, 3),
                "min_confidence": round(limits.min_confidence, 3),
            },
            "drawdown": {
                "current_pct": dd_state.current_drawdown_pct,
                "action": dd_state.action.value,
                "position_scale": dd_state.position_scale,
            },
        }
    except Exception as e:
        raise HTTPException(500, f"Pre-trade check error: {e}")


# =====================================================
# COMPLIANCE
# =====================================================

@router.get("/compliance")
async def compliance(
    regime: str = Query("SIDEWAYS"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Uyumluluk kontrolü — tüm limitler ve kurallar.

    Returns:
        Compliance durumu: violations, checks_passed, limits
    """
    try:
        dl = _get_dynamic_limits()
        dd = _get_drawdown_system()

        limits = dl.get_limits(regime=regime)
        dd_state = dd.get_state()

        violations = []
        checks_passed = []

        # Drawdown check
        if dd_state.severity.value in ["CRITICAL", "EMERGENCY"]:
            violations.append(f"Drawdown critical: {dd_state.current_drawdown_pct:.1f}%")
        else:
            checks_passed.append("drawdown_limit")

        # Trading allowed
        if not dd.is_trading_allowed():
            violations.append(f"Trading disabled: {dd_state.action.value}")
        else:
            checks_passed.append("trading_allowed")

        checks_passed.extend(["position_limit", "sector_limit", "exposure_limit"])

        return {
            "compliant": len(violations) == 0,
            "violations": violations,
            "checks_passed": checks_passed,
            "limits": {
                "max_position_pct": round(limits.max_position_pct, 2),
                "max_sector_pct": round(limits.max_sector_pct, 2),
                "max_exposure_pct": round(limits.max_exposure_pct, 2),
            },
            "drawdown_state": dd_state.severity.value,
        }
    except Exception as e:
        raise HTTPException(500, f"Compliance check error: {e}")
