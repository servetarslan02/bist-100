from typing import Any
"""FAZ 4: MEKANİZMA BAZLI ADAY TESTLERİ (Anti-Overfit Protocol)
V3 Baseline ve 4 Aday birbirinden bağımsız olarak test edilir.
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


def calculate_capture_ratios(port_rets, bench_rets) -> Any:
    """Otomatik eklendi."""
    if len(port_rets) == 0 or len(bench_rets) == 0:
        return 0.0, 0.0
    df = pd.DataFrame({"port": port_rets, "bench": bench_rets})
    up_market = df[df["bench"] > 0]
    down_market = df[df["bench"] <= 0]
    up_capture = (up_market["port"].mean() / up_market["bench"].mean()) * 100 if up_market["bench"].mean() > 0 else 0
    down_capture = (
        (down_market["port"].mean() / down_market["bench"].mean()) * 100 if down_market["bench"].mean() < 0 else 0
    )
    return up_capture, down_capture


def run_mechanism_candidate(eval_dates, features_by_ticker, xu100_close, trainer, candidate_name) -> Any:
    """Otomatik eklendi."""
    portfolio_cash = 10_000_000.0
    positions = {}

    equity_curve = []
    daily_rets = []
    exposure_history = []
    regime_pnl = {
        "BULL_TREND": 0,
        "BEAR_MARKET": 0,
        "SIDEWAYS_RANGE": 0,
        "HIGH_VOLATILITY": 0,
        "LOW_VOLATILITY": 0,
        "V_DIP_RECOVERY": 0,
    }

    smoothed_scores = {tk: 0.0 for tk in features_by_ticker}

    total_costs = 0.0
    wins, trades = 0, 0
    gross_win = 0.0
    gross_loss = 0.0
    trade_pnls = []

    peak_equity = portfolio_cash

    for step_i, current_date in enumerate(eval_dates):
        # Retrain every step_i % 30
        if step_i % FROZEN_PARAMS["retraining_freq"] == 0:
            train_rows = [fdf.loc[: current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(comb_train)

        # Market Data
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        hist_xu = xu100_close.loc[:current_date]
        ret_5d_xu = (hist_xu.iloc[-1] / hist_xu.iloc[-5] - 1.0) * 100.0 if len(hist_xu) >= 5 else 0.0
        current_regime = detect_market_regime_v2(xu100_close, current_date)
        is_v_dip = current_regime == "BULL_TREND" and ret_5d_xu > 3.5
        regime_tag = "V_DIP_RECOVERY" if is_v_dip else current_regime

        # Breadth
        advancing_stocks = sum(1 for row in day_rows if float(row.get("roc_5d", 0)) > 0)
        breadth_pct = (advancing_stocks / len(day_tickers)) * 100.0 if day_tickers else 0.0

        # Signals
        weights = {m: 0.166 for m in MODELS}
        batch_sigs = trainer.predict_batch_day(day_tickers, day_rows)
        cand = []
        for i, tk in enumerate(day_tickers):
            raw_c = sum(weights[m] * batch_sigs[tk][m] for m in MODELS)
            smoothed_scores[tk] = 0.5 * raw_c + 0.5 * smoothed_scores[tk]

            # CANDIDATE C: Breadth + Signal (Multiplier)
            adj_score = smoothed_scores[tk]
            if candidate_name == "C_Breadth_Signal":
                adj_score = smoothed_scores[tk] * (1.0 + breadth_pct / 100.0)

            cand.append(
                {
                    "ticker": tk,
                    "score": adj_score,
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
                or pos["days_held"] >= FROZEN_PARAMS["max_hold_days"]
            ):
                should_exit = True

            # CANDIDATE B: Signal-Decay Exit
            if candidate_name == "B_Signal_Decay":
                entry_thresh = FROZEN_PARAMS["min_score"].get(regime_tag, 0.15)
                # Ensure no lookahead: using today's calculated smoothed score
                if smoothed_scores[tk] < entry_thresh:
                    should_exit = True
            else:
                # V3 Default Signal Exit
                if (
                    pos["days_held"] >= FROZEN_PARAMS["min_hold_days"]
                    and smoothed_scores[tk] < FROZEN_PARAMS["signal_reversal_thresh"]
                ):
                    should_exit = True

            if should_exit:
                net_val = (pos["shares"] * cur_p) * (1.0 - TOTAL_FRICTION)
                net_pnl = net_val - (pos["shares"] * pos["entry_price"])
                portfolio_cash += net_val
                total_costs += (pos["shares"] * cur_p) * TOTAL_FRICTION
                closed_tickers.append(tk)
                trades += 1
                trade_pnls.append(pnl_pct)
                regime_pnl[pos["regime"]] += net_pnl
                if net_pnl > 0:
                    wins += 1
                    gross_win += net_pnl
                else:
                    gross_loss += abs(net_pnl)

        for tk in closed_tickers:
            del positions[tk]

        # Entries
        max_pos = FROZEN_PARAMS["max_pos"].get(current_regime, 2)
        min_score = FROZEN_PARAMS["min_score"].get(current_regime, 0.15)
        cand.sort(key=lambda x: x["score"], reverse=True)
        top_cand = [c for c in cand if c["score"] >= min_score and c["ticker"] not in positions]
        slots = max_pos - len(positions)

        invested_pre = sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        cur_eq_pre = portfolio_cash + invested_pre
        peak_equity = max(peak_equity, cur_eq_pre)
        current_dd = (peak_equity - cur_eq_pre) / peak_equity if peak_equity > 0 else 0.0

        if slots > 0 and len(top_cand) > 0 and portfolio_cash > 200_000:
            selected = top_cand[:slots]

            # CANDIDATE A: Conviction-Weighted Allocation (Proportional to Score)
            if candidate_name == "A_Conviction_Alloc":
                score_sum = sum(c["score"] for c in selected)
                for c in selected:
                    # Allocate all available cash proportionally by score, no artificial caps
                    alloc = portfolio_cash * (c["score"] / score_sum)
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
            else:
                tot_val = portfolio_cash + invested_pre
                for rank_idx, c in enumerate(selected):
                    alloc_pct = FROZEN_PARAMS["top1_alloc_pct"] if rank_idx == 0 else FROZEN_PARAMS["default_alloc_pct"]

                    # CANDIDATE D: Drawdown-Aware Exposure
                    if candidate_name == "D_Drawdown_Aware":
                        # Linearly reduce allocation based on drawdown (e.g. 10% DD = 90% normal alloc)
                        alloc_pct = alloc_pct * (1.0 - current_dd)

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

        # Equity Tracking
        cur_eq = portfolio_cash + sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        equity_curve.append(cur_eq)
        exposure_history.append(1.0 - (portfolio_cash / cur_eq))

    eq_s = pd.Series(equity_curve, index=eval_dates)
    daily_rets = eq_s.pct_change().dropna()
    xu_rets = xu100_close.loc[daily_rets.index].pct_change().dropna()

    # Align indexes
    common_idx = daily_rets.index.intersection(xu_rets.index)
    daily_rets = daily_rets.loc[common_idx]
    xu_rets = xu_rets.loc[common_idx]

    ret_total = (eq_s.iloc[-1] / 10_000_000.0 - 1.0) * 100.0
    days = (eval_dates[-1] - eval_dates[0]).days
    cagr = ((1 + ret_total / 100) ** (365.25 / days) - 1) * 100 if days > 0 else 0
    cummax = eq_s.cummax()
    max_dd = abs(((eq_s - cummax) / cummax).min()) * 100.0

    rf = 0.40 / 252
    excess = daily_rets - rf
    sharpe = np.sqrt(252) * excess.mean() / daily_rets.std() if daily_rets.std() > 0 else 0
    downside_std = daily_rets[daily_rets < 0].std()
    sortino = np.sqrt(252) * excess.mean() / downside_std if downside_std > 0 else 0
    calmar = cagr / max_dd if max_dd > 0 else 0

    win_rate = wins / trades * 100.0 if trades > 0 else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else 99.0
    up_cap, down_cap = calculate_capture_ratios(daily_rets, xu_rets)

    worst_trade = min(trade_pnls) if trade_pnls else 0.0
    monthly_rets = eq_s.resample("ME").last().pct_change().dropna() * 100
    worst_month = monthly_rets.min() if not monthly_rets.empty else 0.0
    avg_exp = np.mean(exposure_history) * 100.0

    return {
        "Ret": ret_total,
        "CAGR": cagr,
        "MaxDD": max_dd,
        "Sharpe": sharpe,
        "Sortino": sortino,
        "Calmar": calmar,
        "PF": pf,
        "WR": win_rate,
        "UpCap": up_cap,
        "DnCap": down_cap,
        "Trades": trades,
        "Cost": total_costs,
        "AvgExp": avg_exp,
        "WorstTrade": worst_trade,
        "WorstMonth": worst_month,
        "RegimePnL": regime_pnl,
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
    candidates = ["Baseline_V3", "A_Conviction_Alloc", "B_Signal_Decay", "C_Breadth_Signal", "D_Drawdown_Aware"]

    results = {}
    logger.info("🚀 PHASE 4: MECHANISM EVALUATION (TRAIN/VAL 2025-03 -> 2025-10)")
    for c in candidates:
        r = run_mechanism_candidate(val_dates, features_by_ticker, xu100_close, trainer, c)
        results[c] = r
        logger.info(f"\n[{c}]")
        logger.info(
            f"Net: %{r['Ret']:.2f} | CAGR: %{r['CAGR']:.2f} | MaxDD: %{r['MaxDD']:.2f} | PF: {r['PF']:.2f} | WR: %{r['WR']:.1f}"
        )
        logger.info(
            f"UpCap: %{r['UpCap']:.1f} | DnCap: %{r['DnCap']:.1f} | Trades: {r['Trades']} | Cost: ₺{r['Cost']:,.0f} | AvgExp: %{r['AvgExp']:.1f}"
        )
        logger.info(f"Sharpe: {r['Sharpe']:.2f} | Sortino: {r['Sortino']:.2f} | Calmar: {r['Calmar']:.2f}")
        logger.info(f"Worst Trade: %{r['WorstTrade']:.2f} | Worst Month: %{r['WorstMonth']:.2f}")

    logger.info("\n📊 INCREMENTAL CONTRIBUTION VS BASELINE:")
    base = results["Baseline_V3"]
    for c in candidates[1:]:
        r = results[c]
        logger.info(f"\n{c}:")
        logger.info(
            f"Δ CAGR: {r['CAGR'] - base['CAGR']:>+6.2f}% | Δ UpCap: {r['UpCap'] - base['UpCap']:>+6.2f}% | Δ DnCap: {r['DnCap'] - base['DnCap']:>+6.2f}%"
        )
        logger.info(
            f"Δ MaxDD: {r['MaxDD'] - base['MaxDD']:>+6.2f}% | Δ PF: {r['PF'] - base['PF']:>+6.2f} | Δ Trades: {r['Trades'] - base['Trades']:>+4}"
        )
