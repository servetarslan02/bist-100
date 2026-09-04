"""Portföy API — Tüm endpoint'ler gerçek servislere bağlı."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import orjson
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from ..dependencies import check_rate_limit, get_current_user
from ...core.swr_cache import SWRCache

logger = logging.getLogger(__name__)

router = APIRouter()

_alpha_signals_cache = SWRCache(ttl_seconds=300)


def _get_pm() -> Any:
    """Tekil gerçeklik kaynağı: paper_orchestrator VirtualPortfolio.

    Returns:
        Any: VirtualPortfolio örneği.
    """
    from ...paper_trading.paper_orchestrator import paper_orchestrator

    paper_orchestrator.portfolio.load_from_store()
    return paper_orchestrator.portfolio


# =====================================================
# CORE QUERIES
# =====================================================


@router.get("")
@router.get("/")
@router.get("/summary")
@router.get("/state")
async def portfolio_summary(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Portföy özeti döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Nakit, yatırılan, toplam değer ve pozisyon sayısı.
    """
    try:
        pm = _get_pm()
        summary = pm.get_summary()
        return {
            **summary,
            "positions_count": summary.get("num_positions", 0),
            "positions": pm.get_all_positions(),
        }
    except Exception as exc:
        logger.error("portfoy_ozet_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Portföy özeti alınamadı: {exc}") from exc


@router.get("/positions")
async def positions(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Açık pozisyonları döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Pozisyon listesi, sayısı ve toplam değer.
    """
    try:
        pm = _get_pm()
        pos_list = pm.get_all_positions()
        total_val = pm.get_total_value()
        return {"positions": pos_list, "count": len(pos_list), "total_value": total_val}
    except Exception as exc:
        logger.error("pozisyon_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Pozisyonlar alınamadı: {exc}") from exc


@router.get("/trades")
async def trades(
    limit: int = Query(50, ge=1, le=500, description="Maksimum işlem sayısı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """İşlem geçmişini döndürür.

    Args:
        limit: Maksimum işlem sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: İşlem listesi ve toplam işlem sayısı.
    """
    try:
        pm = _get_pm()
        all_trades = pm.get_trades()
        return {"trades": all_trades[-limit:], "total_trades": len(all_trades)}
    except Exception as exc:
        logger.error("islem_gecmisi_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"İşlem geçmişi alınamadı: {exc}") from exc


@router.get("/pnl")
async def pnl(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """K/Z durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Gerçekleşmemiş, gerçekleşmiş K/Z ve komisyon.
    """
    try:
        pm = _get_pm()
        summary = pm.get_summary()
        return {
            "unrealized_pnl": summary.get("unrealized_pnl", 0.0),
            "unrealized_pnl_pct": summary.get("unrealized_pnl_pct", 0.0),
            "realized_pnl_total": summary.get("realized_pnl_total", summary.get("total_pnl", 0.0)),
            "commission_total": summary.get("total_commission", 0.0),
            "net_pnl": summary.get("total_pnl", 0.0),
            "return_on_equity_pct": summary.get("total_pnl_pct", 0.0),
        }
    except Exception as exc:
        logger.error("pnl_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"K/Z verisi alınamadı: {exc}") from exc


@router.get("/equity-curve")
async def equity_curve(
    limit: int = Query(252, ge=1, le=1000, description="Maksimum veri noktası"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Equity curve verisini döndürür.

    Args:
        limit: Maksimum veri noktası.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Equity curve, snapshot'lar ve yüksek su işareti.
    """
    try:
        pm = _get_pm()
        curve = pm.get_equity_curve()
        sliced = curve[-limit:]
        return {
            "equity_curve": sliced,
            "snapshots": sliced,
            "high_water_mark": max(
                [pt.get("total_value", 0.0) for pt in sliced],
                default=pm.initial_capital,
            ),
        }
    except Exception as exc:
        logger.error("equity_curve_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Equity curve alınamadı: {exc}") from exc


# =====================================================
# RISK METRICS
# =====================================================


@router.get("/risk-metrics")
async def risk_metrics(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Portföy risk metriklerini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Max drawdown, pozisyon sayısı, nakit oranı ve yerleşmemiş nakit.
    """
    try:
        pm = _get_pm()
        summary = pm.get_summary()
        return {
            "max_drawdown_pct": summary.get("max_drawdown_pct", 0.0),
            "positions_count": summary.get("num_positions", 0),
            "cash_ratio": summary.get("cash", 0.0) / max(abs(summary.get("total_value", 1.0)), 1.0),
            "settled_cash": summary.get("settled_cash", 0.0),
            "unsettled_t1": summary.get("unsettled_cash_t1", 0.0),
            "unsettled_t2": summary.get("unsettled_cash_t2", 0.0),
        }
    except Exception as exc:
        logger.error("risk_metrik_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Risk metrikleri alınamadı: {exc}") from exc


@router.get("/drawdown")
async def drawdown(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Drawdown durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Max ve güncel drawdown yüzdesi.
    """
    try:
        pm = _get_pm()
        summary = pm.get_summary()
        return {
            "max_drawdown_pct": summary.get("max_drawdown_pct", 0.0),
            "current_drawdown_pct": summary.get("current_drawdown_pct", 0.0),
        }
    except Exception as exc:
        logger.error("drawdown_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Drawdown verisi alınamadı: {exc}") from exc


# =====================================================
# PERFORMANCE & ACCOUNTING METRICS
# =====================================================


@router.get("/metrics")
async def performance_metrics(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Performans metriklerini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sharpe, CAGR, win rate, profit factor ve diğer metrikler.

    Raises:
        HTTPException: Metrikler alınamazsa 500 hatası döner.
    """
    try:
        from ...paper_trading.paper_orchestrator import paper_orchestrator

        report = paper_orchestrator.get_full_report()
        perf = report.get("performance_metrics", {})
        if not perf or "error" in perf:
            raise HTTPException(
                status_code=503,
                detail="Performans metrikleri hesaplanamadı. Yeterli işlem verisi yok.",
            )
        return {
            **perf,
            "sharpe_ratio": perf.get("sharpe", perf.get("sharpe_ratio", 0.0)),
            "max_drawdown": perf.get("max_drawdown_pct", perf.get("max_drawdown", 0.0)),
            "win_rate": perf.get("win_rate", 0.0),
            "avg_holding_days": perf.get("avg_holding_days", 0.0),
            "total_trades": perf.get("total_trades", 0),
            "profit_factor": perf.get("profit_factor", 0.0),
            "calmar_ratio": perf.get("calmar_ratio", 0.0),
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("performans_metrik_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Performans metrikleri alınamadı: {exc}") from exc


@router.get("/accounting")
async def accounting(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Muhasebe özetini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Nakit, yatırılan, toplam değer ve K/Z bilgileri.
    """
    try:
        pm = _get_pm()
        summary = pm.get_summary()

        # Doğrulama: total_value = cash + invested_value
        cash = summary.get("cash", 0.0)
        invested = summary.get("invested_value", 0.0)
        total = summary.get("total_value", 0.0)
        invariant_ok = abs(total - (cash + invested)) < 0.01

        return {
            "cash": cash,
            "settled_cash": summary.get("settled_cash", 0.0),
            "unsettled_t1": summary.get("unsettled_cash_t1", 0.0),
            "unsettled_t2": summary.get("unsettled_cash_t2", 0.0),
            "invested_value": invested,
            "total_value": total,
            "num_positions": summary.get("num_positions", 0),
            "invariant_check": invariant_ok,
            "unrealized_pnl": summary.get("unrealized_pnl", 0.0),
            "realized_pnl": summary.get("realized_pnl", 0.0),
            "realized_pnl_total": summary.get("realized_pnl", 0.0),
            "total_pnl": summary.get("total_pnl", 0.0),
        }
    except Exception as exc:
        logger.error("muhasebe_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Muhasebe özeti alınamadı: {exc}") from exc


@router.post("/reset")
async def reset_portfolio_to_cash(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Portföydeki tüm pozisyonları kapatır ve nakite çeker.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sıfırlama sonucu ve güncel nakit.

    Raises:
        HTTPException: Sıfırlama başarısız olursa 500 hatası döner.
    """
    try:
        pm = _get_pm()
        pm.close_all_positions()
        pm.settled_cash = pm.initial_capital
        pm.unsettled_cash_t1 = 0.0
        pm.unsettled_cash_t2 = 0.0
        pm.save_to_store(datetime.now(UTC).strftime("%Y-%m-%d"))
        return {
            "success": True,
            "cash": pm.cash,
            "message": "Portföy sıfırlandı.",
        }
    except Exception as exc:
        logger.error("portfoy_sifirlama_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Portföy sıfırlanamadı: {exc}") from exc


# =====================================================
# LEDGER & HISTORY
# =====================================================


@router.get("/cash-ledger")
async def cash_ledger(
    limit: int = Query(100, ge=1, le=1000, description="Maksimum kayıt sayısı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Nakit hareket geçmişini döndürür.

    Args:
        limit: Maksimum kayıt sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Nakit hareket listesi ve güncel nakit.
    """
    try:
        pm = _get_pm()
        trades_list = pm.get_trades()
        return {
            "ledger": trades_list[-limit:],
            "cash": round(pm.cash, 2),
            "settled_cash": round(pm.settled_cash, 2),
        }
    except Exception as exc:
        logger.error("nakit_hareket_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Nakit hareket geçmişi alınamadı: {exc}") from exc


@router.get("/orders")
async def portfolio_orders(
    limit: int = Query(100, ge=1, le=1000, description="Maksimum kayıt sayısı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Portföy emir geçmişini döndürür.

    Args:
        limit: Maksimum kayıt sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Emir listesi ve toplam emir sayısı.
    """
    try:
        pm = _get_pm()
        orders = pm.get_orders()
        return {"orders": orders[-limit:], "total_orders": len(orders)}
    except Exception as exc:
        logger.error("emir_gecmisi_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Emir geçmişi alınamadı: {exc}") from exc


@router.get("/position-history")
async def position_history(
    ticker: str = Query("", description="Hisse filtresi"),
    limit: int = Query(100, ge=1, le=1000, description="Maksimum kayıt sayısı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Pozisyon değişiklik geçmişini döndürür.

    Args:
        ticker: Hisse filtresi (boş = tümü).
        limit: Maksimum kayıt sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Pozisyon değişiklik geçmişi.
    """
    try:
        pm = _get_pm()
        return {"history": pm.get_position_history(ticker=ticker, limit=limit)}
    except Exception as exc:
        logger.error("pozisyon_gecmisi_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Pozisyon geçmişi alınamadı: {exc}") from exc


@router.get("/equity-snapshots")
async def equity_snapshots(
    limit: int = Query(252, ge=1, le=1000, description="Maksimum kayıt sayısı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Günlük equity snapshot'larını döndürür.

    Args:
        limit: Maksimum kayıt sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Equity snapshot listesi.
    """
    try:
        pm = _get_pm()
        return {"snapshots": pm.get_equity_snapshots(limit=limit)}
    except Exception as exc:
        logger.error("equity_snapshot_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Equity snapshot'lar alınamadı: {exc}") from exc


# =====================================================
# ATTRIBUTION & TAX & TCA
# =====================================================


@router.get("/attribution")
async def attribution(
    portfolio_id: int = Query(1, description="Portföy tanımlayıcısı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Performans attribüsyonunu döndürür.

    Args:
        portfolio_id: Portföy tanımlayıcısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Factor ve sektör attribüsyonu.

    Raises:
        HTTPException: Attribüsyon yapılamazsa 501 hatası döner.
    """
    try:
        raise HTTPException(
            status_code=501,
            detail="Factor attribüsyonu için gerçek piyasa verisi servisi gerekli. Henüz bağlı değil.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("attribusyon_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail="Attribüsyon yapılamadı.") from exc


@router.get("/tax")
async def tax_analysis(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Vergi analizini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sermaye kazancı vergisi, temettü vergisi ve BSMV.

    Raises:
        HTTPException: Vergi analizi yapılamazsa hata döner.
    """
    try:
        from ...portfolio.enhancements import tax_model

        pm = _get_pm()
        trades_list = pm.get_trades()
        trades_data = [
            {"realized_pnl": t.get("realized_pnl", 0), "holding_days": t.get("holding_days", 0)}
            for t in trades_list
        ]

        result = tax_model.compute_total_tax(
            trades=trades_data,
            dividends=[],
            commissions=pm.get_total_commission() if hasattr(pm, "get_total_commission") else 0.0,
        )
        return result
    except Exception as exc:
        logger.error("vergi_analizi_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Vergi analizi yapılamadı: {exc}") from exc


@router.get("/tca")
async def transaction_cost_analysis(
    order_value: float = Query(50000, description="Emir değeri (TL)"),
    daily_volume: float = Query(5000000, description="Günlük hacim (TL)"),
    volatility: float = Query(0.02, description="Günlük volatilite"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """İşlem maliyeti analizini döndürür.

    Args:
        order_value: Emir değeri.
        daily_volume: Günlük hacim.
        volatility: Volatilite.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Komisyon, spread, slippage ve toplam maliyet.
    """
    try:
        from ...portfolio.enhancements import tca_analyzer

        return tca_analyzer.analyze(order_value, daily_volume, volatility)
    except Exception as exc:
        logger.error("tca_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"İşlem maliyeti analizi yapılamadı: {exc}") from exc


# =====================================================
# REBALANCING
# =====================================================


@router.get("/rebalance")
async def rebalance_analysis(
    target_weights: str = Query("", description='Hedef ağırlıklar (JSON): {"THYAO": 0.3}'),
    threshold_pct: float = Query(5.0, description="Sapma eşiği (%)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Rebalance analizini döndürür.

    Args:
        target_weights: Hedef ağırlıklar (JSON string).
        threshold_pct: Sapma eşiği.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Rebalance ihtiyacı, sapmalar ve maksimum sapma.
    """
    try:
        pm = _get_pm()

        if not target_weights:
            raise HTTPException(
                status_code=400,
                detail="target_weights parametresi gerekli (JSON format).",
            )

        try:
            weights = orjson.loads(target_weights)
        except orjson.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Geçersiz JSON formatı.") from None

        return pm.check_rebalance(weights, threshold_pct=threshold_pct)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("rebalance_analiz_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Rebalance analizi yapılamadı: {exc}") from exc


@router.post("/rebalance/orders")
async def rebalance_orders(
    target_weights: dict[str, float] = Body(..., description="Hedef ağırlıklar"),
    threshold_pct: float = Query(5.0, description="Sapma eşiği (%)"),
    turnover_limit: float = Query(0.3, description="Maksimum turnover (0-1)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Rebalance emirleri oluşturur.

    Args:
        target_weights: Hedef ağırlıklar {ticker: weight}.
        threshold_pct: Sapma eşiği.
        turnover_limit: Maksimum turnover.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Rebalance emirleri, toplam değer ve turnover limiti.
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
            "total_value": sum(o.get("value", 0.0) for o in orders),
            "turnover_limit": turnover_limit,
        }
    except Exception as exc:
        logger.error("rebalance_emir_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Rebalance emirleri oluşturulamadı: {exc}") from exc


_background_tasks: set[asyncio.Task] = set()


@router.post("/trigger")
@router.post("/rebalance/trigger")
async def trigger_portfolio_cycle(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Günlük portföy döngüsünü tetikler.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Tetikleme durumu ve mesaj.
    """
    try:
        from ...pipeline.run_unified_daily import run_unified_daily_cycle

        task = asyncio.create_task(run_unified_daily_cycle())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return {
            "status": "TRIGGERED",
            "message": "Günlük portföy ve seans yürütme döngüsü arka planda başlatıldı.",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:
        logger.error("portfoy_tetikleme_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Portföy döngüsü tetiklenemedi: {exc}") from exc


# =====================================================
# QUANTITATIVE PORTFOLIO OPTIMIZATION
# =====================================================


@router.post("/optimize")
async def optimize_portfolio(
    body: dict[str, Any] = Body(...),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Portföy optimizasyonu yapar (Risk Parity, HRP, Max Sharpe, Min Variance, Black-Litterman).

    Args:
        body: Optimizasyon parametreleri (tickers, method, model_scores, regime).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Ağırlıklar, beklenen getiri, volatilite, Sharpe ve maliyet.

    Raises:
        HTTPException: Optimizasyon yapılamazsa hata döner.
    """
    try:
        from ...portfolio.portfolio_optimizer import (
            OptimizationMethod,
            PortfolioOptimizerConstraints,
            portfolio_optimizer,
        )

        tickers = body.get("tickers", [])
        if not tickers:
            pm = _get_pm()
            pos = pm.get_all_positions()
            tickers = [p.get("ticker") for p in pos if p.get("ticker")]

        if not tickers:
            raise HTTPException(
                status_code=400,
                detail="Ticker listesi gerekli veya portföyde pozisyon bulunamadı.",
            )

        method_str = body.get("method", "RISK_PARITY").upper()
        try:
            method = OptimizationMethod(method_str)
        except ValueError:
            method = OptimizationMethod.RISK_PARITY

        regime = body.get("regime", "SIDEWAYS")
        model_scores = body.get("model_scores")
        sector_map = body.get("sector_map")
        liquidity_scores = body.get("liquidity_scores")

        # Tarihsel getiri matrisi — warehouse (TradingView + yerel depo)
        from ...data.data_source import data_source

        close_series: dict[str, list[float]] = {}
        for ticker_sym in tickers:
            df = data_source.get_stock_data(
                ticker=ticker_sym,
                period="3mo",
                interval="1d",
                source_priority=["warehouse", "local"],
            )
            if df is not None and not df.is_empty() and "Close" in df.columns:
                closes = df["Close"].drop_nulls().to_list()
                if len(closes) >= 20:
                    close_series[ticker_sym] = closes

        if not close_series:
            raise HTTPException(
                status_code=503,
                detail="Tarihsel veri alınamadı. Optimizasyon yapılamaz.",
            )

        # Eşit uzunlukta getiri matrisi oluştur
        min_len = min(len(v) for v in close_series.values())
        import numpy as np

        returns_list = []
        for ticker_sym in tickers:
            if ticker_sym in close_series:
                prices = close_series[ticker_sym][-min_len:]
                rets = np.diff(prices) / np.array(prices[:-1])
                returns_list.append(rets)

        returns_matrix = np.column_stack(returns_list) if len(returns_list) > 1 else np.array(returns_list[0]).reshape(-1, 1)

        c = PortfolioOptimizerConstraints(
            max_position_pct=float(body.get("max_position_pct", 0.10)),
            min_position_pct=float(body.get("min_position_pct", 0.015)),
            max_sector_pct=float(body.get("max_sector_pct", 0.30)),
            turnover_penalty_lambda=float(body.get("turnover_penalty_lambda", 0.015)),
            hysteresis_threshold=float(body.get("hysteresis_threshold", 0.02)),
        )

        current_weights: dict[str, float] = {}
        total_val = 100000.0
        try:
            pm = _get_pm()
            summary = pm.get_summary()
            total_val = float(summary.get("total_value", 100000.0))
            for p in pm.get_all_positions():
                t = p.get("ticker")
                mv = float(p.get("market_value", 0.0))
                if t and total_val > 0:
                    current_weights[t] = mv / total_val
        except Exception as weight_err:
            logger.warning("mevcut_agirlik_hatasi: hata=%s", weight_err)

        res = portfolio_optimizer.optimize(
            tickers=tickers,
            returns_matrix=returns_matrix,
            method=method,
            model_scores=model_scores,
            current_weights=current_weights,
            sector_map=sector_map,
            liquidity_scores=liquidity_scores,
            regime=regime,
            constraints=c,
            portfolio_value=total_val,
        )

        return {
            "success": True,
            "method": res.method.value,
            "weights": res.weights,
            "cash_weight": res.cash_weight,
            "expected_return_annual": res.expected_return,
            "portfolio_volatility_annual": res.portfolio_volatility,
            "sharpe_ratio": res.sharpe_ratio,
            "diversification_ratio": res.diversification_ratio,
            "turnover": res.turnover_from_current,
            "estimated_cost_tl": res.estimated_transaction_cost_tl,
            "effective_positions": res.effective_positions_count,
            "sector_exposures": res.sector_exposures,
            "is_optimal": res.is_optimal,
            "warnings": res.warnings,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("optimizasyon_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Portföy optimizasyonu yapılamadı: {exc}") from exc


# =====================================================
# STATUS & TRIGGERS
# =====================================================


@router.get("/status")
async def portfolio_status(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Portföy servis durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Servis durumu, pozisyon sayısı ve nakit bilgileri.
    """
    try:
        from ...paper_trading.paper_orchestrator import paper_orchestrator

        summary = paper_orchestrator.portfolio.get_summary()
        return {
            "status": "ok",
            "trading_enabled": True,
            "positions_count": summary.get("num_positions", 0),
            "cash": summary.get("cash", 0.0),
            "settled_cash": summary.get("settled_cash", 0.0),
            "unsettled_cash_t1": summary.get("unsettled_cash_t1", 0.0),
            "unsettled_cash_t2": summary.get("unsettled_cash_t2", 0.0),
            "total_value": summary.get("total_value", 0.0),
            "unrealized_pnl": summary.get("unrealized_pnl", 0.0),
            "realized_pnl": summary.get("realized_pnl", 0.0),
            "drawdown_pct": summary.get("max_drawdown_pct", 0.0),
            "strict_t2": getattr(paper_orchestrator.portfolio, "strict_t2", False),
        }
    except Exception as exc:
        logger.error("portfoy_durum_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Portföy durumu alınamadı: {exc}") from exc


@router.post("/trigger_eod_signals")
async def trigger_eod_signals(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """18:15 EOD sinyal üretimini tetikler.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sinyal üretim sonucu.
    """
    try:
        from ...pipeline.run_unified_daily import run_eod_signal_cycle

        res = await run_eod_signal_cycle()
        return {
            "status": "success",
            "message": "EOD sinyal üretimi ve portföy MTM değerlemesi tamamlandı.",
            "details": res,
        }
    except Exception as exc:
        logger.error("eod_sinyal_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"EOD sinyal üretimi başarısız: {exc}") from exc


@router.post("/trigger_morning_execution")
async def trigger_morning_execution(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """09:55 sabah açılışı yürütme döngüsünü tetikler.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Yürütme sonucu.
    """
    try:
        from ...pipeline.run_unified_daily import run_morning_execution_cycle

        res = await run_morning_execution_cycle()
        return {
            "status": "success",
            "message": "Sabah açılışı mikro-yapı yürütme döngüsü tamamlandı.",
            "details": res,
        }
    except Exception as exc:
        logger.error("sabah_acilisi_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Sabah açılışı yürütmesi başarısız: {exc}") from exc


@router.post("/trigger_phase18")
async def trigger_phase18(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Phase 18 unified daily döngüsünü tetikler.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Döngü sonucu.
    """
    try:
        from ...pipeline.run_unified_daily import run_unified_daily_cycle

        res = await run_unified_daily_cycle()
        return {"status": "success", "message": "Unified Daily döngüsü tetiklendi.", "details": res}
    except Exception as exc:
        logger.error("phase18_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Phase 18 döngüsü tetiklenemedi: {exc}") from exc


@router.post("/auto_rebalance")
async def trigger_auto_rebalance(
    body: Any | None = Body(None),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Otonom portföy yeniden dengelemeyi tetikler.

    Args:
        body: İsteğe bağlı parametreler.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Yeniden dengeleme sonucu.
    """
    try:
        from ...pipeline.run_unified_daily import run_unified_daily_cycle

        res = await run_unified_daily_cycle()
        return {
            "status": "success",
            "message": "Otonom rebalance tetiklendi.",
            "details": res,
            "params_received": {
                "threshold_pct": body.get("threshold_pct") if body else None,
                "max_turnover": body.get("max_turnover") if body else None,
            },
        }
    except Exception as exc:
        logger.error("oto_rebalance_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Otonom rebalance tetiklenemedi: {exc}") from exc


@router.post("/deposit")
async def deposit_funds(
    body: dict[str, Any] = Body(...),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Portföye nakit ekler.

    Args:
        body: Yatırım bilgileri (amount, description).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Yatırım sonucu ve güncel nakit.

    Raises:
        HTTPException: Yatırım yapılamazsa hata döner.
    """
    try:
        amount = float(body.get("amount", 0))
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Yatırım tutarı pozitif olmalıdır.")

        desc = body.get("description", "Yatırımcı Nakit Transferi")
        pm = _get_pm()
        new_cash = pm.deposit_cash(amount=amount, description=desc)
        summary = pm.get_summary()
        return {
            "success": True,
            "deposited_amount": amount,
            "new_cash": new_cash,
            "total_value": summary.get("total_value", new_cash),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("nakit_yatirma_hatasi: hata=%s", exc)
        raise HTTPException(status_code=500, detail=f"Nakit yatırılamadı: {exc}") from exc



@router.get("/alpha")
@router.get("/alpha-signals")
@router.get("/strategy/alpha")
async def alpha_signals(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Alpha stratejisi canlı sinyallerini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Alpha sinyalleri, pozisyonlar ve durum.
    """
    cached = _alpha_signals_cache.get()
    if cached is not None:
        return cached

    from ...core.redis_helper import get_cached, set_cached

    try:
        redis_cached = get_cached("alpha:signals")
        if redis_cached:
            _alpha_signals_cache.set(redis_cached)
            return redis_cached
    except Exception as exc:
        logger.warning("alpha_cache_okuma_hatasi: hata=%s", exc)

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, _hesapla_alpha_canli)

    _alpha_signals_cache.set(res)

    try:
        set_cached("alpha:signals", res, ttl=900)
    except Exception as exc:
        logger.warning("alpha_cache_yazma_hatasi: hata=%s", exc)

    return res


def _hesapla_alpha_canli() -> dict[str, Any]:
    """Canlı alpha sinyallerini hesaplar.

    Öncelik sırası: Redis cache → radar verisi → ML scanner → nakit kalkanı.

    Returns:
        dict: Alpha sinyalleri ve durum bilgisi.
    """
    try:
        from ...core.redis_helper import get_cached as gc

        radar = gc("radar:data") or []
        if radar:
            top_items = sorted(radar, key=lambda x: x.get("score", 0), reverse=True)[:5]
            if len(top_items) >= 5:
                return {
                    "strategy": "Dual Momentum Top 5 + PPF Cash Shield",
                    "active_positions": [
                        {
                            "ticker": it.get("symbol"),
                            "weight": 0.20,
                            "score": it.get("score", 0.0),
                            "sector": it.get("sector", "SANAYI"),
                        }
                        for it in top_items
                    ],
                    "cash_shield_pct": 0.0,
                    "status": "active",
                }
    except Exception as err:
        logger.warning("alpha_hesaplama_hatasi: hata=%s", err)

    try:
        from ...scanner.bist_ml_scanner import bist_ml_scanner

        opps = bist_ml_scanner.scan_all_opportunities(limit=5)
        if opps and len(opps) >= 1:
            weight_each = round(1.0 / len(opps), 4)
            return {
                "strategy": "Dual Momentum Top 5 + PPF Cash Shield",
                "active_positions": [
                    {
                        "ticker": opp.get("symbol") or opp.get("ticker"),
                        "weight": weight_each,
                        "score": float(opp.get("score", 0.0)),
                        "sector": opp.get("sector", "SANAYI"),
                    }
                    for opp in opps
                ],
                "cash_shield_pct": round(max(0.0, 1.0 - weight_each * len(opps)) * 100.0, 1),
                "status": "active",
                "source": "ml_scanner_live",
            }
    except Exception as scan_err:
        logger.warning("alpha_scanner_hatasi: hata=%s", scan_err)

    return {
        "strategy": "Dual Momentum Top 5 + PPF Cash Shield",
        "active_positions": [],
        "cash_shield_pct": 100.0,
        "status": "unavailable",
        "message": "Canlı sinyal verisi bulunamadı; sermaye %100 nakit kalkanında korunuyor.",
    }
