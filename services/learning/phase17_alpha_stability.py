"""FAZ 17: ALPHA STABILITY & INDEPENDENCE AUDIT
"""

import numpy as np
import pandas as pd
from datetime import timedelta
import lightgbm as lgb
import random
import warnings
warnings.filterwarnings('ignore')

from services.learning.institutional_walkforward_engine import (
import structlog
logger = structlog.get_logger()

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
    feats["momentum_20d"] = feats["roc_20d"]

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
    feats["bb_position"] = (close - (sma20 - 2*bb_std)) / (4 * bb_std).replace(0, 1.0)

    # For training
    feats["target_5d_ret"] = (close.shift(-5) / close - 1.0) * 100.0
    
    # Purely for Forensic Evaluation Horizons
    feats["target_1d_ret"] = (close.shift(-1) / close - 1.0) * 100.0
    feats["target_10d_ret"] = (close.shift(-10) / close - 1.0) * 100.0
    feats["target_20d_ret"] = (close.shift(-20) / close - 1.0) * 100.0
    
    return feats.dropna(subset=["roc_20d", "volatility_20d"])


def run_alpha_stability_audit():
    logger.info("🚀 FAZ 17: ALPHA STABILITY & INDEPENDENCE AUDIT\n")
    logger.info("Kurallar İşletiliyor: Final Holdout Kilitli. PnL Backtest YOK. Sadece Alpha Stabilitesi.")
    
    stock_data, xu100_close = load_all_market_data()
    feature_cols = ["roc_5d", "roc_20d", "momentum_20d", "price_vs_sma20", "price_vs_sma50", "price_vs_sma200", "atr_pct", "volatility_20d", "volume_zscore", "bb_position"]
    
    features_by_ticker = {tk: extract_forensic_features(df) for tk, df in stock_data.items() if len(df) >= 120}
    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = [d for d in common_dates[120:] if d <= pd.Timestamp("2025-10-31")]
    
    logger.info(f"Veri Seti Hazır: {len(val_dates)} gün (Sample Size).")
    
    cached_scores = {}
    rank_model = None
    
    logger.info("⏳ Model Eğitimi & Scoring Başlıyor (Purged Walk-Forward)...")
    for step_i, current_date in enumerate(val_dates):
        if step_i % 20 == 0:
            train_rows = []
            for tk, fdf in features_by_ticker.items():
                hist_df = fdf.loc[:current_date - timedelta(days=7)]
                if not hist_df.empty:
                    hist_df = hist_df.copy()
                    hist_df['date'] = hist_df.index
                    train_rows.append(hist_df)
            if train_rows:
                train_df = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
                if len(train_df) >= 100:
                    df_sorted = train_df.sort_values('date').copy()
                    df_sorted['target_rank_pct'] = df_sorted.groupby('date')['target_5d_ret'].rank(pct=True, method='average')
                    df_sorted['relevance'] = (df_sorted['target_rank_pct'] * 4.999).fillna(0).astype(int)
                    groups = df_sorted.groupby('date').size().values
                    rank_model = lgb.LGBMRanker(n_estimators=40, learning_rate=0.05, num_leaves=15, min_data_in_leaf=10, objective='lambdarank', metric='ndcg', random_state=42, n_jobs=2, verbose=-1)
                    rank_model.fit(df_sorted[feature_cols], df_sorted['relevance'], group=groups)
        
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        X_mat = np.array([f[feature_cols].values for f in day_rows])
        scores = {tk: 0.0 for tk in day_tickers}
        if rank_model:
            raw_lgb = rank_model.predict(X_mat)
            for i, tk in enumerate(day_tickers):
                scores[tk] = float(raw_lgb[i])
        cached_scores[current_date] = scores

    # Metrics Collection
    daily_metrics = []
    
    # Set fixed seed for Random Benchmark reproducibility in this phase
    np.random.seed(42)
    random.seed(42)
    
    for i, current_date in enumerate(val_dates):
        scores = cached_scores.get(current_date, {})
        if not scores: continue
        tickers = list(scores.keys())
        
        # Avoid days where forward returns are completely NaN at the end of dataset
        if pd.isna(features_by_ticker[tickers[0]].loc[current_date].get("target_5d_ret", np.nan)):
            continue
            
        regime = detect_market_regime(xu100_close, current_date)
        
        day_ret = {
            "1D": {tk: features_by_ticker[tk].loc[current_date]["target_1d_ret"] for tk in tickers},
            "5D": {tk: features_by_ticker[tk].loc[current_date]["target_5d_ret"] for tk in tickers},
            "10D": {tk: features_by_ticker[tk].loc[current_date]["target_10d_ret"] for tk in tickers},
            "20D": {tk: features_by_ticker[tk].loc[current_date]["target_20d_ret"] for tk in tickers},
        }
        
        mod_sorted = sorted(tickers, key=lambda x: scores[x], reverse=True)
        
        # 1000 Random Top-5 Selections for Empirical P-Value
        rand_5d_rets = []
        for _ in range(1000):
            rand_sel = random.sample(tickers, 5)
            rand_5d_rets.append(np.nanmean([day_ret["5D"][t] for t in rand_sel]))
            
        # Shuffled
        shuffled = tickers.copy()
        random.shuffle(shuffled)
            
        day_m = {
            "date": current_date,
            "regime": regime,
            "top3_5d": np.nanmean([day_ret["5D"][t] for t in mod_sorted[:3]]),
            "top5_5d": np.nanmean([day_ret["5D"][t] for t in mod_sorted[:5]]),
            "top10_5d": np.nanmean([day_ret["5D"][t] for t in mod_sorted[:10]]),
            "bot5_5d": np.nanmean([day_ret["5D"][t] for t in mod_sorted[-5:]]),
            
            "top5_1d": np.nanmean([day_ret["1D"][t] for t in mod_sorted[:5]]),
            "top5_10d": np.nanmean([day_ret["10D"][t] for t in mod_sorted[:5]]),
            "top5_20d": np.nanmean([day_ret["20D"][t] for t in mod_sorted[:5]]),
            
            "shuf5_1d": np.nanmean([day_ret["1D"][t] for t in shuffled[:5]]),
            "shuf5_5d": np.nanmean([day_ret["5D"][t] for t in shuffled[:5]]),
            "shuf5_10d": np.nanmean([day_ret["10D"][t] for t in shuffled[:5]]),
            "shuf5_20d": np.nanmean([day_ret["20D"][t] for t in shuffled[:5]]),
            
            "rand_dist_mean": np.mean(rand_5d_rets),
            "rand_dist_std": np.std(rand_5d_rets),
            "rand_dist_p95": np.percentile(rand_5d_rets, 95),
            "rand_samples": rand_5d_rets
        }
        
        day_m["spread_5d"] = day_m["top5_5d"] - day_m["rand_dist_mean"]
        daily_metrics.append(day_m)

    df_m = pd.DataFrame(daily_metrics).dropna(subset=["top5_5d"])
    
    logger.info("\n==================================================")
    logger.info("1. WALK-FORWARD TIME BLOCKS STABILITY")
    logger.info("==================================================")
    blocks = [df_m.iloc[idx] for idx in np.array_split(range(len(df_m)), 5)]
    pos_blocks = 0
    for i, b in enumerate(blocks):
        t3 = b['top3_5d'].mean()
        t5 = b['top5_5d'].mean()
        t10 = b['top10_5d'].mean()
        b5 = b['bot5_5d'].mean()
        spr = b['spread_5d'].mean()
        if spr > 0: pos_blocks += 1
        logger.info(f"Block {i+1} | N={len(b):<2} | Top3: %{t3:>5.2f} | Top5: %{t5:>5.2f} | Bot5: %{b5:>5.2f} | Spread (Top5-Rand): %{spr:>5.2f}")
        
    logger.info(f"\nPositive Spread Block Rate: %{pos_blocks/5*100:.1f} ({pos_blocks}/5 blocks)")

    logger.info("\n==================================================")
    logger.info("2. REGIME STABILITY")
    logger.info("==================================================")
    for reg in ["BULL_TREND", "BEAR_MARKET", "SIDEWAYS_RANGE"]:
        d_sub = df_m[df_m['regime'] == reg]
        if len(d_sub) > 0:
            act = d_sub['top5_5d'].mean()
            rnd = d_sub['rand_dist_mean'].mean()
            spr = d_sub['spread_5d'].mean()
            pos_days = (d_sub['spread_5d'] > 0).mean() * 100
            logger.info(f"{reg:15} | N={len(d_sub):<3} | Ranker: %{act:>5.2f} | Random: %{rnd:>5.2f} | Spread: %{spr:>5.2f} | Pos Days: %{pos_days:.1f}")

    logger.info("\n==================================================")
    logger.info("3. TOP-5 ALPHA CONCENTRATION (DAY RELIANCE)")
    logger.info("==================================================")
    sorted_spreads = df_m['spread_5d'].sort_values(ascending=False).values
    total_mean = sorted_spreads.mean()
    
    n = len(sorted_spreads)
    drop_1pct = int(n * 0.01)
    drop_5pct = int(n * 0.05)
    drop_10pct = int(n * 0.10)
    drop_20pct = int(n * 0.20)
    
    mean_no_1 = sorted_spreads[drop_1pct:].mean() if drop_1pct < n else 0
    mean_no_5 = sorted_spreads[drop_5pct:].mean() if drop_5pct < n else 0
    mean_no_10 = sorted_spreads[drop_10pct:].mean() if drop_10pct < n else 0
    mean_no_20 = sorted_spreads[drop_20pct:].mean() if drop_20pct < n else 0
    
    logger.info(f"Bütün Günler (All Data) Spread: %{total_mean:.3f}")
    logger.info(f"En iyi %1 Gün Çıkarıldığında : %{mean_no_1:.3f}")
    logger.info(f"En iyi %5 Gün Çıkarıldığında : %{mean_no_5:.3f}")
    logger.info(f"En iyi %10 Gün Çıkarıldığında: %{mean_no_10:.3f}")
    logger.info(f"En iyi %20 Gün Çıkarıldığında: %{mean_no_20:.3f} (DİKKAT: Eğer bu eksiye düşüyorsa Alpha sadece birkaç güne bağlıdır!)")

    logger.info("\n==================================================")
    logger.info("4. HORIZON ROBUSTNESS")
    logger.info("==================================================")
    horizons = [(1, "top5_1d", "shuf5_1d"), (5, "top5_5d", "shuf5_5d"), (10, "top5_10d", "shuf5_10d"), (20, "top5_20d", "shuf5_20d")]
    for h, top_col, shuf_col in horizons:
        # Check if the target exists
        if df_m[top_col].isnull().all(): continue
        mean_top = df_m[top_col].mean()
        mean_shuf = df_m[shuf_col].mean()
        spread = mean_top - mean_shuf
        logger.info(f"{h:>2}D Horizon | Top-5: %{mean_top:>5.2f} | Shuffled-5: %{mean_shuf:>5.2f} | Spread: %{spread:>5.2f}")

    logger.info("\n==================================================")
    logger.info("5. EMPIRICAL P-VALUE (1000 RANDOM SEEDS PER DAY)")
    logger.info("==================================================")
    # Average across all days for each of the 1000 samples
    all_rand_samples = np.array(df_m['rand_samples'].tolist()) # Shape: (N_days, 1000)
    avg_portfolio_returns = all_rand_samples.mean(axis=0) # Shape: (1000,)
    
    actual_mean = df_m['top5_5d'].mean()
    p_value = np.mean(avg_portfolio_returns >= actual_mean)
    ci_95_lower = np.percentile(avg_portfolio_returns, 2.5)
    ci_95_upper = np.percentile(avg_portfolio_returns, 97.5)
    
    logger.info(f"Actual Ranker Top-5 Mean: %{actual_mean:.3f}")
    logger.info(f"Random Distributions 95% CI: [%{ci_95_lower:.3f}, %{ci_95_upper:.3f}]")
    logger.info(f"Empirical P-Value (H0: Actual <= Random): {p_value:.4f}")
    if p_value > 0.05:
        logger.info("-> DİKKAT: Top-5 Alpha 1000 rastgele teste karşı istatistiksel anlamlılığını (p < 0.05) KORUYAMADI.")

    logger.info("\n==================================================")
    logger.info("6. NİHAİ KARAR")
    logger.info("==================================================")
    # Decision logic
    if p_value < 0.05 and pos_blocks >= 4 and mean_no_20 > 0:
        logger.info("Sonuç: A) ROBUST ALPHA")
    elif p_value < 0.10 or (pos_blocks >= 3 and mean_no_10 > 0):
        logger.info("Sonuç: B) PROMISING BUT NOT YET ROBUST")
    else:
        logger.info("Sonuç: C) NO ROBUST ALPHA")
        
if __name__ == "__main__":
    run_alpha_stability_audit()
