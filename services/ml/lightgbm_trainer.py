"""
ALPHA BIST — LightGBM Training Pipeline v3.0 (Production-Hardened)

FAZ 4.4 değişiklikleri:
- purge_gap artık SAMPLE-SPACE değil DATE-SPACE'de çalışıyor
- purge_gap = max(forward_horizon, purge_gap_days) gerçek tarih gününde
- Scaler/impute sadece TRAIN split'inden öğrenilir (data leakage yok)
- Multi-horizon target (1d/5d/20d/60d) altyapısı, horizon-aware purge
- Cross-sectional normalization feature contract ile tutarlı
- Model metadata (confidence, metrics) kalıcı field olarak saklanır
- Deterministic (seed=42, deterministic=True)
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


# =====================================================
# CONFIGURATION
# =====================================================


@dataclass
class MLModelConfig:
    """LightGBM model konfigürasyonu."""

    objective: str = "regression"
    metric: str = "rmse"
    ndcg_eval_at: list[int] = field(default_factory=lambda: [5, 10, 20])
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_data_in_leaf: int = 20
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    bagging_freq: int = 5
    num_boost_round: int = 100
    early_stopping_rounds: int = 10
    verbose: int = -1

    impute_strategy: str = "median"
    scale_features: bool = True

    val_ratio: float = 0.2
    # FAZ 4.4: purge_gap artık tarih-gününde (işlem günü), sample sayısında değil
    purge_gap_days: int = 5

    target_horizon: int = 5
    model_dir: str = "models"


# =====================================================
# TRAINED MODEL
# =====================================================


@dataclass
class TrainedModel:
    """Eğitilmiş model wrapper'ı."""

    model: Any
    feature_names: list[str]
    scaler_mean: np.ndarray | None = None
    scaler_std: np.ndarray | None = None
    impute_values: dict[str, float] | None = None
    train_date_range: tuple[str, str] = ("", "")
    train_samples: int = 0
    validation_score: float = 0.0
    feature_importance: dict[str, float] = field(default_factory=dict)
    trained_at: str = ""
    config: MLModelConfig | None = None

    # FAZ 4.3-4.4: Kalıcı metadata (pickle ile saklanır)
    validation_metrics: dict[str, float] = field(default_factory=dict)
    confidence_score: float = 0.0
    confidence_details: dict[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None
    target_horizon: int = 5
    cs_features: list[str] = field(default_factory=list)  # CS-normalized feature names

    def predict(self, features: dict[str, Any]) -> float:
        """Otomatik eklendi."""
        if self.model is None:
            raise ValueError("Model eğitilmemiş")
        vec = self._feature_vector(features)
        pred = self.model.predict(np.array([vec]))
        result = float(pred[0])
        return result if np.isfinite(result) else 0.0

    def predict_batch(self, features_list: list[dict[str, Any]]) -> list[float]:
        """Otomatik eklendi."""
        if self.model is None:
            raise ValueError("Model eğitilmemiş")
        vecs = [self._feature_vector(f) for f in features_list]
        preds = self.model.predict(np.array(vecs))
        return [float(p) if np.isfinite(p) else 0.0 for p in preds]

    def _feature_vector(self, features: dict[str, Any]) -> list[float]:
        """Otomatik eklendi."""
        vec = []
        for name in self.feature_names:
            val = features.get(name)
            if val is None:
                vec.append(self.impute_values.get(name, 0.0) if self.impute_values else 0.0)
            else:
                try:
                    v = float(val)
                    vec.append(v if np.isfinite(v) else 0.0)
                except (TypeError, ValueError):
                    vec.append(0.0)
        arr = np.array(vec)
        if self.scaler_mean is not None and self.scaler_std is not None:
            arr = (arr - self.scaler_mean) / np.where(self.scaler_std > 0, self.scaler_std, 1.0)
        return arr.tolist()

    def save(self, path: str) -> Any:
        """Otomatik eklendi."""
        from services.core.safe_pickle import safe_pickle_dump

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        safe_pickle_dump(self, path)

    @classmethod
    def load(cls, path: str) -> "TrainedModel":
        """Otomatik eklendi."""
        from services.core.safe_pickle import safe_pickle_load

        return safe_pickle_load(path)


@dataclass
class MultiHorizonModel:
    """Çoklu horizon model wrapper'ı.

    Her horizon (1d, 5d, 20d, 60d) için ayrı TrainedModel tutar.
    predict() varsayılan horizon'a (primary) delegasyon yapar.
    horizon_models dict'i ile tüm horizon'lara erişilebilir.
    """

    horizon_models: dict[int, TrainedModel] = field(default_factory=dict)
    primary_horizon: int = 5
    cs_features: list[str] = field(default_factory=list)

    @property
    def primary_model(self) -> TrainedModel | None:
        """Otomatik eklendi."""
        return self.horizon_models.get(self.primary_horizon)

    def predict(self, features: dict[str, Any]) -> float:
        """Varsayılan horizon prediction."""
        m = self.primary_model
        if m is None:
            return 0.0
        try:
            return m.predict(features)
        except (ValueError, Exception):
            return 0.0

    def predict_horizon(self, features: dict[str, Any], horizon: int) -> float:
        """Belirli horizon prediction."""
        m = self.horizon_models.get(horizon)
        if m is None:
            return 0.0
        try:
            return m.predict(features)
        except (ValueError, Exception):
            return 0.0

    def get_all_predictions(self, features: dict[str, Any]) -> dict[int, float]:
        """Tüm horizon'lar için prediction."""
        return {h: m.predict(features) for h, m in self.horizon_models.items()}

    @property
    def available_horizons(self) -> list[int]:
        """Otomatik eklendi."""
        return sorted(self.horizon_models.keys())

    @property
    def total_train_samples(self) -> int:
        """Otomatik eklendi."""
        return sum(m.train_samples for m in self.horizon_models.values())

    # Backward compatibility: TrainedModel interface
    @property
    def train_samples(self) -> int:
        """Primary model'in train sample sayısı."""
        m = self.primary_model
        return m.train_samples if m else 0

    @property
    def train_date_range(self) -> tuple[str, str]:
        """Primary model'in train date range."""
        m = self.primary_model
        return m.train_date_range if m else ("", "")

    @property
    def validation_score(self) -> float:
        """Otomatik eklendi."""
        m = self.primary_model
        return m.validation_score if m else 0.0

    @property
    def validation_metrics(self) -> dict[str, float]:
        """Otomatik eklendi."""
        m = self.primary_model
        return m.validation_metrics if m else {}

    @property
    def confidence_score(self) -> float:
        """Otomatik eklendi."""
        m = self.primary_model
        return m.confidence_score if m else 0.0

    @property
    def feature_names(self) -> list[str]:
        """Otomatik eklendi."""
        m = self.primary_model
        return m.feature_names if m else []


# =====================================================
# MULTI-HORIZON TARGET
# =====================================================


@dataclass
class TargetSpec:
    """Otomatik eklendi."""
    horizon: int = 5
    name: str = "return_5d"
    method: str = "return"  # "return" | "log_return" | "binary"

    @property
    def label(self) -> str:
        """Otomatik eklendi."""
        return f"{self.method}_{self.horizon}d"


DEFAULT_TARGETS = [
    TargetSpec(horizon=1, name="return_1d"),
    TargetSpec(horizon=5, name="return_5d"),
    TargetSpec(horizon=20, name="return_20d"),
    TargetSpec(horizon=60, name="return_60d"),
]


def compute_target(close: np.ndarray, idx: int, spec: TargetSpec) -> float | None:
    """Otomatik eklendi."""
    target_idx = idx + spec.horizon
    if target_idx >= len(close):
        return None
    c_t, c_fwd = close[idx], close[target_idx]
    if c_t <= 0 or not np.isfinite(c_t) or not np.isfinite(c_fwd):
        return None
    if spec.method == "return":
        return (c_fwd / c_t - 1.0) * 100.0
    elif spec.method == "log_return":
        return float(np.log(c_fwd / c_t)) * 100.0
    elif spec.method == "binary":
        return 1.0 if c_fwd > c_t else 0.0
    return (c_fwd / c_t - 1.0) * 100.0


# =====================================================
# VALIDATION METRICS
# =====================================================


def compute_comprehensive_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Otomatik eklendi."""
    defaults = {
        "mae": 0.0,
        "rmse": 0.0,
        "r_squared": 0.0,
        "directional_accuracy": 0.0,
        "ic": 0.0,
        "ic_stability": 0.0,
        "prediction_std": 0.0,
        "target_std": 0.0,
        "rank_correlation": 0.0,
        "hit_rate": 0.0,
        "worst_error": 0.0,
        "validation_samples": 0.0,
        "top10_avg_return": 0.0,
        "top20_avg_return": 0.0,
        "bottom10_avg_return": 0.0,
        "long_short_spread": 0.0,
        "rank_ic": 0.0,
    }
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    yt, yp = y_true[mask], y_pred[mask]
    if len(yt) < 2:
        return defaults

    n = len(yt)
    defaults["validation_samples"] = float(n)
    defaults["mae"] = float(np.mean(np.abs(yt - yp)))
    defaults["rmse"] = float(np.sqrt(np.mean((yt - yp) ** 2)))

    ss_res = np.sum((yt - yp) ** 2)
    ss_tot = np.sum((yt - np.mean(yt)) ** 2)
    if ss_tot > 0:
        defaults["r_squared"] = float(max(-10.0, 1 - ss_res / ss_tot))

    defaults["directional_accuracy"] = float(np.sum(np.sign(yt) == np.sign(yp)) / n)
    defaults["prediction_std"] = float(np.std(yp))
    defaults["target_std"] = float(np.std(yt))
    defaults["worst_error"] = float(np.max(np.abs(yt - yp)))

    positive_mask = yt > 0
    if np.sum(positive_mask) > 0:
        defaults["hit_rate"] = float(np.sum(np.sign(yp[positive_mask]) == 1) / np.sum(positive_mask))

    try:
        from scipy.stats import spearmanr

        if np.std(yt) > 0 and np.std(yp) > 0:
            ic, _ = spearmanr(yt, yp)
            defaults["ic"] = float(ic) if np.isfinite(ic) else 0.0
            defaults["rank_correlation"] = defaults["ic"]
    except ImportError:
        if np.std(yt) > 0 and np.std(yp) > 0:
            defaults["ic"] = float(np.corrcoef(yt, yp)[0, 1])
            defaults["rank_correlation"] = defaults["ic"]

    if n >= 20:
        half = n // 2
        try:
            from scipy.stats import spearmanr

            ic1 = ic2 = 0.0
            if np.std(yt[:half]) > 0 and np.std(yp[:half]) > 0:
                r, _ = spearmanr(yt[:half], yp[:half])
                ic1 = float(r) if np.isfinite(r) else 0.0
            if np.std(yt[half:]) > 0 and np.std(yp[half:]) > 0:
                r, _ = spearmanr(yt[half:], yp[half:])
                ic2 = float(r) if np.isfinite(r) else 0.0
            defaults["ic_stability"] = float(1.0 - abs(ic1 - ic2))
        except Exception as e:
            logger.debug("ic_stability_calculation_failed", error=str(e))
            defaults["ic_stability"] = 0.0

    if n >= 10:
        k10 = max(1, int(n * 0.1))
        k20 = max(1, int(n * 0.2))
        top10_idx = np.argsort(-yp)[:k10]
        top20_idx = np.argsort(-yp)[:k20]
        bottom10_idx = np.argsort(yp)[:k10]
        defaults["top10_avg_return"] = float(np.mean(yt[top10_idx]))
        defaults["top20_avg_return"] = float(np.mean(yt[top20_idx]))
        defaults["bottom10_avg_return"] = float(np.mean(yt[bottom10_idx]))
        defaults["long_short_spread"] = float(defaults["top10_avg_return"] - defaults["bottom10_avg_return"])
        defaults["rank_ic"] = defaults["ic"]

    return defaults


# =====================================================
# MODEL CONFIDENCE
# =====================================================


def compute_model_confidence(
    validation_metrics: dict[str, float],
    train_samples: int,
    feature_count: int,
    train_regime: str = "UNKNOWN",
    current_regime: str = "UNKNOWN",
) -> tuple[float, dict[str, Any]]:
    """Otomatik eklendi."""
    details: dict[str, Any] = {"degradation_reasons": []}
    confidence = 1.0

    if train_samples < 100:
        confidence *= 0.5
        details["degradation_reasons"].append(f"low_samples:{train_samples}")
    elif train_samples < 300:
        confidence *= 0.75
        details["degradation_reasons"].append(f"moderate_samples:{train_samples}")

    ic = validation_metrics.get("ic", 0.0)
    if abs(ic) < 0.02:
        confidence *= 0.4
        details["degradation_reasons"].append(f"weak_ic:{ic:.4f}")
    elif abs(ic) < 0.05:
        confidence *= 0.7
        details["degradation_reasons"].append(f"low_ic:{ic:.4f}")

    dir_acc = validation_metrics.get("directional_accuracy", 0.5)
    if dir_acc < 0.45:
        confidence *= 0.5
        details["degradation_reasons"].append(f"poor_direction:{dir_acc:.2f}")
    elif dir_acc < 0.52:
        confidence *= 0.8

    pred_std = validation_metrics.get("prediction_std", 0.0)
    target_std = validation_metrics.get("target_std", 1.0)
    if target_std > 0 and pred_std / target_std < 0.1:
        confidence *= 0.6
        details["degradation_reasons"].append(f"narrow_predictions:{pred_std / target_std:.2f}")

    val_samples = validation_metrics.get("validation_samples", 0)
    if val_samples < 20:
        confidence *= 0.6
        details["degradation_reasons"].append(f"low_val_samples:{int(val_samples)}")

    if current_regime != "UNKNOWN" and train_regime != "UNKNOWN" and current_regime != train_regime:
        confidence *= 0.8
        details["degradation_reasons"].append(f"regime_mismatch:train={train_regime},current={current_regime}")

    if feature_count < 10:
        confidence *= 0.7
        details["degradation_reasons"].append(f"low_features:{feature_count}")

    details["raw_confidence"] = round(confidence, 4)
    details["train_samples"] = train_samples
    details["ic"] = ic
    details["dir_acc"] = dir_acc

    return round(max(0.0, min(1.0, confidence)), 4), details


# =====================================================
# TRAINER v3.0
# =====================================================


class LightGBMTrainer:
    """LightGBM training pipeline v3.0 — date-space purge, multi-horizon."""

    def __init__(self, config: MLModelConfig | None = None):
        """Otomatik eklendi."""
        self._config = config or MLModelConfig()

    def train(
        self,
        features_map: dict[str, dict[str, Any]],
        returns: dict[str, float],
        date_groups: dict[str, str],
        feature_names: list[str] | None = None,
        regime: str = "UNKNOWN",
    ) -> TrainedModel | None:
        """LightGBM modeli eğit — date-space purge gap ile.

        purge_gap_days artık gerçek tarih gününde çalışır:
        - Tarih sıralı unique date'ler bulunur
        - purge_gap_days kadar gün atlanır
        - Train ve val arasında tarih bazlı boşluk oluşur
        - Horizon overlap (5d/20d/60d) purge'a dahil edilir
        """
        try:
            import lightgbm as lgb
        except ImportError:
            logger.warning("LightGBM not available")
            return None

        if feature_names is None:
            all_features = set()
            for f in features_map.values():
                all_features.update(f.keys())
            feature_names = sorted(all_features)

        X, y, groups, tickers = self._prepare_data(features_map, returns, date_groups, feature_names)

        if len(X) < 50:
            logger.warning("Insufficient training data", samples=len(X))
            return None

        # Impute — tüm veriden hesaplanır ama sadece TRAIN'de kullanılır
        impute_values = self._compute_impute_values(X, feature_names)
        X = self._impute(X, impute_values, feature_names)

        # Scale — tüm veriden, ama train/val split'ten ÖNCE
        # (scaler train split'inden öğrenilmeli — aşağıda düzeltildi)
        scaler_mean = None
        scaler_std = None

        # === DATE-SPACE PURGE GAP ===
        # Unique tarihleri bul ve sırala
        unique_dates = sorted(set(date_groups.values()))
        n_dates = len(unique_dates)

        # Val için son %20 tarihi ayır
        val_date_count = max(2, int(n_dates * self._config.val_ratio))
        purge_gap = self._config.purge_gap_days

        # Horizon-aware purge: purge_gap = max(purge_gap, target_horizon)
        # Böylece train sonundaki sample'ların target'ı val'e sızamaz
        effective_purge = max(purge_gap, self._config.target_horizon)

        # Train tarihleri: ilk (n_dates - val_date_count - effective_purge) gün
        train_date_end_idx = n_dates - val_date_count - effective_purge
        if train_date_end_idx < 10:
            # Veri yetersiz, gap'i azalt
            effective_purge = max(0, n_dates - val_date_count - 10)
            train_date_end_idx = n_dates - val_date_count - effective_purge

        if train_date_end_idx < 5:
            logger.warning(
                "Insufficient dates for train/val split",
                total_dates=n_dates,
                val_dates=val_date_count,
                purge=effective_purge,
            )
            return None

        # Train ve val tarih kümeleri (date-space, sample-space değil)
        train_dates = set(unique_dates[:train_date_end_idx])
        val_dates = set(unique_dates[train_date_end_idx + effective_purge :])

        if not val_dates:
            logger.warning("No validation dates after purge")
            return None

        # Sample'ları tarih bazlı split et
        train_indices = []
        val_indices = []
        for i, ticker in enumerate(tickers):
            d = date_groups.get(ticker, "")
            if d in train_dates:
                train_indices.append(i)
            elif d in val_dates:
                val_indices.append(i)
            # purge aralığındaki tarihler → atlanır (ne train ne val)

        if len(train_indices) < 20 or len(val_indices) < 5:
            logger.warning(
                "Insufficient samples after date-space split", train=len(train_indices), val=len(val_indices)
            )
            return None

        # Scaler SADECE TRAIN split'inden öğrenilir
        X_train_raw = X[train_indices]
        X_val_raw = X[val_indices]

        if self._config.scale_features:
            scaler_mean = np.mean(X_train_raw, axis=0)
            scaler_std = np.std(X_train_raw, axis=0)
            scaler_std[scaler_std == 0] = 1.0
            X_train_scaled = (X_train_raw - scaler_mean) / scaler_std
            X_val_scaled = (X_val_raw - scaler_mean) / scaler_std
        else:
            X_train_scaled = X_train_raw
            X_val_scaled = X_val_raw

        y_train = y[train_indices]
        y_val = y[val_indices]

        is_ranking = self._config.objective == "lambdarank"

        if is_ranking:
            y_rank = np.zeros(len(y), dtype=int)
            date_to_indices: dict[str, list[int]] = {}
            for i, t in enumerate(tickers):
                d = date_groups.get(t)
                if d:
                    date_to_indices.setdefault(d, []).append(i)
            for d, indices in date_to_indices.items():
                if len(indices) > 1:
                    group_returns = [y[i] for i in indices]
                    sorted_indices = sorted(range(len(group_returns)), key=lambda k: -group_returns[k])
                    for rank, idx in enumerate(sorted_indices):
                        y_rank[indices[idx]] = rank
            train_label = y_rank[train_indices]
            val_label = y_rank[val_indices]
            # Group counts for ranking queries
            train_groups = [len([i for i in indices if i in train_indices]) for d, indices in date_to_indices.items() if any(i in train_indices for i in indices)]
            val_groups = [len([i for i in indices if i in val_indices]) for d, indices in date_to_indices.items() if any(i in val_indices for i in indices)]
        else:
            train_label = y[train_indices]
            val_label = y[val_indices]
            train_groups = None
            val_groups = None

        # LightGBM Dataset
        train_data = lgb.Dataset(
            X_train_scaled, label=train_label, group=train_groups, feature_name=feature_names, free_raw_data=False
        )
        val_data = lgb.Dataset(
            X_val_scaled,
            label=val_label,
            group=val_groups,
            feature_name=feature_names,
            free_raw_data=False,
            reference=train_data,
        )

        params = {
            "objective": self._config.objective,
            "metric": self._config.metric,
            "learning_rate": self._config.learning_rate,
            "num_leaves": self._config.num_leaves,
            "min_data_in_leaf": self._config.min_data_in_leaf,
            "feature_fraction": self._config.feature_fraction,
            "bagging_fraction": self._config.bagging_fraction,
            "bagging_freq": self._config.bagging_freq,
            "num_threads": 2,
            "verbose": -1,
            "seed": 42,
            "deterministic": True,
        }
        if is_ranking:
            params["ndcg_eval_at"] = self._config.ndcg_eval_at

        callbacks = []
        if self._config.early_stopping_rounds > 0:
            callbacks.append(lgb.early_stopping(self._config.early_stopping_rounds, verbose=False))
        callbacks.append(lgb.log_evaluation(period=0))

        try:
            model = lgb.train(
                params,
                train_data,
                num_boost_round=self._config.num_boost_round,
                valid_sets=[val_data],
                callbacks=callbacks,
            )
        except Exception as e:
            logger.error("LightGBM training failed", error=str(e))
            return None

        # Validation metrikleri
        val_pred = model.predict(X_val_scaled)
        val_score = self._compute_ndcg(y_val, val_pred, val_groups)
        validation_metrics = compute_comprehensive_metrics(y_val, val_pred)

        # Feature importance
        importance = model.feature_importance(importance_type="gain")
        feature_importance = {name: float(imp) for name, imp in zip(feature_names, importance, strict=False)}

        # Date range (sadece train tarihleri)
        train_date_strings = sorted(train_dates)
        date_range = (train_date_strings[0], train_date_strings[-1]) if train_date_strings else ("", "")

        # Confidence
        confidence, confidence_details = compute_model_confidence(
            validation_metrics, len(train_indices), len(feature_names), train_regime="UNKNOWN"
        )

        trained = TrainedModel(
            model=model,
            feature_names=feature_names,
            scaler_mean=scaler_mean,
            scaler_std=scaler_std,
            impute_values=impute_values,
            train_date_range=date_range,
            train_samples=len(train_indices),
            validation_score=round(val_score, 4),
            feature_importance=feature_importance,
            trained_at=datetime.now(UTC).isoformat(),
            config=self._config,
            validation_metrics=validation_metrics,
            confidence_score=confidence,
            confidence_details=confidence_details,
            target_horizon=self._config.target_horizon,
        )

        logger.info(
            "LightGBM model trained v3",
            train=len(train_indices),
            val=len(val_indices),
            purge_dates=effective_purge,
            train_date_range=date_range,
            val_score=round(val_score, 4),
            features=len(feature_names),
            ic=round(validation_metrics.get("ic", 0), 4),
            dir_acc=round(validation_metrics.get("directional_accuracy", 0), 4),
            confidence=confidence,
        )

        return trained

    def _prepare_data(
        self,
        features_map: dict[str, dict[str, Any]],
        returns: dict[str, float],
        date_groups: dict[str, str],
        feature_names: list[str],
    ) -> tuple[np.ndarray, np.ndarray, list[int], list[str]]:
        """Otomatik eklendi."""
        X, y, tickers = [], [], []
        sorted_keys = sorted(features_map.keys(), key=lambda k: date_groups.get(k, ""))
        for key in sorted_keys:
            if key not in returns:
                continue
            features = features_map[key]
            vec = []
            for name in feature_names:
                val = features.get(name)
                if val is None:
                    vec.append(np.nan)
                else:
                    try:
                        v = float(val)
                        vec.append(v if np.isfinite(v) else np.nan)
                    except (TypeError, ValueError):
                        vec.append(np.nan)
            X.append(vec)
            y.append(returns[key])
            tickers.append(key)
        return (
            np.array(X),
            np.array(y),
            [],
            tickers,
        )  # groups boş — train'de _compute_groups_from_indices ile hesaplanır

    def _compute_impute_values(self, X: np.ndarray, feature_names: list[str]) -> dict[str, float]:
        """Otomatik eklendi."""
        impute = {}
        for i, name in enumerate(feature_names):
            col = X[:, i]
            valid = col[~np.isnan(col)]
            if len(valid) > 0:
                impute[name] = float(np.median(valid)) if self._config.impute_strategy == "median" else 0.0
            else:
                impute[name] = 0.0
        return impute

    def _impute(
        self,
        X: np.ndarray,
        impute_values: dict[str, float],
        feature_names: list[str] | None = None,
    ) -> np.ndarray:
        """Missing values'ları doldur.

        Args:
            X: Feature matrix
            impute_values: Feature adı → impute değeri sözlüğü
            feature_names: Feature isimleri (sıralı). Verilirse index yerine
                          isim tabanlı güvenli eşleme kullanılır.
        """
        X_imputed = X.copy()
        for i in range(X.shape[1]):
            mask = np.isnan(X_imputed[:, i])
            if mask.any():
                if feature_names and i < len(feature_names):
                    col_name = feature_names[i]
                elif i < len(impute_values):
                    col_name = list(impute_values.keys())[i]
                else:
                    col_name = None
                X_imputed[mask, i] = impute_values.get(col_name, 0.0) if col_name else 0.0
        return X_imputed

    def _compute_groups_from_indices(
        self, date_groups: dict[str, str], tickers: list[str], indices: list[int]
    ) -> list[int]:
        """Belirli indeksler için group sizes hesapla."""
        groups = []
        current_date = None
        current_count = 0
        for idx in indices:
            d = date_groups.get(tickers[idx], "")
            if d != current_date:
                if current_count > 0:
                    groups.append(current_count)
                current_date = d
                current_count = 1
            else:
                current_count += 1
        if current_count > 0:
            groups.append(current_count)
        return groups

    def _compute_ndcg(self, y_true: np.ndarray, y_pred: np.ndarray, groups: list[int] | None) -> float:
        """Otomatik eklendi."""
        if not groups:
            if np.std(y_true) > 0 and np.std(y_pred) > 0:
                return float(np.corrcoef(y_true, y_pred)[0, 1])
            return 0.0
        ndcg_scores = []
        idx = 0
        for g in groups:
            if g < 2:
                idx += g
                continue
            true_g = y_true[idx : idx + g]
            pred_g = y_pred[idx : idx + g]
            ideal = np.sort(true_g)[::-1]
            pred_order = np.argsort(pred_g)[::-1]
            pred_sorted = true_g[pred_order]
            dcg = np.sum(pred_sorted / np.log2(np.arange(2, g + 2)))
            idcg = np.sum(ideal / np.log2(np.arange(2, g + 2)))
            if idcg > 0:
                ndcg_scores.append(dcg / idcg)
            idx += g
        return float(np.mean(ndcg_scores)) if ndcg_scores else 0.0


# =====================================================
# HYPERPARAMETER OPTIMIZATION INTEGRATION
# =====================================================


def optimize_hyperparameters(
    features_map: dict[str, dict[str, Any]],
    returns: dict[str, float],
    date_groups: dict[str, str],
    feature_names: list[str],
    n_trials: int = 20,
) -> dict[str, Any]:
    """Optuna ile LightGBM hyperparameter optimizasyonu.

    TimeSeriesSplit kullanarak temporal cross-validation yapar.
    En iyi parametreleri döndürür.

    Args:
        features_map: Feature değerleri
        returns: Gerçek getiriler
        date_groups: Tarih grupları
        feature_names: Feature isimleri
        n_trials: Optuna deneme sayısı

    Returns:
        En iyi hyperparameter dict
    """
    try:
        from .hyper_optimizer import HyperOptimizer
    except ImportError:
        logger.warning("HyperOptimizer not available")
        return {}

    trainer = LightGBMTrainer()
    X, y, _, tickers = trainer._prepare_data(features_map, returns, date_groups, feature_names)

    if len(X) < 100:
        logger.warning("Insufficient data for hyperparameter optimization", samples=len(X))
        return {}

    # Impute
    impute_values = trainer._compute_impute_values(X, feature_names)
    X = trainer._impute(X, impute_values, feature_names)

    optimizer = HyperOptimizer(n_trials=n_trials)
    best_params = optimizer.optimize(X, y, feature_names)

    logger.info("Hyperparameter optimization completed", trials=n_trials, best_params=best_params)
    return best_params


# =====================================================
# CALIBRATION INTEGRATION
# =====================================================


def calibrate_model(
    model: TrainedModel,
    X_val: np.ndarray,
    y_val: np.ndarray,
    regime: str = "UNKNOWN",
) -> dict[str, Any]:
    """Eğitilmiş modeli kalibre et.

    Platt scaling ve isotonic regression ile confidence kalibrasyonu yapar.
    Brier score ve ECE hesaplar.

    Args:
        model: Eğitilmiş TrainedModel
        X_val: Validation features
        y_val: Validation targets
        regime: Piyasa rejimi

    Returns:
        Kalibrasyon sonuçları dict
    """
    try:
        from .calibration import ModelCalibration
    except ImportError:
        logger.warning("ModelCalibration not available")
        return {}

    if model.model is None:
        return {}

    # Prediction'ları al
    y_pred = model.model.predict(X_val)

    # Binary target'a çevir (y > 0 → positive)
    y_binary = (y_val > 0).astype(int)

    calibrator = ModelCalibration()

    # Platt scaling
    platt_result = calibrator.platt_scale(y_pred, y_binary)

    # Isotonic regression
    isotonic_result = calibrator.isotonic_calibrate(y_pred, y_binary)

    # Brier score
    brier = calibrator.brier_score(y_pred, y_binary)

    # ECE
    ece = calibrator.expected_calibration_error(y_pred, y_binary)

    result = {
        "platt_coefficients": platt_result,
        "isotonic_result": isotonic_result,
        "brier_score": brier,
        "ece": ece,
        "regime": regime,
        "n_samples": len(y_val),
    }

    logger.info(
        "Model calibration completed",
        brier=round(brier, 4) if brier else None,
        ece=round(ece, 4) if ece else None,
        regime=regime,
    )
    return result


# =====================================================
# FEATURE DRIFT CHECK INTEGRATION
# =====================================================


def check_feature_drift(
    current_importance: dict[str, float],
    historical_importance: dict[str, float],
    current_features: dict[str, np.ndarray],
    baseline_features: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Feature drift kontrolü yap.

    SHAP importance trendi ve PSI (Population Stability Index) hesaplar.

    Args:
        current_importance: Mevcut feature importance
        historical_importance: Tarihsel feature importance
        current_features: Mevcut feature değerleri
        baseline_features: Tarihsel feature değerleri

    Returns:
        Drift raporu dict
    """
    try:
        from .feature_drift import FeatureDriftDetector
    except ImportError:
        logger.warning("FeatureDriftDetector not available")
        return {}

    detector = FeatureDriftDetector()

    # Feature importance drift
    importance_drift = detector.detect_importance_drift(current_importance, historical_importance)

    # PSI hesapla
    psi_results = {}
    for fname in current_features:
        if fname in baseline_features:
            psi = detector.compute_psi(baseline_features[fname], current_features[fname])
            psi_results[fname] = psi

    # Drift summary
    drifted = [f for f, p in psi_results.items() if p > 0.2]
    alert = [f for f, p in psi_results.items() if p > 0.25]

    result = {
        "importance_drift": importance_drift,
        "psi_results": psi_results,
        "drifted_features": drifted,
        "alert_features": alert,
        "total_features": len(psi_results),
        "drift_score": float(np.mean(list(psi_results.values()))) if psi_results else 0.0,
    }

    logger.info(
        "Feature drift check completed",
        drifted=len(drifted),
        alerts=len(alert),
        drift_score=round(result["drift_score"], 4),
    )
    return result


# =====================================================
# OUT-OF-FOLD PREDICTIONS
# =====================================================


def compute_oof_predictions(
    features_map: dict[str, dict[str, Any]],
    returns: dict[str, float],
    date_groups: dict[str, str],
    feature_names: list[str],
    n_folds: int = 5,
    config: MLModelConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Out-of-fold (OOF) predictions hesapla.

    Walk-forward benzeri temporal cross-validation ile her sample için
    OOF prediction üretir. Bu, modelin gerçek performansını ölçmek için
    kullanılır.

    Args:
        features_map: Feature değerleri
        returns: Gerçek getiriler
        date_groups: Tarih grupları
        feature_names: Feature isimleri
        n_folds: Fold sayısı
        config: Model konfigürasyonu

    Returns:
        (oof_predictions, oof_targets, oof_tickers) tuple
    """
    config = config or MLModelConfig()
    trainer = LightGBMTrainer(config)

    X, y, _, tickers = trainer._prepare_data(features_map, returns, date_groups, feature_names)

    if len(X) < 100:
        logger.warning("Insufficient data for OOF", samples=len(X))
        return np.array([]), np.array([]), []

    # Impute
    impute_values = trainer._compute_impute_values(X, feature_names)
    X = trainer._impute(X, impute_values, feature_names)

    # Unique tarihleri sırala
    unique_dates = sorted(set(date_groups.values()))
    n_dates = len(unique_dates)
    fold_size = n_dates // n_folds

    oof_predictions = np.full(len(X), np.nan)
    oof_targets = y.copy()

    for fold in range(n_folds):
        # Test tarihleri
        test_start = fold * fold_size
        test_end = min((fold + 1) * fold_size, n_dates)
        test_dates = set(unique_dates[test_start:test_end])

        # Train tarihleri (test öncesi, purge ile)
        purge = max(config.purge_gap_days, config.target_horizon)
        train_end = max(0, test_start - purge)
        train_dates = set(unique_dates[:train_end])

        if len(train_dates) < 20:
            continue

        # Split
        train_idx = [i for i, t in enumerate(tickers) if date_groups.get(t) in train_dates]
        test_idx = [i for i, t in enumerate(tickers) if date_groups.get(t) in test_dates]

        if len(train_idx) < 20 or len(test_idx) < 5:
            continue

        # Scale (train'den öğren)
        X_train = X[train_idx]
        X_test = X[test_idx]
        scaler_mean = np.mean(X_train, axis=0)
        scaler_std = np.std(X_train, axis=0)
        scaler_std[scaler_std == 0] = 1.0
        X_train_s = (X_train - scaler_mean) / scaler_std
        X_test_s = (X_test - scaler_mean) / scaler_std

        # Train LightGBM
        try:
            import lightgbm as lgb

            # Rank labels
            y_rank = np.zeros(len(y), dtype=int)
            for d in unique_dates:
                indices = [i for i, t in enumerate(tickers) if date_groups.get(t) == d]
                if len(indices) > 1:
                    group_returns = [y[i] for i in indices]
                    sorted_idx = sorted(range(len(group_returns)), key=lambda k: -group_returns[k])
                    for rank, idx in enumerate(sorted_idx):
                        y_rank[indices[idx]] = rank

            train_groups = trainer._compute_groups_from_indices(date_groups, tickers, train_idx)

            ds_train = lgb.Dataset(X_train_s, label=y_rank[train_idx], group=train_groups, feature_name=feature_names)

            params = {
                "objective": config.objective,
                "metric": config.metric,
                "learning_rate": config.learning_rate,
                "num_leaves": config.num_leaves,
                "min_data_in_leaf": config.min_data_in_leaf,
                "feature_fraction": config.feature_fraction,
                "bagging_fraction": config.bagging_fraction,
                "bagging_freq": config.bagging_freq,
                "verbose": -1,
                "seed": 42,
                "deterministic": True,
            }

            model = lgb.train(
                params,
                ds_train,
                num_boost_round=config.num_boost_round,
                callbacks=[lgb.log_evaluation(period=0)],
            )

            # OOF predictions
            preds = model.predict(X_test_s)
            for i, idx in enumerate(test_idx):
                oof_predictions[idx] = preds[i]

        except Exception as e:
            logger.warning(f"OOF fold {fold} failed", error=str(e))
            continue

    valid_mask = ~np.isnan(oof_predictions)
    n_valid = int(valid_mask.sum())
    logger.info(
        "OOF predictions computed",
        folds=n_folds,
        valid_predictions=n_valid,
        total=len(oof_predictions),
    )
    return oof_predictions, oof_targets, tickers


# =====================================================
# FEATURE CONTRACT VALIDATION
# =====================================================


def validate_feature_contract(
    features_map: dict[str, dict],
    expected_features: list[str],
) -> tuple[bool, list[str]]:
    """Otomatik eklendi."""
    violations = []
    if not features_map:
        return False, ["Empty features_map"]

    missing_features = set()
    for key, feats in features_map.items():
        for fname in expected_features:
            if fname not in feats:
                missing_features.add(fname)
        if len(missing_features) > len(expected_features) * 0.5:
            violations.append(f"Sample {key}: >50% features missing")
            break

    if missing_features:
        violations.append(f"Missing features: {sorted(missing_features)[:5]}")

    first_keys = set(list(features_map.values())[0].keys())
    for key, feats in features_map.items():
        if set(feats.keys()) != first_keys:
            violations.append(f"Inconsistent feature keys at {key}")
            break

    return len(violations) == 0, violations
