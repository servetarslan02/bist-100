from typing import Any
"""FAZ 16: PORTFOLIO-RELEVANT ALPHA FORENSICS"""

import random
import warnings
from datetime import timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score

warnings.filterwarnings("ignore")

import structlog

logger = structlog.get_logger()

from services.learning.institutional_walkforward_engine import detect_market_regime, load_all_market_data


def extract_forensic_features(df) -> Any:
    """Otomatik eklendi."""
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
    bb_upper = sma20 + 2 * bb_std
    bb_lower = sma20 - 2 * bb_std
    feats["bb_position"] = (close - bb_lower) / (bb_upper - bb_lower).replace(0, 1.0)

    # For training (must match old pipeline exactly)
    feats["target_5d_ret"] = (close.shift(-5) / close - 1.0) * 100.0

    # Purely for Forensic Evaluation Horizons
    feats["target_1d_ret"] = (close.shift(-1) / close - 1.0) * 100.0
    feats["target_10d_ret"] = (close.shift(-10) / close - 1.0) * 100.0
    feats["target_20d_ret"] = (close.shift(-20) / close - 1.0) * 100.0

    return feats.dropna(subset=["roc_20d", "volatility_20d"])


def get_top_k(scores_dict, k) -> Any:
    """Otomatik eklendi."""
    return sorted(scores_dict.keys(), key=lambda x: scores_dict[x], reverse=True)[:k]


def get_bottom_k(scores_dict, k) -> Any:
    """Otomatik eklendi."""
    return sorted(scores_dict.keys(), key=lambda x: scores_dict[x])[:k]


def run_forensics() -> Any:
    """Otomatik eklendi."""
    logger.info("🚀 FAZ 16: PORTFOLIO-RELEVANT ALPHA FORENSICS\n")
    logger.info("Kurallar İşletiliyor: Final Holdout Kilitli. PnL Backtest YOK. Hyperparameter Tuning YOK.")

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

    features_by_ticker = {tk: extract_forensic_features(df) for tk, df in stock_data.items() if len(df) >= 120}
    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = [d for d in common_dates[120:] if d <= pd.Timestamp("2025-10-31")]

    logger.info(f"Veri Seti Hazır: {len(val_dates)} gün (Sample Size).")

    cached_scores = {}
    rank_model = None

    # 1. Walk-Forward Prediction Loop
    logger.info("⏳ Model Eğitimi & Scoring Başlıyor (Purged Walk-Forward)...")
    for step_i, current_date in enumerate(val_dates):
        if step_i % 20 == 0:
            train_rows = []
            for tk, fdf in features_by_ticker.items():
                hist_df = fdf.loc[: current_date - timedelta(days=7)]
                if not hist_df.empty:
                    hist_df = hist_df.copy()
                    hist_df["date"] = hist_df.index
                    train_rows.append(hist_df)
            if train_rows:
                train_df = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
                if len(train_df) >= 100:
                    df_sorted = train_df.sort_values("date").copy()
                    df_sorted["target_rank_pct"] = df_sorted.groupby("date")["target_5d_ret"].rank(
                        pct=True, method="average"
                    )
                    df_sorted["relevance"] = (df_sorted["target_rank_pct"] * 4.999).fillna(0).astype(int)
                    groups = df_sorted.groupby("date").size().values
                    rank_model = lgb.LGBMRanker(
                        n_estimators=40,
                        learning_rate=0.05,
                        num_leaves=15,
                        min_data_in_leaf=10,
                        objective="lambdarank",
                        metric="ndcg",
                        random_state=42,
                        n_jobs=2,
                        verbose=-1,
                    )
                    rank_model.fit(df_sorted[feature_cols], df_sorted["relevance"], group=groups)

        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        X_mat = np.array([f[feature_cols].values for f in day_rows])
        scores = {tk: 0.0 for tk in day_tickers}
        if rank_model:
            raw_lgb = rank_model.predict(X_mat)
            for i, tk in enumerate(day_tickers):
                scores[tk] = float(raw_lgb[i])
        cached_scores[current_date] = scores

    # 2. Daily Analysis Arrays
    metrics = []

    for i, current_date in enumerate(val_dates):
        scores = cached_scores.get(current_date, {})
        if not scores:
            continue

        tickers = list(scores.keys())
        # Avoid days where forward returns are completely NaN at the end of dataset
        if pd.isna(features_by_ticker[tickers[0]].loc[current_date].get("target_5d_ret", np.nan)):
            continue

        regime = detect_market_regime(xu100_close, current_date)

        day_actual_ret = {tk: features_by_ticker[tk].loc[current_date]["target_5d_ret"] for tk in tickers}
        day_actual_1d = {tk: features_by_ticker[tk].loc[current_date]["target_1d_ret"] for tk in tickers}
        day_actual_10d = {tk: features_by_ticker[tk].loc[current_date]["target_10d_ret"] for tk in tickers}

        # Rankings
        act_sorted = sorted(tickers, key=lambda x: day_actual_ret[x], reverse=True)
        mod_sorted = sorted(tickers, key=lambda x: scores[x], reverse=True)
        shuffled_sorted = tickers.copy()
        random.seed(i)
        random.shuffle(shuffled_sorted)

        day_m = {"date": current_date, "regime": regime}
        for k in [3, 5, 10]:
            # Model Top-K / Bot-K
            model_top_k = mod_sorted[:k]
            model_bot_k = mod_sorted[-k:]
            day_m[f"model_top_{k}_ret"] = np.nanmean([day_actual_ret[t] for t in model_top_k])
            day_m[f"model_bot_{k}_ret"] = np.nanmean([day_actual_ret[t] for t in model_bot_k])
            day_m[f"model_top_{k}_1d"] = np.nanmean([day_actual_1d[t] for t in model_top_k])
            day_m[f"model_top_{k}_10d"] = np.nanmean([day_actual_10d[t] for t in model_top_k])

            # Precision@K
            true_top_k = set(act_sorted[:k])
            p_at_k = len(set(model_top_k).intersection(true_top_k)) / k
            day_m[f"precision@{k}"] = p_at_k

            # Shuffled Top-K
            shuf_top_k = shuffled_sorted[:k]
            day_m[f"shuf_top_{k}_ret"] = np.nanmean([day_actual_ret[t] for t in shuf_top_k])

        # Top-10% (Top 2 for 20 stocks)
        true_top_10pct = set(act_sorted[: max(1, len(tickers) // 10)])
        model_top_5 = set(mod_sorted[:5])
        day_m["top_10pct_in_top5"] = (
            len(true_top_10pct.intersection(model_top_5)) / len(true_top_10pct) if len(true_top_10pct) > 0 else 0
        )

        # Rank IC for Top-K (Top 5 items)
        top5_pred = [scores[t] for t in mod_sorted[:5]]
        top5_act = [day_actual_ret[t] for t in mod_sorted[:5]]
        day_m["rank_ic_top5"] = (
            spearmanr(top5_pred, top5_act)[0] if len(set(top5_pred)) > 1 and len(set(top5_act)) > 1 else 0
        )

        # Score Separation (Deciles)
        day_m["decile_1_5"] = np.nanmean([day_actual_ret[t] for t in mod_sorted[0:5]])
        day_m["decile_6_10"] = np.nanmean([day_actual_ret[t] for t in mod_sorted[5:10]])
        day_m["decile_11_20"] = np.nanmean([day_actual_ret[t] for t in mod_sorted[10:]])

        # NDCG@K calculation
        rel_scores = np.array([day_actual_ret[t] for t in tickers])
        # scale relevance to > 0
        rel_scores = rel_scores - rel_scores.min()
        pred_scores = np.array([scores[t] for t in tickers])
        try:
            day_m["ndcg@5"] = ndcg_score([rel_scores], [pred_scores], k=5)
        except Exception:
            day_m["ndcg@5"] = 0.0

        # Rank stability
        if i > 0 and metrics:
            prev_top5 = set(sorted(tickers, key=lambda x: cached_scores[val_dates[i - 1]][x], reverse=True)[:5])
            curr_top5 = set(model_top_5)
            day_m["jaccard_top5"] = len(prev_top5.intersection(curr_top5)) / len(prev_top5.union(curr_top5))
        else:
            day_m["jaccard_top5"] = np.nan

        metrics.append(day_m)

    df_m = pd.DataFrame(metrics).dropna(subset=["model_top_5_ret"])

    logger.info("\n==================================================")
    logger.info("1. TOP-K ALPHA SPREADS (5D HORIZON)")
    logger.info("==================================================")
    for k in [3, 5, 10]:
        t_ret = df_m[f"model_top_{k}_ret"].mean()
        b_ret = df_m[f"model_bot_{k}_ret"].mean()
        s_ret = df_m[f"shuf_top_{k}_ret"].mean()
        logger.info(
            f"K={k:<2} | Top-K: %{t_ret:>5.2f} | Bot-K: %{b_ret:>5.2f} | Spread: %{t_ret - b_ret:>5.2f} | Shuffled: %{s_ret:>5.2f}"
        )

    logger.info("\n==================================================")
    logger.info("2. PRECISION & NDCG")
    logger.info("==================================================")
    logger.info(f"Precision@3 : %{df_m['precision@3'].mean() * 100:.1f} (Gerçek Top-3'ün kaçı Model Top-3'te)")
    logger.info(f"Precision@5 : %{df_m['precision@5'].mean() * 100:.1f}")
    logger.info(f"Precision@10: %{df_m['precision@10'].mean() * 100:.1f}")
    logger.info(f"Top 10% Winners in Model Top-5: %{df_m['top_10pct_in_top5'].mean() * 100:.1f}")
    logger.info(f"NDCG@5      : {df_m['ndcg@5'].mean():.3f}")

    logger.info("\n==================================================")
    logger.info("3. RANK IC VS PORTFOLIO-RELEVANT RANK IC")
    logger.info("==================================================")
    logger.info(f"Portföyün Top 5 Hissesi İçi Rank IC: {df_m['rank_ic_top5'].mean():.4f}")
    if df_m["rank_ic_top5"].mean() < 0.10:
        logger.info("-> DİKKAT: Model ilk 5'i kendi içinde doğru sıralayamıyor. (Gürültü)")

    logger.info("\n==================================================")
    logger.info("4. SCORE SEPARATION (TIERS)")
    logger.info("==================================================")
    logger.info(f"Rank 1-5  Return: %{df_m['decile_1_5'].mean():.2f}")
    logger.info(f"Rank 6-10 Return: %{df_m['decile_6_10'].mean():.2f}")
    logger.info(f"Rank 11-20 Return: %{df_m['decile_11_20'].mean():.2f}")

    logger.info("\n==================================================")
    logger.info("5. RANK STABILITY")
    logger.info("==================================================")
    logger.info(f"Top-5 Jaccard Similarity (T vs T+1): {df_m['jaccard_top5'].mean():.3f}")

    logger.info("\n==================================================")
    logger.info("6. BOOTSTRAP 95% CI (ACTUAL TOP-5 VS SHUFFLED TOP-5)")
    logger.info("==================================================")
    np.random.seed(42)
    diffs = df_m["model_top_5_ret"] - df_m["shuf_top_5_ret"]
    boot_means = [np.mean(np.random.choice(diffs, size=len(diffs), replace=True)) for _ in range(1000)]
    ci_lower = np.percentile(boot_means, 2.5)
    ci_upper = np.percentile(boot_means, 97.5)
    p_value = np.mean(np.array(boot_means) <= 0)

    logger.info(f"Mean Difference: %{np.mean(diffs):.2f}")
    logger.info(f"95% CI         : [%{ci_lower:.2f}, %{ci_upper:.2f}]")
    logger.info(f"P-value (H0: Diff<=0): {p_value:.4f}")

    logger.info("\n==================================================")
    logger.info("7. REJİM BAZLI TOP-5 SPREAD ANALİZİ")
    logger.info("==================================================")
    for reg in ["BULL_TREND", "BEAR_MARKET", "SIDEWAYS_RANGE"]:
        d_sub = df_m[df_m["regime"] == reg]
        if len(d_sub) > 0:
            act = d_sub["model_top_5_ret"].mean()
            shuf = d_sub["shuf_top_5_ret"].mean()
            logger.info(
                f"{reg:15} | N={len(d_sub):<3} | Ranker: %{act:>5.2f} | Shuf: %{shuf:>5.2f} | Fark: %{act - shuf:>5.2f}"
            )

    logger.info("\n==================================================")
    logger.info("8. KRİTİK NULL TESTİ & NİHAİ KARAR")
    logger.info("==================================================")
    if ci_lower > 0 and p_value < 0.05:
        logger.info("H0 REDDEDİLDİ: PORTFOLIO-RELEVANT ALPHA İÇİN İSTATİSTİKSEL KANIT VAR")
        logger.info("\nSonuç: A) STRONG PORTFOLIO-RELEVANT ALPHA")
    elif np.mean(diffs) > 0:
        logger.info("H0 REDDEDİLEMEDİ: PORTFOLIO-RELEVANT ALPHA İSTATİSTİKSEL OLARAK ZAYIF")
        logger.info("\nSonuç: B) WEAK / INCONCLUSIVE ALPHA")
    else:
        logger.info("H0 REDDEDİLEMEDİ: RANKER, RASTGELE SEÇİMDEN DAHA İYİ DEĞİL.")
        logger.info("\nSonuç: C) NO PORTFOLIO-RELEVANT ALPHA")


if __name__ == "__main__":
    run_forensics()
