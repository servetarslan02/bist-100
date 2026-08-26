"""
UNIFIED BIST DAILY PIPELINE: EOD SIGNAL GENERATION & MORNING MICROSTRUCTURE EXECUTION
=====================================================================================
Bu modül, Borsa İstanbul (BIST) işlem takvimine ve mikro-yapı gerçekliğine tam uyumlu
iki aşamalı günlük işlem akışını yönetir:

1. Seans Sonu (EOD / 18:15):
   - AlphaEngine model eğitimi ve tahmin üretimi.
   - Sinyaller derlenir ve "BEKLEYEN EMİR" (PENDING) olarak PaperStateStore'a kaydedilir.
   - Aynı gün kapanışından ASLA emir doldurulmaz (Sıfır Geleceğe Bakış / Zero Lookahead).
   - Mevcut portföy Mark-to-Market ile değerlenir ve T+2 valör kaydırılır.

2. Seans Açılışı (Morning / 09:55 - 10:05):
   - T+1 gerçek açılış fiyatları ve 20 günlük geçmiş OHLCV çekilir.
   - KAP kısıtları (KAPMarketRestrictionRegistry: VBTS, Brüt Takas, Devre Kesici) denetlenir.
   - Pre-trade bloklayıcı risk kapısı (PaperRiskGate - Shadow mod DEĞİL!) çalıştırılır.
   - 10 Kademeli sentetik derinlik defteri ve Walk-the-Book (SyntheticOrderBookBuilder) ile emirler yürütülür.
   - Gerçekleşen işlemler tekil portföy defterine (VirtualPortfolio) kaydedilir.
"""

import asyncio
import orjson
import structlog
from datetime import datetime, date
import polars as pl
from typing import Dict, Any, Optional

from services.core.database import pg_fetch, pg_execute, init_databases
from services.core.alpha_engine import AlphaEngine
from services.paper_trading.paper_orchestrator import paper_orchestrator

logger = structlog.get_logger("unified_daily")

# Backtest ile birebir aynı holding süresi (63 iş günü = ~88 takvim günü)
HOLDING_PERIOD_DAYS = 63


async def get_last_rebalance_date() -> Optional[date]:
    """Veritabanından son gerçek rebalance tarihini döner."""
    query = """
        SELECT created_at 
        FROM paper_trade_portfolio 
        WHERE is_rebalance = TRUE
        ORDER BY created_at DESC 
        LIMIT 1
    """
    try:
        rows = await pg_fetch(query)
        if rows:
            return rows[0]["created_at"].date()
    except Exception:
        logger.warning("Caught Exception in get_last_rebalance_date", exc_info=True)
    return None


async def run_eod_signal_cycle(target_date: Optional[str] = None, force_rebalance: bool = False) -> Dict[str, Any]:
    """18:15 EOD: Sinyalleri üretir, kuyruğa alır ve portföy MTM değerlemesini yapar."""
    await init_databases()
    today_str = target_date or date.today().strftime("%Y-%m-%d")
    today_dt = pl.Series(today_str).date()
    logger.info("EOD Signal Cycle Started", date=today_str)

    current_positions = [p["ticker"] for p in paper_orchestrator.portfolio.get_all_positions()]
    last_rebalance = await get_last_rebalance_date()
    
    # Eger portfoyde hic pozisyon yoksa (0 pozisyon) veya force_rebalance istenmisse MUTLAKA rebalance yap
    needs_rebalance = True
    if len(current_positions) > 0 and not force_rebalance:
        if last_rebalance is not None:
            days_passed = (today_dt - last_rebalance).days
            if days_passed < HOLDING_PERIOD_DAYS:
                needs_rebalance = False
                logger.info("Rebalance period not reached. Only MTM will be performed", days_passed=days_passed)

    engine = AlphaEngine()
    start_date = (today_dt - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    market_data, bm_df, sector_map = engine.fetch_data(start_date, today_str)

    if bm_df.empty or not market_data:
        logger.error("Market data fetch failed! EOD cycle aborted", date=today_str)
        return {"status": "ERROR", "reason": "EMPTY_MARKET_DATA", "date": today_str}

    current_prices = {}
    for ticker, df in market_data.items():
        if not df.empty:
            current_prices[ticker] = float(df['Close'][-1])

    # 1. Mevcut portföy Mark-to-Market değerlemesi
    mtm_summary = paper_orchestrator.mark_to_market_cycle(current_prices, today_str)

    queued_signals = []
    if needs_rebalance:
        common_dates = list(sorted([d.strftime('%Y-%m-%d') for d in bm_df.index]))
        if len(common_dates) >= 2:
            train_start = common_dates[0]
            train_end = common_dates[-2]
            signal_date = common_dates[-1]

            logger.info("Training AlphaEngine for EOD signals", start=train_start, end=train_end)
            success = engine.train(market_data, bm_df, sector_map, train_start, train_end, optimize=True)
            if success:
                preds = engine.predict(market_data, bm_df, sector_map, signal_date)

                # Likidite filtresi (Minimum 5M TL ADV)
                valid_preds = []
                MIN_LIQUIDITY_TL = 5_000_000
                for p in preds:
                    tick = p["ticker"]
                    if tick in market_data:
                        df = market_data[tick]
                        df_past = df[df.index <= signal_date]
                        if len(df_past) >= 10:
                            avg_vol = df_past['Volume'].tail(20).mean() if len(df_past) >= 20 else df_past['Volume'].mean()
                            avg_close = df_past['Close'].tail(20).mean() if len(df_past) >= 20 else df_past['Close'].mean()
                            if (avg_vol * avg_close) >= MIN_LIQUIDITY_TL:
                                valid_preds.append(p)

                if not valid_preds:
                    valid_preds = preds[:10]

                top_10 = valid_preds[:10]
                top_10_set = {item["ticker"] for item in top_10}

                # 1. Top-10 dışına çıkan mevcut pozisyonlar için SATIŞ (EXIT/SHORT) sinyalleri
                exit_signals = [
                    {
                        "ticker": ticker,
                        "direction": "SHORT",
                        "rank": 99,
                        "score": 0.0,
                        "confidence": 1.0,
                        "model_version": paper_orchestrator._champion_version,
                        "target_weight": 0.0,
                        "sector": sector_map.get(ticker, ""),
                    }
                    for ticker in current_positions
                    if ticker not in top_10_set
                ]

                # 2. Yeni giren hisseler için ALIŞ (LONG) sinyalleri
                entry_signals = [
                    {
                        "ticker": item["ticker"],
                        "direction": "LONG",
                        "rank": idx + 1,
                        "score": float(item.get("score", 10.0 - idx)),
                        "confidence": float(item.get("confidence", 0.85)),
                        "model_version": paper_orchestrator._champion_version,
                        "target_weight": 0.10,
                        "sector": sector_map.get(item["ticker"], ""),
                    }
                    for idx, item in enumerate(top_10)
                    if item["ticker"] not in current_positions
                ]

                queued_signals = exit_signals + entry_signals

                # Sinyalleri sabah açılışı için bekleyen emir olarak kaydet
                paper_orchestrator.queue_pending_signals(queued_signals, today_str)

                # DB log kaydı
                top_10_tickers = [item["ticker"] for item in top_10]
                try:
                    await pg_execute(
                        "INSERT INTO paper_trade_portfolio (target_date, tickers, is_cash_regime, is_rebalance) VALUES ($1, $2, $3, $4)",
                        today_dt, orjson.dumps(top_10_tickers).decode(), False, True
                    )
                except Exception as e:
                    logger.error("DB Record Error", error=str(e))

    return {
        "status": "COMPLETED",
        "phase": "EOD_SIGNAL_PHASE",
        "date": today_str,
        "needs_rebalance": needs_rebalance,
        "queued_signals_count": len(queued_signals),
        "portfolio_summary": mtm_summary,
    }


async def run_morning_execution_cycle(target_date: Optional[str] = None) -> Dict[str, Any]:
    """09:55-10:05 Sabah Açılışı: Bekleyen emirleri gerçek açılış ve mikro-yapı defteriyle yürütür."""
    await init_databases()
    today_str = target_date or date.today().strftime("%Y-%m-%d")
    today_dt = pl.Series(today_str).date()
    logger.info("Morning Execution Cycle Started", date=today_str)

    # Eger bekleyen sinyal yoksa ve portfoy bossa, aninda sinyal uretimini bootstrap et
    pending = paper_orchestrator.store.load_pending_signals()
    if not pending:
        logger.info("No pending signals in store, triggering immediate signal generation cycle...")
        await run_eod_signal_cycle(target_date=today_str, force_rebalance=True)

    engine = AlphaEngine()
    start_date = (today_dt - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    market_data, bm_df, sector_map = engine.fetch_data(start_date, today_str)

    bm_ret = 0.0
    if not bm_df.empty and len(bm_df) >= 2:
        bm_ret = float((bm_df['Close'][-1] / bm_df['Close'][-2] - 1.0) * 100)

    # Bekleyen sinyalleri T+1 açılış fiyatları, KAP kısıtları ve sentetik derinlikle yürüt
    report = paper_orchestrator.execute_pending_signals(
        date=today_str,
        market_data=market_data,
        sector_map=sector_map,
        benchmark_return_pct=bm_ret,
        data_quality_ok=(not bm_df.empty),
    )

    logger.info("Morning Execution Cycle Completed", report=report)
    return report


async def run_unified_daily_cycle() -> Dict[str, Any]:
    """API ve zamanlayıcı için ortak orkestrasyon fonksiyonu."""
    now_hour = datetime.now().hour
    pending = paper_orchestrator.store.load_pending_signals()
    # Sabah seansinda, portfoy henuz bosken VEYA geceden bekleyen emirler varsa once sabah yurutme dongusu calisir
    if len(pending) > 0 or len(paper_orchestrator.portfolio.get_all_positions()) == 0 or now_hour < 12:
        return await run_morning_execution_cycle()
    else:
        return await run_eod_signal_cycle()


if __name__ == '__main__':
    asyncio.run(run_unified_daily_cycle())

