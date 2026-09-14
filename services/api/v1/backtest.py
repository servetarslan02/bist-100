"""Backtest API — Gerçek servislere bağlı uç noktalar."""

from __future__ import annotations

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
    initial_capital: float = Query(100_000.0),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Backtest çalıştırır ve gerçek sermaye eğrisi ile metrikleri döndürür.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        period: Backtest süresi (ör. 6mo, 1y, 2y, 5y).
        strategy: Strateji adı (momentum, mean_reversion, breakout).
        initial_capital: Başlangıç sermayesi.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Backtest durumu, performans metrikleri, equity curve ve işlem defteri.
    """
    clean_ticker = ticker.strip().upper().replace(".IS", "")
    try:
        from ...data.data_source import YahooFinanceSource
        import numpy as np

        ys = YahooFinanceSource()
        df = ys.fetch(ticker=clean_ticker, period=period, interval="1d")

        if df is None or len(df) < 15:
            # Yedek: yfinance doğrudan
            import yfinance as yf
            import polars as pl
            raw = yf.Ticker(f"{clean_ticker}.IS").history(period=period, interval="1d")
            if raw is not None and not raw.empty:
                df = pl.from_pandas(raw.reset_index())
                if "Date" in df.columns:
                    df = df.with_columns(pl.col("Date").cast(pl.Datetime).alias("Date"))

        if df is None or len(df) < 10:
            raise HTTPException(
                status_code=404,
                detail=f"{clean_ticker} için yeterli tarihsel fiyat verisi temin edilemedi.",
            )

        # Veri hazırlığı
        dates = [str(d)[:10] for d in df["Date"].to_list()]
        closes = [float(c) for c in df["Close"].to_list()]
        volumes = [float(v) for v in df["Volume"].to_list()] if "Volume" in df.columns else [100000.0] * len(closes)
        highs = [float(h) for h in df["High"].to_list()] if "High" in df.columns else closes
        lows = [float(l) for l in df["Low"].to_list()] if "Low" in df.columns else closes

        # Stratejiye göre sinyal üretimi
        n = len(closes)
        strat_key = strategy.lower().strip()

        # Basit Hareketli Ortalamalar (SMA)
        sma20 = [None] * n
        sma50 = [None] * n
        for i in range(n):
            if i >= 19:
                sma20[i] = sum(closes[i - 19 : i + 1]) / 20.0
            if i >= 49:
                sma50[i] = sum(closes[i - 49 : i + 1]) / 50.0

        # RSI Hesaplama
        rsi14 = [50.0] * n
        gains, losses = [], []
        for i in range(1, n):
            delta = closes[i] - closes[i - 1]
            gains.append(max(0.0, delta))
            losses.append(max(0.0, -delta))
            if i >= 14:
                avg_gain = sum(gains[-14:]) / 14.0
                avg_loss = sum(losses[-14:]) / 14.0
                rs = avg_gain / max(avg_loss, 1e-6)
                rsi14[i] = 100.0 - (100.0 / (1.0 + rs))

        # Simülasyon döngüsü
        cash = initial_capital
        position_qty = 0
        entry_price = 0.0
        entry_date = ""
        trades = []
        equity_curve = []
        peak_equity = initial_capital
        drawdowns = []

        comm_rate = 0.001  # Binde 1 komisyon
        slippage_rate = 0.0008  # Binde 0.8 kayma

        for i in range(n):
            cur_price = closes[i]
            cur_date = dates[i]

            # Alış/Satış Koşulları
            buy_signal = False
            sell_signal = False

            if strat_key == "mean_reversion":
                buy_signal = (rsi14[i] < 35) and (position_qty == 0)
                sell_signal = (rsi14[i] > 65 or (entry_price > 0 and cur_price < entry_price * 0.94)) and (position_qty > 0)
            elif strat_key == "breakout":
                highest_20 = max(highs[max(0, i - 20) : i]) if i > 20 else cur_price
                lowest_10 = min(lows[max(0, i - 10) : i]) if i > 10 else cur_price
                buy_signal = (cur_price > highest_20) and (position_qty == 0)
                sell_signal = (cur_price < lowest_10 or (entry_price > 0 and cur_price < entry_price * 0.93)) and (position_qty > 0)
            else:  # Momentum (Varsayılan)
                s20 = sma20[i]
                s50 = sma50[i]
                buy_signal = (s20 is not None and s50 is not None and s20 > s50 and rsi14[i] > 48) and (position_qty == 0)
                sell_signal = ((s20 is not None and s50 is not None and s20 < s50) or (entry_price > 0 and cur_price < entry_price * 0.93)) and (position_qty > 0)

            # İşlem Uygulama
            if buy_signal and cash > cur_price * 10:
                fill_price = cur_price * (1.0 + slippage_rate)
                invest_amt = cash * 0.95
                position_qty = int(invest_amt // fill_price)
                fee = position_qty * fill_price * comm_rate
                cash -= (position_qty * fill_price + fee)
                entry_price = fill_price
                entry_date = cur_date

            elif sell_signal and position_qty > 0:
                exit_price = cur_price * (1.0 - slippage_rate)
                gross = position_qty * exit_price
                fee = gross * comm_rate
                net_revenue = gross - fee
                pnl = net_revenue - (position_qty * entry_price)
                pnl_pct = ((exit_price / entry_price) - 1.0) * 100.0

                trades.append({
                    "trade_id": len(trades) + 1,
                    "ticker": clean_ticker,
                    "side": "LONG",
                    "entry_date": entry_date,
                    "exit_date": cur_date,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "quantity": position_qty,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                })
                cash += net_revenue
                position_qty = 0
                entry_price = 0.0

            # Günlük portföy net değeri (NAV)
            cur_equity = cash + (position_qty * cur_price)
            equity_curve.append({
                "date": cur_date,
                "equity": round(cur_equity, 2),
                "benchmark": round(initial_capital * (closes[i] / max(closes[0], 1e-6)), 2),
            })
            if cur_equity > peak_equity:
                peak_equity = cur_equity
            dd = ((peak_equity - cur_equity) / peak_equity * 100.0) if peak_equity > 0 else 0.0
            drawdowns.append(round(dd, 2))

        # Açık pozisyon varsa son fiyattan kapat
        if position_qty > 0:
            last_price = closes[-1]
            gross = position_qty * last_price
            fee = gross * comm_rate
            net_revenue = gross - fee
            pnl = net_revenue - (position_qty * entry_price)
            pnl_pct = ((last_price / entry_price) - 1.0) * 100.0
            trades.append({
                "trade_id": len(trades) + 1,
                "ticker": clean_ticker,
                "side": "OPEN_CLOSE",
                "entry_date": entry_date,
                "exit_date": dates[-1],
                "entry_price": round(entry_price, 2),
                "exit_price": round(last_price, 2),
                "quantity": position_qty,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            })
            cash += net_revenue

        final_capital = cash
        total_return_pct = ((final_capital / initial_capital) - 1.0) * 100.0

        # Benchmark getirisi (Buy & Hold)
        bh_return_pct = ((closes[-1] / max(closes[0], 1e-6)) - 1.0) * 100.0

        # Metrikler
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] <= 0]
        win_rate = (len(winning_trades) / len(trades) * 100.0) if trades else 0.0
        gross_profit = sum(t["pnl"] for t in winning_trades)
        gross_loss = abs(sum(t["pnl"] for t in losing_trades))
        profit_factor = (gross_profit / max(gross_loss, 1.0)) if gross_loss > 0 else (9.99 if gross_profit > 0 else 1.0)

        # Günlük getirilerden Sharpe Oranı
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]["equity"]
            curr = equity_curve[i]["equity"]
            returns.append((curr - prev) / max(prev, 1e-6))
        
        if returns and np.std(returns) > 0:
            sharpe_ratio = round(float(np.mean(returns) / np.std(returns) * np.sqrt(252)), 2)
        else:
            sharpe_ratio = 0.0

        max_dd = max(drawdowns) if drawdowns else 0.0

        # Yıllıklandırılmış CAGR
        years = max(len(dates) / 252.0, 0.1)
        cagr = ((final_capital / initial_capital) ** (1.0 / years) - 1.0) * 100.0 if final_capital > 0 else -100.0

        return {
            "status": "completed",
            "ticker": clean_ticker,
            "period": period,
            "strategy": strat_key,
            "initial_capital": round(initial_capital, 2),
            "final_capital": round(final_capital, 2),
            "total_return_pct": round(total_return_pct, 2),
            "benchmark_return_pct": round(bh_return_pct, 2),
            "cagr_pct": round(cagr, 2),
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "total_trades": len(trades),
            "winning_trades_count": len(winning_trades),
            "losing_trades_count": len(losing_trades),
            "equity_curve": equity_curve,
            "trades": trades,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("backtest_calistirma_hatasi: ticker=%s, hata=%s", clean_ticker, exc)
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
        from ...backtest.walk_forward_engine import WalkForwardEngineV5

        analyzer = WalkForwardEngineV5()
        result = await analyzer.run_async(ticker=ticker, n_folds=n_folds)
        return {
            "status": "completed",
            "ticker": ticker,
            "n_folds": n_folds,
            "result": result,
        }
    except ImportError as exc:
        logger.warning("walk_forward_yuklenemedi: WalkForwardAnalyzer modülü mevcut değil")
        raise HTTPException(
            status_code=503,
            detail="Walk-forward analiz motoru şu anda kullanılamıyor.",
        ) from exc
    except HTTPException:
        raise
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
