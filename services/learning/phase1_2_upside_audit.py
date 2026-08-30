from typing import Any

"""Phase 1 & 2: Baseline and Upside/BULL_TREND Loss Audit
Bu betik, Train/Validation (Holdout ÖNCESİ) dönemdeki işlemleri derinlemesine analiz eder.
Amacı: BULL_TREND rejimindeki kayıpların ve kaçırılan rallilerin (V-dip) KÖK NEDENİNİ bulmaktır.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import structlog

from services.learning.frozen_strategy_engine import FROZEN_PARAMS, MODELS, TOTAL_FRICTION
from services.learning.institutional_walkforward_engine import (
    ModelTrainer,
    extract_point_in_time_features,
    load_all_market_data,
)
from services.learning.upside_capture_validator import detect_market_regime_v2

logger = structlog.get_logger()


def run_audit_simulation(eval_dates, features_by_ticker, xu100_close, trainer, initial_capital=10_000_000.0) -> Any:
    """Otomatik eklendi."""
    portfolio_cash = initial_capital
    positions = {}

    trade_history = []
    daily_stats = []

    smoothed_scores = {tk: 0.0 for tk in features_by_ticker}
    pending_evals = []
    completed_wins = {m: 0 for m in MODELS}
    completed_totals = {m: 0 for m in MODELS}

    start_xu100 = (
        float(xu100_close.loc[eval_dates[0]]) if eval_dates[0] in xu100_close.index else float(xu100_close.iloc[0])
    )

    current_fold = 0

    for step_i, current_date in enumerate(eval_dates):
        # 0. Kapanan tahmin havuzlarını güncelle
        still_pending = []
        for pe in pending_evals:
            if pe["eval_date"] <= current_date:
                completed_totals[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins[pe["model"]] += 1
            else:
                still_pending.append(pe)
        pending_evals = still_pending

        # 1. RETRAINING
        if step_i % FROZEN_PARAMS["retraining_freq"] == 0:
            current_fold += 1
            train_rows = [fdf.loc[: current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(comb_train)

        # 2. REJIM TESPİTİ
        current_regime = detect_market_regime_v2(xu100_close, current_date)
        hist_xu = xu100_close.loc[:current_date]
        ret_5d_xu = (hist_xu.iloc[-1] / hist_xu.iloc[-5] - 1.0) * 100.0 if len(hist_xu) >= 5 else 0.0
        is_v_dip = current_regime == "BULL_TREND" and ret_5d_xu > 3.5
        regime_tag = "V_DIP_RECOVERY" if is_v_dip else current_regime

        max_pos = FROZEN_PARAMS["max_pos"].get(current_regime, 2)
        min_score = FROZEN_PARAMS["min_score"].get(current_regime, 0.15)

        # 3. DİNAMİK TRUST AĞIRLIKLARI
        weights = {}
        for m in MODELS:
            n_done = completed_totals[m]
            if n_done >= 15:
                acc = completed_wins[m] / n_done
                shrinkage = 1.0 - np.exp(-n_done / 50.0)
                trust = (1.0 - shrinkage) * 0.50 + shrinkage * acc
            else:
                trust = 0.50
            weights[m] = max(0.05, min(0.35, trust))
        norm_w = {m: w / sum(weights.values()) for m, w in weights.items()}

        # 4. SİNYAL FUSION
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        batch_sigs = trainer.predict_batch_day(day_tickers, day_rows)

        cand = []
        for i, tk in enumerate(day_tickers):
            row = day_rows[i]
            ret_5d = float(row.get("target_5d_ret", 0.0))
            atr_p = float(row.get("atr_pct", 3.0))

            raw_c = sum(norm_w[m] * batch_sigs[tk][m] for m in MODELS)
            delta_s = abs(raw_c - smoothed_scores[tk])
            alpha_ema = (
                FROZEN_PARAMS["ema_alpha_fast"]
                if delta_s > FROZEN_PARAMS["ema_delta_thresh"]
                else FROZEN_PARAMS["ema_alpha_slow"]
            )
            smoothed_scores[tk] = alpha_ema * raw_c + (1.0 - alpha_ema) * smoothed_scores[tk]

            cand.append(
                {
                    "ticker": tk,
                    "score": smoothed_scores[tk],
                    "raw_score": raw_c,
                    "close": float(row["close"]),
                    "ret_5d": ret_5d,
                    "atr_pct": atr_p,
                }
            )

            for m in MODELS:
                p_val = 1 if batch_sigs[tk][m] > 0 else -1
                act_sign = 1 if ret_5d > 0 else -1
                pending_evals.append(
                    {"eval_date": current_date + timedelta(days=7), "model": m, "is_correct": (p_val == act_sign)}
                )

        # 5. POZİSYON ÇIKIŞLARI (Deep Audit)
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos["highest_price"], cur_p)
            pos["lowest_price"] = min(pos["lowest_price"], cur_p)

            mfe = (pos["highest_price"] / pos["entry_price"] - 1.0) * 100.0  # Max Favorable Excursion
            mae = (pos["lowest_price"] / pos["entry_price"] - 1.0) * 100.0  # Max Adverse Excursion

            atr_buffer = max(FROZEN_PARAMS["min_atr_pct"], pos.get("atr_pct", 3.0) * FROZEN_PARAMS["trailing_atr_mult"])

            exit_reason = None
            if pnl_pct <= FROZEN_PARAMS["hard_stop_pct"]:
                exit_reason = "HARD_STOP"
            elif pos["highest_price"] > pos["entry_price"] * 1.06 and cur_p < pos["highest_price"] * (
                1.0 - atr_buffer / 100.0
            ):
                exit_reason = "TRAILING_STOP"
            elif pnl_pct >= FROZEN_PARAMS["take_profit_pct"]:
                exit_reason = "TAKE_PROFIT"
            elif (
                pos["days_held"] >= FROZEN_PARAMS["min_hold_days"]
                and smoothed_scores[tk] < FROZEN_PARAMS["signal_reversal_thresh"]
            ):
                exit_reason = "SIGNAL_REVERSAL"
            elif pos["days_held"] >= FROZEN_PARAMS["max_hold_days"]:
                exit_reason = "MAX_HOLD_TIME"

            if exit_reason:
                t_val = pos["shares"] * cur_p
                friction = t_val * TOTAL_FRICTION
                net_val = t_val - friction
                net_val - (pos["shares"] * pos["entry_price"])
                portfolio_cash += net_val

                trade_history.append(
                    {
                        "ticker": tk,
                        "entry_date": pos["entry_date"],
                        "exit_date": current_date,
                        "entry_regime": pos["regime_tag"],
                        "days_held": pos["days_held"],
                        "entry_price": pos["entry_price"],
                        "exit_price": cur_p,
                        "pnl_pct": (net_val / (pos["shares"] * pos["entry_price"]) - 1.0) * 100.0,
                        "mfe_pct": mfe,
                        "mae_pct": mae,
                        "exit_reason": exit_reason,
                        "exit_score": smoothed_scores[tk],
                    }
                )

                closed_tickers.append(tk)

        for tk in closed_tickers:
            del positions[tk]

        # 6. YENİ POZİSYON AÇILIŞLARI
        cand.sort(key=lambda x: x["score"], reverse=True)
        top_cand = [c for c in cand if c["score"] >= min_score and c["ticker"] not in positions]
        slots = max_pos - len(positions)

        # Nakit Oranı ve Kaçırılan Fırsat Ölçümü İçin
        invested_pre_open = sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        portfolio_cash / (portfolio_cash + invested_pre_open) if (portfolio_cash + invested_pre_open) > 0 else 1.0

        if slots > 0 and len(top_cand) > 0 and portfolio_cash > FROZEN_PARAMS["min_cash_to_open"]:
            tot_val = portfolio_cash + invested_pre_open
            for rank_idx, c in enumerate(top_cand[:slots]):
                alloc_pct = (
                    FROZEN_PARAMS["top1_alloc_pct"]
                    if (rank_idx == 0 and c["score"] > FROZEN_PARAMS["conviction_score_min"])
                    else FROZEN_PARAMS["default_alloc_pct"]
                )
                alloc_slot = min(portfolio_cash / (slots - rank_idx), tot_val * alloc_pct)
                shares = int((alloc_slot * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    friction = cost * TOTAL_FRICTION
                    portfolio_cash -= cost + friction
                    positions[c["ticker"]] = {
                        "shares": shares,
                        "entry_price": c["close"],
                        "entry_date": current_date,
                        "days_held": 0,
                        "highest_price": c["close"],
                        "lowest_price": c["close"],
                        "atr_pct": c["atr_pct"],
                        "regime": current_regime,
                        "regime_tag": regime_tag,
                    }

        # 7. GÜNLÜK KAYITLAR
        cur_eq = portfolio_cash + sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        cur_xu = float(xu100_close.loc[current_date]) if current_date in xu100_close.index else start_xu100

        daily_stats.append(
            {
                "date": current_date,
                "regime": regime_tag,
                "equity": cur_eq,
                "xu100": cur_xu,
                "cash_ratio": portfolio_cash / cur_eq,
                "num_positions": len(positions),
                "max_pos_allowed": max_pos,
                "top_cand_score": top_cand[0]["score"] if top_cand else 0.0,
                "top_cand_raw": top_cand[0]["raw_score"] if top_cand else 0.0,
            }
        )

    return pd.DataFrame(trade_history), pd.DataFrame(daily_stats)


if __name__ == "__main__":
    logger.info("🔄 PHASE 1 & 2: Loading Data for Train/Validation Audit...")
    stock_data, xu100_close = load_all_market_data()
    feature_cols = [
        "roc_5d",
        "roc_20d",
        "momentum_20d",
        "price_vs_sma20",
        "price_vs_sma50",
        "price_vs_sma200",
        "atr_pct",
        "volatility_20d",
        "volume_zscore",
        "bb_position",
    ]
    features_by_ticker = {}
    for tk, df in stock_data.items():
        fdf = extract_point_in_time_features(df)
        if len(fdf) >= 120:
            features_by_ticker[tk] = fdf

    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = common_dates[120:280]  # Exact Train/Val period used before

    trainer = ModelTrainer(feature_cols)
    logger.info(f"🕵️ Running Deep Audit Simulation from {val_dates[0].date()} to {val_dates[-1].date()}...")

    trades_df, daily_df = run_audit_simulation(val_dates, features_by_ticker, xu100_close, trainer)

    # --- PHASE 2: AUDIT ANALYSIS ---
    logger.info("\n=========================================================")
    logger.info("PHASE 2: UPSIDE LOSS & BULL_TREND ROOT-CAUSE AUDIT")
    logger.info("=========================================================")

    # 1. Trade Analysis by Regime
    logger.info("\n📊 1. TRADE PERFORMANCE BY REGIME (TRAIN/VAL)")
    regime_perf = (
        trades_df.groupby("entry_regime")
        .agg(
            trades=("ticker", "count"),
            win_rate=("pnl_pct", lambda x: (x > 0).mean() * 100),
            avg_pnl=("pnl_pct", "mean"),
            avg_mfe=("mfe_pct", "mean"),  # Ne kadar potansiyel vardı?
            avg_mae=("mae_pct", "mean"),  # Ne kadar terste kaldı?
            avg_days=("days_held", "mean"),
        )
        .round(2)
    )
    logger.info(regime_perf.to_string())

    # 2. Deep Dive into BULL_TREND failures
    bull_trades = trades_df[trades_df["entry_regime"] == "BULL_TREND"]
    logger.info(f"\n🔍 2. BULL_TREND DEEP DIVE (Total Trades: {len(bull_trades)})")
    if len(bull_trades) > 0:
        exit_reasons = bull_trades["exit_reason"].value_counts()
        logger.info("Exit Reasons in BULL_TREND:")
        logger.info(exit_reasons.to_string())

        # Did they ever have profit? (MFE analysis)
        had_profit = bull_trades[bull_trades["mfe_pct"] > 3.0]
        logger.info(f"Trades that went >+3% in profit before closing: {len(had_profit)} / {len(bull_trades)}")
        if len(had_profit) > 0:
            avg_lost_profit = (had_profit["mfe_pct"] - had_profit["pnl_pct"]).mean()
            logger.info(f"Average profit given back from peak: {avg_lost_profit:.2f}%")

    # 3. Missed Upside Days (XU100 > 1.5% but Portfolio < 0.5%)
    daily_df["strat_ret"] = daily_df["equity"].pct_change() * 100
    daily_df["xu_ret"] = daily_df["xu100"].pct_change() * 100

    missed_rallies = daily_df[(daily_df["xu_ret"] > 1.5) & (daily_df["strat_ret"] < 0.5)]
    logger.info("\n🚀 3. MISSED RALLIES AUDIT")
    logger.info(f"Days XU100 rallied >1.5%: {len(daily_df[daily_df['xu_ret'] > 1.5])}")
    logger.info(f"Days we missed it (Strat < 0.5%): {len(missed_rallies)}")

    if len(missed_rallies) > 0:
        avg_cash_on_miss = missed_rallies["cash_ratio"].mean() * 100
        logger.info(f"Average Cash Ratio on missed days: {avg_cash_on_miss:.1f}%")
        logger.info("Regimes during missed rallies:")
        logger.info(missed_rallies["regime"].value_counts().to_string())

        # Neden nakitteydik? Sinyaller mi zayıftı, kısıtlamalar mı vurdu?
        missed_high_cash = missed_rallies[missed_rallies["cash_ratio"] > 0.4]
        avg_top_score = missed_high_cash["top_cand_score"].mean()
        avg_top_raw = missed_high_cash["top_cand_raw"].mean()
        logger.info("\nWhy were we in cash? (When cash > 40% on missed rally days)")
        logger.info(f"Average Top Smoothed Score: {avg_top_score:.3f} (Raw: {avg_top_raw:.3f})")
        logger.info("Note: Bulls need >0.08, Bears need >0.28 to enter.")

    logger.info("\n📝 NEXT STEPS: Use this diagnostic to design Phase 3 Alternatives.")
