import datetime
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
import structlog

from services.ml.feature_engine import compute_universe_features

logger = structlog.get_logger(__name__)


class LightGBMPipeline:
    """LightGBM training and inference pipeline for universe alpha prediction."""

    def __init__(self):
        """Initialize LightGBMPipeline."""
        self.model = None
        self.features: list[str] = []
        self.params = {
            "objective": "regression",
            "metric": "rmse",
            "boosting_type": "gbdt",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 5,
            "feature_fraction": 0.8,
            "min_data_in_leaf": 20,
            "verbose": -1,
            "random_state": 42,
        }

    def generate_samples(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        train_start: datetime.datetime | str,
        train_end: datetime.datetime | str,
        snapshot_offsets: list[int] | None = None,
        forward_days: int = 20,
    ) -> Any:
        """Generate point-in-time training samples and forward return labels."""
        if snapshot_offsets is None:
            snapshot_offsets = [20, 40, 60, 80]
        rows = []
        labels = []
        all_keys: list[str] = []

        t_start = train_start if isinstance(train_start, datetime.datetime) else datetime.datetime.fromisoformat(str(train_start)[:10])
        t_end = train_end if isinstance(train_end, datetime.datetime) else datetime.datetime.fromisoformat(str(train_end)[:10])

        for offset in snapshot_offsets:
            t_snap = t_end - datetime.timedelta(days=int(offset))
            t_fwd = t_snap + datetime.timedelta(days=int(forward_days))

            if t_snap < t_start:
                continue

            snap_md = {}
            for t, df in market_data.items():
                if df is None or len(df) == 0:
                    continue
                if "Date" in df.columns:
                    sub_df = df.filter(pl.col("Date") <= t_snap)
                else:
                    sub_df = df
                if len(sub_df) >= 120:
                    snap_md[t] = sub_df

            if bm_df is None or len(bm_df) == 0:
                continue
            if "Date" in bm_df.columns:
                snap_bm = bm_df.filter(pl.col("Date") <= t_snap)
            else:
                snap_bm = bm_df
            if len(snap_bm) < 120:
                continue

            features = compute_universe_features(snap_md, snap_bm, sector_map)

            for ticker, feats in features.items():
                if not feats or ticker not in market_data:
                    continue

                df_t = market_data[ticker]
                if df_t is None or len(df_t) == 0 or "Date" not in df_t.columns:
                    continue

                df_fwd = df_t.filter((pl.col("Date") >= t_snap) & (pl.col("Date") <= t_fwd))
                bm_fwd = bm_df.filter((pl.col("Date") >= t_snap) & (pl.col("Date") <= t_fwd)) if "Date" in bm_df.columns else pl.DataFrame()

                if len(df_fwd) < 2 or len(bm_fwd) < 2:
                    continue

                p_0 = float(df_fwd["Close"][0])
                p_1 = float(df_fwd["Close"][-1])
                b_0 = float(bm_fwd["Close"][0])
                b_1 = float(bm_fwd["Close"][-1])

                if p_0 <= 0 or b_0 <= 0:
                    continue

                ret = (p_1 / p_0) - 1.0
                bm_ret = (b_1 / b_0) - 1.0
                excess_ret = ret - bm_ret

                rows.append(feats)
                labels.append(excess_ret)

                if not all_keys:
                    all_keys = sorted(list(feats.keys()))

        if not rows:
            return np.array([]), np.array([]), []

        X = np.array([[r.get(k, 0.0) or 0.0 for k in all_keys] for r in rows])
        y = np.array(labels)

        return X, y, all_keys

    def train(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        train_start: datetime.datetime | str,
        train_end: datetime.datetime | str,
    ) -> bool:
        """Train LightGBM model on historical snapshot samples."""
        X, y, feature_names = self.generate_samples(market_data, bm_df, sector_map, train_start, train_end)

        if len(X) == 0:
            logger.warning("No training samples generated")
            return False

        self.features = feature_names
        train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
        self.model = lgb.train(self.params, train_data, num_boost_round=100)
        return True

    def predict(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        target_date: datetime.datetime | str,
    ) -> list[dict[str, Any]]:
        """Predict universe forward excess returns as of target_date."""
        if not self.model:
            return []

        t_target = target_date if isinstance(target_date, datetime.datetime) else datetime.datetime.fromisoformat(str(target_date)[:10])

        snap_md = {}
        for t, df in market_data.items():
            if df is None or len(df) == 0:
                continue
            if "Date" in df.columns:
                sub_df = df.filter(pl.col("Date") <= t_target)
            else:
                sub_df = df
            if len(sub_df) >= 120:
                snap_md[t] = sub_df

        if bm_df is None or len(bm_df) == 0:
            return []
        if "Date" in bm_df.columns:
            snap_bm = bm_df.filter(pl.col("Date") <= t_target)
        else:
            snap_bm = bm_df
        if len(snap_bm) < 120:
            return []

        features = compute_universe_features(snap_md, snap_bm, sector_map)

        predictions = []
        for ticker, feats in features.items():
            if not feats:
                continue
            x_vec = np.array([[feats.get(k, 0.0) or 0.0 for k in self.features]])
            score = self.model.predict(x_vec)[0]
            predictions.append({"ticker": ticker, "score": float(score), "features": feats})

        # Sort by score descending
        predictions.sort(key=lambda x: x["score"], reverse=True)
        return predictions

