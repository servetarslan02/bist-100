from typing import Any

"""FAZ 27: VOLATILITY REGIME PORTFOLIO INTEGRATION TEST"""

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import structlog

from services.learning.institutional_walkforward_engine import load_all_market_data

logger = structlog.get_logger()


def calc_metrics(ret_series, exposure_series, name, tc_per_trade=0.002) -> Any:
    """Otomatik eklendi."""
    # Apply TC
    flips = exposure_series.diff().abs().fillna(0)
    net_ret = ret_series - (flips * tc_per_trade)
    net_ret = net_ret.dropna()

    if len(net_ret) < 10:
        return None

    cum_ret = (1 + net_ret).cumprod()
    tot_ret = cum_ret.iloc[-1] - 1

    yrs = len(net_ret) / 252.0
    cagr = (cum_ret.iloc[-1] ** (1 / yrs) - 1) if cum_ret.iloc[-1] > 0 else -1

    ann_mean = net_ret.mean() * 252
    ann_std = net_ret.std() * np.sqrt(252)
    sharpe = ann_mean / ann_std if ann_std != 0 else 0

    neg_ret = net_ret[net_ret < 0]
    down_std = neg_ret.std() * np.sqrt(252)
    sortino = ann_mean / down_std if down_std != 0 else 0

    peak = cum_ret.cummax()
    dd = (cum_ret - peak) / peak
    max_dd = dd.min()

    pos_sum = net_ret[net_ret > 0].sum()
    neg_sum = abs(net_ret[net_ret < 0].sum())
    pf = pos_sum / neg_sum if neg_sum != 0 else 0

    win_rate = (net_ret > 0).mean()
    exposure = exposure_series.mean()

    # 5 time blocks
    blocks = [net_ret.iloc[idx] for idx in np.array_split(range(len(net_ret)), 5)]
    block_sharpes = []
    for b in blocks:
        bm = b.mean() * 252
        bv = b.std() * np.sqrt(252)
        block_sharpes.append(bm / bv if bv != 0 else 0)

    return {
        "Name": name,
        "TotRet": tot_ret,
        "CAGR": cagr,
        "Sharpe": sharpe,
        "Sortino": sortino,
        "MaxDD": max_dd,
        "ProfitFactor": pf,
        "WinRate": win_rate,
        "Exposure": exposure,
        "Blocks": block_sharpes,
        "Series": net_ret,
    }


def run_phase_27() -> Any:
    """Otomatik eklendi."""
    logger.info("🚀 FAZ 27: VOLATILITY REGIME PORTFOLIO INTEGRATION TEST")
    logger.info("Kurallar: Holdout Kilitli. ML Yok. Realistic TC/Slippage.\n")

    stock_data, xu100_close = load_all_market_data()

    df = pd.DataFrame(index=xu100_close.index)
    df["close"] = xu100_close
    df["ret_1d"] = df["close"].pct_change()

    # 1. VOLATILITY REGIME SIGNAL (Risk ON/OFF)
    df["vol_20d"] = df["ret_1d"].rolling(20).std()
    df["vol_p75"] = df["vol_20d"].rolling(252).quantile(0.75)
    df["risk_on"] = (df["vol_20d"] < df["vol_p75"]).astype(int)

    # Pre-calculate stock universe metrics
    liquid_ew_rets = pd.Series(index=df.index, data=0.0)
    ranker_rets = pd.Series(index=df.index, data=0.0)

    for d in df.index:
        valid_stocks = []
        for tk, sdf in stock_data.items():
            if d in sdf.index and len(sdf.loc[:d]) >= 20:
                vol_mean = sdf.loc[:d, "Volume"][-20:].mean()
                ret_1d = sdf.at[d, "Close"] / sdf.loc[:d, "Close"].iloc[-2] - 1.0 if len(sdf.loc[:d]) > 1 else 0
                mom_20d = sdf.at[d, "Close"] / sdf.loc[:d, "Close"].iloc[-20] - 1.0
                valid_stocks.append({"tk": tk, "vol_mean": vol_mean, "ret": ret_1d, "mom": mom_20d})

        if len(valid_stocks) > 10:
            vdf = pd.DataFrame(valid_stocks)
            med_vol = vdf["vol_mean"].median()
            liquid_vdf = vdf[vdf["vol_mean"] > med_vol]

            if len(liquid_vdf) > 0:
                liquid_ew_rets.loc[d] = liquid_vdf["ret"].mean()

            # M1 Mock (Old Ranker - Buy top momentum, which failed)
            top_mom = vdf.nlargest(5, "mom")
            ranker_rets.loc[d] = top_mom["ret"].mean()

    df["liquid_ew_ret"] = liquid_ew_rets
    df["ranker_ret"] = ranker_rets

    # Align and Filter Holdout
    df = df[df.index <= pd.Timestamp("2025-10-31")].dropna()

    logger.info("==================================================")
    logger.info("PERFORMANCE METRICS (Transaction Costs: 0.2% per flip)")
    logger.info("==================================================")

    # M4: Buy & Hold
    m4 = calc_metrics(df["ret_1d"], pd.Series(1, index=df.index), "M4: Buy & Hold BIST100", 0)

    # M1: Old V3 Ranker Baseline (Always invested, Mom Crash)
    m1 = calc_metrics(df["ranker_ret"], pd.Series(1, index=df.index), "M1: Old V3 Ranker Baseline", 0.002)

    # M2: Volatility Regime Only (Index Timing)
    exposure_m2 = df["risk_on"].shift(1).fillna(0)
    m2 = calc_metrics(df["ret_1d"] * exposure_m2, exposure_m2, "M2: Vol Regime (Index)", 0.002)

    # M3: Volatility Regime + Liquid EW
    exposure_m3 = df["risk_on"].shift(1).fillna(0)
    m3 = calc_metrics(df["liquid_ew_ret"] * exposure_m3, exposure_m3, "M3: Vol Regime + Liquid EW", 0.002)

    models = [m4, m1, m2, m3]
    for m in models:
        if m is None:
            continue
        logger.info(f"\n{m['Name']}")
        logger.info(
            f"  CAGR: %{m['CAGR'] * 100:6.1f} | TotRet: %{m['TotRet'] * 100:6.1f} | Sharpe: {m['Sharpe']:5.2f} | Sortino: {m['Sortino']:5.2f}"
        )
        logger.info(
            f"  MaxDD: %{m['MaxDD'] * 100:6.1f} | WinRate: %{m['WinRate'] * 100:4.1f} | ProfitFactor: {m['ProfitFactor']:4.2f}"
        )
        logger.info(f"  Exposure: %{m['Exposure'] * 100:4.1f} | Block Sharpes: {[round(x, 2) for x in m['Blocks']]}")

    logger.info("\n==================================================")
    logger.info("ROBUSTNESS & DOWNSIDE CAPTURE (M3 vs B&H)")
    logger.info("==================================================")

    down_days = m4["Series"] < 0
    m3_down_cap = (m3["Series"][down_days].sum() / m4["Series"][down_days].sum()) * 100
    logger.info(f"M3 Downside Capture: %{m3_down_cap:.1f} of Market Losses")
    logger.info(f"Risk OFF (Cash) Süresi: %{(1 - m3['Exposure']) * 100:.1f}")

    # Bootstrap CI for M3 Sharpe
    np.random.seed(42)
    s_ret = m3["Series"].values
    boot = [
        np.mean(np.random.choice(s_ret, size=len(s_ret), replace=True))
        / np.std(np.random.choice(s_ret, size=len(s_ret), replace=True))
        * np.sqrt(252)
        for _ in range(1000)
    ]
    logger.info(f"M3 Sharpe 95% CI: [{np.percentile(boot, 2.5):.2f}, {np.percentile(boot, 97.5):.2f}]")

    logger.info("\nÖZEL TEST: Tek Bir Kriz Mi?")
    pos_blocks = sum(1 for x in m3["Blocks"] if x > 0)
    zero_blocks = sum(1 for x in m3["Blocks"] if x == 0)
    logger.info(
        f"{len(m3['Blocks'])} zaman bloğunun {pos_blocks}'i pozitif kâr, {zero_blocks}'i %100 nakit (korunma) olarak geçildi."
    )

    if m3["CAGR"] > m4["CAGR"] and m3["MaxDD"] > m4["MaxDD"] and m3["Sharpe"] > 1.0:
        logger.info("\nFINAL DECISION: A) PRODUCTION READY")
    else:
        logger.info("\nFINAL DECISION: C) REJECT")


if __name__ == "__main__":
    run_phase_27()
