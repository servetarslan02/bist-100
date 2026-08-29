from typing import Any
"""FAZ 4: INDEPENDENT CANDIDATE OPTIMIZATION
Bu script A, B, C ve D stratejilerini V3'e karşı birbirinden bağımsız olarak test eder.
"""

from datetime import timedelta

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


def run_phase4_candidate(eval_dates, features_by_ticker, xu100_close, trainer, candidate_name) -> Any:
    """Otomatik eklendi."""
    portfolio_cash = 10_000_000.0
    positions = {}
    equity_curve = []
    daily_rets = []

    smoothed_scores = {tk: 0.0 for tk in features_by_ticker}
    pending_evals = []
    completed_totals = {m: 0 for m in MODELS}
    completed_wins = {m: 0 for m in MODELS}

    total_costs = 0.0
    wins, trades = 0, 0
    gross_win = 0.0
    gross_loss = 0.0

    for step_i, current_date in enumerate(eval_dates):
        # 1. Update Trust
        still_pending = []
        for pe in pending_evals:
            if pe["eval_date"] <= current_date:
                completed_totals[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins[pe["model"]] += 1
            else:
                still_pending.append(pe)
        pending_evals = still_pending

        # 2. Retrain
        if step_i % FROZEN_PARAMS["retraining_freq"] == 0:
            train_rows = [fdf.loc[: current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(comb_train)

        # 3. Signals & Breadth
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]

        # Breadth Calculation
        advancing_stocks = sum(1 for row in day_rows if float(row.get("roc_5d", 0)) > 0)
        breadth_pct = (advancing_stocks / len(day_tickers)) * 100.0 if day_tickers else 0.0

        weights = {m: 0.166 for m in MODELS}
        batch_sigs = trainer.predict_batch_day(day_tickers, day_rows)
        cand = []
        for i, tk in enumerate(day_tickers):
            raw_c = sum(weights[m] * batch_sigs[tk][m] for m in MODELS)
            smoothed_scores[tk] = 0.5 * raw_c + 0.5 * smoothed_scores[tk]
            cand.append(
                {
                    "ticker": tk,
                    "score": smoothed_scores[tk],
                    "close": float(day_rows[i]["close"]),
                    "atr_pct": float(day_rows[i].get("atr_pct", 3.0)),
                }
            )

        # 4. Regime Detection
        current_regime = detect_market_regime_v2(xu100_close, current_date)
        hist_xu = xu100_close.loc[:current_date]
        ret_5d_xu = (hist_xu.iloc[-1] / hist_xu.iloc[-5] - 1.0) * 100.0 if len(hist_xu) >= 5 else 0.0
        is_v_dip = current_regime == "BULL_TREND" and ret_5d_xu > 3.5

        # CANDIDATE A: Breadth Thrust
        if candidate_name == "A_Breadth_Thrust" and breadth_pct >= 65.0:
            is_v_dip = True

        regime_tag = "V_DIP_RECOVERY" if is_v_dip else current_regime

        # 5. Exits
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos["highest_price"], cur_p)

            # CANDIDATE C: Adaptive Stop
            atr_mult = FROZEN_PARAMS["trailing_atr_mult"]
            if candidate_name == "C_Adaptive_Stop":
                if regime_tag in ["BULL_TREND", "V_DIP_RECOVERY"]:
                    atr_mult = 3.0
                elif regime_tag == "BEAR_MARKET":
                    atr_mult = 1.5
                else:
                    atr_mult = 2.0
                # Tighten further if profit > 8%
                if pnl_pct > 8.0:
                    atr_mult *= 0.6

            atr_buffer = max(FROZEN_PARAMS["min_atr_pct"], pos["atr_pct"] * atr_mult)

            should_exit = False
            if (
                pnl_pct <= FROZEN_PARAMS["hard_stop_pct"]
                or pos["highest_price"] > pos["entry_price"] * 1.06
                and cur_p < pos["highest_price"] * (1.0 - atr_buffer / 100.0)
                or pnl_pct >= FROZEN_PARAMS["take_profit_pct"]
                or pos["days_held"] >= FROZEN_PARAMS["min_hold_days"]
                and smoothed_scores[tk] < FROZEN_PARAMS["signal_reversal_thresh"]
                or pos["days_held"] >= FROZEN_PARAMS["max_hold_days"]
            ):
                should_exit = True

            if should_exit:
                net_val = (pos["shares"] * cur_p) * (1.0 - TOTAL_FRICTION)
                net_pnl = net_val - (pos["shares"] * pos["entry_price"])
                portfolio_cash += net_val
                total_costs += (pos["shares"] * cur_p) * TOTAL_FRICTION
                closed_tickers.append(tk)
                trades += 1
                if net_pnl > 0:
                    wins += 1
                    gross_win += net_pnl
                else:
                    gross_loss += abs(net_pnl)

        for tk in closed_tickers:
            del positions[tk]

        # 6. Entries
        # CANDIDATE D: Full Deployment
        max_pos = (
            6
            if (candidate_name == "D_Full_Deployment" and regime_tag in ["BULL_TREND", "V_DIP_RECOVERY"])
            else FROZEN_PARAMS["max_pos"].get(current_regime, 2)
        )

        min_score = FROZEN_PARAMS["min_score"].get(current_regime, 0.15)
        cand.sort(key=lambda x: x["score"], reverse=True)
        top_cand = [c for c in cand if c["score"] >= min_score and c["ticker"] not in positions]
        slots = max_pos - len(positions)

        invested_pre = sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )

        if slots > 0 and len(top_cand) > 0 and portfolio_cash > 200_000:
            tot_val = portfolio_cash + invested_pre
            for rank_idx, c in enumerate(top_cand[:slots]):
                # CANDIDATE B: Volatility Targeting
                if candidate_name == "B_Vol_Targeting":
                    target_vol = 1.0  # 1% target daily vol for position
                    alloc_pct = min(0.40, target_vol / c["atr_pct"])  # Cap at 40% per stock
                else:
                    alloc_pct = FROZEN_PARAMS["top1_alloc_pct"] if rank_idx == 0 else FROZEN_PARAMS["default_alloc_pct"]

                alloc = min(portfolio_cash / (slots - rank_idx), tot_val * alloc_pct)
                shares = int((alloc * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    portfolio_cash -= cost + cost * TOTAL_FRICTION
                    total_costs += cost * TOTAL_FRICTION
                    positions[c["ticker"]] = {
                        "shares": shares,
                        "entry_price": c["close"],
                        "days_held": 0,
                        "highest_price": c["close"],
                        "lowest_price": c["close"],
                        "atr_pct": c["atr_pct"],
                        "regime": regime_tag,
                    }

        # 7. Equity Tracking
        cur_eq = portfolio_cash + sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        equity_curve.append(cur_eq)
        if len(equity_curve) > 1:
            daily_rets.append(equity_curve[-1] / equity_curve[-2] - 1.0)

    # Metrics
    eq_s = pd.Series(equity_curve)
    ret = (eq_s.iloc[-1] / 10_000_000.0 - 1.0) * 100.0
    cummax = eq_s.cummax()
    max_dd = abs(((eq_s - cummax) / cummax).min()) * 100.0
    win_rate = wins / trades * 100.0 if trades > 0 else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else 99.0

    return {"Return": ret, "MaxDD": max_dd, "WinRate": win_rate, "Trades": trades, "Costs": total_costs, "PF": pf}


if __name__ == "__main__":
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
    candidates = ["Baseline_V3", "A_Breadth_Thrust", "B_Vol_Targeting", "C_Adaptive_Stop", "D_Full_Deployment"]

    results = {}
    logger.info("🚀 PHASE 4: INDEPENDENT CANDIDATE TESTING (TRAIN/VAL)")
    for c in candidates:
        res = run_phase4_candidate(val_dates, features_by_ticker, xu100_close, trainer, c)
        results[c] = res
        logger.info(
            f"[{c.ljust(20)}] Net: %{res['Return']:>6.2f} | MaxDD: %{res['MaxDD']:>5.2f} | PF: {res['PF']:>4.2f} | WR: %{res['WinRate']:>4.1f} | Trades: {res['Trades']}"
        )

    logger.info("\n📊 DELTA VS BASELINE:")
    base = results["Baseline_V3"]
    for c in candidates[1:]:
        r = results[c]
        logger.info(
            f"{c.ljust(20)} | Δ Ret: {r['Return'] - base['Return']:>+6.2f}% | Δ DD: {r['MaxDD'] - base['MaxDD']:>+5.2f}% | Δ PF: {r['PF'] - base['PF']:>+4.2f}"
        )
