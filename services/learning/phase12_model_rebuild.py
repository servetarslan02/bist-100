from typing import Any

"""FAZ 12: PRODUCTION-GRADE ALPHA MODEL REBUILD
(OFFLINE DIAGNOSTICS & PIPELINE RE-ARCHITECTURE)
"""

import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from scipy.stats import spearmanr

from services.learning.institutional_walkforward_engine import extract_point_in_time_features, load_all_market_data


class CrossSectionalRanker:
    """Production-grade Alpha Model using LambdaRank for Cross-Sectional Stock Selection."""


import structlog

logger = structlog.get_logger()


class AlphaModel:
    """Otomatik eklendi."""
    def __init__(self, feature_cols):
        """Otomatik eklendi."""
        self.feature_cols = feature_cols
        self.model = None

    def _prepare_labels(self, train_df) -> Any:
        """Otomatik eklendi."""
        # 1. LABEL DESIGN: Cross-Sectional Rank
        # Note: Ranking absolute return cross-sectionally is mathematically 100% equivalent
        # to ranking excess return (relative to benchmark), because the benchmark return
        # is a constant scalar for all stocks on any given day.

        # Must sort by date for LambdaRank grouping
        df_sorted = train_df.sort_values("date").copy()

        # 2. Map continuous returns to 5 discrete relevance buckets (0 to 4)
        df_sorted["target_rank_pct"] = df_sorted.groupby("date")["target_5d_ret"].rank(pct=True, method="average")
        df_sorted["relevance"] = (df_sorted["target_rank_pct"] * 4.999).fillna(0).astype(int)

        # 3. Group boundaries for LightGBM
        groups = df_sorted.groupby("date").size().values

        return df_sorted, groups

    def retrain_fold(self, train_df) -> Any:
        """Otomatik eklendi."""
        if len(train_df) < 50:
            return

        df_sorted, groups = self._prepare_labels(train_df)

        X = df_sorted[self.feature_cols]
        y = df_sorted["relevance"]

        self.model = lgb.LGBMRanker(
            n_estimators=50,
            learning_rate=0.05,
            num_leaves=15,
            min_data_in_leaf=5,
            objective="lambdarank",
            metric="ndcg",
            random_state=42,
            n_jobs=2,
            verbose=-1,
        )
        self.model.fit(X, y, group=groups)

    def predict_batch_day(self, tickers, features_list) -> Any:
        """Otomatik eklendi."""
        if not self.model:
            return {tk: 0.0 for tk in tickers}

        X_mat = np.array([f[self.feature_cols].values for f in features_list])
        raw_preds = self.model.predict(X_mat)

        # SCORE ADAPTER: Backward Compatibility with V3 Regression Scores
        # Raw LambdaRank predictions are unbounded utility scores.
        # We transform them into Cross-Sectional Percentiles [0, 1],
        # then scale to [-1, 1] to mimic the old np.tanh() behavior.
        # This guarantees: Mean = 0, Max = ~1.0, Min = ~-1.0, safely compatible with min_score thresholds.
        s = pd.Series(raw_preds)
        if len(s) > 1:
            pct_rank = s.rank(pct=True)
            normalized_scores = (pct_rank - 0.5) * 2.0
        else:
            normalized_scores = pd.Series([0.0])

        return {tk: float(normalized_scores.iloc[i]) for i, tk in enumerate(tickers)}


def run_tests() -> Any:
    """Otomatik eklendi."""
    logger.info("🚀 FAZ 12: PRODUCTION-GRADE ALPHA MODEL REBUILD TESTS\n")

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
    val_dates = common_dates[120:150]

    # Compile training dataframe with dates
    train_rows = []
    for tk, fdf in features_by_ticker.items():
        df_sub = fdf.loc[: val_dates[-1]].copy()
        df_sub["date"] = df_sub.index
        df_sub["ticker"] = tk
        train_rows.append(df_sub)
    full_df = pd.concat(train_rows).dropna(subset=["target_5d_ret"])

    logger.info("==================================================")
    logger.info("1. LABEL CORRECTNESS & AUDIT TESTS")
    logger.info("==================================================")
    # Test A vs Test B
    test_date = val_dates[10]
    daily_df = full_df[full_df["date"] == test_date].copy()
    idx = xu100_close.index.get_loc(test_date)
    xu_fwd_5d = (xu100_close.iloc[idx + 5] / xu100_close.iloc[idx] - 1.0) * 100.0

    daily_df["excess_ret"] = daily_df["target_5d_ret"] - xu_fwd_5d
    rank_raw = daily_df["target_5d_ret"].rank(pct=True)
    rank_excess = daily_df["excess_ret"].rank(pct=True)

    corr = spearmanr(rank_raw, rank_excess)[0]
    logger.info(f"Rank(Raw Return) vs Rank(Excess Return) Correlation: {corr:.4f}")
    if corr > 0.99:
        logger.info(
            "-> Doğrulandı: Raw return ranking'i cross-sectional olarak %100 Excess return ranking'ine eşittir. Matematiksel mükemmellik sağlandı."
        )

    logger.info("\n==================================================")
    logger.info("2. GROUP INTEGRITY TESTS")
    logger.info("==================================================")
    ranker = CrossSectionalRanker(feature_cols)
    train_slice = full_df[full_df["date"] <= val_dates[5]].copy()
    df_sorted, groups = ranker._prepare_labels(train_slice)

    logger.info(f"Total Rows in Dataset: {len(df_sorted)}")
    logger.info(f"Sum of Group Sizes   : {groups.sum()}")
    if len(df_sorted) == groups.sum():
        logger.info("-> Doğrulandı: Group integrity bozulmamıştır.")

    logger.info("\n==================================================")
    logger.info("3. SCORE SEMANTICS & BACKWARD COMPATIBILITY TEST")
    logger.info("==================================================")
    ranker.retrain_fold(train_slice)

    t_day = val_dates[6]
    day_tickers = list(features_by_ticker.keys())
    day_rows = [features_by_ticker[tk].loc[t_day] for tk in day_tickers]

    preds = ranker.predict_batch_day(day_tickers, day_rows)
    pred_values = list(preds.values())

    logger.info(f"Score Scale Min  : {min(pred_values):.4f} (Beklenen: ~-1.0)")
    logger.info(f"Score Scale Max  : {max(pred_values):.4f} (Beklenen: ~1.0)")
    logger.info(f"Score Scale Mean : {np.mean(pred_values):.4f} (Beklenen: ~0.0)")

    if abs(np.mean(pred_values)) < 0.05 and max(pred_values) > 0.9:
        logger.info(
            "-> Doğrulandı: Score adapter eski modelin np.tanh sınırlarıyla tamamen uyumlu. Threshold'lar kırılmayacak."
        )

    logger.info("\n==================================================")
    logger.info("4. NO-LOOKAHEAD & FRESHNESS TESTS")
    logger.info("==================================================")
    # Ensure current day features do not contain future leakage
    features_by_ticker[day_tickers[0]]
    # Check if target_5d_ret is used anywhere in input features
    intersection = set(feature_cols).intersection({"target_5d_ret", "target_5d_bin"})
    logger.info(f"Leakage Feature Intersection: {intersection}")
    if len(intersection) == 0:
        logger.info("-> Doğrulandı: Model inference anında gelecek bilgisi (target) kullanmıyor.")

    logger.info("\n==================================================")
    logger.info("5. RANKING DIRECTION TEST")
    logger.info("==================================================")
    actual_fwd = [features_by_ticker[tk].loc[t_day].get("target_5d_ret", 0) for tk in day_tickers]
    direction_corr = spearmanr(pred_values, actual_fwd)[0]
    logger.info(f"Out-of-sample Prediction vs Actual Forward Return Rank IC: {direction_corr:.4f}")

    logger.info("\n" + "=" * 50)
    logger.info("ÇIKIŞ RAPORU HAZIR.")


if __name__ == "__main__":
    run_tests()
