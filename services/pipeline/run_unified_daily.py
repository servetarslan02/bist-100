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
from datetime import date, datetime, timedelta, timezone
from typing import Any

import orjson
import structlog

from services.core.alpha_engine import AlphaEngine
from services.core.database import init_databases, pg_execute, pg_fetch
from services.paper_trading.paper_orchestrator import paper_orchestrator

logger = structlog.get_logger("unified_daily")

# Backtest ile birebir aynı holding süresi (63 iş günü = ~88 takvim günü)
HOLDING_PERIOD_DAYS = 63


async def get_last_rebalance_date() -> date | None:
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


async def run_eod_signal_cycle(target_date: str | None = None, force_rebalance: bool = False) -> dict[str, Any]:
    """18:15 EOD: Sinyalleri üretir, kuyruğa alır ve portföy MTM değerlemesini yapar."""
    await init_databases()
    today_str = target_date or date.today().strftime("%Y-%m-%d")
    today_dt = date.fromisoformat(today_str)
    logger.info("EOD Signal Cycle Started", date=today_str)

    current_positions = [p["ticker"] for p in paper_orchestrator.portfolio.get_all_positions()]
    last_rebalance = await get_last_rebalance_date()

    # Eger portfoyde hic pozisyon yoksa (0 pozisyon) veya force_rebalance istenmisse MUTLAKA rebalance yap
    needs_rebalance = True
    if len(current_positions) > 0 and not force_rebalance and last_rebalance is not None:
        days_passed = (today_dt - last_rebalance).days
        if days_passed < HOLDING_PERIOD_DAYS:
            needs_rebalance = False
            logger.info("Rebalance period not reached. Only MTM will be performed", days_passed=days_passed)

    from services.ingestion.bist_universe import bist_universe

    current_prices = {}
    if current_positions:
        # 1. PRIMARY: TradingView Scanner API (150ms 0-Gecikmeli Canlı Veri)
        try:
            from services.ingestion.providers.tradingview_provider import tradingview_provider
            tv_stocks = await tradingview_provider.fetch_all_bist_stocks()
            if tv_stocks:
                for ticker in current_positions:
                    d = tv_stocks.get(ticker)
                    if d:
                        p = d.get("price") or d.get("close")
                        if p and float(p) > 0:
                            current_prices[ticker] = float(p)
                logger.info("TradingView primary feed used for MTM", matched=len(current_prices), total=len(current_positions))
        except Exception as tv_err:
            logger.warning(f"TradingView MTM fetch warning: {tv_err}, falling back to yfinance")

        # 2. FALLBACK: yfinance (Eğer TradingView'de eksik kalan hisse varsa)
        missing_ticks = [t for t in current_positions if t not in current_prices]
        if missing_ticks:
            logger.info("yfinance fallback triggered for missing MTM tickers", count=len(missing_ticks))
            engine = AlphaEngine()
            start_date = (today_dt - timedelta(days=60)).strftime("%Y-%m-%d")
            pos_data, _, _ = engine.fetch_data(start_date, today_str, tickers=missing_ticks)
            for ticker, df in pos_data.items():
                if len(df) > 0:
                    valid_closes = df["Close"].drop_nulls().to_list()
                    if valid_closes:
                        current_prices[ticker] = float(valid_closes[-1])

    # 1. Mevcut portföy Mark-to-Market değerlemesi
    mtm_summary = paper_orchestrator.mark_to_market_cycle(current_prices, today_str)

    queued_signals = []
    if needs_rebalance:
        # TEK BEYİN İLKESİ (SINGLE SOURCE OF TRUTH):
        # Portföy alımları ve Otonom Fırsatlar sayfası aynı ortak Şampiyon Modelden (BistMLScanner) beslenir.
        from services.core.redis_helper import set_cached
        from services.scanner.bist_ml_scanner import bist_ml_scanner

        logger.info("Generating signals via Champion BistMLScanner (Single Source of Truth)...")
        preds = bist_ml_scanner.scan_all_opportunities(limit=50)
        if preds:
            set_cached("phase18:predictions", preds, ttl=86400)
            valid_preds = preds
        else:
            valid_preds = []

        if valid_preds:
            # Rejim bazlı dinamik pozisyon tavanı (Boğa: 30, Nötr: 15, Ayı: 6, Kriz: 3)
            from services.risk.regime_limits import regime_limits

            current_regime_str = "BULL"
            try:
                from services.market_state.ensemble_regime import EnsembleRegimeDetector
                detector = EnsembleRegimeDetector()
                det_res = detector.detect()
                if hasattr(det_res, "regime"):
                    current_regime_str = str(det_res.regime)
                elif isinstance(det_res, dict):
                    current_regime_str = str(det_res.get("regime", "BULL"))
            except Exception:
                current_regime_str = "BULL"

            limits = regime_limits.get_limits(current_regime_str)
            max_slots = getattr(limits, "max_positions", 30)

            # 1. Seçici Giriş Eşiği (Hurdle Rate): İlla 24-30 dolmak zorunda değil, sadece kalite kriterini geçenler
            qualified_candidates = []
            for p in valid_preds:
                sc = float(p.get("score", 0.0))
                exp_ret = float(p.get("expected_return_pct", 15.0))
                # Kalite eşiği: Pozitif getiri beklentisi ve güçlü model skoru
                if exp_ret > 0 and sc >= 50.0:
                    qualified_candidates.append(p)
                if len(qualified_candidates) >= max_slots:
                    break

            if not qualified_candidates:
                qualified_candidates = valid_preds[:min(10, max_slots)]

            top_rank_map = {item["ticker"]: idx + 1 for idx, item in enumerate(qualified_candidates)}

            # 2. Münferit Satış Mantığı (Individual Degradation Exit):
            # Sırf listede birkaç sıra geriledi diye satılmaz; ciddi bozulma veya stop aranır
            exit_signals = []
            for ticker in current_positions:
                pos_pred = next((p for p in preds if p.get("ticker") == ticker), None)
                should_exit = False
                exit_reason = ""

                if pos_pred is None:
                    should_exit = True
                    exit_reason = "UNIVERSE_REMOVAL"
                else:
                    pos_score = float(pos_pred.get("score", 0.0))
                    pos_rank = top_rank_map.get(ticker, 999)
                    if pos_score < 45.0 or pos_rank > (max_slots * 1.8):
                        should_exit = True
                        exit_reason = "ALPHA_DECAY"

                if should_exit:
                    logger.info("Individual position exit triggered", ticker=ticker, reason=exit_reason)
                    exit_signals.append(
                        {
                            "ticker": ticker,
                            "direction": "SHORT",
                            "rank": 99,
                            "score": 0.0,
                            "confidence": 1.0,
                            "model_version": paper_orchestrator._champion_version,
                            "target_weight": 0.0,
                            "sector": bist_universe.get_ticker_sector(ticker),
                        }
                    )

            # 3. Dinamik Portföy Ağırlıklandırması (Conviction & Return Weighted Sizing):
            # KULLANICI KURALI: Bir hisse en fazla %20 (0.20), en az için kriter yoktur (0.00 serbest).
            new_entries = [p for p in qualified_candidates if p["ticker"] not in current_positions]
            entry_signals = []

            if new_entries:
                investable_pool = max(0.10, 1.0 - limits.min_cash_pct)  # Örn: %92
                # Güçlü Conviction Skew: En çok yükselmesi beklenen ve güvenilen hisseye %15-20, alt sıralara %0.5-2 verilir
                raw_weights = []
                for idx, p in enumerate(new_entries):
                    sc = max(1.0, float(p.get("score", 50.0)))
                    exp_r = max(5.0, float(p.get("expected_return_pct", 15.0))) / 100.0
                    rank_multiplier = max(0.05, (len(new_entries) - idx) / len(new_entries))
                    factor = ((sc / 50.0) ** 2) * (1.0 + exp_r * 2.0) * (rank_multiplier ** 1.8)
                    raw_weights.append(factor)

                tot_factor = sum(raw_weights) if sum(raw_weights) > 0 else len(new_entries)
                max_pos_cap = min(0.20, limits.max_position_pct)  # KULLANICI KURALI: En fazla %20
                min_pos_floor = 0.00  # KULLANICI KURALI: En az için kriter yoktur

                for idx, (p, raw_f) in enumerate(zip(new_entries, raw_weights, strict=False)):
                    ideal_weight = (raw_f / tot_factor) * investable_pool
                    bounded_weight = round(min(max_pos_cap, max(min_pos_floor, ideal_weight)), 4)

                    entry_signals.append(
                        {
                            "ticker": p["ticker"],
                            "direction": "LONG",
                            "rank": idx + 1,
                            "score": float(p.get("score", 100.0 - idx)),
                            "confidence": float(p.get("confidence", 0.90)),
                            "model_version": paper_orchestrator._champion_version,
                            "target_weight": bounded_weight,
                            "sector": bist_universe.get_ticker_sector(p["ticker"]),
                        }
                    )

            queued_signals = exit_signals + entry_signals

            # Sinyalleri sabah açılışı için bekleyen emir olarak kaydet
            paper_orchestrator.queue_pending_signals(queued_signals, today_str)

            # DB log kaydı
            top_tickers = [item["ticker"] for item in qualified_candidates]
            try:
                await pg_execute(
                    "INSERT INTO paper_trade_portfolio (target_date, tickers, is_cash_regime, is_rebalance) VALUES ($1, $2, $3, $4)",
                    today_dt,
                    orjson.dumps(top_tickers).decode(),
                    False,
                    True,
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


async def run_morning_execution_cycle(target_date: str | None = None) -> dict[str, Any]:
    """09:55-10:05 Sabah Açılışı: Bekleyen emirleri gerçek açılış ve mikro-yapı defteriyle yürütür."""
    await init_databases()
    today_str = target_date or date.today().strftime("%Y-%m-%d")
    today_dt = date.fromisoformat(today_str)
    logger.info("Morning Execution Cycle Started", date=today_str)

    # Eger bekleyen sinyal yoksa ve portfoy bossa, aninda sinyal uretimini bootstrap et
    pending = paper_orchestrator.store.load_pending_signals()
    if not pending:
        logger.info("No pending signals in store, triggering immediate signal generation cycle...")
        await run_eod_signal_cycle(target_date=today_str, force_rebalance=True)
        pending = paper_orchestrator.store.load_pending_signals()

    engine = AlphaEngine()
    # Son 60 günü ve sadece bekleyen hisseleri çek (Hızlı ve güvenilir: 1-2 saniye)
    start_date = (today_dt - timedelta(days=60)).strftime("%Y-%m-%d")
    target_tickers = list(set([s["ticker"] for s in pending])) if pending else None
    market_data, bm_df, sector_map = engine.fetch_data(start_date, today_str, tickers=target_tickers)

    bm_ret = 0.0
    bm_valid = len(bm_df) >= 2 if bm_df is not None else False
    if bm_valid:
        last_close = bm_df["Close"][-1]
        prev_close = bm_df["Close"][-2]
        if last_close is not None and prev_close is not None and prev_close != 0:
            bm_ret = float((last_close / prev_close - 1.0) * 100)
        else:
            bm_ret = 0.0

    # Bekleyen sinyalleri T+1 açılış fiyatları, KAP kısıtları ve sentetik derinlikle yürüt
    report = paper_orchestrator.execute_pending_signals(
        date=today_str,
        market_data=market_data,
        sector_map=sector_map,
        benchmark_return_pct=bm_ret,
        data_quality_ok=bm_valid,
    )

    logger.info("Morning Execution Cycle Completed", report=report)
    return report


async def run_unified_daily_cycle() -> dict[str, Any]:
    """API ve zamanlayıcı için ortak orkestrasyon fonksiyonu."""
    now_hour = datetime.now(timezone(timedelta(hours=3))).hour
    pending = paper_orchestrator.store.load_pending_signals()
    # Sabah seansinda, portfoy henuz bosken VEYA geceden bekleyen emirler varsa once sabah yurutme dongusu calisir
    if len(pending) > 0 or len(paper_orchestrator.portfolio.get_all_positions()) == 0 or now_hour < 12:
        return await run_morning_execution_cycle()
    else:
        return await run_eod_signal_cycle()


if __name__ == "__main__":
    asyncio.run(run_unified_daily_cycle())
