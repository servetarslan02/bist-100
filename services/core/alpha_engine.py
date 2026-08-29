from __future__ import annotations

from typing import Any
"""
ALPHA BIST — Alpha Engine v2.0 (Enterprise-Grade)
"""


import datetime
import functools
import hashlib
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
import structlog
import yfinance as yf
from opentelemetry import metrics, trace

from services.core.safe_pickle import safe_pickle_dump, safe_pickle_load
from services.ingestion.bist_universe import bist_universe
from services.ml.feature_engine import compute_universe_features

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.alpha_engine")
meter = metrics.get_meter("alpha-bist.alpha_engine")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


def _yf_to_polars(yf_df) -> pl.DataFrame:
    """yfinance pandas DataFrame'ini Polars'a çevir."""
    if yf_df is None or len(yf_df) == 0:
        return pl.DataFrame()
    df = yf_df.reset_index()
    if isinstance(df.columns, __import__("pandas").MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return pl.from_pandas(df)


def _detect_gpu_cuda() -> Any:
    """Detect NVIDIA GPU CUDA capability."""
    try:
        import torch

        if torch.cuda.is_available():
            return True, torch.cuda.get_device_name(0)
    except Exception as exc:
        logger.debug("GPU/CUDA algılanamadı, CPU kullanılacak", error=str(exc))
    return False, "CPU"


class AlphaEngine:
    """Otomatik eklendi."""
    def __init__(self, exclude_features: list[str] = None):
        """Otomatik eklendi."""
        has_gpu, dev_name = _detect_gpu_cuda()
        self.has_gpu = has_gpu
        self.gpu_device_name = dev_name
        self.params = {
            "objective": "regression",
            "metric": "rmse",
            "n_estimators": 100,
            "learning_rate": 0.05,
            "max_depth": 3,
            "num_leaves": 7,
            "verbose": -1,
            "n_jobs": -1,
        }
        if self.has_gpu:
            logger.info("AlphaEngine configured with GPU acceleration", device=self.gpu_device_name)
        self.model = None
        self.features = []

        default_bad_features = ["momentum_accel", "roc_120d", "dist_sma200", "cs_zscore_ret_1d", "roc_5d"]
        self.exclude_features = exclude_features if exclude_features is not None else default_bad_features

    @otel_trace("alpha_engine.fetch_data")
    def fetch_data(self, start_date: str, end_date: str, tickers: list[str] = None) -> Any:
        """Otomatik eklendi."""
        if tickers is None:
            tickers = (
                bist_universe.BIST_ALL_TICKERS
                if hasattr(bist_universe, "BIST_ALL_TICKERS") and bist_universe.BIST_ALL_TICKERS
                else (bist_universe.BIST_100_TICKERS if hasattr(bist_universe, "BIST_100_TICKERS") else [])
            )
        sector_map = {t: bist_universe.get_ticker_sector(t) for t in tickers}

        market_data: dict[str, pl.DataFrame] = {}
        batch_size = 100
        for i in range(0, len(tickers), batch_size):
            chunk = tickers[i : i + batch_size]
            chunk_symbols = [f"{t}.IS" for t in chunk]
            try:
                raw = yf.download(
                    tickers=" ".join(chunk_symbols),
                    start=start_date,
                    end=end_date,
                    group_by="ticker",
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
                if raw is not None and len(raw) > 0:
                    for t in chunk:
                        tick_sym = f"{t}.IS"
                        try:
                            if isinstance(raw.columns, __import__("pandas").MultiIndex):
                                if tick_sym in raw.columns.levels[0]:
                                    df_t = raw[tick_sym].dropna(how="all")
                                    if len(df_t) >= 10:
                                        market_data[t] = _yf_to_polars(df_t)
                            else:
                                df_t = raw.dropna(how="all")
                                if len(df_t) >= 10:
                                    market_data[t] = _yf_to_polars(df_t)
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"AlphaEngine batch download warning (chunk {i}): {e}")

        # Benchmark
        bm_df = pl.DataFrame()
        try:
            bm_raw = yf.download("XU100.IS", start=start_date, end=end_date, auto_adjust=True, progress=False)
            bm_df = _yf_to_polars(bm_raw.dropna(how="all"))
        except Exception as e:
            logger.warning(f"Benchmark download warning: {e}")

        return market_data, bm_df, sector_map

    @otel_trace("alpha_engine.generate_training_samples")
    def generate_training_samples(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        train_start: datetime.datetime,
        train_end: datetime.datetime,
        snapshot_offsets: list[int] = None,
        forward_days: int = 20,
    ) -> Any:
        """Otomatik eklendi."""
        if snapshot_offsets is None:
            snapshot_offsets = [20, 40, 60, 80]
        rows = []
        labels = []
        all_keys = []

        for offset in snapshot_offsets:
            t_snap = train_end - datetime.timedelta(days=int(offset))
            t_fwd = t_snap + datetime.timedelta(days=int(forward_days))

            if t_snap < train_start:
                continue

            snap_md = {}
            for t, df in market_data.items():
                if "Date" in df.columns:
                    sub_df = df.filter((pl.col("Date") >= train_start) & (pl.col("Date") <= t_snap))
                    if len(sub_df) >= 120:
                        snap_md[t] = sub_df

            if "Date" in bm_df.columns:
                snap_bm = bm_df.filter((pl.col("Date") >= train_start) & (pl.col("Date") <= t_snap))
            else:
                snap_bm = bm_df
            if len(snap_bm) < 120:
                continue

            features = compute_universe_features(snap_md, snap_bm, sector_map)

            for ticker, feats in features.items():
                if not feats or ticker not in market_data:
                    continue

                if self.exclude_features:
                    for exf in self.exclude_features:
                        feats.pop(exf, None)

                df_t = market_data[ticker]
                if "Date" in df_t.columns:
                    df_fwd = df_t.filter((pl.col("Date") >= t_snap) & (pl.col("Date") <= t_fwd))
                else:
                    df_fwd = df_t

                if "Date" in bm_df.columns:
                    bm_fwd = bm_df.filter((pl.col("Date") >= t_snap) & (pl.col("Date") <= t_fwd))
                else:
                    bm_fwd = bm_df

                if len(df_fwd) < 2 or len(bm_fwd) < 2:
                    continue

                try:
                    p_0 = float(df_fwd["Close"][0])
                    p_1 = float(df_fwd["Close"][-1])
                    b_0 = float(bm_fwd["Close"][0])
                    b_1 = float(bm_fwd["Close"][-1])
                except Exception:
                    continue

                if p_0 <= 0 or b_0 <= 0:
                    continue

                excess_ret = float(((p_1 / p_0) - 1.0) - ((b_1 / b_0) - 1.0))
                rows.append(feats)
                labels.append(excess_ret)
                if not all_keys:
                    all_keys = sorted(list(feats.keys()))

        if not rows:
            return np.array([]), np.array([]), []

        X = np.array([[r.get(k, 0.0) or 0.0 for k in all_keys] for r in rows])
        y = np.array(labels)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        return X, y, all_keys

    @otel_trace("alpha_engine.train")
    def train(self, market_data, bm_df, sector_map, train_start_str: str, train_end_str: str, optimize: bool = True) -> Any:
        """Otomatik eklendi."""
        t_start = datetime.datetime.strptime(train_start_str, "%Y-%m-%d")
        t_end = datetime.datetime.strptime(train_end_str, "%Y-%m-%d")
        X, y, feature_names = self.generate_training_samples(market_data, bm_df, sector_map, t_start, t_end)

        if len(X) == 0:
            logger.error("No training samples generated")
            return False

        self.features = feature_names

        if optimize:
            from services.ml.hyper_optimizer import HyperOptimizer

            optimizer = HyperOptimizer(n_trials=20, objective=self.params.get("objective", "regression"))
            best_params = optimizer.optimize(X, y, feature_names)
            self.params.update(best_params)
            logger.info(
                f"Optuna params: lr={self.params.get('learning_rate', 0):.3f}, leaves={self.params.get('num_leaves', 0)}"
            )

        train_params = dict(self.params)
        if train_params.get("objective") == "lambdarank":
            train_data = lgb.Dataset(X, label=y, feature_name=feature_names, group=[len(X)])
        else:
            train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
        if self.has_gpu:
            train_params["device"] = "gpu"
        try:
            self.model = lgb.train(train_params, train_data, num_boost_round=100)
        except Exception:
            train_params.pop("device", None)
            self.model = lgb.train(train_params, train_data, num_boost_round=100)
        logger.info(f"Model trained on {len(X)} samples")
        self._save_model()
        return True

    @otel_trace("alpha_engine.predict")
    def predict(self, market_data, bm_df, sector_map, target_date_str: str) -> Any:
        """Otomatik eklendi."""
        if not self.model:
            raise ValueError("Model not trained")

        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d")
        start_date_dt = target_date - datetime.timedelta(days=400)

        snap_md = {}
        for t, df in market_data.items():
            if "Date" in df.columns:
                sub_df = df.filter((pl.col("Date") >= start_date_dt) & (pl.col("Date") <= target_date))
                if len(sub_df) >= 120:
                    snap_md[t] = sub_df

        if "Date" in bm_df.columns:
            snap_bm = bm_df.filter((pl.col("Date") >= start_date_dt) & (pl.col("Date") <= target_date))
        else:
            snap_bm = bm_df
        if len(snap_bm) < 120:
            raise ValueError("Insufficient benchmark data")

        features = compute_universe_features(snap_md, snap_bm, sector_map)

        if self.exclude_features:
            for ticker, feats in features.items():
                for exf in self.exclude_features:
                    feats.pop(exf, None)

        predictions = []
        for ticker, feats in features.items():
            if not feats:
                continue
            x_vec = np.array([[feats.get(k, 0.0) or 0.0 for k in self.features]])
            x_vec = np.nan_to_num(x_vec, nan=0.0, posinf=0.0, neginf=0.0)
            score = float(self.model.predict(x_vec)[0])
            predictions.append({"ticker": ticker, "score": score, "features": feats})

        predictions.sort(key=lambda x: x["score"], reverse=True)
        return predictions

    def _save_model(self, path: str = "data/alpha_engine_model.pkl") -> Any:
        """Otomatik eklendi."""
        if self.model is None:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "model": self.model,
                "features": self.features,
                "params": self.params,
                "exclude_features": self.exclude_features,
                "trained_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "feature_hash": hashlib.sha256("|".join(sorted(self.features)).encode()).hexdigest()[:16],
            }
            safe_pickle_dump(payload, path)
            logger.info("AlphaEngine model saved", path=path, features=len(self.features))
        except Exception as e:
            logger.warning("Failed to save AlphaEngine model", error=str(e))

    def _load_model(self, path: str = "data/alpha_engine_model.pkl", max_age_hours: int = 24) -> bool:
        """Otomatik eklendi."""
        if not Path(path).exists():
            return False
        try:
            payload = safe_pickle_load(path)
            trained_at = datetime.datetime.fromisoformat(payload["trained_at"])
            if trained_at.tzinfo is None:
                trained_at = trained_at.replace(tzinfo=datetime.UTC)
            age_hours = (datetime.datetime.now(datetime.UTC) - trained_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                return False
            current_hash = hashlib.sha256("|".join(sorted(payload["features"])).encode()).hexdigest()[:16]
            if current_hash != payload.get("feature_hash"):
                logger.warning("AlphaEngine feature hash mismatch")
                return False
            self.model = payload["model"]
            self.features = payload["features"]
            self.params = payload["params"]
            self.exclude_features = payload.get("exclude_features", self.exclude_features)
            logger.info("AlphaEngine model loaded", path=path, features=len(self.features))
            return True
        except Exception as e:
            logger.warning("Failed to load AlphaEngine model", error=str(e))
            return False

    @otel_trace("alpha_engine.run_daily_pipeline")
    def run_daily_pipeline(self, date: str) -> Any:
        """Otomatik eklendi."""
        end_date_dt = datetime.datetime.strptime(date, "%Y-%m-%d")
        start_date_dt = end_date_dt - datetime.timedelta(days=400)

        if self._load_model():
            logger.info("Using cached AlphaEngine model")
        else:
            market_data, bm_df, sector_map = self.fetch_data(
                start_date_dt.strftime("%Y-%m-%d"), end_date_dt.strftime("%Y-%m-%d")
            )
            success = self.train(market_data, bm_df, sector_map, start_date_dt.strftime("%Y-%m-%d"), date)
            if not success:
                return None

        market_data, bm_df, sector_map = self.fetch_data(
            start_date_dt.strftime("%Y-%m-%d"), end_date_dt.strftime("%Y-%m-%d")
        )
        return self.predict(market_data, bm_df, sector_map, date)
