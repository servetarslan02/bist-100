"""Backtest API — Gerçek servislere bağlı uç noktalar."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/run")
async def run_backtest(
    ticker: str = Query(...),
    period: str = Query("1y"),
    strategy: str = Query("momentum"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Backtest çalıştırır ve sonucu döndürür.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        period: Backtest süresi (ör. 1y, 2y, 5y).
        strategy: Strateji adı (ör. momentum, mean_reversion).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Backtest durumu ve sonuç bilgisi.

    Raises:
        HTTPException: Backtest çalıştırılamazsa 500 hatası döner.
    """
    try:
        from ...backtest.engine import BacktestEngine

        engine = BacktestEngine()
        result = await engine.run(ticker=ticker, period=period, strategy=strategy)
        return {
            "status": "completed",
            "ticker": ticker,
            "period": period,
            "strategy": strategy,
            "result": result,
        }
    except ImportError:
        logger.warning("backtest_engine_yuklenemedi: BacktestEngine modülü mevcut değil")
        raise HTTPException(
            status_code=503,
            detail="Backtest motoru şu anda kullanılamıyor.",
        )
    except Exception as exc:
        logger.error("backtest_calistirma_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Backtest çalıştırılamadı: {exc}",
        ) from exc


@router.get("/results/{backtest_id}")
async def get_result(
    backtest_id: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Belirli bir backtest sonucunu döndürür.

    Args:
        backtest_id: Backtest tanımlayıcısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Backtest sonucu veya bulunamadı bilgisi.
    """
    try:
        from ...core.database import pg_fetchrow

        row = await pg_fetchrow("SELECT * FROM backtests WHERE id = $1", backtest_id)
        if row:
            return dict(row)
        return {"backtest_id": backtest_id, "status": "not_found"}
    except Exception as exc:
        logger.error("backtest_sorgu_hatasi: id=%s, hata=%s", backtest_id, exc)
        return {"backtest_id": backtest_id, "status": "error", "error": str(exc)}


@router.get("/list")
async def list_backtests(
    limit: int = Query(20),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Backtest listesini döndürür.

    Args:
        limit: Maksimum sonuç sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Backtest listesi ve sayısı.
    """
    try:
        from ...core.database import pg_fetch

        rows = await pg_fetch("SELECT * FROM backtests ORDER BY created_at DESC LIMIT $1", limit)
        return {"backtests": [dict(r) for r in rows], "count": len(rows)}
    except Exception as exc:
        logger.error("backtest_liste_hatasi: hata=%s", exc)
        return {"backtests": [], "error": str(exc)}


@router.post("/walk-forward")
async def walk_forward(
    ticker: str = Query(...),
    n_folds: int = Query(5),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Walk-forward analizi çalıştırır.

    Args:
        ticker: Hisse sembolü.
        n_folds: Katlama sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Walk-forward analiz sonucu.

    Raises:
        HTTPException: Analiz çalıştırılamazsa 500 hatası döner.
    """
    try:
        from ...backtest.walk_forward import WalkForwardAnalyzer

        analyzer = WalkForwardAnalyzer()
        result = await analyzer.run(ticker=ticker, n_folds=n_folds)
        return {
            "status": "completed",
            "ticker": ticker,
            "n_folds": n_folds,
            "result": result,
        }
    except ImportError:
        logger.warning("walk_forward_yuklenemedi: WalkForwardAnalyzer modülü mevcut değil")
        raise HTTPException(
            status_code=503,
            detail="Walk-forward analiz motoru şu anda kullanılamıyor.",
        )
    except Exception as exc:
        logger.error("walk_forward_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Walk-forward analizi çalıştırılamadı: {exc}",
        ) from exc


@router.get("/deflated-sharpe")
async def deflated_sharpe(
    sharpe: float = Query(...),
    n_trials: int = Query(10),
    T: int = Query(252),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Deflated Sharpe Ratio hesaplar.

    Args:
        sharpe: Gözlenen Sharpe oranı.
        n_trials: Deneme sayısı.
        T: Gözlem süresi (gün).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Deflated Sharpe Ratio sonucu.
    """
    try:
        from ...backtest.deflated_sharpe import DeflatedSharpeCalculator

        calc = DeflatedSharpeCalculator()
        result = calc.compute_deflated_sharpe(observed_sharpe=sharpe, n_trials=n_trials, T=T)
        return result if isinstance(result, dict) else {"deflated_sharpe": result}
    except Exception as exc:
        logger.error("deflated_sharpe_hatasi: sharpe=%s, hata=%s", sharpe, exc)
        return {"error": str(exc), "input_sharpe": sharpe}


@router.get("/history_30y")
async def get_30y_history(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """30 yıllık gerçekleşen kriz ve Risk Parity doğrulama raporunu döndürür (1997-2026).

    Kaynak: PostgreSQL backtest_results tablosu. Veri yoksa boş döner.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Yıllık kriz savunma verileri ve özet bilgisi.
    """
    try:
        from ...core.database import get_pg_pool

        pool = await get_pg_pool()
        if pool:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM backtest_results
                    WHERE backtest_id = '30y_historical'
                    ORDER BY created_at DESC LIMIT 1
                """)
                if row:
                    import orjson

                    result = orjson.loads(row["result_json"]) if row.get("result_json") else {}
                    return {
                        "summary": result.get("summary", {}),
                        "yearly_crisis_defense": result.get("yearly_crisis_defense", []),
                        "data_source": "postgresql",
                    }
    except Exception as exc:
        logger.warning("30y_history_db_hatasi: hata=%s", exc)

    return {
        "summary": {},
        "yearly_crisis_defense": [],
        "data_source": "empty",
        "message": "30 yıllık backtest sonucu bulunamadı. Önce backtest çalıştırılmalı.",
    }


@router.get("/transaction-costs")
async def transaction_costs(
    amount: float = Query(...),
    ticker: str = Query("THYAO"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """İşlem maliyetlerini hesaplar.

    Args:
        amount: İşlem tutarı (TL).
        ticker: Hisse sembolü.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Borsa ücretleri ve komisyon oranları.
    """
    try:
        from ...backtest.transaction_costs import BISTFeeStructure

        fees = BISTFeeStructure()
        return {
            "amount": amount,
            "exchange_fee_pct": fees.total_exchange_fee_pct * 100,
            "base_fee_pct": fees.total_base_fee_pct * 100,
            "broker_commission_pct": fees.broker_commission_pct * 100,
        }
    except Exception as exc:
        logger.error("transaction_costs_hatasi: amount=%s, hata=%s", amount, exc)
        return {"error": str(exc), "amount": amount}


@router.get("/trades/{backtest_id}")
async def backtest_trades(
    backtest_id: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Backtest işlem detaylarını döndürür.

    Args:
        backtest_id: Backtest tanımlayıcısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: İşlem listesi veya bulunamadı bilgisi.
    """
    try:
        from ...core.database import pg_fetch

        rows = await pg_fetch(
            "SELECT * FROM backtest_trades WHERE backtest_id = $1 ORDER BY trade_date",
            backtest_id,
        )
        if rows:
            return {"backtest_id": backtest_id, "trades": [dict(r) for r in rows]}
        return {"backtest_id": backtest_id, "trades": [], "message": "Tamamlanmış backtest bulunamadı."}
    except Exception as exc:
        logger.error("backtest_trades_hatasi: id=%s, hata=%s", backtest_id, exc)
        return {"backtest_id": backtest_id, "trades": [], "error": str(exc)}


@router.get("/equity-curve/{backtest_id}")
async def equity_curve(
    backtest_id: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Backtest equity curve verisini döndürür.

    Args:
        backtest_id: Backtest tanımlayıcısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Equity curve verisi veya bulunamadı bilgisi.
    """
    try:
        from ...core.database import pg_fetchrow

        row = await pg_fetchrow(
            "SELECT equity_curve_json FROM backtest_results WHERE backtest_id = $1 ORDER BY created_at DESC LIMIT 1",
            backtest_id,
        )
        if row and row.get("equity_curve_json"):
            import orjson

            curve = orjson.loads(row["equity_curve_json"])
            return {"backtest_id": backtest_id, "equity_curve": curve}
        return {"backtest_id": backtest_id, "equity_curve": [], "message": "Tamamlanmış backtest bulunamadı."}
    except Exception as exc:
        logger.error("equity_curve_hatasi: id=%s, hata=%s", backtest_id, exc)
        return {"backtest_id": backtest_id, "equity_curve": [], "error": str(exc)}
