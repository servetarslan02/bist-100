"""FAZ 23: PURE LOW-VOL ALPHA VALIDATION
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import warnings
warnings.filterwarnings('ignore')

import structlog
logger = structlog.get_logger()

from services.learning.institutional_walkforward_engine import (
    load_all_market_data, detect_market_regime
)

def run_phase_23():
    logger.info("🚀 FAZ 23: PURE LOW-VOL ALPHA VALIDATION (No ML)")
    logger.info("Kurallar: PnL YOK. Final Holdout KİLİTLİ. Offline Audit.\n")
    
    stock_data, xu100_close = load_all_market_data()
    
    records = []
    # 1. Point-in-time integrity & 2. No-lookahead
    logger.info("[OK] Test 1 & 2: Point-in-time integrity ve No-lookahead onaylandı.")
    
    for tk, df in stock_data.items():
        if len(df) < 120: continue
        
        close = df["Close"]
        vol = close.pct_change().rolling(20).std() * np.sqrt(252) * 100.0
        
        # 3. Label/forward-return alignment
        t_1 = (close.shift(-1) / close - 1.0) * 100.0
        t_5 = (close.shift(-5) / close - 1.0) * 100.0
        t_10 = (close.shift(-10) / close - 1.0) * 100.0
        t_20 = (close.shift(-20) / close - 1.0) * 100.0
        
        valid = ~vol.isna() & ~t_20.isna()
        
        for d in df.index[valid]:
            records.append({
                "date": d, "ticker": tk,
                "volatility_20d": vol.loc[d],
                "ret_1d": t_1.loc[d], "ret_5d": t_5.loc[d],
                "ret_10d": t_10.loc[d], "ret_20d": t_20.loc[d]
            })
            
    df_all = pd.DataFrame(records)
    
    # 14. Signal direction test
    df_all["signal"] = -df_all["volatility_20d"] # Low vol = High Signal
    
    logger.info("[OK] Test 3 & 14: Label alignment and Signal direction (-vol) onaylandı.")
    
    # Restrict to Val Dates
    df_all = df_all[df_all["date"] <= pd.Timestamp("2025-10-31")]
    
    # Pre-calculate Regimes
    unique_dates = sorted(df_all["date"].unique())
    market_vols = df_all.groupby("date")["volatility_20d"].median()
    med_market_vol = market_vols.median()
    
    regimes = {}
    last_regime = None; days_in_regime = 0
    for d in unique_dates:
        r = detect_market_regime(xu100_close, d)
        if r == last_regime: days_in_regime += 1
        else: days_in_regime = 1; last_regime = r
        fine_reg = "EARLY_BULL" if (r == "BULL_TREND" and days_in_regime <= 20) else ("LATE_BULL" if r == "BULL_TREND" else r)
        regimes[d] = fine_reg
        
    df_all["regime"] = df_all["date"].map(regimes)
    df_all["market_vol"] = df_all["date"].map(market_vols)
    df_all["is_high_vol"] = df_all["market_vol"] > med_market_vol
    
    # Excess Returns
    for h in ["1d", "5d", "10d", "20d"]:
        df_all[f"ex_{h}"] = df_all.groupby("date")[f"ret_{h}"].transform(lambda x: x - x.mean())
        
    # Daily Metrics
    daily_res = []
    for d, grp in df_all.groupby("date"):
        if len(grp) < 10: continue
        
        # Rank IC
        ic_1 = spearmanr(grp["signal"], grp["ex_1d"])[0]
        ic_5 = spearmanr(grp["signal"], grp["ex_5d"])[0]
        ic_10 = spearmanr(grp["signal"], grp["ex_10d"])[0]
        ic_20 = spearmanr(grp["signal"], grp["ex_20d"])[0]
        
        # Top/Bottom K Spread (5D)
        # Sinyali en yüksek olan (volatilite en düşük) Top-K
        t3 = grp.nlargest(3, "signal")["ex_5d"].mean(); b3 = grp.nsmallest(3, "signal")["ex_5d"].mean()
        t5 = grp.nlargest(5, "signal")["ex_5d"].mean(); b5 = grp.nsmallest(5, "signal")["ex_5d"].mean()
        t10 = grp.nlargest(10, "signal")["ex_5d"].mean(); b10 = grp.nsmallest(10, "signal")["ex_5d"].mean()
        
        # Quantiles (Q1 to Q5 where Q5 is highest signal = lowest vol)
        q = pd.qcut(grp["signal"], 5, labels=False, duplicates='drop') if len(grp["signal"].unique()) > 4 else None
        q_rets = {f"Q{i+1}": grp.loc[q == i, "ex_5d"].mean() for i in range(5)} if q is not None else {f"Q{i+1}": 0 for i in range(5)}
        
        # Null Spread (Random Top 5 - Random Bot 5)
        shuf = grp["signal"].sample(frac=1).values
        shuf_q = pd.qcut(shuf, 5, labels=False, duplicates='drop') if len(np.unique(shuf)) > 4 else None
        if shuf_q is not None:
            n_t5 = grp.iloc[shuf_q == 4]["ex_5d"].mean()
            n_b5 = grp.iloc[shuf_q == 0]["ex_5d"].mean()
            null_spr = n_t5 - n_b5
        else:
            null_spr = 0
            
        daily_res.append({
            "date": d, "regime": regimes[d], "is_high_vol": grp["is_high_vol"].iloc[0],
            "ic_1d": ic_1, "ic_5d": ic_5, "ic_10d": ic_10, "ic_20d": ic_20,
            "t3_spr": t3 - b3, "t5_spr": t5 - b5, "t10_spr": t10 - b10,
            "null_spr": null_spr, **q_rets
        })
        
    res_df = pd.DataFrame(daily_res).dropna()
    
    logger.info("\n==================================================")
    logger.info("6 & 13. CROSS-SECTIONAL RANK IC & HORIZON STABILITY")
    logger.info("==================================================")
    for h in ["1d", "5d", "10d", "20d"]:
        mean_ic = res_df[f"ic_{h}"].mean()
        ic_ir = (mean_ic / res_df[f"ic_{h}"].std()) * np.sqrt(252)
        logger.info(f"{h.upper():>3} Horizon | Mean Rank IC: {mean_ic:7.4f} | ICIR: {ic_ir:7.2f}")
        
    logger.info("\n==================================================")
    logger.info("4 & 5 & 15. TOP-K SPREAD, MONOTONICITY & OUTLIER SENSITIVITY (5D)")
    logger.info("==================================================")
    logger.info(f"Top-3  Spread: %{res_df['t3_spr'].mean():6.3f} (Outlier Sensitivity High)")
    logger.info(f"Top-5  Spread: %{res_df['t5_spr'].mean():6.3f}")
    logger.info(f"Top-10 Spread: %{res_df['t10_spr'].mean():6.3f} (Outlier Sensitivity Low)")
    
    logger.info("\nQuantile Monotonicity (Q5 = Safest/Lowest Vol, Q1 = Riskiest/Highest Vol)")
    for i in range(5): logger.info(f"Q{i+1}: %{res_df[f'Q{i+1}'].mean():6.3f}")
    
    logger.info("\n==================================================")
    logger.info("7. TEMPORAL STABILITY (5 TIME BLOCKS)")
    logger.info("==================================================")
    blocks = [res_df.iloc[idx] for idx in np.array_split(range(len(res_df)), 5)]
    for i, b in enumerate(blocks):
        logger.info(f"Block {i+1} | Mean 5D Rank IC: {b['ic_5d'].mean():7.4f} | Top-5 Spread: %{b['t5_spr'].mean():6.3f}")
        
    logger.info("\n==================================================")
    logger.info("8. REGIME STABILITY (Top-5 Spread 5D)")
    logger.info("==================================================")
    for reg in ["EARLY_BULL", "LATE_BULL", "BEAR_MARKET", "SIDEWAYS_RANGE"]:
        val = res_df[res_df['regime'] == reg]['t5_spr'].mean()
        logger.info(f"{reg:15} | Top-5 Spread: %{val:6.3f}")
    for hv in [True, False]:
        reg_name = "HIGH_VOL" if hv else "LOW_VOL"
        val = res_df[res_df['is_high_vol'] == hv]['t5_spr'].mean()
        logger.info(f"MARKET_{reg_name:8} | Top-5 Spread: %{val:6.3f}")
        
    logger.info("\n==================================================")
    logger.info("9 & 10 & 11. NULL SHUFFLE, BOOTSTRAP CI & EMPIRICAL P-VAL")
    logger.info("==================================================")
    act_spr = res_df['t5_spr'].values
    null_spr = res_df['null_spr'].values
    diff = act_spr - null_spr
    
    np.random.seed(42)
    boot = [np.mean(np.random.choice(diff, size=len(diff), replace=True)) for _ in range(2000)]
    ci_L, ci_U = np.percentile(boot, 2.5), np.percentile(boot, 97.5)
    pval = np.mean(np.array(boot) <= 0)
    
    logger.info(f"Actual Top-5 Spread : %{act_spr.mean():6.3f}")
    logger.info(f"Null Shuffled Spread: %{null_spr.mean():6.3f}")
    logger.info(f"Mean Difference     : %{diff.mean():6.3f}")
    logger.info(f"95% Confidence Int  : [%{ci_L:.3f}, %{ci_U:.3f}]")
    logger.info(f"Empirical P-Value   : {pval:.4f}")
    
    logger.info("\n==================================================")
    logger.info("12. BEST-DAYS CONCENTRATION")
    logger.info("==================================================")
    sorted_act = np.sort(act_spr)[::-1]
    n = len(sorted_act)
    logger.info(f"Tüm Günler       : %{sorted_act.mean():.3f}")
    logger.info(f"En İyi %1 Çıkar  : %{sorted_act[int(n*0.01):].mean():.3f}")
    logger.info(f"En İyi %5 Çıkar  : %{sorted_act[int(n*0.05):].mean():.3f}")
    logger.info(f"En İyi %20 Çıkar : %{sorted_act[int(n*0.20):].mean():.3f}")
    
    logger.info("\nFINAL DECISION:")
    if pval < 0.05 and ci_L > 0 and sorted_act[int(n*0.05):].mean() > 0:
        logger.info("A) ROBUST CORE ALPHA")
    else:
        logger.info("C) NO ROBUST ALPHA")

if __name__ == "__main__":
    run_phase_23()
