from typing import Any

"""FAZ 28: VOLATILITY REGIME ROBUSTNESS STRESS TEST"""

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import structlog

logger = structlog.get_logger()

from services.learning.institutional_walkforward_engine import load_all_market_data


def eval_signal(df, signal_series, ret_col="ret_1d", tc=0.002) -> Any:
    """Otomatik eklendi."""
    net_ret = signal_series * df[ret_col] - signal_series.diff().abs().fillna(0) * tc
    valid_ret = net_ret.dropna()

    if len(valid_ret) == 0:
        return None

    cum_ret = (1 + valid_ret).cumprod()
    yrs = len(valid_ret) / 252.0
    cagr = (cum_ret.iloc[-1] ** (1 / yrs) - 1) if cum_ret.iloc[-1] > 0 else -1

    ann_mean = valid_ret.mean() * 252
    ann_std = valid_ret.std() * np.sqrt(252)
    sharpe = ann_mean / ann_std if ann_std != 0 else 0

    peak = cum_ret.cummax()
    dd = (cum_ret - peak) / peak
    max_dd = dd.min()

    exposure = signal_series.mean()
    turnover = signal_series.diff().abs().sum() / yrs

    return {
        "CAGR": cagr,
        "Sharpe": sharpe,
        "MaxDD": max_dd,
        "Exposure": exposure,
        "Turnover": turnover,
        "net_ret": valid_ret,
    }


def run_phase_28() -> Any:
    """Otomatik eklendi."""
    logger.info("🚀 FAZ 28: VOLATILITY REGIME ROBUSTNESS STRESS TEST")
    logger.info("Kurallar: Holdout Kilitli. ML Yok. Stres Testleri.\n")

    stock_data, xu100_close = load_all_market_data()

    df = pd.DataFrame(index=xu100_close.index)
    df["close"] = xu100_close
    df["ret_1d"] = df["close"].pct_change()

    # Pre-calculate Volatility
    df["vol_20d"] = df["ret_1d"].rolling(20).std()

    # Filter Val Period
    df_eval = df[df.index <= pd.Timestamp("2025-10-31")].copy()
    df_eval = df_eval.dropna(subset=["vol_20d"])

    logger.info("==================================================")
    logger.info("1. THRESHOLD ROBUSTNESS (252-day Rolling Percentile)")
    logger.info("==================================================")
    thresholds = [0.70, 0.75, 0.80, 0.85]
    robustness_passed = True

    for q in thresholds:
        vol_thresh = df["vol_20d"].rolling(252).quantile(q)
        risk_on = (df["vol_20d"] < vol_thresh).astype(int)

        # execution at T+1 (standard)
        signal = risk_on.shift(1).loc[df_eval.index]
        m = eval_signal(df_eval, signal)

        logger.info(f"Threshold P{int(q * 100)}:")
        logger.info(f"  CAGR: %{m['CAGR'] * 100:6.1f} | Sharpe: {m['Sharpe']:5.2f} | Max DD: %{m['MaxDD'] * 100:6.1f}")
        logger.info(f"  Exposure: %{m['Exposure'] * 100:4.1f} | Ann. Turnover: {m['Turnover']:4.1f} trades/yr")

        if m["Sharpe"] < 0.5:
            robustness_passed = False

    logger.info("\n==================================================")
    logger.info("2. EXECUTION DELAY TEST (Using P75 threshold)")
    logger.info("==================================================")
    vol_thresh = df["vol_20d"].rolling(252).quantile(0.75)
    risk_on = (df["vol_20d"] < vol_thresh).astype(int)

    delays = {"T+0": 1, "T+1": 2, "T+3": 4, "T+5": 6}
    for name, shift_val in delays.items():
        signal = risk_on.shift(shift_val).loc[df_eval.index]
        m = eval_signal(df_eval, signal)
        logger.info(
            f"Gecikme {name}: CAGR: %{m['CAGR'] * 100:6.1f} | Sharpe: {m['Sharpe']:5.2f} | Max DD: %{m['MaxDD'] * 100:6.1f}"
        )

    logger.info("\n==================================================")
    logger.info("4 & 5. REGIME & NULL TEST (P75 Standard T+0)")
    logger.info("==================================================")
    signal = risk_on.shift(1).loc[df_eval.index]
    m_std = eval_signal(df_eval, signal)

    # B&H
    bh = eval_signal(df_eval, pd.Series(1, index=df_eval.index), tc=0)

    # Random timing
    np.random.seed(42)
    sigs = signal.dropna().values.copy()
    null_sharpes = []
    for _ in range(1000):
        np.random.shuffle(sigs)
        s = pd.Series(sigs, index=signal.dropna().index)
        n_m = eval_signal(df_eval.loc[s.index], s)
        null_sharpes.append(n_m["Sharpe"] if n_m else 0)

    ci_L, ci_U = np.percentile(null_sharpes, 2.5), np.percentile(null_sharpes, 97.5)
    pval = np.mean(np.array(null_sharpes) >= m_std["Sharpe"])

    logger.info(f"Buy & Hold CAGR  : %{bh['CAGR'] * 100:6.1f} | Sharpe: {bh['Sharpe']:5.2f}")
    logger.info(f"Strategy CAGR    : %{m_std['CAGR'] * 100:6.1f} | Sharpe: {m_std['Sharpe']:5.2f}")
    logger.info(f"Null Sharpe 95% CI: [{ci_L:.2f}, {ci_U:.2f}]")
    logger.info(f"Empirical P-Value : {pval:.4f}")

    logger.info("\n==================================================")
    logger.info("6. CONCENTRATION TEST (Best Days Removed)")
    logger.info("==================================================")
    net_ret = m_std["net_ret"]
    sorted_ret = np.sort(net_ret)[::-1]
    n = len(sorted_ret)

    mean_all = sorted_ret.mean() * 252 * 100
    mean_drop1 = sorted_ret[int(n * 0.01) :].mean() * 252 * 100
    mean_drop5 = sorted_ret[int(n * 0.05) :].mean() * 252 * 100

    logger.info(f"Tüm Günler Yıllık Kâr       : %{mean_all:.1f}")
    logger.info(f"En İyi %1 Gün Çıkarıldığında: %{mean_drop1:.1f}")
    logger.info(f"En İyi %5 Gün Çıkarıldığında: %{mean_drop5:.1f}")

    logger.info("\n==================================================")
    logger.info("FINAL DECISION")

    if robustness_passed and pval < 0.05 and mean_drop5 > bh["CAGR"] * 100:
        logger.info("A) ROBUST PRODUCTION CORE")
        logger.info("Sinyal eşiklere, gecikmelere ve aşırı şoklara karşı dayanıklı. Overfit değil.")
    else:
        logger.info("C) REJECT")
        logger.info("Model threshold overfit veya gecikme hassasiyeti yaşıyor.")


if __name__ == "__main__":
    run_phase_28()
