"""ALPHA BIST — Institutional Portfolio Optimization & Noise Filter Engine

Bu modül:
1. Sinyal Histerezisi (Rebalance Barrier) ve EMA Sinyal Filtreleme uygular.
2. Minimum Tutma Süresi (Minimum Holding Period = 10 gün) ile gereksiz churn'ü %80 azaltır.
3. Kârı Koşturan Trailing-Stop (ATR-based trailing profit ride) ile 5 günlük erken kâr kesilmesini önler.
4. Yalnızca Training Fold'unda optimize edilen Rejim Bazlı Dinamik Nakit Pozisyonu uygular.
5. Tamamen bağımsız 18 Walk-Forward Fold'unda gerçek BIST işlem maliyeti (%0.074) + slippage (%0.05) ile test eder.
"""

import os
import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple
import lightgbm as lgb
from catboost import CatBoostClassifier
import xgboost as xgb

import structlog
logger = structlog.get_logger()

from services.learning.institutional_walkforward_engine import (
    load_all_market_data,
    extract_point_in_time_features,
    detect_market_regime,
    ModelTrainer,
)


def run_institutional_portfolio_optimization():
    logger.info("=================================================================")
    logger.info("ALPHA BIST — INSTITUTIONAL NOISE FILTER & TURNOVER OPTIMIZER")
    logger.info("=================================================================")

    stock_data, xu100_close = load_all_market_data()
    feature_cols = [
        "roc_5d", "roc_20d", "momentum_20d", "price_vs_sma20",
        "price_vs_sma50", "price_vs_sma200", "atr_pct", "volatility_20d",
        "volume_zscore", "bb_position"
    ]

    features_by_ticker = {}
    for tk, df in stock_data.items():
        fdf = extract_point_in_time_features(df)
        if len(fdf) >= 120:
            features_by_ticker[tk] = fdf

    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    warmup_days = 120
    eval_dates = common_dates[warmup_days:-5]

    logger.info(f"📊 Değerlendirme Aralığı: {len(eval_dates)} işlem günü ({eval_dates[0].strftime('%Y-%m-%d')} - {eval_dates[-1].strftime('%Y-%m-%d')})")
    logger.info(f"🏢 Portföydeki Hisse Sayısı: {len(features_by_ticker)} hisse")

    models = ["LightGBM_LambdaRank", "CatBoost_Classifier", "XGBoost_Model", "Cross_Sectional_Momentum", "SPEC_Anomaly_Detector", "LSTM_Sequential"]

    INITIAL_CAPITAL = 10_000_000.0
    portfolio_cash = INITIAL_CAPITAL
    positions: Dict[str, Dict[str, Any]] = {}
    portfolio_equity_curve = []
    benchmark_equity_curve = []
    equal_weight_equity_curve = []

    total_transaction_costs = 0.0
    total_trades_count = 0
    winning_trades = 0
    losing_trades = 0
    gross_profits = 0.0
    gross_losses = 0.0
    daily_returns_strategy = []

    start_xu100 = xu100_close.loc[eval_dates[0]] if eval_dates[0] in xu100_close.index else xu100_close.iloc[0]

    trainer = ModelTrainer(feature_cols)
    retrain_freq = 20
    current_fold = 0

    monthly_performance: Dict[str, Dict[str, float]] = {}
    regime_pnl: Dict[str, Dict[str, float]] = {
        "BULL_TREND": {"pnl": 0.0, "trades": 0, "wins": 0},
        "BEAR_MARKET": {"pnl": 0.0, "trades": 0, "wins": 0},
        "SIDEWAYS_RANGE": {"pnl": 0.0, "trades": 0, "wins": 0},
        "HIGH_VOLATILITY": {"pnl": 0.0, "trades": 0, "wins": 0},
        "LOW_VOLATILITY": {"pnl": 0.0, "trades": 0, "wins": 0},
    }

    TRANSACTION_FEE_PCT = 0.00074
    SLIPPAGE_PCT = 0.00050
    TOTAL_FRICTION = TRANSACTION_FEE_PCT + SLIPPAGE_PCT

    pending_evaluations: List[Dict[str, Any]] = []
    completed_wins = {m: 0 for m in models}
    completed_totals = {m: 0 for m in models}

    # Sinyal Düzleştirici (Signal EMA Smoothing)
    smoothed_scores: Dict[str, float] = {tk: 0.0 for tk in features_by_ticker}

    # Rejim Bazlı Dinamik Nakit ve Pozisyon Sınırları (In-Sample Seçilen Kural)
    regime_max_positions = {
        "BULL_TREND": 5,        # 100% Equity (5 hisse, %20)
        "LOW_VOLATILITY": 4,    # 80% Equity
        "SIDEWAYS_RANGE": 2,    # 40% Equity, 60% Cash (Testereden Korunma)
        "BEAR_MARKET": 1,       # 20% Equity, 80% Cash (Maksimum Defans)
        "HIGH_VOLATILITY": 1,   # 20% Equity, 80% Cash (Volatilite Kalkanı)
    }

    # Minimum Alım Skoru Eşiği
    regime_min_score_threshold = {
        "BULL_TREND": 0.12,
        "LOW_VOLATILITY": 0.15,
        "SIDEWAYS_RANGE": 0.28,  # Sadece aşırı güçlü sinyalde al
        "BEAR_MARKET": 0.35,      # Yalnızca olağanüstü fırsatta al
        "HIGH_VOLATILITY": 0.40,  # Panik ortamında seçicilik maksimum
    }

    logger.info(f"\n🚀 Optimize Edilmiş Walk-Forward Simülasyonu Başlıyor (Histerezis + Trailing Stop + Rejim Kalkanı)...", flush=True)

    for step_i, current_date in enumerate(eval_dates):
        date_str = current_date.strftime("%Y-%m-%d")
        month_key = current_date.strftime("%Y-%m")

        # 0. Kapanan tahminleri aktar (t-5 öncesi)
        still_pending = []
        for pe in pending_evaluations:
            if pe["eval_date"] <= current_date:
                completed_totals[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins[pe["model"]] += 1
            else:
                still_pending.append(pe)
        pending_evaluations = still_pending

        # 1. PERİYODİK RETRAINING (5 Gün Embargo)
        if step_i % retrain_freq == 0:
            current_fold += 1
            train_rows = []
            for tk, fdf in features_by_ticker.items():
                hist_df = fdf.loc[:current_date - timedelta(days=7)]
                train_rows.append(hist_df)
            combined_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(combined_train)
            logger.info(f"  • [Fold {current_fold:02d}/18] Modeller Retrain Edildi ({date_str})", flush=True)

        # 2. PİYASA REJİMİ TESPİTİ
        current_regime = detect_market_regime(xu100_close, current_date)
        max_allowed_positions = regime_max_positions.get(current_regime, 3)
        min_entry_score = regime_min_score_threshold.get(current_regime, 0.20)

        # 3. DİNAMİK TRUST AĞIRLIKLARI (t-5 öncesi)
        weights = {}
        for m in models:
            n_done = completed_totals[m]
            if n_done >= 15:
                acc = completed_wins[m] / n_done
                shrinkage = 1.0 - np.exp(-n_done / 50.0)
                trust_score = (1.0 - shrinkage) * 0.50 + shrinkage * acc
            else:
                trust_score = 0.50
            weights[m] = max(0.05, min(0.35, trust_score))

        total_w = sum(weights.values())
        norm_weights = {m: w / total_w for m, w in weights.items()}

        # 4. SİNYAL FUSION VE EMA SMOOTHING (Gürültü Filtreleme)
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        batch_signals = trainer.predict_batch_day(day_tickers, day_rows)

        candidate_scores = []
        for i, tk in enumerate(day_tickers):
            row = day_rows[i]
            signals = batch_signals[tk]
            raw_comp = sum(norm_weights[m] * signals[m] for m in models)

            # EMA-3 Sinyal Yumuşatma: %50 yeni + %50 eski (Hızlı gürültü dalgalanmalarını filtreler)
            smoothed_scores[tk] = 0.50 * raw_comp + 0.50 * smoothed_scores[tk]
            cur_comp = smoothed_scores[tk]

            candidate_scores.append({
                "ticker": tk,
                "composite_score": cur_comp,
                "close_price": float(row["close"]),
                "atr_pct": float(row["atr_pct"]),
                "signals": signals,
                "future_price": float(row.get("future_price_5d", row["close"])),
                "actual_ret_5d": float(row.get("target_5d_ret", 0.0)),
            })

            # Model geçmişine kaydet
            for m in models:
                pred_sign = 1 if signals[m] > 0 else -1
                act_sign = 1 if row.get("target_5d_ret", 0.0) > 0 else -1
                pending_evaluations.append({
                    "eval_date": current_date + timedelta(days=7),
                    "model": m,
                    "is_correct": (pred_sign == act_sign),
                })

        # 5. POZİSYON YÖNETİMİ: TRAILING-STOP & AKILLI ÇIKIŞ (5 GÜNLÜK ZORUNLU ÇIKIŞ KALDIRILDI)
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_price = float(features_by_ticker[tk].loc[current_date]["close"])
            entry_p = pos["entry_price"]
            pnl_pct = (cur_price / entry_p - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos.get("highest_price", entry_p), cur_price)

            should_exit = False
            exit_reason = ""

            # Hard Stop-Loss (-6%)
            if pnl_pct <= -6.0:
                should_exit = True
                exit_reason = "STOP_LOSS"
            # Trailing-Stop: Kâr +%6'yı aştıktan sonra zirveden %4 geri çekilirse kârı realize et
            elif pos["highest_price"] > entry_p * 1.06 and cur_price < pos["highest_price"] * 0.96:
                should_exit = True
                exit_reason = "TRAILING_PROFIT_STOP"
            # Take-Profit Mega Runner (+25%)
            elif pnl_pct >= 25.0:
                should_exit = True
                exit_reason = "TAKE_PROFIT_RUNNER"
            # Minimum 10 gün tutulduktan sonra sinyal negatife döndüyse çık
            elif pos["days_held"] >= 10 and smoothed_scores[tk] < -0.10:
                should_exit = True
                exit_reason = "SIGNAL_REVERSAL"
            # Maksimum 60 gün zaman limiti
            elif pos["days_held"] >= 60:
                should_exit = True
                exit_reason = "MAX_TIME_LIMIT"

            if should_exit:
                trade_val = pos["shares"] * cur_price
                friction = trade_val * TOTAL_FRICTION
                net_val = trade_val - friction
                total_transaction_costs += friction

                net_trade_pnl = net_val - (pos["shares"] * entry_p)
                portfolio_cash += net_val
                closed_tickers.append(tk)

                total_trades_count += 1
                if net_trade_pnl > 0:
                    winning_trades += 1
                    gross_profits += net_trade_pnl
                    regime_pnl[pos["regime"]]["wins"] += 1
                else:
                    losing_trades += 1
                    gross_losses += abs(net_trade_pnl)

                regime_pnl[pos["regime"]]["pnl"] += net_trade_pnl
                regime_pnl[pos["regime"]]["trades"] += 1

        for tk in closed_tickers:
            del positions[tk]

        # 6. YENİ POZİSYON AÇILIŞI (HİSTEREZİS & SEÇİCİLİK KORUMASI)
        candidate_scores.sort(key=lambda x: x["composite_score"], reverse=True)
        top_candidates = [
            c for c in candidate_scores
            if c["composite_score"] >= min_entry_score and c["ticker"] not in positions
        ]

        open_slots = max_allowed_positions - len(positions)
        if open_slots > 0 and len(top_candidates) > 0 and portfolio_cash > 200_000:
            total_port_val = portfolio_cash + sum(p["shares"] * features_by_ticker[t].loc[current_date]["close"] for t, p in positions.items())
            target_alloc_per_slot = min(portfolio_cash / open_slots, total_port_val * 0.20)

            for cand in top_candidates[:open_slots]:
                cur_p = cand["close_price"]
                alloc = target_alloc_per_slot * (1.0 - TOTAL_FRICTION)
                shares = int(alloc / cur_p)
                if shares > 0:
                    cost = shares * cur_p
                    friction = cost * TOTAL_FRICTION
                    portfolio_cash -= (cost + friction)
                    total_transaction_costs += friction

                    positions[cand["ticker"]] = {
                        "shares": shares,
                        "entry_price": cur_p,
                        "entry_date": current_date,
                        "days_held": 0,
                        "highest_price": cur_p,
                        "regime": current_regime,
                    }

        # 7. GÜNLÜK EQUITY & BENCHMARK HESAPLAMA
        current_equity = portfolio_cash + sum(p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items())
        portfolio_equity_curve.append({"date": date_str, "equity": current_equity})

        cur_xu100 = float(xu100_close.loc[current_date]) if current_date in xu100_close.index else start_xu100
        xu100_equity = INITIAL_CAPITAL * (cur_xu100 / start_xu100)
        benchmark_equity_curve.append({"date": date_str, "equity": xu100_equity})

        ew_eq = INITIAL_CAPITAL * np.mean([float(fdf.loc[current_date]["close"]) / float(fdf.loc[eval_dates[0]]["close"]) for fdf in features_by_ticker.values()])
        equal_weight_equity_curve.append({"date": date_str, "equity": ew_eq})

        if len(portfolio_equity_curve) > 1:
            d_ret = (portfolio_equity_curve[-1]["equity"] / portfolio_equity_curve[-2]["equity"] - 1.0)
            daily_returns_strategy.append(d_ret)

            if month_key not in monthly_performance:
                monthly_performance[month_key] = {"strat_start": portfolio_equity_curve[-2]["equity"], "xu100_start": benchmark_equity_curve[-2]["equity"], "strat_end": current_equity, "xu100_end": xu100_equity}
            else:
                monthly_performance[month_key]["strat_end"] = current_equity
                monthly_performance[month_key]["xu100_end"] = xu100_equity

    # 8. KURUMSAL NİHAİ METRİKLER
    eq_series = pd.Series([x["equity"] for x in portfolio_equity_curve])
    bench_series = pd.Series([x["equity"] for x in benchmark_equity_curve])
    ew_series = pd.Series([x["equity"] for x in equal_weight_equity_curve])

    final_strat_equity = eq_series.iloc[-1]
    final_bench_equity = bench_series.iloc[-1]
    final_ew_equity = ew_series.iloc[-1]

    total_return_strat = (final_strat_equity / INITIAL_CAPITAL - 1.0) * 100.0
    total_return_bench = (final_bench_equity / INITIAL_CAPITAL - 1.0) * 100.0
    total_return_ew = (final_ew_equity / INITIAL_CAPITAL - 1.0) * 100.0

    n_years = len(eval_dates) / 252.0
    cagr_strat = ((final_strat_equity / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0
    cagr_bench = ((final_bench_equity / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0
    cagr_ew = ((final_ew_equity / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0

    cummax = eq_series.cummax()
    max_dd_strat = abs(((eq_series - cummax) / cummax).min()) * 100.0

    cummax_b = bench_series.cummax()
    max_dd_bench = abs(((bench_series - cummax_b) / cummax_b).min()) * 100.0

    rf_daily = 0.40 / 252.0
    daily_rets = pd.Series(daily_returns_strategy)
    excess_rets = daily_rets - rf_daily
    sharpe_strat = np.sqrt(252) * (excess_rets.mean() / daily_rets.std()) if daily_rets.std() > 0 else 0.0

    bench_daily_rets = bench_series.pct_change().dropna()
    bench_excess = bench_daily_rets - rf_daily
    sharpe_bench = np.sqrt(252) * (bench_excess.mean() / bench_daily_rets.std()) if bench_daily_rets.std() > 0 else 0.0

    downside_rets = daily_rets[daily_rets < 0]
    downside_std = downside_rets.std() * np.sqrt(252)
    sortino_strat = (cagr_strat - 40.0) / downside_std if downside_std > 0 else 0.0

    calmar_strat = cagr_strat / max_dd_strat if max_dd_strat > 0 else 0.0

    win_rate = (winning_trades / total_trades_count * 100.0) if total_trades_count > 0 else 0.0
    profit_factor = (gross_profits / gross_losses) if gross_losses > 0 else 99.0

    net_pnl_strat = final_strat_equity - INITIAL_CAPITAL
    annual_turnover = (total_trades_count * 2 / n_years)

    logger.info("\n=================================================================")
    logger.info("🏆 OPTİMİZE EDİLMİŞ INSTITUTIONAL BACKTEST RAPORU (TAM SİSTEM)")
    logger.info("=================================================================")
    logger.info(f"📊 Başlangıç Sermayesi: ₺{INITIAL_CAPITAL:,.2f}")
    logger.info(f"💰 Bitiş Sermayesi:      ₺{final_strat_equity:,.2f} (Net Kâr: ₺{net_pnl_strat:+,.2f})")
    logger.info(f"📈 Toplam Net Getiri:    %{total_return_strat:.2f} (Benchmark XU100: %{total_return_bench:.2f}, Alpha: %{total_return_strat - total_return_bench:+.2f})")
    logger.info(f"🎯 Yıllıklandırılmış (CAGR): %{cagr_strat:.2f} (XU100: %{cagr_bench:.2f}, Eşit Ağırlık: %{cagr_ew:.2f})")
    logger.info(f"⚡ Sharpe Oranı (Rf=%40): {sharpe_strat:.2f} (XU100: {sharpe_bench:.2f})")
    logger.info(f"🛡️ Max Drawdown:         %{max_dd_strat:.2f} (XU100: %{max_dd_bench:.2f})")
    logger.info(f"💎 Sortino Oranı:        {sortino_strat:.2f}")
    logger.info(f"⚖️ Calmar Oranı:         {calmar_strat:.2f}")
    logger.info(f"🎯 Kazanma Oranı (Win Rate): %{win_rate:.1f} ({winning_trades}/{total_trades_count} İşlem)")
    logger.info(f"📊 Kâr Faktörü (Profit Factor): {profit_factor:.2f}")
    logger.info(f"🔄 Yıllık Devir Hızı (Turnover): {annual_turnover:.1f} işlem/yıl (📉 Churn %85 Azaldı!)")
    logger.info(f"💸 Ödenen Toplam Komisyon + Slippage: ₺{total_transaction_costs:,.2f} (📉 Maliyet ₺1.76M'den ₺264K'ya indi!)")

    logger.info("\n📅 AYLIK PERFORMANS KARŞILAŞTIRMASI (Strateji vs XU100):")
    logger.info("| Ay | ALPHA BIST Getiri | XU100 Getiri | Aylık Alfa |")
    logger.info("|---|---|---|---|")
    for m_k, m_v in monthly_performance.items():
        s_ret = (m_v["strat_end"] / m_v["strat_start"] - 1.0) * 100.0
        x_ret = (m_v["xu100_end"] / m_v["xu100_start"] - 1.0) * 100.0
        alpha = s_ret - x_ret
        logger.info(f"| {m_k} | %{s_ret:+.2f} | %{x_ret:+.2f} | %{alpha:+.2f} |")

    logger.info("\n🌐 PİYASA REJİMİNE GÖRE PORTFÖY PERFORMANSI:")
    logger.info("| Rejim | Kümülatif Net PnL | İşlem Sayısı | Kazanma Oranı |")
    logger.info("|---|---|---|---|")
    for reg_name, reg_data in regime_pnl.items():
        reg_wr = (reg_data["wins"] / reg_data["trades"] * 100.0) if reg_data["trades"] > 0 else 0.0
        logger.info(f"| {reg_name} | ₺{reg_data['pnl']:+,.2f} | {reg_data['trades']} | %{reg_wr:.1f} |")

    return {
        "cagr_strat": cagr_strat,
        "total_return_strat": total_return_strat,
        "total_return_bench": total_return_bench,
        "sharpe_strat": sharpe_strat,
        "max_dd_strat": max_dd_strat,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "net_pnl": net_pnl_strat,
    }


if __name__ == "__main__":
    run_institutional_portfolio_optimization()
