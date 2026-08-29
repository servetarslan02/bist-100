from typing import Any
"""Phase 3 & 4: Alternative Strategies Optimizer (Maximum Sustainable Alpha)
Test edilecek hipotezler:
A) Dynamic Trailing (Kar > %8 ise ATR çarpanı 2.5 -> 1.5)
B) Scout Entries (Bear/Sideways rejimlerinde eşiği 0.12 yap, ama yarı pozisyon aç)
C) Combined (A + B)
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import structlog

from services.learning.frozen_strategy_engine import MODELS, TOTAL_FRICTION
from services.learning.institutional_walkforward_engine import (
    ModelTrainer,
    extract_point_in_time_features,
    load_all_market_data,
)
from services.learning.upside_capture_validator import detect_market_regime_v2

logger = structlog.get_logger()


BASE_PARAMS = {
    "max_pos": {"BULL_TREND": 4, "LOW_VOLATILITY": 4, "SIDEWAYS_RANGE": 2, "BEAR_MARKET": 2, "HIGH_VOLATILITY": 2},
    "min_score": {
        "BULL_TREND": 0.08,
        "LOW_VOLATILITY": 0.10,
        "SIDEWAYS_RANGE": 0.20,
        "BEAR_MARKET": 0.28,
        "HIGH_VOLATILITY": 0.22,
    },
    "top1_alloc_pct": 0.30,
    "default_alloc_pct": 0.20,
    "trailing_atr_mult": 2.5,
    "min_atr_pct": 4.0,
    "hard_stop_pct": -6.5,
    "take_profit_pct": 35.0,
    "min_hold_days": 12,
    "max_hold_days": 65,
    "signal_reversal_thresh": -0.15,
    "ema_alpha_fast": 0.75,
    "ema_alpha_slow": 0.40,
    "ema_delta_thresh": 0.15,
    "conviction_score_min": 0.20,
    "min_cash_to_open": 200_000,
    "retraining_freq": 20,
}


def run_candidate(eval_dates, features_by_ticker, xu100_close, trainer, candidate_name, initial_capital=10_000_000.0) -> Any:
    """Otomatik eklendi."""
    portfolio_cash = initial_capital
    positions = {}
    equity_curve = []

    smoothed_scores = {tk: 0.0 for tk in features_by_ticker}
    pending_evals = []
    completed_wins = {m: 0 for m in MODELS}
    completed_totals = {m: 0 for m in MODELS}
    float(xu100_close.loc[eval_dates[0]]) if eval_dates[0] in xu100_close.index else float(xu100_close.iloc[0])

    total_costs = 0.0
    wins, trades = 0, 0

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
        if step_i % BASE_PARAMS["retraining_freq"] == 0:
            train_rows = [fdf.loc[: current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(comb_train)

        # 2. REJIM TESPİTİ
        current_regime = detect_market_regime_v2(xu100_close, current_date)
        hist_xu = xu100_close.loc[:current_date]
        (hist_xu.iloc[-1] / hist_xu.iloc[-5] - 1.0) * 100.0 if len(hist_xu) >= 5 else 0.0

        max_pos = BASE_PARAMS["max_pos"].get(current_regime, 2)
        min_score = BASE_PARAMS["min_score"].get(current_regime, 0.15)

        # CANDIDATE B & C: Scout Entries (Lower threshold in Bear/Sideways)
        if candidate_name in ["B_Scout_Entries", "C_Combined"]:
            if current_regime in ["BEAR_MARKET", "SIDEWAYS_RANGE", "HIGH_VOLATILITY"]:
                min_score = 0.12

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
            raw_c = sum(norm_w[m] * batch_sigs[tk][m] for m in MODELS)
            delta_s = abs(raw_c - smoothed_scores[tk])
            alpha_ema = (
                BASE_PARAMS["ema_alpha_fast"]
                if delta_s > BASE_PARAMS["ema_delta_thresh"]
                else BASE_PARAMS["ema_alpha_slow"]
            )
            smoothed_scores[tk] = alpha_ema * raw_c + (1.0 - alpha_ema) * smoothed_scores[tk]
            cand.append(
                {
                    "ticker": tk,
                    "score": smoothed_scores[tk],
                    "close": float(row["close"]),
                    "atr_pct": float(row.get("atr_pct", 3.0)),
                }
            )

            for m in MODELS:
                pending_evals.append(
                    {
                        "eval_date": current_date + timedelta(days=7),
                        "model": m,
                        "is_correct": ((1 if batch_sigs[tk][m] > 0 else -1) == (1 if ret_5d > 0 else -1)),
                    }
                )

        # 5. POZİSYON ÇIKIŞLARI
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), cur_p)

            # CANDIDATE A & C: Dynamic Trailing
            if candidate_name in ["A_Dynamic_Trailing", "C_Combined"]:
                if pnl_pct > 8.0:
                    current_atr_mult = 1.5  # Profit locked in, tighten stop
                else:
                    current_atr_mult = 2.5
            else:
                current_atr_mult = BASE_PARAMS["trailing_atr_mult"]

            atr_buffer = max(BASE_PARAMS["min_atr_pct"], pos.get("atr_pct", 3.0) * current_atr_mult)

            should_exit = False
            if (
                pnl_pct <= BASE_PARAMS["hard_stop_pct"]
                or pos["highest_price"] > pos["entry_price"] * 1.06
                and cur_p < pos["highest_price"] * (1.0 - atr_buffer / 100.0)
                or pnl_pct >= BASE_PARAMS["take_profit_pct"]
                or pos["days_held"] >= BASE_PARAMS["min_hold_days"]
                and smoothed_scores[tk] < BASE_PARAMS["signal_reversal_thresh"]
                or pos["days_held"] >= BASE_PARAMS["max_hold_days"]
            ):
                should_exit = True

            if should_exit:
                net_val = (pos["shares"] * cur_p) * (1.0 - TOTAL_FRICTION)
                portfolio_cash += net_val
                total_costs += (pos["shares"] * cur_p) * TOTAL_FRICTION
                closed_tickers.append(tk)
                trades += 1
                if net_val > pos["shares"] * pos["entry_price"]:
                    wins += 1

        for tk in closed_tickers:
            del positions[tk]

        # 6. YENİ POZİSYON AÇILIŞLARI
        cand.sort(key=lambda x: x["score"], reverse=True)
        top_cand = [c for c in cand if c["score"] >= min_score and c["ticker"] not in positions]
        slots = max_pos - len(positions)
        invested_pre = sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )

        if slots > 0 and len(top_cand) > 0 and portfolio_cash > BASE_PARAMS["min_cash_to_open"]:
            tot_val = portfolio_cash + invested_pre
            for rank_idx, c in enumerate(top_cand[:slots]):
                alloc_pct = (
                    BASE_PARAMS["top1_alloc_pct"]
                    if (rank_idx == 0 and c["score"] > BASE_PARAMS["conviction_score_min"])
                    else BASE_PARAMS["default_alloc_pct"]
                )

                # CANDIDATE B & C: Scout Position Sizing (Half size for bear/sideways entries below strong conviction)
                if candidate_name in ["B_Scout_Entries", "C_Combined"]:
                    if current_regime in ["BEAR_MARKET", "SIDEWAYS_RANGE"] and c["score"] < 0.20:
                        alloc_pct = alloc_pct * 0.5  # Half size for early scout

                alloc_slot = min(portfolio_cash / (slots - rank_idx), tot_val * alloc_pct)
                shares = int((alloc_slot * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    portfolio_cash -= cost + cost * TOTAL_FRICTION
                    total_costs += cost * TOTAL_FRICTION
                    positions[c["ticker"]] = {
                        "shares": shares,
                        "entry_price": c["close"],
                        "days_held": 0,
                        "highest_price": c["close"],
                        "atr_pct": c["atr_pct"],
                    }

        # 7. EQUITY
        cur_eq = portfolio_cash + sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        equity_curve.append(cur_eq)

    # Metrics
    eq_s = pd.Series(equity_curve)
    ret = (eq_s.iloc[-1] / initial_capital - 1.0) * 100.0
    cummax = eq_s.cummax()
    max_dd = abs(((eq_s - cummax) / cummax).min()) * 100.0
    win_rate = wins / trades * 100.0 if trades > 0 else 0.0

    return {"Return": ret, "MaxDD": max_dd, "WinRate": win_rate, "Trades": trades, "Costs": total_costs}


if __name__ == "__main__":
    logger.info("🚀 PHASE 3: ALTERNATIVE STRATEGIES OPTIMIZER (TRAIN/VAL)")
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
    features_by_ticker = {tk: extract_point_in_time_features(df) for tk, df in stock_data.items() if len(df) >= 120}
    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = common_dates[120:280]

    trainer = ModelTrainer(feature_cols)
    candidates = ["Baseline_V3", "A_Dynamic_Trailing", "B_Scout_Entries", "C_Combined"]

    results = {}
    for c in candidates:
        logger.info(f"🔄 Simulating {c}...")
        res = run_candidate(val_dates, features_by_ticker, xu100_close, trainer, c)
        results[c] = res
        logger.info(
            f"   [{c}] Return: {res['Return']:+.2f}% | MaxDD: {res['MaxDD']:.2f}% | WR: {res['WinRate']:.1f}% | Trades: {res['Trades']}"
        )

    logger.info("\n=========================================================")
    logger.info("PHASE 4: MULTI-OBJECTIVE SELECTION")
    logger.info("=========================================================")
    for c, r in results.items():
        logger.info(
            f"{c.ljust(22)} | Net: %{r['Return']:>6.2f} | Max DD: %{r['MaxDD']:>5.2f} | WinRate: %{r['WinRate']:>4.1f} | Trades: {r['Trades']}"
        )
