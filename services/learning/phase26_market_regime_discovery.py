from typing import Any
"""FAZ 26: MARKET REGIME & TIMING ALPHA DISCOVERY"""

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import structlog

logger = structlog.get_logger()

from services.learning.institutional_walkforward_engine import load_all_market_data


def calc_max_dd(rets) -> Any:
    """Otomatik eklendi."""
    cum = (1 + rets).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return dd.min()


def evaluate_timing(xu100_df, signal_col, tc=0.001) -> Any:
    """Otomatik eklendi."""
    df = xu100_df.copy()

    # Strat return (signal at T determines exposure at T+1)
    df["strat_ret"] = df[signal_col].shift(1) * df["ret_1d"]

    # Transaction costs (applied when signal changes)
    flips = df[signal_col].diff().abs().fillna(0)
    df["strat_ret"] -= flips * tc

    df = df.dropna(subset=["strat_ret"])
    if len(df) == 0:
        return None

    ann_ret = df["strat_ret"].mean() * 252 * 100
    ann_vol = df["strat_ret"].std() * np.sqrt(252) * 100
    sharpe = ann_ret / ann_vol if ann_vol != 0 else 0
    max_dd = calc_max_dd(df["strat_ret"]) * 100
    exposure = df[signal_col].mean() * 100

    # Buy & Hold
    bh_ret = df["ret_1d"].mean() * 252 * 100
    bh_vol = df["ret_1d"].std() * np.sqrt(252) * 100
    bh_sharpe = bh_ret / bh_vol if bh_vol != 0 else 0
    bh_max_dd = calc_max_dd(df["ret_1d"]) * 100

    # Downside capture
    down_days = df["ret_1d"] < 0
    if down_days.sum() > 0:
        down_cap = (df.loc[down_days, "strat_ret"].sum() / df.loc[down_days, "ret_1d"].sum()) * 100
    else:
        down_cap = 100.0

    # Null / Random Shuffle
    np.random.seed(42)
    sigs = df[signal_col].values.copy()
    null_sharpes = []

    for _ in range(1000):
        np.random.shuffle(sigs)
        s_ret = pd.Series(sigs).shift(1).fillna(0) * df["ret_1d"].values
        # rough flip cost
        s_flips = np.abs(np.diff(sigs, prepend=0))
        s_ret -= s_flips * tc

        n_ret = s_ret.mean() * 252
        n_vol = s_ret.std() * np.sqrt(252)
        n_shp = n_ret / n_vol if n_vol != 0 else 0
        null_sharpes.append(n_shp)

    ci_L = np.percentile(null_sharpes, 2.5)
    ci_U = np.percentile(null_sharpes, 97.5)
    pval = np.mean(np.array(null_sharpes) >= sharpe)

    # Time Blocks
    blocks = [df.iloc[idx] for idx in np.array_split(range(len(df)), 5)]
    block_sharpes = []
    for b in blocks:
        br = b["strat_ret"].mean() * 252
        bv = b["strat_ret"].std() * np.sqrt(252)
        block_sharpes.append(br / bv if bv != 0 else 0)

    return {
        "bh_ret": bh_ret,
        "bh_sharpe": bh_sharpe,
        "bh_max_dd": bh_max_dd,
        "ann_ret": ann_ret,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "exposure": exposure,
        "down_cap": down_cap,
        "ci_L": ci_L,
        "ci_U": ci_U,
        "pval": pval,
        "block_sharpes": block_sharpes,
    }


def run_phase_26() -> Any:
    """Otomatik eklendi."""
    logger.info("🚀 FAZ 26: MARKET REGIME & TIMING ALPHA DISCOVERY")
    logger.info("Kurallar: Holdout Kilitli. ML Yok. Market Timing & Downside Protection.\n")

    stock_data, xu100_close = load_all_market_data()

    df = pd.DataFrame(index=xu100_close.index)
    df["close"] = xu100_close
    df["ret_1d"] = df["close"].pct_change()

    # 1. TREND
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    df["trend_50"] = (df["close"] > df["sma50"]).astype(int)

    # 2. VOLATILITY REGIME
    df["vol_20d"] = df["ret_1d"].rolling(20).std()
    # Risk off if vol is in top 25% of its rolling 1-year history
    df["vol_p75"] = df["vol_20d"].rolling(252).quantile(0.75)
    df["vol_safe"] = (df["vol_20d"] < df["vol_p75"]).astype(int)

    # 3. MARKET BREADTH
    # % of stocks above their 20d SMA
    breadth = pd.Series(index=df.index, data=np.nan)
    for d in df.index:
        above = 0
        total = 0
        for tk, sdf in stock_data.items():
            if d in sdf.index:
                c = sdf.at[d, "Close"]
                if len(sdf.loc[:d]) >= 20:
                    sma = sdf.loc[:d, "Close"][-20:].mean()
                    if c > sma:
                        above += 1
                    total += 1
        if total > 0:
            breadth.loc[d] = above / total

    df["breadth"] = breadth
    df["breadth_safe"] = (df["breadth"] > 0.50).astype(int)

    # 4. COMPOSITE RISK-ON/OFF
    df["composite_safe"] = ((df["trend_50"] == 1) & (df["breadth_safe"] == 1)).astype(int)

    # Filter Val Period
    df = df[df.index <= pd.Timestamp("2025-10-31")].dropna()

    signals = {
        "1. TREND (Close > SMA50)": "trend_50",
        "2. VOLATILITY (Vol20d < P75)": "vol_safe",
        "3. BREADTH (>50% stocks above SMA20)": "breadth_safe",
        "4. COMPOSITE (Trend + Breadth)": "composite_safe",
    }

    any_robust = False

    logger.info("==================================================")
    logger.info("BASELINE: BUY & HOLD BIST100")
    logger.info("==================================================")
    bh_ret = df["ret_1d"].mean() * 252 * 100
    bh_vol = df["ret_1d"].std() * np.sqrt(252) * 100
    bh_shp = bh_ret / bh_vol
    bh_dd = calc_max_dd(df["ret_1d"]) * 100
    logger.info(f"Ann Return: %{bh_ret:.1f} | Sharpe: {bh_shp:.2f} | Max DD: %{bh_dd:.1f}\n")

    for name, col in signals.items():
        logger.info("==================================================")
        logger.info(f"STRATEGY: {name}")
        logger.info("==================================================")

        m = evaluate_timing(df, col, tc=0.001)  # 10 bps flip cost
        if not m:
            logger.info("Data error.")
            continue

        logger.info(f"Exposure   : %{m['exposure']:.1f} time invested")
        logger.info(f"Ann Return : %{m['ann_ret']:.1f} (vs B&H %{m['bh_ret']:.1f})")
        logger.info(f"Sharpe     : {m['sharpe']:.2f} (vs B&H {m['bh_sharpe']:.2f})")
        logger.info(f"Max DD     : %{m['max_dd']:.1f} (vs B&H %{m['bh_max_dd']:.1f})")
        logger.info(f"Down Capture:%{m['down_cap']:.1f} of market losses")

        logger.info("\nNULL / RANDOM TIMING SHUFFLE (Same exposure)")
        logger.info(f"95% CI Sharpe: [{m['ci_L']:.2f}, {m['ci_U']:.2f}]")
        logger.info(f"Empirical P-Value: {m['pval']:.4f}")

        logger.info(f"\nTIME BLOCKS SHARPE: {[round(x, 2) for x in m['block_sharpes']]}")

        (
            m["pval"] < 0.05
            and m["sharpe"] > m["bh_sharpe"]
            and m["max_dd"] > m["bh_max_dd"]
            and all(x > 0 for x in m["block_sharpes"])
        )
        if m["pval"] < 0.05 and m["sharpe"] > m["bh_sharpe"]:
            logger.info("=> KARAR: PROMISING (Beats Buy&Hold and Random)")
            any_robust = True
        else:
            logger.info("=> KARAR: REJECT (Fails statistical/performance tests)")

    logger.info("\n==================================================")
    logger.info("FINAL PHASE 26 DECISION")
    if any_robust:
        logger.info("B) PROMISING — FURTHER TEST (En az bir adet Market Timing stratejisi B&H ve şans faktörünü yendi)")
    else:
        logger.info("C) NO ROBUST EDGE (Tüm timing sinyalleri işlem maliyeti veya şans testine yenildi)")


if __name__ == "__main__":
    run_phase_26()
