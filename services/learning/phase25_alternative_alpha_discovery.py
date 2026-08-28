"""FAZ 25: ALTERNATIVE ECONOMIC ALPHA DISCOVERY
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

def evaluate_signal(df_liquid, signal_col):
    res = []
    for d, grp in df_liquid.groupby("date"):
        if len(grp) < 10: continue
        rec = {"date": d, "regime": grp["regime"].iloc[0]}
        
        # IC
        for h in ["1d", "5d", "10d", "20d"]:
            rec[f"ic_{h}"] = spearmanr(grp[signal_col], grp[f"ex_{h}"])[0]
            
        # Top-5 Spread
        t5 = grp.nlargest(5, signal_col)["ex_5d"].mean()
        b5 = grp.nsmallest(5, signal_col)["ex_5d"].mean()
        rec["t5_spr"] = t5 - b5
        
        # Quintiles
        q = pd.qcut(grp[signal_col], 5, labels=False, duplicates='drop') if len(grp[signal_col].unique()) > 4 else None
        if q is not None:
            for i in range(5): rec[f"Q{i+1}"] = grp.loc[q == i, "ex_5d"].mean()
            
        # Null Spread
        shuf_q = pd.qcut(grp[signal_col].sample(frac=1).values, 5, labels=False, duplicates='drop') if q is not None else None
        if shuf_q is not None:
            rec["null_spr"] = grp.iloc[shuf_q == 4]["ex_5d"].mean() - grp.iloc[shuf_q == 0]["ex_5d"].mean()
        else:
            rec["null_spr"] = 0
            
        res.append(rec)
        
    res_df = pd.DataFrame(res).dropna()
    if len(res_df) == 0: return None
    
    # Calculate Aggregates
    metrics = {}
    metrics["ic_1d"] = res_df["ic_1d"].mean(); metrics["ic_5d"] = res_df["ic_5d"].mean()
    metrics["ic_10d"] = res_df["ic_10d"].mean(); metrics["ic_20d"] = res_df["ic_20d"].mean()
    metrics["icir_5d"] = (metrics["ic_5d"] / res_df["ic_5d"].std()) * np.sqrt(252)
    
    metrics["t5_spr"] = res_df["t5_spr"].mean()
    for i in range(5): metrics[f"Q{i+1}"] = res_df[f"Q{i+1}"].mean() if f"Q{i+1}" in res_df.columns else 0
    
    # Null & Bootstrap
    act = res_df["t5_spr"].values
    null = res_df["null_spr"].values
    diff = act - null
    np.random.seed(42)
    boot = [np.mean(np.random.choice(diff, size=len(diff), replace=True)) for _ in range(2000)]
    metrics["ci_L"] = np.percentile(boot, 2.5); metrics["ci_U"] = np.percentile(boot, 97.5)
    metrics["pval"] = np.mean(np.array(boot) <= 0)
    metrics["null_spr"] = null.mean()
    
    # Time Blocks
    blocks = [res_df.iloc[idx] for idx in np.array_split(range(len(res_df)), 5)]
    metrics["blocks_spr"] = [b["t5_spr"].mean() for b in blocks]
    
    # Regimes
    metrics["regimes"] = {reg: res_df[res_df["regime"] == reg]["t5_spr"].mean() 
                          for reg in ["EARLY_BULL", "LATE_BULL", "BEAR_MARKET", "SIDEWAYS_RANGE"]}
                          
    # Concentration
    sorted_act = np.sort(act)[::-1]
    n = len(sorted_act)
    metrics["best_5pct_removed"] = sorted_act[int(n*0.05):].mean()
    
    return metrics

def run_phase_25():
    logger.info("🚀 FAZ 25: ALTERNATIVE ECONOMIC ALPHA DISCOVERY")
    logger.info("Kurallar: Holdout Kilitli. ML Yok. Sadece Likit Evren.\n")
    
    stock_data, xu100_close = load_all_market_data()
    xu100_ret3 = xu100_close.pct_change(3)
    xu100_ret5 = xu100_close.pct_change(5)
    
    records = []
    
    for tk, df in stock_data.items():
        if len(df) < 120: continue
        
        c = df["Close"]
        v = df["Volume"]
        
        vol_mean = v.rolling(20).mean()
        
        # Base targets
        t_1 = (c.shift(-1) / c - 1.0) * 100.0
        t_5 = (c.shift(-5) / c - 1.0) * 100.0
        t_10 = (c.shift(-10) / c - 1.0) * 100.0
        t_20 = (c.shift(-20) / c - 1.0) * 100.0
        
        # CANDIDATE 1: MEAN REVERSION 3D (Short-term oversold)
        sig_mr_3d = -c.pct_change(3) 
        
        # CANDIDATE 2: RELATIVE STRENGTH REVERSAL (Stock vs BIST 5D)
        # BIST'e göre çok yükselmişse düşer, çok düşmüşse çıkar hipotezi
        stock_ret5 = c.pct_change(5)
        sig_rel_rev_5d = -(stock_ret5 - xu100_ret5)
        
        # CANDIDATE 3: VOLUME SHOCK / SURGE (Düşük hacimden aniden yüksek hacme geçiş = ilgi)
        sig_vol_surge = v / vol_mean
        
        # CANDIDATE 4: VOLATILITY COMPRESSION (Daralan Bollinger/Volatilite patlar)
        vol_20d = c.pct_change().rolling(20).std()
        vol_60d = c.pct_change().rolling(60).std()
        sig_vol_comp = -(vol_20d / vol_60d.replace(0, 1e-5)) # Eksi çünkü düşük oran yüksek kompresyon
        
        valid = ~vol_mean.isna() & ~t_20.isna() & ~sig_vol_comp.isna()
        
        for d in df.index[valid]:
            records.append({
                "date": d, "ticker": tk, "vol_mean": vol_mean.loc[d],
                "ret_1d": t_1.loc[d], "ret_5d": t_5.loc[d],
                "ret_10d": t_10.loc[d], "ret_20d": t_20.loc[d],
                "sig_mr_3d": sig_mr_3d.loc[d],
                "sig_rel_rev_5d": sig_rel_rev_5d.loc[d],
                "sig_vol_surge": sig_vol_surge.loc[d],
                "sig_vol_comp": sig_vol_comp.loc[d]
            })
            
    df_all = pd.DataFrame(records)
    df_all = df_all[df_all["date"] <= pd.Timestamp("2025-10-31")]
    
    # Structural Liquidity Filter (Likit Yarı)
    df_all["daily_med_vol"] = df_all.groupby("date")["vol_mean"].transform("median")
    df_liquid = df_all[df_all["vol_mean"] > df_all["daily_med_vol"]].copy()
    
    # Excess Returns
    for h in ["1d", "5d", "10d", "20d"]:
        df_liquid[f"ex_{h}"] = df_liquid.groupby("date")[f"ret_{h}"].transform(lambda x: x - x.mean())
        
    unique_dates = sorted(df_liquid["date"].unique())
    regimes = {}
    last_reg = None; days = 0
    for d in unique_dates:
        r = detect_market_regime(xu100_close, d)
        if r == last_reg: days += 1
        else: days = 1; last_reg = r
        regimes[d] = "EARLY_BULL" if (r == "BULL_TREND" and days <= 20) else ("LATE_BULL" if r == "BULL_TREND" else r)
    df_liquid["regime"] = df_liquid["date"].map(regimes)
    
    signals = ["sig_mr_3d", "sig_rel_rev_5d", "sig_vol_surge", "sig_vol_comp"]
    
    any_robust = False
    
    for sig in signals:
        logger.info(f"\n==================================================")
        logger.info(f"EVALUATING SIGNAL: {sig.upper()}")
        logger.info(f"==================================================")
        
        m = evaluate_signal(df_liquid, sig)
        if not m:
            logger.info("Yeterli veri yok.")
            continue
            
        logger.info(f"1. IC (Rank Correlation)")
        logger.info(f"   1D: {m['ic_1d']:7.4f} | 5D: {m['ic_5d']:7.4f} (ICIR: {m['icir_5d']:5.2f}) | 10D: {m['ic_10d']:7.4f}")
        
        logger.info(f"2. Q1-Q5 MONOTONICITY (5D Spread)")
        logger.info(f"   Q1:%{m['Q1']:6.3f} | Q2:%{m['Q2']:6.3f} | Q3:%{m['Q3']:6.3f} | Q4:%{m['Q4']:6.3f} | Q5:%{m['Q5']:6.3f}")
        
        logger.info(f"3. NULL & STATISTICAL SIGNIFICANCE")
        logger.info(f"   Actual Spread : %{m['t5_spr']:6.3f}")
        logger.info(f"   Null Spread   : %{m['null_spr']:6.3f}")
        logger.info(f"   95% CI        : [%{m['ci_L']:.3f}, %{m['ci_U']:.3f}]")
        logger.info(f"   P-Value       : {m['pval']:.4f}")
        
        logger.info(f"4. STABILITY")
        logger.info(f"   Time Blocks   : {[round(x,3) for x in m['blocks_spr']]}")
        logger.info(f"   Regimes       : ER_BULL:%{m['regimes'].get('EARLY_BULL',0):.3f} | LT_BULL:%{m['regimes'].get('LATE_BULL',0):.3f} | BEAR:%{m['regimes'].get('BEAR_MARKET',0):.3f}")
        
        logger.info(f"5. CONCENTRATION")
        logger.info(f"   Best %5 drop  : %{m['best_5pct_removed']:6.3f}")
        
        robust = (m['pval'] < 0.05 and m['ci_L'] > 0 and m['best_5pct_removed'] > 0 and m['t5_spr'] > m['null_spr'])
        if robust:
            logger.info("=> KARAR: PROMISING (ROBUST ALPHA CANDIDATE)")
            any_robust = True
        else:
            logger.info("=> KARAR: REJECT (FAILS ROBUSTNESS CRITERIA)")

    logger.info("\n==================================================")
    logger.info("FINAL PHASE 25 DECISION")
    if any_robust:
        logger.info("B) PROMISING — FURTHER TEST (En az bir adet potansiyel robust sinyal bulundu)")
    else:
        logger.info("C) NO ROBUST ALPHA (Tüm adaylar likit evrende Null/Shuffle'a veya konsantrasyon testine yenildi)")

if __name__ == "__main__":
    run_phase_25()
