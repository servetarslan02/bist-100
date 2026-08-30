from typing import Any

"""FAZ 8: STRUCTURAL ALPHA DISCOVERY
V3'ün getiri darboğazlarını Alpha, Threshold, Allocation ve Exit olarak ayrıştırır.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import structlog
from scipy.stats import spearmanr

from services.learning.frozen_strategy_engine import FROZEN_PARAMS, MODELS, TOTAL_FRICTION
from services.learning.institutional_walkforward_engine import (
    ModelTrainer,
    extract_point_in_time_features,
    load_all_market_data,
)
from services.learning.upside_capture_validator import detect_market_regime_v2

logger = structlog.get_logger()


def run_structural_discovery(eval_dates, features_by_ticker, stock_data, xu100_close, trainer) -> Any:
    """Otomatik eklendi."""
    daily_ic = []
    bucket_data = []  # (score, fwd_1d, fwd_5d, fwd_10d)
    oracle_logs = []

    # Portfolio simulation logs
    portfolio_cash = 10_000_000.0
    positions = {}
    smoothed_scores = {tk: 0.0 for tk in features_by_ticker}

    upside_loss_cats = {
        "A_No_Signal": 0.0,
        "B_Signal_Below_Threshold": 0.0,
        "C_No_Cash_Exposure_Limit": 0.0,
        "D_Underweighted": 0.0,
    }

    for step_i, current_date in enumerate(eval_dates):
        if step_i % FROZEN_PARAMS["retraining_freq"] == 0:
            train_rows = [fdf.loc[: current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(comb_train)

        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        current_regime = detect_market_regime_v2(xu100_close, current_date)

        weights = {m: 0.166 for m in MODELS}
        batch_sigs = trainer.predict_batch_day(day_tickers, day_rows)

        cross_sectional_scores = []
        cross_sectional_fwd5 = []

        cand = []
        for i, tk in enumerate(day_tickers):
            raw_c = sum(weights[m] * batch_sigs[tk][m] for m in MODELS)
            smoothed_scores[tk] = 0.5 * raw_c + 0.5 * smoothed_scores[tk]
            score = smoothed_scores[tk]

            try:
                curr_idx = features_by_ticker[tk].index.get_loc(current_date)
                tk_feat = features_by_ticker[tk]
                fwd_1d = (
                    (tk_feat.iloc[curr_idx + 1]["close"] / tk_feat.iloc[curr_idx]["close"] - 1.0)
                    if curr_idx + 1 < len(tk_feat)
                    else np.nan
                )
                fwd_5d = (
                    (tk_feat.iloc[curr_idx + 5]["close"] / tk_feat.iloc[curr_idx]["close"] - 1.0)
                    if curr_idx + 5 < len(tk_feat)
                    else np.nan
                )
                fwd_10d = (
                    (tk_feat.iloc[curr_idx + 10]["close"] / tk_feat.iloc[curr_idx]["close"] - 1.0)
                    if curr_idx + 10 < len(tk_feat)
                    else np.nan
                )
            except Exception:
                fwd_1d, fwd_5d, fwd_10d = np.nan, np.nan, np.nan

            if not np.isnan(fwd_5d):
                cross_sectional_scores.append(score)
                cross_sectional_fwd5.append(fwd_5d)
                bucket_data.append((score, fwd_1d, fwd_5d, fwd_10d))

            cand.append(
                {
                    "ticker": tk,
                    "score": score,
                    "close": float(day_rows[i]["close"]),
                    "fwd_5d": fwd_5d,
                    "atr_pct": float(day_rows[i].get("atr_pct", 3.0)),
                }
            )

        # Rank IC Calculation
        if len(cross_sectional_scores) > 10:
            corr, _ = spearmanr(cross_sectional_scores, cross_sectional_fwd5)
            if not np.isnan(corr):
                daily_ic.append({"date": current_date, "ic": corr, "regime": current_regime})

        # Oracle Analysis
        valid_cand = [c for c in cand if not np.isnan(c["fwd_5d"])]
        valid_cand.sort(key=lambda x: x["fwd_5d"], reverse=True)
        oracle_top_4 = valid_cand[:4]
        oracle_top_4_avg_fwd5 = np.mean([c["fwd_5d"] for c in oracle_top_4]) if oracle_top_4 else 0.0

        # V3 Selection
        min_score = FROZEN_PARAMS["min_score"].get(current_regime, 0.15)
        cand.sort(key=lambda x: x["score"], reverse=True)
        v3_top_cand = [c for c in cand if c["score"] >= min_score]
        v3_picked = v3_top_cand[: FROZEN_PARAMS["max_pos"].get(current_regime, 2)]
        v3_picked_avg_fwd5 = np.mean([c["fwd_5d"] for c in v3_picked]) if v3_picked else 0.0

        oracle_logs.append(
            {
                "oracle_fwd5": oracle_top_4_avg_fwd5,
                "v3_fwd5": v3_picked_avg_fwd5,
                "best_oracle_score": oracle_top_4[0]["score"] if oracle_top_4 else 0.0,
                "v3_had_cash": portfolio_cash > 200_000,
                "v3_slots_open": FROZEN_PARAMS["max_pos"].get(current_regime, 2) - len(positions),
            }
        )

        # Upside Loss Categorization (Counterfactual)
        if oracle_top_4_avg_fwd5 > 0.05:  # If there was a >5% opportunity in the market
            for oc in oracle_top_4:
                if oc["fwd_5d"] > 0.05:
                    if oc["score"] < 0.10:
                        upside_loss_cats["A_No_Signal"] += 1
                    elif oc["score"] < min_score:
                        upside_loss_cats["B_Signal_Below_Threshold"] += 1
                    elif oc["ticker"] not in [p["ticker"] for p in v3_picked]:
                        if (
                            FROZEN_PARAMS["max_pos"].get(current_regime, 2) - len(positions) <= 0
                            or portfolio_cash < 200_000
                        ):
                            upside_loss_cats["C_No_Cash_Exposure_Limit"] += 1
                    else:
                        upside_loss_cats["D_Underweighted"] += 1

        # V3 Mechanical Exits
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos["highest_price"], cur_p)
            atr_buffer = max(FROZEN_PARAMS["min_atr_pct"], pos["atr_pct"] * FROZEN_PARAMS["trailing_atr_mult"])

            should_exit = False
            if (
                pnl_pct <= FROZEN_PARAMS["hard_stop_pct"]
                or pos["highest_price"] > pos["entry_price"] * 1.06
                and cur_p < pos["highest_price"] * (1.0 - atr_buffer / 100.0)
                or pnl_pct >= FROZEN_PARAMS["take_profit_pct"]
                or pos["days_held"] >= FROZEN_PARAMS["max_hold_days"]
                or pos["days_held"] >= FROZEN_PARAMS["min_hold_days"]
                and smoothed_scores[tk] < FROZEN_PARAMS["signal_reversal_thresh"]
            ):
                should_exit = True

            if should_exit:
                net_val = (pos["shares"] * cur_p) * (1.0 - TOTAL_FRICTION)
                portfolio_cash += net_val
                closed_tickers.append(tk)
        for tk in closed_tickers:
            del positions[tk]

        # V3 Mechanical Entries
        slots = FROZEN_PARAMS["max_pos"].get(current_regime, 2) - len(positions)
        top_cand_v3 = [c for c in cand if c["score"] >= min_score and c["ticker"] not in positions]

        invested_pre = sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )

        if slots > 0 and len(top_cand_v3) > 0 and portfolio_cash > 200_000:
            tot_val = portfolio_cash + invested_pre
            for rank_idx, c in enumerate(top_cand_v3[:slots]):
                alloc_pct = FROZEN_PARAMS["top1_alloc_pct"] if rank_idx == 0 else FROZEN_PARAMS["default_alloc_pct"]
                alloc = min(portfolio_cash / (slots - rank_idx), tot_val * alloc_pct)
                shares = int((alloc * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    portfolio_cash -= cost + cost * TOTAL_FRICTION
                    positions[c["ticker"]] = {
                        "shares": shares,
                        "entry_price": c["close"],
                        "days_held": 0,
                        "highest_price": c["close"],
                        "lowest_price": c["close"],
                        "atr_pct": c["atr_pct"],
                    }

    # Process Results
    df_ic = pd.DataFrame(daily_ic)
    df_buckets = pd.DataFrame(bucket_data, columns=["score", "fwd_1d", "fwd_5d", "fwd_10d"])
    df_oracle = pd.DataFrame(oracle_logs)

    return df_ic, df_buckets, df_oracle, upside_loss_cats


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
    logger.info("🚀 PHASE 8: STRUCTURAL ALPHA DISCOVERY")

    df_ic, df_buckets, df_oracle, upside_loss_cats = run_structural_discovery(
        val_dates, features_by_ticker, stock_data, xu100_close, trainer
    )

    logger.info("\n" + "=" * 50)
    logger.info("D) RANK IC / INFORMATION COEFFICIENT")
    logger.info("=" * 50)
    logger.info(f"Mean IC: {df_ic['ic'].mean():.4f}")
    logger.info(f"Median IC: {df_ic['ic'].median():.4f}")
    icir = df_ic["ic"].mean() / df_ic["ic"].std() if df_ic["ic"].std() > 0 else 0
    logger.info(f"ICIR: {icir:.4f}")
    logger.info(f"Positive IC Ratio: {(df_ic['ic'] > 0).mean() * 100:.1f}%")
    logger.info("\nIC by Regime:")
    logger.info(df_ic.groupby("regime")["ic"].mean().apply(lambda x: f"{x:.4f}"))

    logger.info("\n" + "=" * 50)
    logger.info("C) SCORE -> FUTURE RETURN RELATIONSHIP (CONVICTION)")
    logger.info("=" * 50)
    # Define score buckets
    bins = [0, 0.10, 0.15, 0.20, 0.25, 0.30, 1.0]
    df_buckets["bucket"] = pd.cut(df_buckets["score"], bins)
    res = df_buckets.groupby("bucket").agg(
        Count=("fwd_5d", "count"),
        Fwd_5d_Mean=("fwd_5d", lambda x: x.mean() * 100),
        Fwd_5d_Median=("fwd_5d", lambda x: x.median() * 100),
        Hit_Rate=("fwd_5d", lambda x: (x > 0).mean() * 100),
    )
    logger.info(res)

    logger.info("\n" + "=" * 50)
    logger.info("E) ORACLE ANALYSIS")
    logger.info("=" * 50)
    logger.info(f"Avg Fwd5d of Oracle's Top 4   : %{df_oracle['oracle_fwd5'].mean() * 100:.2f}")
    logger.info(f"Avg Fwd5d of V3's Picked      : %{df_oracle['v3_fwd5'].mean() * 100:.2f}")
    logger.info(f"Avg Score of Oracle's best pick: {df_oracle['best_oracle_score'].mean():.3f}")

    logger.info("\n" + "=" * 50)
    logger.info("B) UPSIDE LOSS DECOMPOSITION (COUNT)")
    logger.info("=" * 50)
    total_opps = sum(upside_loss_cats.values())
    for k, v in upside_loss_cats.items():
        pct = (v / total_opps * 100) if total_opps > 0 else 0
        logger.info(f"{k.ljust(30)}: {v} instances ({pct:.1f}%)")
