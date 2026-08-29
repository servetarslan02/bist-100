from typing import Any
"""FAZ 2: UPSIDE LOSS DECOMPOSITION
V3 Frozen Baseline'ın Train/Validation döneminde kârından ne kadarını, HANGİ MEKANİZMA yüzünden kaybettiğini ölçer.
"""

import structlog

from services.learning.frozen_strategy_engine import FROZEN_PARAMS, MODELS, TOTAL_FRICTION
from services.learning.institutional_walkforward_engine import (
    ModelTrainer,
    extract_point_in_time_features,
    load_all_market_data,
)
from services.learning.upside_capture_validator import detect_market_regime_v2

logger = structlog.get_logger()


def run_loss_decomposition(eval_dates, features_by_ticker, xu100_close, trainer) -> Any:
    """Otomatik eklendi."""
    portfolio_cash = 10_000_000.0
    positions = {}

    smoothed_scores = {tk: 0.0 for tk in features_by_ticker}
    pending_evals = []

    # Decomposition Buckets
    total_transaction_cost = 0.0
    stop_loss_giveback_tl = 0.0
    cash_drag_opportunity_loss_tl = 0.0
    regime_lag_opportunity_loss_tl = 0.0

    # Tracking for cash drag (only count when market goes up)
    for step_i, current_date in enumerate(eval_dates):
        # Update Trust
        still_pending = []
        for pe in pending_evals:
            if pe["eval_date"] > current_date:
                still_pending.append(pe)
        pending_evals = still_pending

        # Daily market data
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]

        hist_xu = xu100_close.loc[:current_date]
        ret_1d_xu = (hist_xu.iloc[-1] / hist_xu.iloc[-2] - 1.0) if len(hist_xu) >= 2 else 0.0
        ret_3d_xu = (hist_xu.iloc[-1] / hist_xu.iloc[-4] - 1.0) if len(hist_xu) >= 4 else 0.0

        current_regime = detect_market_regime_v2(xu100_close, current_date)

        # 1. Cash Drag Calculation
        # If market went up today, the cash sitting idle lost us potential index return
        if ret_1d_xu > 0:
            cash_drag_opportunity_loss_tl += portfolio_cash * ret_1d_xu

        # 2. Regime Lag Calculation
        # If market is rallying hard (V-dip) but we are stuck in Bear/Sideways, measure what we missed
        if ret_3d_xu > 0.03 and current_regime in ["BEAR_MARKET", "SIDEWAYS_RANGE"]:
            # Theoretical gain if we had deployed full cash to index
            regime_lag_opportunity_loss_tl += portfolio_cash * ret_1d_xu

        # Signals
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

        # Exits
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
                or pos["days_held"] >= FROZEN_PARAMS["min_hold_days"]
                and smoothed_scores[tk] < FROZEN_PARAMS["signal_reversal_thresh"]
                or pos["days_held"] >= FROZEN_PARAMS["max_hold_days"]
            ):
                should_exit = True

            if should_exit:
                net_val = (pos["shares"] * cur_p) * (1.0 - TOTAL_FRICTION)

                # 3. Stop-Loss Giveback Calculation
                highest_val = (pos["shares"] * pos["highest_price"]) * (1.0 - TOTAL_FRICTION)
                if highest_val > net_val and pos["highest_price"] > pos["entry_price"]:
                    stop_loss_giveback_tl += highest_val - net_val

                portfolio_cash += net_val
                total_transaction_cost += (pos["shares"] * cur_p) * TOTAL_FRICTION
                closed_tickers.append(tk)

        for tk in closed_tickers:
            del positions[tk]

        # Entries
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
                    cost = shares * c["close"]
                    portfolio_cash -= cost + cost * TOTAL_FRICTION
                    total_transaction_cost += cost * TOTAL_FRICTION
                    positions[c["ticker"]] = {
                        "shares": shares,
                        "entry_price": c["close"],
                        "days_held": 0,
                        "highest_price": c["close"],
                        "lowest_price": c["close"],
                        "atr_pct": c["atr_pct"],
                        "regime": current_regime,
                    }

    # Final liquidation
    for tk, pos in positions.items():
        cur_p = float(features_by_ticker[tk].loc[eval_dates[-1]]["close"])
        portfolio_cash += (pos["shares"] * cur_p) * (1.0 - TOTAL_FRICTION)

    return {
        "Final Portfolio": portfolio_cash,
        "Transaction Cost (TL)": total_transaction_cost,
        "Stop-Loss Giveback (TL)": stop_loss_giveback_tl,
        "Cash Drag Loss (TL)": cash_drag_opportunity_loss_tl,
        "Regime Lag Loss (TL)": regime_lag_opportunity_loss_tl,
    }


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
    logger.info("V3 UPSIDE LOSS DECOMPOSITION (Train/Val)...")
    res = run_loss_decomposition(val_dates, features_by_ticker, xu100_close, trainer)

    logger.info("\n" + "=" * 50)
    logger.info("V3 UPSIDE LOSS DECOMPOSITION RESULTS")
    logger.info("=" * 50)
    for k, v in res.items():
        logger.info(f"{k}: ₺{v:,.2f}")
