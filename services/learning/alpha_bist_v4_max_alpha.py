from typing import Any
"""Phase 7, 8 & 9: V4 Max Alpha (Final Holdout Confirmation)
Bu script, Train/Val üzerinde muazzam sinerji yaratan 'C_Combined'
(Dynamic Trailing + Scout Entries) stratejisini dondurur ve FINAL HOLDOUT'ta test eder.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import structlog

from services.learning.frozen_strategy_engine import MODELS
from services.learning.institutional_walkforward_engine import (
    ModelTrainer,
    extract_point_in_time_features,
    load_all_market_data,
)
from services.learning.upside_capture_validator import detect_market_regime_v2

logger = structlog.get_logger()


# BIST Commission + Slippage
TOTAL_FRICTION = 0.00074 + 0.00050

# ============================================================
# V4 MAX ALPHA - FROZEN PARAMETERS (DONDURULDU)
# ============================================================
V4_PARAMS = {
    "max_pos": {"BULL_TREND": 4, "LOW_VOLATILITY": 4, "SIDEWAYS_RANGE": 2, "BEAR_MARKET": 2, "HIGH_VOLATILITY": 2},
    "min_score": {
        "BULL_TREND": 0.08,
        "LOW_VOLATILITY": 0.10,
        "SIDEWAYS_RANGE": 0.20,
        "BEAR_MARKET": 0.28,
        "HIGH_VOLATILITY": 0.22,
    },
    "scout_min_score": 0.12,  # Scout entry for Bear/Sideways
    "top1_alloc_pct": 0.30,
    "default_alloc_pct": 0.20,
    "trailing_atr_base": 2.5,  # Base ATR mult
    "trailing_atr_tight": 1.5,  # Tight ATR mult when profit secured
    "profit_secure_thresh": 8.0,  # PnL % to tighten trailing stop
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


def run_v4_strategy(
    eval_dates, features_by_ticker, xu100_close, trainer, initial_capital=10_000_000.0, label="V4_Max_Alpha"
) -> Any:
    """Otomatik eklendi."""
    portfolio_cash = initial_capital
    positions = {}
    equity_curve = []
    daily_rets = []

    regime_pnl = {
        r: {"pnl": 0.0, "trades": 0, "wins": 0}
        for r in ["BULL_TREND", "BEAR_MARKET", "SIDEWAYS_RANGE", "HIGH_VOLATILITY", "LOW_VOLATILITY", "V_DIP_RECOVERY"]
    }

    smoothed_scores = {tk: 0.0 for tk in features_by_ticker}
    pending_evals = []
    completed_wins = {m: 0 for m in MODELS}
    completed_totals = {m: 0 for m in MODELS}

    start_xu100 = (
        float(xu100_close.loc[eval_dates[0]]) if eval_dates[0] in xu100_close.index else float(xu100_close.iloc[0])
    )
    equity_xu100 = []
    daily_rets_xu100 = []

    total_costs = 0.0
    wins, trades = 0, 0
    gross_win = 0.0
    gross_loss = 0.0

    for step_i, current_date in enumerate(eval_dates):
        # 0. Trust Queue Update
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
        if step_i % V4_PARAMS["retraining_freq"] == 0:
            train_rows = [fdf.loc[: current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(comb_train)

        # 2. REGIME & V-DIP
        current_regime = detect_market_regime_v2(xu100_close, current_date)
        hist_xu = xu100_close.loc[:current_date]
        ret_5d_xu = (hist_xu.iloc[-1] / hist_xu.iloc[-5] - 1.0) * 100.0 if len(hist_xu) >= 5 else 0.0
        is_v_dip = current_regime == "BULL_TREND" and ret_5d_xu > 3.5
        regime_tag = "V_DIP_RECOVERY" if is_v_dip else current_regime

        max_pos = V4_PARAMS["max_pos"].get(current_regime, 2)

        # Scout mechanism: standard min_score vs scout_min_score
        standard_min_score = V4_PARAMS["min_score"].get(current_regime, 0.15)
        scout_allowed = current_regime in ["BEAR_MARKET", "SIDEWAYS_RANGE", "HIGH_VOLATILITY"]
        active_min_score = V4_PARAMS["scout_min_score"] if scout_allowed else standard_min_score

        # 3. DYNAMIC TRUST
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

        # 4. SIGNAL FUSION
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
                V4_PARAMS["ema_alpha_fast"] if delta_s > V4_PARAMS["ema_delta_thresh"] else V4_PARAMS["ema_alpha_slow"]
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

        # 5. EXITS (Dynamic Trailing)
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), cur_p)

            if pnl_pct > V4_PARAMS["profit_secure_thresh"]:
                current_atr_mult = V4_PARAMS["trailing_atr_tight"]
            else:
                current_atr_mult = V4_PARAMS["trailing_atr_base"]

            atr_buffer = max(V4_PARAMS["min_atr_pct"], pos.get("atr_pct", 3.0) * current_atr_mult)

            should_exit = False
            if (
                pnl_pct <= V4_PARAMS["hard_stop_pct"]
                or pos["highest_price"] > pos["entry_price"] * 1.06
                and cur_p < pos["highest_price"] * (1.0 - atr_buffer / 100.0)
                or pnl_pct >= V4_PARAMS["take_profit_pct"]
                or pos["days_held"] >= V4_PARAMS["min_hold_days"]
                and smoothed_scores[tk] < V4_PARAMS["signal_reversal_thresh"]
                or pos["days_held"] >= V4_PARAMS["max_hold_days"]
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
                    regime_pnl[pos["regime_tag"]]["wins"] += 1
                else:
                    gross_loss += abs(net_pnl)

                regime_pnl[pos["regime_tag"]]["trades"] += 1
                regime_pnl[pos["regime_tag"]]["pnl"] += net_pnl

        for tk in closed_tickers:
            del positions[tk]

        # 6. ENTRIES (Scout Sizing)
        cand.sort(key=lambda x: x["score"], reverse=True)
        top_cand = [c for c in cand if c["score"] >= active_min_score and c["ticker"] not in positions]
        slots = max_pos - len(positions)
        invested_pre = sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )

        if slots > 0 and len(top_cand) > 0 and portfolio_cash > V4_PARAMS["min_cash_to_open"]:
            tot_val = portfolio_cash + invested_pre
            for rank_idx, c in enumerate(top_cand[:slots]):
                is_scout = scout_allowed and (c["score"] < standard_min_score)
                alloc_pct = (
                    V4_PARAMS["top1_alloc_pct"]
                    if (rank_idx == 0 and c["score"] > V4_PARAMS["conviction_score_min"])
                    else V4_PARAMS["default_alloc_pct"]
                )

                if is_scout:
                    alloc_pct *= 0.5  # Half position size for scout entries

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
                        "regime_tag": regime_tag,
                    }

        # 7. EQUITY
        cur_eq = portfolio_cash + sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        equity_curve.append(cur_eq)

        cur_xu = float(xu100_close.loc[current_date]) if current_date in xu100_close.index else start_xu100
        equity_xu100.append(initial_capital * (cur_xu / start_xu100))

        if len(equity_curve) > 1:
            daily_rets.append(equity_curve[-1] / equity_curve[-2] - 1.0)
            daily_rets_xu100.append(equity_xu100[-1] / equity_xu100[-2] - 1.0)

    # Calculate Metrics
    n_years = len(eval_dates) / 252.0
    eq_s = pd.Series(equity_curve)
    d_s = pd.Series(daily_rets)
    xu_s = pd.Series(daily_rets_xu100)

    tot_ret = (eq_s.iloc[-1] / initial_capital - 1.0) * 100.0
    tot_ret_xu = (equity_xu100[-1] / initial_capital - 1.0) * 100.0

    cummax = eq_s.cummax()
    max_dd = abs(((eq_s - cummax) / cummax).min()) * 100.0
    max_dd_xu = (
        abs(((pd.Series(equity_xu100) - pd.Series(equity_xu100).cummax()) / pd.Series(equity_xu100).cummax()).min())
        * 100.0
    )

    cagr = ((eq_s.iloc[-1] / initial_capital) ** (1.0 / n_years) - 1.0) * 100.0 if n_years > 0 else 0.0
    win_rate = wins / trades * 100.0 if trades > 0 else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else 99.0
    turnover = trades * 2 / n_years if n_years > 0 else 0.0

    downside_std = d_s[d_s < 0].std() * np.sqrt(252)
    sortino = (cagr - 40.0) / downside_std if downside_std > 0 else 0.0
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    up_idx = xu_s > 0
    upside_cap = (d_s[up_idx].mean() / xu_s[up_idx].mean()) * 100.0 if xu_s[up_idx].mean() > 0 else 0.0

    return {
        "label": label,
        "final_equity": eq_s.iloc[-1],
        "tot_ret": tot_ret,
        "tot_ret_xu": tot_ret_xu,
        "cagr": cagr,
        "max_dd": max_dd,
        "max_dd_xu": max_dd_xu,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "sortino": sortino,
        "calmar": calmar,
        "turnover": turnover,
        "costs": total_costs,
        "upside_cap": upside_cap,
        "trades": trades,
        "regime_pnl": regime_pnl,
    }


def print_final_report(m) -> Any:
    """Otomatik eklendi."""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"🏆 NİHAİ HOLDOUT RAPORU — {m['label']}")
    logger.info(f"{'=' * 60}")
    logger.info(f"| Metrik | {m['label']} | XU100 |")
    logger.info("|---|---|---|")
    logger.info(f"| Net Getiri | %{m['tot_ret']:+.2f} | %{m['tot_ret_xu']:+.2f} |")
    logger.info(f"| CAGR | %{m['cagr']:+.2f} | - |")
    logger.info(f"| Max DD | %{m['max_dd']:.2f} | %{m['max_dd_xu']:.2f} |")
    logger.info(f"| Profit Factor | {m['profit_factor']:.2f} | - |")
    logger.info(f"| Win Rate | %{m['win_rate']:.1f} | - |")
    logger.info(f"| Sortino | {m['sortino']:.2f} | - |")
    logger.info(f"| Calmar | {m['calmar']:.2f} | - |")
    logger.info(f"| Upside Capture | %{m['upside_cap']:.1f} | %100.0 |")
    logger.info(f"| Turnover | {m['turnover']:.1f}/yıl | - |")
    logger.info(f"| Total Cost | ₺{m['costs']:,.2f} | ₺0 |")
    logger.info(f"| Toplam İşlem | {m['trades']} | - |")

    logger.info("\n🌐 REJİM BAZLI PERFORMANS:")
    logger.info("| Rejim | PnL | İşlem | Win Rate |")
    logger.info("|---|---|---|---|")
    for rn, rd in m["regime_pnl"].items():
        wr = (rd["wins"] / rd["trades"] * 100.0) if rd["trades"] > 0 else 0.0
        logger.info(f"| {rn} | ₺{rd['pnl']:+,.2f} | {rd['trades']} | %{wr:.1f} |")


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

    # EXACT FINAL HOLDOUT DATES USED BEFORE (2025-10-31 to 2026-08-14)
    holdout_dates = common_dates[280:-5]
    logger.info("🚀 PHASE 8: FINAL HOLDOUT RUN (TEK SEFERLİK ÇALIŞTIRMA)")
    logger.info(f"Holdout Dates: {holdout_dates[0].date()} to {holdout_dates[-1].date()}")

    trainer_h = ModelTrainer(feature_cols)
    res_v4 = run_v4_strategy(holdout_dates, features_by_ticker, xu100_close, trainer_h)

    print_final_report(res_v4)
