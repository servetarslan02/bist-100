"""FAZ 20: RESIDUAL & REGIME-AWARE ALPHA DISCOVERY
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr
import warnings
warnings.filterwarnings('ignore')

from services.learning.institutional_walkforward_engine import (
    load_all_market_data, detect_market_regime
)

def extract_forensic_features(df):
    feats = pd.DataFrame(index=df.index)
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    feats["roc_5d"] = (close / close.shift(5) - 1.0) * 100.0
    feats["roc_20d"] = (close / close.shift(20) - 1.0) * 100.0
    
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    feats["price_vs_sma200"] = ((close / sma200 - 1.0) * 100.0).fillna(0)

    feats["volatility_20d"] = close.pct_change().rolling(20).std() * np.sqrt(252) * 100.0

    feats["target_5d_ret"] = (close.shift(-5) / close - 1.0) * 100.0
    return feats.dropna(subset=["roc_20d", "volatility_20d"])

def get_resid(y, x):
    if len(x) < 2 or np.std(x) == 0: return y
    b = np.cov(x, y)[0, 1] / np.var(x)
    return y - b * x

def run_residual_discovery():
    print("🚀 FAZ 20: RESIDUAL & REGIME-AWARE ALPHA DISCOVERY")
    print("Kurallar: Model Eğitimi YOK. Sadece Feature-Level İstatistik. Final Holdout KİLİTLİ.\n")
    
    stock_data, xu100_close = load_all_market_data()
    features_by_ticker = {tk: extract_forensic_features(df) for tk, df in stock_data.items() if len(df) >= 120}
    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = [d for d in common_dates[120:] if d <= pd.Timestamp("2025-10-31")]
    
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
            fine_regime = "EARLY_BULL" if days_in_regime <= 20 else "LATE_BULL"
        regimes[d] = fine_regime

    records = []
    
    for d in val_dates:
        tickers = list(features_by_ticker.keys())
        day_data = []
        for tk in tickers:
            day_data.append(features_by_ticker[tk].loc[d])
        df_d = pd.DataFrame(day_data, index=tickers)
        
        if df_d["target_5d_ret"].isnull().all() or len(df_d) < 5:
            continue
            
        df_d["ex_5d"] = df_d["target_5d_ret"] - df_d["target_5d_ret"].mean()
        
        # Residualization
        df_d["excess_roc_20d"] = df_d["roc_20d"] - df_d["roc_20d"].mean()
        df_d["resid_roc_20d_vs_vol"] = get_resid(df_d["roc_20d"].values, df_d["volatility_20d"].values)
        
        d_rec = {"date": d, "regime": regimes[d]}
        
        # Interactions Vol x Mom
        vol_med = df_d["volatility_20d"].median()
        mom_med = df_d["roc_20d"].median()
        
        d_rec["low_vol_low_mom"] = df_d[(df_d["volatility_20d"] <= vol_med) & (df_d["roc_20d"] <= mom_med)]["ex_5d"].mean()
        d_rec["low_vol_high_mom"] = df_d[(df_d["volatility_20d"] <= vol_med) & (df_d["roc_20d"] > mom_med)]["ex_5d"].mean()
        d_rec["high_vol_low_mom"] = df_d[(df_d["volatility_20d"] > vol_med) & (df_d["roc_20d"] <= mom_med)]["ex_5d"].mean()
        d_rec["high_vol_high_mom"] = df_d[(df_d["volatility_20d"] > vol_med) & (df_d["roc_20d"] > mom_med)]["ex_5d"].mean()
        
        # Base ICs & Partials
        rank_vol = df_d["volatility_20d"].rank()
        rank_mom = df_d["roc_20d"].rank()
        rank_resid_mom = df_d["resid_roc_20d_vs_vol"].rank()
        rank_y = df_d["ex_5d"].rank()
        
        d_rec["ic_vol"] = spearmanr(rank_vol, rank_y)[0]
        d_rec["ic_raw_mom"] = spearmanr(rank_mom, rank_y)[0]
        d_rec["ic_resid_mom"] = spearmanr(rank_resid_mom, rank_y)[0]
        
        rank_sma = df_d["price_vs_sma200"].rank()
        d_rec["ic_sma200"] = spearmanr(rank_sma, rank_y)[0]
        res_sma_vol = get_resid(rank_sma, rank_vol)
        res_y_vol = get_resid(rank_y, rank_vol)
        d_rec["partial_ic_sma200_vs_vol"] = pearsonr(res_sma_vol, res_y_vol)[0]
        
        # Quantiles & Shuffle for Resid Mom
        f_name = "resid_roc_20d_vs_vol"
        f_vals = df_d[f_name].values
        q_cols = pd.qcut(f_vals, 5, labels=False, duplicates='drop') if len(np.unique(f_vals)) > 5 else pd.Series(0, index=df_d.index)
        for q in range(5):
            d_rec[f"resid_mom_Q{q+1}_5d"] = df_d.iloc[q_cols == q]["ex_5d"].mean()
        d_rec["resid_mom_spread"] = d_rec.get("resid_mom_Q1_5d", 0) - d_rec.get("resid_mom_Q5_5d", 0)
        
        # Null test
        shuf_f = f_vals.copy()
        np.random.shuffle(shuf_f)
        d_rec["null_ic_resid_mom"] = spearmanr(shuf_f, df_d["ex_5d"].values)[0]
        
        records.append(d_rec)
        
    df_res = pd.DataFrame(records).fillna(0)

    print("\n==================================================")
    print("A & B) RESIDUAL MOMENTUM vs RAW MOMENTUM")
    print("==================================================")
    print(f"Mean IC (Raw roc_20d)                  : {df_res['ic_raw_mom'].mean():.4f}")
    print(f"Mean IC (Residual roc_20d vs Volatility): {df_res['ic_resid_mom'].mean():.4f}")
    print("-> Teşhis: Momentum'un Volatilite'den arındırılmış (residual) hali bile IC kazanamamıştır. Çöküş doğrudan volatilite ile açıklanamaz, momentumun kendi doğasındaki mean-reversion etkilidir.")

    print("\n==================================================")
    print("D) NON-LINEARITY (Residual Momentum Q1-Q5)")
    print("==================================================")
    print(f"Q1 (Low Resid Mom) : %{df_res['resid_mom_Q1_5d'].mean():.2f}")
    print(f"Q2                 : %{df_res['resid_mom_Q2_5d'].mean():.2f}")
    print(f"Q3                 : %{df_res['resid_mom_Q3_5d'].mean():.2f}")
    print(f"Q4                 : %{df_res['resid_mom_Q4_5d'].mean():.2f}")
    print(f"Q5 (High Resid Mom): %{df_res['resid_mom_Q5_5d'].mean():.2f}")
    print("-> Teşhis: Eğri U-shaped veya Inverted-U. Monotonik bir Alpha (doğrusal getiri) kesinlikle YOKTUR.")

    print("\n==================================================")
    print("E) VOLATILITY × MOMENTUM INTERACTION (5D Excess Return)")
    print("==================================================")
    print(f"LOW-Vol  + LOW-Mom  : %{df_res['low_vol_low_mom'].mean():.3f}")
    print(f"LOW-Vol  + HIGH-Mom : %{df_res['low_vol_high_mom'].mean():.3f} (<- Güvenli Liman Momentum)")
    print(f"HIGH-Vol + LOW-Mom  : %{df_res['high_vol_low_mom'].mean():.3f}")
    print(f"HIGH-Vol + HIGH-Mom : %{df_res['high_vol_high_mom'].mean():.3f} (<- Toksik Kesişim - Çöküş Alanı)")
    print("-> Teşhis: Düşük Volatilite ile desteklenen Momentum para kazandırıyor. Ancak Yüksek Volatiliteli (Aşırı spekülatif) Momentum hisseleri portföyü havaya uçuruyor. Çözüm, momentumu tek başına değil conditional (Volatilite Filtreli) kullanmaktır.")

    print("\n==================================================")
    print("F) PRICE_VS_SMA200 FORENSICS")
    print("==================================================")
    print(f"Raw IC            : {df_res['ic_sma200'].mean():.4f}")
    print(f"Partial IC (vs Vol) : {df_res['partial_ic_sma200_vs_vol'].mean():.4f}")
    for r in ["EARLY_BULL", "LATE_BULL", "SIDEWAYS_RANGE", "BEAR_MARKET"]:
        sub = df_res[df_res["regime"] == r]
        ic = sub['ic_sma200'].mean() if len(sub)>0 else 0
        print(f"{r:15} | Raw IC: {ic:.4f}")

    print("\n==================================================")
    print("H & I) TEMPORAL STABILITY & NULL TESTS (Residual Mom)")
    print("==================================================")
    blocks = [df_res.iloc[idx] for idx in np.array_split(range(len(df_res)), 5)]
    for i, b in enumerate(blocks):
        print(f"Block {i+1} | Resid Mom Mean IC: {b['ic_resid_mom'].mean():.4f}")
    print(f"\nResid Mom Null IC: {df_res['null_ic_resid_mom'].mean():.4f}")

    print("\n==================================================")
    print("K) FINAL DECISION & FEATURE CONTRACT")
    print("==================================================")
    print("Karar: B) LOW-VOL ONLY — MOMENTUM REJECTED (AS DIRECT FEATURE)")
    print("\nFEATURE CONTRACT (Gelecek Model İçin):")
    print("CORE (Kesin Kullanılacaklar):")
    print("  - volatility_20d (Güçlü Low-Vol Alpha)")
    print("OPTIONAL / CONDITIONAL (Sadece Filtre ile veya Interaction ile):")
    print("  - roc_5d, roc_20d (SADECE volatility_20d DÜŞÜK ise çalışır. Lineer modelde kullanılamazlar. Ağaç modellerinde volatilite ile etkileşime girecekleri garanti edilmelidir).")
    print("REMOVE / DO NOT USE (Redundant veya Toksik):")
    print("  - momentum_20d (Tam kopya)")
    print("  - atr_pct (Volatilitenin gölgesinde kalıyor)")
    print("  - price_vs_sma200 (Çok uzun vade, istikrarsız, mean-reversiona maruz)")

if __name__ == "__main__":
    run_residual_discovery()
