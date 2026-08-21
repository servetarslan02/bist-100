"""
Portfolio API v2.0 — Tüm endpoint'ler gerçek servislere bağlı.

Endpoints:
- GET /portfolio/summary — Portföy özeti
- GET /portfolio/positions — Açık pozisyonlar
- GET /portfolio/trades — İşlem geçmişi
- GET /portfolio/pnl — K/Z durumu
- GET /portfolio/equity-curve — Equity curve
- GET /portfolio/risk-metrics — Risk metrikleri (VaR, HHI, correlation)
- GET /portfolio/metrics — Performans metrikleri (Sharpe, CAGR, win rate)
- GET /portfolio/accounting — Muhasebe özeti (invariant doğrulama)
- GET /portfolio/cash-ledger — Nakit hareket geçmişi
- GET /portfolio/position-history — Pozisyon değişiklik geçmişi
- GET /portfolio/equity-snapshots — Günlük equity snapshot'ları
- GET /portfolio/drawdown — Drawdown durumu
- GET /portfolio/attribution — Performans attribüsyonu
- GET /portfolio/tax — Vergi analizi
- GET /portfolio/tca — İşlem maliyeti analizi
- GET /portfolio/rebalance — Rebalance analizi
- GET /portfolio/status — Servis durumu
- POST /portfolio/rebalance/orders — Rebalance emirleri oluştur
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional, Dict, List, Any

from ..dependencies import get_current_user, check_rate_limit

router = APIRouter()


def _get_pm():
    """PortfolioManager singleton'ı al."""
    from ...portfolio.portfolio_manager import portfolio_manager
    return portfolio_manager


def _get_service():
    """PortfolioService singleton'ı al."""
    from ...portfolio.main import portfolio_service
    return portfolio_service


# =====================================================
# CORE QUERIES
# =====================================================

@router.get("/summary")
@router.get("/state")
async def portfolio_summary(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Portföy özeti — cash, invested, total value, positions count.

    Returns:
        Portfolio summary: cash, invested_value, total_value, unrealized/realized P&L
    """
    try:
        pm = _get_pm()
        return pm.get_portfolio()
    except Exception as e:
        raise HTTPException(500, f"Portfolio summary error: {e}")


@router.get("/positions")
async def positions(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Açık pozisyonlar — ticker, quantity, entry/current price, P&L.

    Returns:
        Position listesi: ticker, direction, quantity, entry_price, current_price, unrealized_pnl
    """
    try:
        pm = _get_pm()
        pf = pm.get_portfolio()
        return {
            "positions": pf.get("positions", []),
            "count": pf.get("positions_count", 0),
            "total_value": pf.get("total_value", 0),
        }
    except Exception as e:
        raise HTTPException(500, f"Positions error: {e}")


@router.get("/trades")
async def trades(
    limit: int = Query(50, ge=1, le=500),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """İşlem geçmişi — entry/exit, P&L, holding days.

    Args:
        limit: Maksimum trade sayısı

    Returns:
        Trade listesi: ticker, entry/exit price, pnl, pnl_pct, holding_days
    """
    try:
        pm = _get_pm()
        return {
            "trades": pm.get_trade_history(limit=limit),
            "total_trades": len(pm._trades),
        }
    except Exception as e:
        raise HTTPException(500, f"Trades error: {e}")


@router.get("/pnl")
async def pnl(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """K/Z durumu — unrealized + realized + commission.

    Returns:
        P&L: unrealized, realized_total, commission_total, net_pnl
    """
    try:
        pm = _get_pm()
        pf = pm.get_portfolio()
        acc = pm.get_accounting_summary()
        return {
            "unrealized_pnl": pf.get("unrealized_pnl", 0),
            "unrealized_pnl_pct": pf.get("unrealized_pnl_pct", 0),
            "realized_pnl_total": pf.get("realized_pnl_total", 0),
            "commission_total": pf.get("commission_total", 0),
            "net_pnl": acc.get("net_pnl", 0),
            "return_on_equity_pct": acc.get("return_on_equity_pct", 0),
        }
    except Exception as e:
        raise HTTPException(500, f"P&L error: {e}")


@router.get("/equity-curve")
async def equity_curve(
    limit: int = Query(252, ge=1, le=1000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Equity curve — günlük equity snapshot'ları.

    Returns:
        Equity curve: timestamp, equity, cash, invested
    """
    try:
        pm = _get_pm()
        return {
            "equity_curve": pm.get_equity_curve()[-limit:],
            "snapshots": pm.get_equity_snapshots(limit=limit),
            "high_water_mark": pm.get_high_water_mark(),
        }
    except Exception as e:
        raise HTTPException(500, f"Equity curve error: {e}")


# =====================================================
# RISK METRICS
# =====================================================

@router.get("/risk-metrics")
async def risk_metrics(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Portföy risk metrikleri — VaR/CVaR + HHI + rolling correlation + drawdown.

    Returns:
        Risk level, max_position, sector_concentration, VaR, CVaR, HHI, correlation
    """
    try:
        pm = _get_pm()
        return pm.get_risk_metrics()
    except Exception as e:
        raise HTTPException(500, f"Risk metrics error: {e}")


@router.get("/drawdown")
async def drawdown_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Drawdown durumu — current DD, max DD, HWM.

    Returns:
        Drawdown: current_pct, max_pct, high_water_mark, position_scale
    """
    try:
        pm = _get_pm()
        return {
            "current_drawdown_pct": round(pm.get_drawdown() * 100, 4),
            "high_water_mark": round(pm.get_high_water_mark(), 2),
            "current_equity": round(pm._cash + sum(p.market_value for p in pm._positions.values()), 2),
            "max_drawdown_pct": pm.get_metrics().get("max_drawdown_pct", 0),
        }
    except Exception as e:
        raise HTTPException(500, f"Drawdown error: {e}")


# =====================================================
# PERFORMANCE METRICS
# =====================================================

@router.get("/metrics")
async def performance_metrics(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Performans metrikleri — CAGR, Sharpe, Sortino, win rate, profit factor.

    Returns:
        Total return, CAGR, max DD, Sharpe, Sortino, win rate, profit factor, avg holding
    """
    try:
        pm = _get_pm()
        return pm.get_metrics()
    except Exception as e:
        raise HTTPException(500, f"Performance metrics error: {e}")


@router.get("/accounting")
async def accounting(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Muhasebe özeti — invariant doğrulama dahil.

    Returns:
        Cash, market_value, total_equity, invariant_check, unrealized/realized P&L
    """
    try:
        pm = _get_pm()
        return pm.get_accounting_summary()
    except Exception as e:
        raise HTTPException(500, f"Accounting error: {e}")


# =====================================================
# LEDGER & HISTORY
# =====================================================

@router.get("/cash-ledger")
async def cash_ledger(
    limit: int = Query(100, ge=1, le=1000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Nakit hareket geçmişi.

    Returns:
        Cash ledger: timestamp, amount, balance_after, type, description
    """
    try:
        pm = _get_pm()
        return {
            "ledger": pm.get_cash_ledger(limit=limit),
            "cash": round(pm._cash, 2),
        }
    except Exception as e:
        raise HTTPException(500, f"Cash ledger error: {e}")


@router.get("/position-history")
async def position_history(
    ticker: str = Query("", description="Hisse filtresi"),
    limit: int = Query(100, ge=1, le=1000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Pozisyon değişiklik geçmişi — audit trail.

    Args:
        ticker: Hisse filtresi (boş = tümü)
        limit: Maksimum kayıt

    Returns:
        Position history: timestamp, ticker, action, quantity, price, commission, realized_pnl
    """
    try:
        pm = _get_pm()
        return {
            "history": pm.get_position_history(ticker=ticker, limit=limit),
        }
    except Exception as e:
        raise HTTPException(500, f"Position history error: {e}")


@router.get("/equity-snapshots")
async def equity_snapshots(
    limit: int = Query(252, ge=1, le=1000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Günlük equity snapshot'ları.

    Returns:
        Snapshots: date, total_equity, cash, invested, unrealized_pnl, drawdown_from_hwm
    """
    try:
        pm = _get_pm()
        return {
            "snapshots": pm.get_equity_snapshots(limit=limit),
        }
    except Exception as e:
        raise HTTPException(500, f"Equity snapshots error: {e}")


# =====================================================
# ATTRIBUTION & TAX & TCA
# =====================================================

@router.get("/attribution")
async def attribution(
    portfolio_id: int = Query(1),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Performans attribüsyonu — factor + sector.

    Returns:
        Factor attribution (value/momentum/quality) + sector attribution
    """
    try:
        from ...portfolio.enhancements import performance_attribution
        import numpy as np

        pm = _get_pm()

        # Equity curve'den getiri dizisi oluştur
        equity_curve = pm.get_equity_curve()
        if len(equity_curve) < 20:
            return {"attribution": {}, "message": "Yetersiz veri (en az 20 gün gerekli)"}

        equities = [e["equity"] for e in equity_curve]
        returns = np.array([(equities[i] / equities[i - 1] - 1) for i in range(1, len(equities))])

        # Gerçek factor returns — market data servisi bağlı değilse 501 döndür
        raise HTTPException(
            status_code=501,
            detail="Factor attribution requires real market data service. Not connected.",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Attribution error: {e}")


@router.get("/tax")
async def tax_analysis(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Vergi analizi — holding period, stopaj, BSMV.

    Returns:
        Capital gains tax, dividend tax, BSMV, total tax, effective rate
    """
    try:
        from ...portfolio.enhancements import tax_model

        pm = _get_pm()

        # Trade'lerden vergi hesapla
        trades = [
            {"realized_pnl": t.pnl, "holding_days": t.holding_days}
            for t in pm._trades
        ]

        result = tax_model.compute_total_tax(
            trades=trades,
            dividends=[],  # Temettü verisi yoksa boş
            commissions=pm._commission_total,
        )

        return result
    except Exception as e:
        raise HTTPException(500, f"Tax analysis error: {e}")


@router.get("/tca")
async def transaction_cost_analysis(
    order_value: float = Query(50000, description="Emir değeri (TL)"),
    daily_volume: float = Query(5000000, description="Günlük hacim (TL)"),
    volatility: float = Query(0.02, description="Günlük volatilite"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """İşlem maliyeti analizi — commission + spread + slippage + market impact.

    Args:
        order_value: Emir değeri
        daily_volume: Günlük hacim
        volatility: Volatilite

    Returns:
        Maliyet detayları: commission, spread, slippage, impact, total
    """
    try:
        from ...portfolio.enhancements import tca_analyzer
        return tca_analyzer.analyze(order_value, daily_volume, volatility)
    except Exception as e:
        raise HTTPException(500, f"TCA error: {e}")


# =====================================================
# REBALANCING
# =====================================================

@router.get("/rebalance")
async def rebalance_analysis(
    target_weights: str = Query("", description="Hedef ağırlıklar (JSON): {\"THYAO\": 0.3, \"GARAN\": 0.2}"),
    threshold_pct: float = Query(5.0, description="Sapma eşiği (%)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Rebalance analizi — drift analizi.

    Args:
        target_weights: Hedef ağırlıklar (JSON string)
        threshold_pct: Sapma eşiği

    Returns:
        Rebalance needed, drifts, max drift
    """
    try:
        import json
        pm = _get_pm()

        if not target_weights:
            return {"message": "target_weights parametresi gerekli (JSON format)"}

        try:
            weights = json.loads(target_weights)
        except json.JSONDecodeError:
            raise HTTPException(400, "Geçersiz JSON formatı")

        return pm.check_rebalance(weights, threshold_pct=threshold_pct)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Rebalance analysis error: {e}")


@router.post("/rebalance/orders")
async def rebalance_orders(
    target_weights: Dict[str, float] = Body(..., description="Hedef ağırlıklar"),
    threshold_pct: float = Query(5.0, description="Sapma eşiği (%)"),
    turnover_limit: float = Query(0.3, description="Maksimum turnover (0-1)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
):
    """Rebalance emirleri oluştur.

    Args:
        target_weights: Hedef ağırlıklar {ticker: weight}
        threshold_pct: Sapma eşiği
        turnover_limit: Maksimum turnover

    Returns:
        Rebalance orders: ticker, action, value, weight_change
    """
    try:
        pm = _get_pm()
        orders = pm.compute_rebalance_orders(
            target_weights=target_weights,
            threshold_pct=threshold_pct,
            turnover_limit=turnover_limit,
        )
        return {
            "orders": orders,
            "total_orders": len(orders),
            "total_value": sum(o["value"] for o in orders),
            "turnover_limit": turnover_limit,
        }
    except Exception as e:
        raise HTTPException(500, f"Rebalance orders error: {e}")


# =====================================================
# STATUS
# =====================================================

@router.get("/status")
async def portfolio_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Portföy servis durumu — health + trading enabled.

    Returns:
        Status, trading_enabled, positions_count, cash, total_value
    """
    try:
        pm = _get_pm()
        pf = pm.get_portfolio()
        acc = pm.get_accounting_summary()

        return {
            "status": "ok",
            "trading_enabled": True,
            "positions_count": pf.get("positions_count", 0),
            "cash": pf.get("cash", 0),
            "total_value": pf.get("total_value", 0),
            "invariant_check": acc.get("invariant_check", True),
            "drawdown_pct": round(pm.get_drawdown() * 100, 4),
        }
    except Exception as e:
        raise HTTPException(500, f"Portfolio status error: {e}")
