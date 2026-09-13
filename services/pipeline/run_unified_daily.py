"""UNIFIED BIST DAILY PIPELINE: EOD SIGNAL GENERATION & MORNING MICROSTRUCTURE EXECUTION.

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
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import orjson
import structlog

from services.core.alpha_engine import AlphaEngine
from services.core.database import init_databases, pg_execute, pg_fetch
from services.paper_trading.paper_orchestrator import paper_orchestrator

logger = structlog.get_logger("unified_daily")

# Backtest ile birebir aynı holding süresi (63 iş günü = ~88 takvim günü)
HOLDING_PERIOD_DAYS: int = 63

# Portföy ve Risk Eşikleri
DEFAULT_MAX_POSITION_CAP: float = 0.20  # Bir hisse en fazla %20 (Kullanıcı kuralı)
DEFAULT_MIN_POSITION_FLOOR: float = 0.00  # En az için taban yok (0.00 serbest)
DEFAULT_MIN_SCORE_THRESHOLD: float = 50.0
DEFAULT_MIN_EXIT_SCORE: float = 45.0
DEFAULT_INVESTABLE_POOL_FLOOR: float = 0.10
DEFAULT_SCAN_LIMIT: int = 50
DEFAULT_LOOKBACK_DAYS: int = 60


from services.learning.frozen_strategy_engine import FROZEN_PARAMS
from services.learning.strategy_diagnostician import strategy_diagnostician


async def get_last_rebalance_date() -> date | None:
    """Veritabanından en son gerçekleştirilen başarılı rebalance tarihini döner.

    Returns:
        date | None: Son rebalance tarihi veya henüz kayıt yoksa None.
    """
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
        logger.warning("Son rebalance tarihi sorgulanirken hata olustu", exc_info=True)
    return None


async def run_eod_signal_cycle(target_date: str | None = None, force_rebalance: bool = False) -> dict[str, Any]:
    """18:15 EOD: Sinyalleri üretir, kuyruğa alır ve portföy MTM değerlemesini yapar.

    Args:
        target_date: İşlem yapılacak hedef tarih (ISO format: YYYY-MM-DD). Boşsa bugünün tarihi.
        force_rebalance: Holding periyoduna bakılmaksızın zorla rebalance yapılıp yapılmayacağı.

    Returns:
        dict[str, Any]: EOD döngü sonuç raporu (durum, sinyal sayısı, mtm özeti vb.).
    """
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

    current_prices: dict[str, float] = {}
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
            start_date = (today_dt - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
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
        preds = bist_ml_scanner.scan_all_opportunities(limit=DEFAULT_SCAN_LIMIT)
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

            # FROZEN_PARAMS'tan öğrenilmiş dinamik rejim bazlı giriş eşiği
            regime_map = {
                "BULL": "BULL_TREND",
                "BEAR": "BEAR_MARKET",
                "SIDEWAYS": "SIDEWAYS_RANGE",
                "HIGH_VOLATILITY": "HIGH_VOLATILITY",
                "LOW_VOLATILITY": "LOW_VOLATILITY",
            }
            r_target = regime_map.get(current_regime_str, current_regime_str)
            raw_min_score = (
                FROZEN_PARAMS.get("min_score", {}).get(r_target)
                or FROZEN_PARAMS.get("min_score", {}).get(current_regime_str)
            )
            if raw_min_score is not None:
                dynamic_min_score = raw_min_score * 100.0 if raw_min_score <= 1.0 else raw_min_score
            else:
                dynamic_min_score = DEFAULT_MIN_SCORE_THRESHOLD

            # 1. Seçici Giriş Eşiği (Hurdle Rate): İlla 24-30 dolmak zorunda değil, sadece kalite kriterini geçenler
            # Kurumsal Seviye: Sektör Karantina Filtresi (Model Körlüğü Yaşanan Sektörler Engellenir)
            quarantined_sectors = strategy_diagnostician.get_quarantined_sectors()
            if quarantined_sectors:
                logger.warning("Aktif karantinadaki sektorler tespit edildi", karantinadaki_sektorler=list(quarantined_sectors))

            qualified_candidates = []
            for p in valid_preds:
                ticker = p.get("ticker", "")
                ticker_sector = bist_universe.get_ticker_sector(ticker)
                if ticker_sector in quarantined_sectors:
                    logger.warning("Aday elendi -- Sektor karantinada (Model Korlugu Korumasi)", ticker=ticker, sektor=ticker_sector)
                    continue

                sc = float(p.get("score", 0.0))
                exp_ret = float(p.get("expected_return_pct", 15.0))
                # Kalite eşiği: Pozitif getiri beklentisi ve dinamik öğrenilen model skoru
                if exp_ret > 0 and sc >= dynamic_min_score:
                    qualified_candidates.append(p)
                if len(qualified_candidates) >= max_slots:
                    break

            if not qualified_candidates:
                # Karantinada olmayanlardan fallback seç
                non_quar_preds = [p for p in valid_preds if bist_universe.get_ticker_sector(p.get("ticker", "")) not in quarantined_sectors]
                qualified_candidates = non_quar_preds[: min(10, max_slots)] if non_quar_preds else valid_preds[: min(10, max_slots)]

            top_rank_map = {item["ticker"]: idx + 1 for idx, item in enumerate(qualified_candidates)}

            # 2. Münferit Satış & Stop Mantığı (FROZEN_PARAMS ile tam senkronize):
            hard_stop_val = float(FROZEN_PARAMS.get("hard_stop_pct", -6.5))
            min_hold_val = int(FROZEN_PARAMS.get("min_hold_days", 12))
            max_hold_val = int(FROZEN_PARAMS.get("max_hold_days", 65))
            pos_dict_by_ticker = {p["ticker"]: p for p in paper_orchestrator.portfolio.get_all_positions()}

            exit_signals = []
            for ticker in current_positions:
                pos_info = pos_dict_by_ticker.get(ticker, {})
                pos_pred = next((p for p in preds if p.get("ticker") == ticker), None)
                pnl_pct = float(pos_info.get("unrealized_pnl_pct", 0.0))

                entry_date_str = str(pos_info.get("entry_date") or pos_info.get("created_at") or "")[:10]
                days_held = 0
                if len(entry_date_str) == 10:
                    try:
                        days_held = (today_dt - date.fromisoformat(entry_date_str)).days
                    except Exception:
                        days_held = 0

                peak_gain_pct = max(float(pos_info.get("peak_pnl_pct", pnl_pct)), pnl_pct)
                atr_pct = float(pos_pred.get("atr_pct", 3.5)) if pos_pred else 3.5
                trailing_mult = float(FROZEN_PARAMS.get("trailing_atr_mult", 2.5))
                atr_buffer_pct = max(float(FROZEN_PARAMS.get("min_atr_pct", 4.5)), atr_pct * trailing_mult)

                if pnl_pct <= hard_stop_val:
                    should_exit = True
                    exit_reason = "HARD_STOP"
                elif peak_gain_pct >= float(FROZEN_PARAMS.get("breakeven_trigger_pct", 8.0)) and pnl_pct <= float(FROZEN_PARAMS.get("breakeven_lock_pct", 1.0)):
                    should_exit = True
                    exit_reason = "BREAKEVEN_PROTECTION"
                elif peak_gain_pct >= float(FROZEN_PARAMS.get("take_profit_activation_pct", 12.0)) and pnl_pct <= (peak_gain_pct - atr_buffer_pct):
                    should_exit = True
                    exit_reason = "ATR_TRAILING_PROFIT"
                elif days_held >= max_hold_val and peak_gain_pct < 8.0:
                    should_exit = True
                    exit_reason = "MAX_HOLD"
                elif pos_pred is None:
                    should_exit = True
                    exit_reason = "UNIVERSE_REMOVAL"
                elif days_held >= min_hold_val:
                    pos_score = float(pos_pred.get("score", 0.0))
                    pos_rank = top_rank_map.get(ticker, 999)
                    if pos_score < DEFAULT_MIN_EXIT_SCORE or pos_rank > (max_slots * 1.8):
                        should_exit = True
                        exit_reason = "ALPHA_DECAY"

                if should_exit:
                    logger.info("Position exit triggered", ticker=ticker, reason=exit_reason, pnl_pct=pnl_pct, days_held=days_held)
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
                            "reason": exit_reason,
                            "exit_reason": exit_reason,
                        }
                    )

            # 3. Dinamik Portföy Ağırlıklandırması (Conviction & Return Weighted Sizing):
            # FROZEN_PARAMS'tan öğrenilen dinamik pozisyon tavanı ve nakit kalkanı
            dynamic_max_cap = float(FROZEN_PARAMS.get("max_alloc_pct", DEFAULT_MAX_POSITION_CAP))
            dynamic_cash_buffer = float(FROZEN_PARAMS.get("min_cash_buffer_pct", limits.min_cash_pct))
            effective_min_cash = max(limits.min_cash_pct, dynamic_cash_buffer)

            new_entries = [p for p in qualified_candidates if p["ticker"] not in current_positions]
            entry_signals = []

            if new_entries:
                investable_pool = max(DEFAULT_INVESTABLE_POOL_FLOOR, 1.0 - effective_min_cash)
                # Güçlü Conviction Skew: En çok yükselmesi beklenen ve güvenilen hisseye %15-20, alt sıralara %0.5-2 verilir
                raw_weights = []
                for idx, p in enumerate(new_entries):
                    sc = max(1.0, float(p.get("score", 50.0)))
                    exp_r = max(5.0, float(p.get("expected_return_pct", 15.0))) / 100.0
                    conviction = (sc / 100.0) * exp_r
                    raw_weights.append(conviction)

                sum_weights = sum(raw_weights) if sum(raw_weights) > 0 else 1.0
                norm_weights = [w / sum_weights for w in raw_weights]

                # Cap & Flow: Hiçbir hisse dynamic_max_cap tavanını aşamaz
                for p, nw in zip(new_entries, norm_weights, strict=False):
                    allocated_weight = min(dynamic_max_cap, nw * investable_pool)
                    entry_signals.append(
                        {
                            "ticker": p["ticker"],
                            "direction": "BUY",
                            "rank": top_rank_map.get(p["ticker"], 99),
                            "score": float(p.get("score", 50.0)),
                            "confidence": float(p.get("confidence", 0.70)),
                            "model_version": paper_orchestrator._champion_version,
                            "target_weight": allocated_weight,
                            "sector": bist_universe.get_ticker_sector(p["ticker"]),
                        }
                    )

            # Rebalance sinyallerini birleştir: Önce Çıkışlar, Sonra Girişler
            queued_signals = exit_signals + entry_signals
            logger.info("Compiled dynamic portfolio signals", exits=len(exit_signals), entries=len(entry_signals))

            # Sinyalleri StateStore'a PENDING olarak kaydet (Sabah Açılışında Yürütülecek)
            if queued_signals:
                paper_orchestrator.store.save_pending_signals(queued_signals)
                logger.info("Queued signals stored for morning execution", count=len(queued_signals))

        # DB Takas/Portföy Log Kaydı
        if paper_orchestrator.portfolio:
            try:
                await pg_execute(
                    """
                    INSERT INTO paper_trade_portfolio (
                        total_equity, cash, positions_count, is_rebalance, metadata, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    paper_orchestrator.portfolio.get_total_value(),
                    paper_orchestrator.portfolio.cash,
                    len(current_positions),
                    needs_rebalance,
                    orjson.dumps(mtm_summary).decode("utf-8"),
                    datetime.now(UTC),
                )
            except Exception as e:
                logger.error("DB Record Error", error=str(e))

    # ============================================================
    # STRATEJI TESHIS DONGUSU — Kapali Geri Bildirim
    # Tamamlanan islemleri analiz edip FROZEN_PARAMS i otomatik gunceller.
    # ============================================================
    try:
        raw_trades = paper_orchestrator.portfolio.get_trades() or paper_orchestrator.portfolio._trades
        completed_trades = [t.__dict__ if hasattr(t, "__dict__") else dict(t) for t in raw_trades]
        diag_result = strategy_diagnostician.run_daily_diagnosis(
            trades=completed_trades,
            current_params=FROZEN_PARAMS,
            equity_curve=list(paper_orchestrator.portfolio.get_equity_curve() or paper_orchestrator.portfolio._equity_curve),
            date=today_str,
        )
        if diag_result.get("change_count", 0) > 0:
            logger.info(
                "StrategyDiagnostician parametre guncellemesi yapti",
                degisiklikler=diag_result.get("changes"),
            )
    except Exception as _diag_exc:
        logger.warning("StrategyDiagnostician calistirilamadi", hata=str(_diag_exc))

    return {
        "status": "COMPLETED",
        "phase": "EOD_SIGNAL_PHASE",
        "date": today_str,
        "needs_rebalance": needs_rebalance,
        "queued_signals_count": len(queued_signals),
        "portfolio_summary": mtm_summary,
    }


async def run_morning_execution_cycle(target_date: str | None = None) -> dict[str, Any]:
    """09:55-10:05 Sabah Açılışı: Bekleyen emirleri gerçek açılış ve mikro-yapı defteriyle yürütür.

    Args:
        target_date: İşlem yapılacak hedef tarih (ISO format: YYYY-MM-DD). Boşsa bugünün tarihi.

    Returns:
        dict[str, Any]: Sabah yürütme döngüsü sonuç raporu.
    """
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
    start_date = (today_dt - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
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
    """API ve zamanlayıcı için ortak orkestrasyon fonksiyonu.

    Günün saatine ve bekleyen emir durumuna göre sabah yürütme veya akşam EOD
    döngüsünü dinamik olarak seçip çalıştırır.

    Returns:
        dict[str, Any]: Çalıştırılan döngünün sonuç özeti.
    """
    now_hour = datetime.now(timezone(timedelta(hours=3))).hour
    pending = paper_orchestrator.store.load_pending_signals()
    # Sabah seansinda, portfoy henuz bosken VEYA geceden bekleyen emirler varsa once sabah yurutme dongusu calisir
    if len(pending) > 0 or len(paper_orchestrator.portfolio.get_all_positions()) == 0 or now_hour < 12:
        return await run_morning_execution_cycle()
    else:
        return await run_eod_signal_cycle()


__all__ = [
    "DEFAULT_INVESTABLE_POOL_FLOOR",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_MAX_POSITION_CAP",
    "DEFAULT_MIN_EXIT_SCORE",
    "DEFAULT_MIN_POSITION_FLOOR",
    "DEFAULT_MIN_SCORE_THRESHOLD",
    "DEFAULT_SCAN_LIMIT",
    "HOLDING_PERIOD_DAYS",
    "get_last_rebalance_date",
    "run_eod_signal_cycle",
    "run_morning_execution_cycle",
    "run_unified_daily_cycle",
]


if __name__ == "__main__":
    asyncio.run(run_unified_daily_cycle())
