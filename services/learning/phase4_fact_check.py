from typing import Any
"""FAZ 4 ÖNCESİ EK DOĞRULAMA (FACT-CHECKING)
1. BULL_TREND zararlarının kök nedenini işlem bazında MFE/MAE ile kanıtlama.
2. V-Dip fırsat kaybını Breadth vs XU100 Getiri gecikmesiyle günlük olarak kanıtlama.
"""

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


def run_fact_check_audit(eval_dates, features_by_ticker, xu100_close, trainer) -> Any:
    """Otomatik eklendi."""
    portfolio_cash = 10_000_000.0
    positions = {}

    trade_logs = []
    daily_breadth_logs = []

    smoothed_scores = {tk: 0.0 for tk in features_by_ticker}
    pending_evals = []
    completed_totals = {m: 0 for m in MODELS}
    completed_wins = {m: 0 for m in MODELS}

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

        # 2. Daily Breadth & Market State Calculation
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]

        # Calculate Breadth: % of stocks with positive 5-day momentum
        advancing_stocks = sum(1 for row in day_rows if float(row.get("roc_5d", 0)) > 0)
        breadth_pct = (advancing_stocks / len(day_tickers)) * 100.0 if day_tickers else 0.0

        hist_xu = xu100_close.loc[:current_date]
        ret_3d = (hist_xu.iloc[-1] / hist_xu.iloc[-3] - 1.0) * 100.0 if len(hist_xu) >= 3 else 0.0
        ret_5d = (hist_xu.iloc[-1] / hist_xu.iloc[-5] - 1.0) * 100.0 if len(hist_xu) >= 5 else 0.0
        ret_10d = (hist_xu.iloc[-1] / hist_xu.iloc[-10] - 1.0) * 100.0 if len(hist_xu) >= 10 else 0.0
        ret_20d = (hist_xu.iloc[-1] / hist_xu.iloc[-20] - 1.0) * 100.0 if len(hist_xu) >= 20 else 0.0
        vol_20d = hist_xu.pct_change().tail(20).std() * np.sqrt(252) * 100.0 if len(hist_xu) >= 20 else 0.0

        current_regime = detect_market_regime_v2(xu100_close, current_date)
        is_v_dip = current_regime == "BULL_TREND" and ret_5d > 3.5
        regime_tag = "V_DIP_RECOVERY" if is_v_dip else current_regime

        daily_breadth_logs.append(
            {
                "date": current_date,
                "regime": regime_tag,
                "breadth_pct": breadth_pct,
                "ret_3d": ret_3d,
                "ret_5d": ret_5d,
                "ret_10d": ret_10d,
                "ret_20d": ret_20d,
                "vol_20d": vol_20d,
            }
        )

        # 3. Signals (Simplified for speed as we just need actual trades logic from V3)
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

        # 4. Exits (Fact-Checking MFE/MAE)
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos["highest_price"], cur_p)
            pos["lowest_price"] = min(pos["lowest_price"], cur_p)

            atr_buffer = max(FROZEN_PARAMS["min_atr_pct"], pos["atr_pct"] * FROZEN_PARAMS["trailing_atr_mult"])

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
                exit_reason = "MAX_HOLD"

            if exit_reason:
                net_val = (pos["shares"] * cur_p) * (1.0 - TOTAL_FRICTION)
                realized_pnl_pct = (net_val / (pos["shares"] * pos["entry_price"]) - 1.0) * 100.0
                mfe = (pos["highest_price"] / pos["entry_price"] - 1.0) * 100.0
                mae = (pos["lowest_price"] / pos["entry_price"] - 1.0) * 100.0

                trade_logs.append(
                    {
                        "ticker": tk,
                        "entry_regime": pos["regime"],
                        "days_held": pos["days_held"],
                        "mfe": mfe,
                        "mae": mae,
                        "realized_pnl": realized_pnl_pct,
                        "giveback": mfe - realized_pnl_pct if mfe > realized_pnl_pct else 0.0,
                        "exit_reason": exit_reason,
                    }
                )
                portfolio_cash += net_val
                closed_tickers.append(tk)

        for tk in closed_tickers:
            del positions[tk]

        # 5. Entries
        max_pos = FROZEN_PARAMS["max_pos"].get(current_regime, 2)
        min_score = FROZEN_PARAMS["min_score"].get(current_regime, 0.15)
        cand.sort(key=lambda x: x["score"], reverse=True)
        top_cand = [c for c in cand if c["score"] >= min_score and c["ticker"] not in positions]
        slots = max_pos - len(positions)

        if slots > 0 and len(top_cand) > 0 and portfolio_cash > 200_000:
            for rank_idx, c in enumerate(top_cand[:slots]):
                alloc = min(portfolio_cash / (slots - rank_idx), portfolio_cash * 0.20)
                shares = int((alloc * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    portfolio_cash -= (shares * c["close"]) * (1.0 + TOTAL_FRICTION)
                    positions[c["ticker"]] = {
                        "shares": shares,
                        "entry_price": c["close"],
                        "days_held": 0,
                        "highest_price": c["close"],
                        "lowest_price": c["close"],
                        "atr_pct": c["atr_pct"],
                        "regime": regime_tag,
                    }

    return pd.DataFrame(trade_logs), pd.DataFrame(daily_breadth_logs)


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
    logger.info("FACT-CHECK RUNNING ON TRAIN/VAL (2025-03 to 2025-10)...")
    trades_df, breadth_df = run_fact_check_audit(val_dates, features_by_ticker, xu100_close, trainer)

    logger.info("\n" + "=" * 50)
    logger.info("FACT 1 & 2: BULL_TREND MFE/MAE & GIVEBACK ANALYSIS")
    logger.info("=" * 50)
    if not trades_df.empty:
        bull_trades = trades_df[trades_df["entry_regime"] == "BULL_TREND"]
        if not bull_trades.empty:
            logger.info(
                bull_trades[
                    ["ticker", "exit_reason", "days_held", "mfe", "mae", "realized_pnl", "giveback"]
                ].to_string()
            )
            logger.info(f"\nAvg MFE: {bull_trades['mfe'].mean():.2f}%")
            logger.info(f"Avg Realized: {bull_trades['realized_pnl'].mean():.2f}%")
            logger.info(f"Avg Giveback: {bull_trades['giveback'].mean():.2f}%")
        else:
            logger.info("No BULL_TREND trades in this period.")

    logger.info("\n" + "=" * 50)
    logger.info("FACT 3 & 4: V-DIP BREADTH VS LAG ANALYSIS")
    logger.info("=" * 50)
    # Ralli başlangıç günlerini bul (XU100 3 günde > %3 yapmış, ama rejim hala BULL değil)
    missed_rally_days = breadth_df[
        (breadth_df["ret_3d"] > 3.0)
        & (breadth_df["regime"] != "BULL_TREND")
        & (breadth_df["regime"] != "V_DIP_RECOVERY")
    ]
    if not missed_rally_days.empty:
        logger.info("Days where market rallied hard but regime lagged:")
        logger.info(
            missed_rally_days[["date", "regime", "breadth_pct", "ret_3d", "ret_20d", "vol_20d"]].head(10).to_string()
        )

        # Test Breadth Threshold logic
        logger.info("\nCan Breadth predict these lags?")
        high_breadth = missed_rally_days[missed_rally_days["breadth_pct"] >= 65.0]
        logger.info(f"Total missed rally days: {len(missed_rally_days)}")
        logger.info(f"Days caught if Breadth > 65% triggers V-Dip: {len(high_breadth)}")
