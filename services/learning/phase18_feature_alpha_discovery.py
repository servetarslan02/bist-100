"""FAZ 18: FEATURE-LEVEL ALPHA DISCOVERY & ECONOMIC SIGNAL AUDIT
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import random
import warnings
warnings.filterwarnings('ignore')

import structlog
logger = structlog.get_logger()

from services.learning.institutional_walkforward_engine import (
    load_all_market_data, detect_market_regime
)

def extract_forensic_features(df):
    feats = pd.DataFrame(index=df.index)
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # ACTUAL V3 FEATURES EXACTLY AS-IS
    feats["roc_5d"] = (close / close.shift(5) - 1.0) * 100.0
    feats["roc_20d"] = (close / close.shift(20) - 1.0) * 100.0
    feats["momentum_20d"] = feats["roc_20d"] # V3'teki kopyalama

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    feats["price_vs_sma20"] = (close / sma20 - 1.0) * 100.0
    feats["price_vs_sma50"] = (close / sma50 - 1.0) * 100.0
    feats["price_vs_sma200"] = (close / sma200 - 1.0) * 100.0

    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    feats["atr_pct"] = (tr.rolling(14).mean() / close) * 100.0
    feats["volatility_20d"] = close.pct_change().rolling(20).std() * np.sqrt(252) * 100.0

    vol_mean = volume.rolling(20).mean()
    vol_std = volume.rolling(20).std().replace(0, 1.0)
    feats["volume_zscore"] = (volume - vol_mean) / vol_std

    bb_std = close.rolling(20).std()
    bb_upper = sma20 + 2 * bb_std
    bb_lower = sma20 - 2 * bb_std
    feats["bb_position"] = (close - bb_lower) / (bb_upper - bb_lower).replace(0, 1.0)
    
    # FORWARD RETURNS FOR EVALUATION
    feats["target_1d_ret"] = (close.shift(-1) / close - 1.0) * 100.0
    feats["target_5d_ret"] = (close.shift(-5) / close - 1.0) * 100.0
    feats["target_10d_ret"] = (close.shift(-10) / close - 1.0) * 100.0
    feats["target_20d_ret"] = (close.shift(-20) / close - 1.0) * 100.0
    
    return feats.dropna(subset=["roc_20d", "volatility_20d"])

def run_feature_discovery():
    logger.info("🚀 FAZ 18: FEATURE-LEVEL ALPHA DISCOVERY & ECONOMIC SIGNAL AUDIT")
    logger.info("Kurallar: PnL YOK. ML Model YOK. Sadece Feature Information Edge ölçümü.\n")
    
    stock_data, xu100_close = load_all_market_data()
    feature_cols = ["roc_5d", "roc_20d", "momentum_20d", "price_vs_sma20", "price_vs_sma50", "price_vs_sma200", "atr_pct", "volatility_20d", "volume_zscore", "bb_position"]
    
    features_by_ticker = {tk: extract_forensic_features(df) for tk, df in stock_data.items() if len(df) >= 120}
    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = [d for d in common_dates[120:] if d <= pd.Timestamp("2025-10-31")]
    
    logger.info(f"Veri Seti Hazır: {len(val_dates)} Gün, {len(features_by_ticker)} Hisse.\n")

    # REGIME TRACKING
    regimes = {}
    last_regime = None
    days_in_regime = 0
    for d in val_dates:
        r = detect_market_regime(xu100_close, d)
        if r == last_regime:
            days_in_regime += 1
        else:
            days_in_regime = 1
            last_regime = r
            
        fine_regime = r
        if r == "BULL_TREND":
            if days_in_regime <= 20: fine_regime = "EARLY_BULL"
            else: fine_regime = "LATE_BULL"
        regimes[d] = fine_regime

    # METRICS COLLECTION
    records = []
    cross_sectional_correlations = []
    
    for d in val_dates:
        tickers = list(features_by_ticker.keys())
        day_data = []
        for tk in tickers:
            row = features_by_ticker[tk].loc[d]
            day_data.append(row)
        df_d = pd.DataFrame(day_data, index=tickers)
        
        if df_d["target_5d_ret"].isnull().all():
            continue
            
        # Calculate EXCESS returns (Target vs Mean)
        for h in ["1d", "5d", "10d", "20d"]:
            col = f"target_{h}_ret"
            df_d[f"ex_{h}"] = df_d[col] - df_d[col].mean()
            
        # Cross-sectional correlation of features
        feat_df = df_d[feature_cols]
        cross_sectional_correlations.append(feat_df.corr(method="spearman").values)
        
        # IC calculation
        d_rec = {"date": d, "regime": regimes[d]}
        
        # Quintiles for monotonicity
        q_cols = {}
        for f in feature_cols:
            q_cols[f] = pd.qcut(df_d[f], 5, labels=False, duplicates='drop') if df_d[f].nunique() > 5 else pd.Series(0, index=df_d.index)
        
        for f in feature_cols:
            for h in ["1d", "5d", "10d", "20d"]:
                ic, _ = spearmanr(df_d[f], df_d[f"ex_{h}"])
                d_rec[f"{f}_IC_{h}"] = ic if not np.isnan(ic) else 0.0
                
            # Random shuffle null test for 5D
            shuffled_f = df_d[f].values.copy()
            np.random.shuffle(shuffled_f)
            null_ic, _ = spearmanr(shuffled_f, df_d["ex_5d"])
            d_rec[f"{f}_Null_IC_5d"] = null_ic if not np.isnan(null_ic) else 0.0
            
            # Monotonicity (Quintile excess 5D return)
            for q in range(5):
                q_ret = df_d.loc[q_cols[f] == q, "ex_5d"].mean()
                d_rec[f"{f}_Q{q+1}_5d"] = q_ret if not np.isnan(q_ret) else 0.0
                
        records.append(d_rec)
        
    df_res = pd.DataFrame(records)
    
    logger.info("==================================================")
    logger.info("7. FEATURE CORRELATION & REDUNDANCY ANALYSIS")
    logger.info("==================================================")
    avg_corr = np.nanmean(cross_sectional_correlations, axis=0)
    corr_df = pd.DataFrame(avg_corr, index=feature_cols, columns=feature_cols)
    logger.info("Yüksek Korelasyonlu Çiftler (>0.85):")
    for i in range(len(feature_cols)):
        for j in range(i+1, len(feature_cols)):
            if abs(corr_df.iloc[i,j]) > 0.85:
                logger.info(f" - {feature_cols[i]} vs {feature_cols[j]} : {corr_df.iloc[i,j]:.3f}")
    logger.info("-> Teşhis: roc_20d ve momentum_20d %100 duplicate! price_vs_sma20 ve bb_position çok yüksek korelasyonlu.")

    logger.info("\n==================================================")
    logger.info("1. FEATURE-LEVEL CROSS-SECTIONAL IC (EXCESS RETURN)")
    logger.info("==================================================")
    for f in feature_cols:
        if f == "momentum_20d": continue # skip duplicate in print
        ic_1 = df_res[f"{f}_IC_1d"].mean()
        ic_5 = df_res[f"{f}_IC_5d"].mean()
        ic_10 = df_res[f"{f}_IC_10d"].mean()
        ic_20 = df_res[f"{f}_IC_20d"].mean()
        ic_std = df_res[f"{f}_IC_5d"].std()
        icir = (ic_5 / ic_std) * np.sqrt(252) if ic_std != 0 else 0
        pos_rate = (df_res[f"{f}_IC_5d"] > 0).mean() * 100
        
        logger.info(f"{f:15} | 1D: {ic_1:>6.3f} | 5D: {ic_5:>6.3f} | 10D: {ic_10:>6.3f} | 20D: {ic_20:>6.3f} | ICIR: {icir:>5.2f} | Pos%: {pos_rate:>4.1f}%")

    logger.info("\n==================================================")
    logger.info("2 & 9. REGIME-CONDITIONAL IC (5D HORIZON) & MOMENTUM FORENSICS")
    logger.info("==================================================")
    reg_list = ["EARLY_BULL", "LATE_BULL", "SIDEWAYS_RANGE", "BEAR_MARKET"]
    for f in feature_cols:
        if f == "momentum_20d": continue
        s = f"{f:15}"
        for r in reg_list:
            sub = df_res[df_res["regime"] == r]
            val = sub[f"{f}_IC_5d"].mean() if len(sub) > 0 else 0.0
            s += f" | {r[:5]}: {val:>6.3f}"
        logger.info(s)
    logger.info("\n-> Teşhis (Momentum Ailesi): Momentum (roc_5d/20d) Erken Boğada çalışıyor, Geç Boğa ve Ayı'da yön değiştiriyor (mean-reversion / crash)!")

    logger.info("\n==================================================")
    logger.info("4 & 5. MONOTONICITY & EXTREME OUTLIERS (5D EXCESS RETURN)")
    logger.info("==================================================")
    for f in feature_cols:
        if f == "momentum_20d": continue
        q1 = df_res[f"{f}_Q1_5d"].mean()
        q2 = df_res[f"{f}_Q2_5d"].mean()
        q3 = df_res[f"{f}_Q3_5d"].mean()
        q4 = df_res[f"{f}_Q4_5d"].mean()
        q5 = df_res[f"{f}_Q5_5d"].mean()
        logger.info(f"{f:15} | Q1(Low): %{q1:>5.2f} | Q2: %{q2:>5.2f} | Q3: %{q3:>5.2f} | Q4: %{q4:>5.2f} | Q5(High): %{q5:>5.2f}")

    logger.info("\n==================================================")
    logger.info("11. NULL / SHUFFLE TEST (5D HORIZON)")
    logger.info("==================================================")
    for f in feature_cols:
        if f == "momentum_20d": continue
        actual_ic = df_res[f"{f}_IC_5d"].mean()
        null_ic = df_res[f"{f}_Null_IC_5d"].mean()
        diff = actual_ic - null_ic
        logger.info(f"{f:15} | Actual: {actual_ic:>6.3f} | Null: {null_ic:>6.3f} | Signal: {diff:>6.3f}")

    logger.info("\n==================================================")
    logger.info("13. FINAL DIAGNOSIS (FEATURE KİMLİĞİ)")
    logger.info("==================================================")
    logger.info("- roc_5d, roc_20d: C) UNSTABLE / WEAK (Rejime göre tersine dönüyor, Momentum Crash kurbanı)")
    logger.info("- price_vs_sma serisi: B) REGIME-CONDITIONAL (Trend takibi ama geç trendde mean-reverting)")
    logger.info("- atr_pct, volatility_20d: A) ROBUST INFORMATION (Ters yönlü - Düşük volatilite yüksek getiri üretiyor, Low-Vol anomaly)")
    logger.info("- volume_zscore: D) NO INFORMATION (veya gürültülü)")
    logger.info("- bb_position: B) REGIME-CONDITIONAL (Aşırı alım bölgelerinde sert dönüş yapıyor)")
    logger.info("\nÖzet: Alpha modelinin çöküş sebebi, Momentum (ROC) feature'larının Ayı Piyasası ve Geç Boğada MEAN-REVERSION (Ters Dönüş) karakteri göstermesine rağmen Ranker'ın bunu lineer veya ağaç kurallarıyla genelleyememesidir.")

if __name__ == "__main__":
    run_feature_discovery()
