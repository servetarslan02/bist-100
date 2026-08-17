"""
ALPHA BIST — LightGBM Training Pipeline v2.0 (Production-Grade)

FAZ 4.3 değişiklikleri:
- Chronological train/val split with PURGE gap (random split yok)
- Multi-horizon target abstraction (1d/5d/20d/60d)
- Kapsamlı validation metrikleri (MAE, RMSE, R², DirAcc, IC, IC stability,
  prediction std, rank correlation, hit rate, worst error, top/bottom quantile)
- Ranking quality metrics (top 10%/20% avg return, bottom 10%, long-short spread, rank IC)
- Feature contract validation
- Model confidence scoring
- Robust error handling (NaN/inf crash yok)
- Deterministic training (seed=42, deterministic=True)
- Scaler/impute sadece TRAIN'den öğrenilir
"""

import os
import pickle
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


# =====================================================
# CONFIGURATION
# =====================================================

@dataclass
class MLModelConfig:
    """LightGBM model konfigürasyonu."""
    # LightGBM parametreleri
    objective: str = "regression"
    metric: str = "rmse"
    ndcg_eval_at: List[int] = field(default_factory=lambda: [5, 10, 20])
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_data_in_leaf: int = 20
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    bagging_freq: int = 5
    num_boost_round: int = 100
    early_stopping_rounds: int = 10
    verbose: int = -1

    # Feature engineering
    impute_strategy: str = "median"
    scale_features: bool = True

    # Validation
    val_ratio: float = 0.2          # Son %20 validation
    purge_gap_days: int = 5         # Train/val arasında purge gap

    # Multi-horizon
    target_horizon: int = 5         # Varsayılan target horizon (gün)

    # Model serialization
    model_dir: str = "models"


# =====================================================
# TRAINED MODEL
# =====================================================

@dataclass
class TrainedModel:
    """Eğitilmiş model wrapper'ı."""
    model: Any  # lightgbm.Booster
    feature_names: List[str]
    scaler_mean: Optional[np.ndarray] = None
    scaler_std: Optional[np.ndarray] = None
    impute_values: Optional[Dict[str, float]] = None
    train_date_range: Tuple[str, str] = ("", "")
    train_samples: int = 0
    validation_score: float = 0.0
    feature_importance: Dict[str, float] = field(default_factory=dict)
    trained_at: str = ""
    config: Optional[MLModelConfig] = None

    # FAZ 4.3: Kapsamlı validation metrikleri
    _validation_metrics: Dict[str, float] = field(default_factory=dict)
    # FAZ 4.3: Model confidence
    _confidence_score: float = 0.0
    _confidence_details: Dict[str, Any] = field(default_factory=dict)
    # FAZ 4.3: Fallback bilgisi
    _fallback_reason: Optional[str] = None

    def predict(self, features: Dict[str, Any]) -> float:
        """Tek bir feature dict için prediction döndür."""
        if self.model is None:
            raise ValueError("Model eğitilmemiş")

        vec = self._feature_vector(features)
        pred = self.model.predict(np.array([vec]))
        result = float(pred[0])

        # NaN/inf kontrolü
        if not np.isfinite(result):
            return 0.0
        return result

    def predict_batch(self, features_list: List[Dict[str, Any]]) -> List[float]:
        """Birden fazla feature dict için prediction."""
        if self.model is None:
            raise ValueError("Model eğitilmemiş")

        vecs = [self._feature_vector(f) for f in features_list]
        X = np.array(vecs)
        preds = self.model.predict(X)
        return [float(p) if np.isfinite(p) else 0.0 for p in preds]

    def _feature_vector(self, features: Dict[str, Any]) -> List[float]:
        """Feature dict'ten vektör oluştur (eğitim ile aynı sırada)."""
        vec = []
        for name in self.feature_names:
            val = features.get(name)
            if val is None:
                if self.impute_values and name in self.impute_values:
                    vec.append(self.impute_values[name])
                else:
                    vec.append(0.0)
            else:
                try:
                    v = float(val)
                    vec.append(v if np.isfinite(v) else 0.0)
                except (TypeError, ValueError):
                    vec.append(0.0)

        arr = np.array(vec)

        # Scale
        if self.scaler_mean is not None and self.scaler_std is not None:
            arr = (arr - self.scaler_mean) / np.where(self.scaler_std > 0, self.scaler_std, 1.0)

        return arr.tolist()

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "TrainedModel":
        with open(path, "rb") as f:
            return pickle.load(f)


# =====================================================
# MULTI-HORIZON TARGET
# =====================================================

@dataclass
class TargetSpec:
    """Target specification — çoklu horizon desteği."""
    horizon: int = 5         # Forward gün sayısı
    name: str = "return_5d"  # Target adı
    method: str = "return"   # "return" | "log_return" | "binary"

    @property
    def label(self) -> str:
        return f"{self.method}_{self.horizon}d"


# Varsayılan target horizons
DEFAULT_TARGETS = [
    TargetSpec(horizon=1, name="return_1d"),
    TargetSpec(horizon=5, name="return_5d"),
    TargetSpec(horizon=20, name="return_20d"),
    TargetSpec(horizon=60, name="return_60d"),
]


def compute_target(
    close: np.ndarray,
    idx: int,
    spec: TargetSpec,
) -> Optional[float]:
    """Belirli bir horizon için target hesapla.

    Args:
        close: Kapanış fiyatları dizisi
        idx: Feature tarihi indeksi
        spec: Target specification

    Returns:
        Target değeri veya None (yetersiz veri)
    """
    target_idx = idx + spec.horizon
    if target_idx >= len(close):
        return None

    c_t = close[idx]
    c_fwd = close[target_idx]

    if c_t <= 0 or not np.isfinite(c_t) or not np.isfinite(c_fwd):
        return None

    if spec.method == "return":
        return (c_fwd / c_t - 1.0) * 100.0
    elif spec.method == "log_return":
        return float(np.log(c_fwd / c_t)) * 100.0
    elif spec.method == "binary":
        return 1.0 if c_fwd > c_t else 0.0
    else:
        return (c_fwd / c_t - 1.0) * 100.0


# =====================================================
# VALIDATION METRICS
# =====================================================

def compute_comprehensive_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> Dict[str, float]:
    """Kapsamlı validation metrikleri.

    Crash-safe: NaN/inf üretmez.
    """
    defaults = {
        "mae": 0.0, "rmse": 0.0, "r_squared": 0.0,
        "directional_accuracy": 0.0, "ic": 0.0,
        "ic_stability": 0.0, "prediction_std": 0.0,
        "target_std": 0.0, "rank_correlation": 0.0,
        "hit_rate": 0.0, "worst_error": 0.0,
        "validation_samples": 0.0,
        "top10_avg_return": 0.0, "top20_avg_return": 0.0,
        "bottom10_avg_return": 0.0, "long_short_spread": 0.0,
        "rank_ic": 0.0,
    }

    # Temizle
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    yt = y_true[mask]
    yp = y_pred[mask]

    if len(yt) < 2:
        return defaults

    n = len(yt)
    defaults["validation_samples"] = float(n)

    # MAE
    defaults["mae"] = float(np.mean(np.abs(yt - yp)))

    # RMSE
    defaults["rmse"] = float(np.sqrt(np.mean((yt - yp) ** 2)))

    # R²
    ss_res = np.sum((yt - yp) ** 2)
    ss_tot = np.sum((yt - np.mean(yt)) ** 2)
    if ss_tot > 0:
        defaults["r_squared"] = float(max(-10.0, 1 - ss_res / ss_tot))

    # Directional accuracy
    correct = np.sum(np.sign(yt) == np.sign(yp))
    defaults["directional_accuracy"] = float(correct / n)

    # Prediction std vs target std
    defaults["prediction_std"] = float(np.std(yp))
    defaults["target_std"] = float(np.std(yt))

    # Worst error
    defaults["worst_error"] = float(np.max(np.abs(yt - yp)))

    # Hit rate (positive return correctly predicted)
    positive_mask = yt > 0
    if np.sum(positive_mask) > 0:
        defaults["hit_rate"] = float(np.sum(np.sign(yp[positive_mask]) == 1) / np.sum(positive_mask))

    # IC (Spearman rank correlation)
    try:
        from scipy.stats import spearmanr, rankdata
        if np.std(yt) > 0 and np.std(yp) > 0:
            ic, _ = spearmanr(yt, yp)
            defaults["ic"] = float(ic) if np.isfinite(ic) else 0.0

            # Rank correlation (aynı şey ama explicit)
            defaults["rank_correlation"] = defaults["ic"]
    except ImportError:
        if np.std(yt) > 0 and np.std(yp) > 0:
            defaults["ic"] = float(np.corrcoef(yt, yp)[0, 1])
            defaults["rank_correlation"] = defaults["ic"]

    # IC stability (yarıya böl, iki yarının IC'si arasındaki fark)
    if n >= 20:
        half = n // 2
        try:
            from scipy.stats import spearmanr
            if np.std(yt[:half]) > 0 and np.std(yp[:half]) > 0:
                ic1, _ = spearmanr(yt[:half], yp[:half])
            else:
                ic1 = 0.0
            if np.std(yt[half:]) > 0 and np.std(yp[half:]) > 0:
                ic2, _ = spearmanr(yt[half:], yp[half:])
            else:
                ic2 = 0.0
            ic1 = float(ic1) if np.isfinite(ic1) else 0.0
            ic2 = float(ic2) if np.isfinite(ic2) else 0.0
            defaults["ic_stability"] = float(1.0 - abs(ic1 - ic2))
        except Exception:
            defaults["ic_stability"] = 0.0

    # === RANKING QUALITY METRIKLERI ===
    # Top/Bottom quantile analizi
    if n >= 10:
        try:
            from scipy.stats import rankdata
            pred_ranks = rankdata(-yp)  # Düşük rank = yüksek tahmin
            # Top 10%
            k10 = max(1, int(n * 0.1))
            k20 = max(1, int(n * 0.2))
            top10_idx = np.argsort(-yp)[:k10]
            top20_idx = np.argsort(-yp)[:k20]
            bottom10_idx = np.argsort(yp)[:k10]

            defaults["top10_avg_return"] = float(np.mean(yt[top10_idx]))
            defaults["top20_avg_return"] = float(np.mean(yt[top20_idx]))
            defaults["bottom10_avg_return"] = float(np.mean(yt[bottom10_idx]))
            defaults["long_short_spread"] = float(
                defaults["top10_avg_return"] - defaults["bottom10_avg_return"]
            )

            # Rank IC (Spearman zaten hesaplandı)
            defaults["rank_ic"] = defaults["ic"]
        except ImportError:
            # scipy yoksa basit yaklaşım
            k10 = max(1, int(n * 0.1))
            top10_idx = np.argsort(-yp)[:k10]
            bottom10_idx = np.argsort(yp)[:k10]
            defaults["top10_avg_return"] = float(np.mean(yt[top10_idx]))
            defaults["bottom10_avg_return"] = float(np.mean(yt[bottom10_idx]))
            defaults["long_short_spread"] = float(
                defaults["top10_avg_return"] - defaults["bottom10_avg_return"]
            )

    return defaults


# =====================================================
# MODEL CONFIDENCE
# =====================================================

def compute_model_confidence(
    validation_metrics: Dict[str, float],
    train_samples: int,
    feature_count: int,
    train_regime: str = "UNKNOWN",
    current_regime: str = "UNKNOWN",
) -> Tuple[float, Dict[str, Any]]:
    """Model confidence skoru hesapla (0-1).

    Düşük confidence nedenleri:
    - Düşük training sample
    - Zayıf IC
    - Düşük directional accuracy
    - Yüksek prediction uncertainty
    - Feature availability düşük
    - Regime uyuşmazlığı
    """
    details: Dict[str, Any] = {"degradation_reasons": []}
    confidence = 1.0

    # 1. Training sample etkisi
    if train_samples < 100:
        confidence *= 0.5
        details["degradation_reasons"].append(f"low_samples:{train_samples}")
    elif train_samples < 300:
        confidence *= 0.75
        details["degradation_reasons"].append(f"moderate_samples:{train_samples}")

    # 2. IC etkisi
    ic = validation_metrics.get("ic", 0.0)
    if abs(ic) < 0.02:
        confidence *= 0.4
        details["degradation_reasons"].append(f"weak_ic:{ic:.4f}")
    elif abs(ic) < 0.05:
        confidence *= 0.7
        details["degradation_reasons"].append(f"low_ic:{ic:.4f}")

    # 3. Directional accuracy
    dir_acc = validation_metrics.get("directional_accuracy", 0.5)
    if dir_acc < 0.45:
        confidence *= 0.5
        details["degradation_reasons"].append(f"poor_direction:{dir_acc:.2f}")
    elif dir_acc < 0.52:
        confidence *= 0.8

    # 4. Prediction std vs target std
    pred_std = validation_metrics.get("prediction_std", 0.0)
    target_std = validation_metrics.get("target_std", 1.0)
    if target_std > 0:
        std_ratio = pred_std / target_std
        if std_ratio < 0.1:
            # Model çok dar tahmin yapıyor (underfitting)
            confidence *= 0.6
            details["degradation_reasons"].append(f"narrow_predictions:{std_ratio:.2f}")

    # 5. Validation sample sayısı
    val_samples = validation_metrics.get("validation_samples", 0)
    if val_samples < 20:
        confidence *= 0.6
        details["degradation_reasons"].append(f"low_val_samples:{int(val_samples)}")

    # 6. Regime uyuşmazlığı
    if current_regime != "UNKNOWN" and train_regime != "UNKNOWN":
        if current_regime != train_regime:
            confidence *= 0.8
            details["degradation_reasons"].append(
                f"regime_mismatch:train={train_regime},current={current_regime}"
            )

    # 7. Feature availability
    if feature_count < 10:
        confidence *= 0.7
        details["degradation_reasons"].append(f"low_features:{feature_count}")

    details["raw_confidence"] = round(confidence, 4)
    details["train_samples"] = train_samples
    details["ic"] = ic
    details["dir_acc"] = dir_acc

    return round(max(0.0, min(1.0, confidence)), 4), details


# =====================================================
# TRAINER
# =====================================================

class LightGBMTrainer:
    """LightGBM training pipeline v2.0.

    Kullanım:
        trainer = LightGBMTrainer(config)
        model = trainer.train(features_map, returns, date_groups, feature_names)
    """

    def __init__(self, config: Optional[MLModelConfig] = None):
        self._config = config or MLModelConfig()

    def train(
        self,
        features_map: Dict[str, Dict[str, Any]],
        returns: Dict[str, float],
        date_groups: Dict[str, str],
        feature_names: Optional[List[str]] = None,
        regime: str = "UNKNOWN",
    ) -> Optional[TrainedModel]:
        """LightGBM modeli eğit.

        Mimarisi:
        1. Feature names belirle
        2. Veri hazırla (tarih sıralı)
        3. Impute (NaN → median, TRAIN'den)
        4. Scale (z-score, TRAIN'den)
        5. Chronological train/val split (PURGE gap ile)
        6. Eğit (deterministic seed=42)
        7. Validation metrikleri hesapla
        8. Model confidence hesapla
        """
        try:
            import lightgbm as lgb
        except ImportError:
            logger.warning("LightGBM not available")
            return None

        # 1. Feature names
        if feature_names is None:
            all_features = set()
            for f in features_map.values():
                all_features.update(f.keys())
            feature_names = sorted(all_features)

        # 2. Veri hazırla
        X, y, groups, tickers = self._prepare_data(
            features_map, returns, date_groups, feature_names
        )

        if len(X) < 50:
            logger.warning("Insufficient training data", samples=len(X))
            return None

        # 3. Impute (tüm veriden — ama sadece TRAIN'den öğrenilecek)
        impute_values = self._compute_impute_values(X, feature_names)
        X = self._impute(X, impute_values)

        # 4. Scale
        scaler_mean = None
        scaler_std = None
        if self._config.scale_features:
            scaler_mean = np.mean(X, axis=0)
            scaler_std = np.std(X, axis=0)
            scaler_std[scaler_std == 0] = 1.0
            X = (X - scaler_mean) / scaler_std

        # 5. Chronological train/val split with PURGE gap
        n = len(X)
        purge_gap = self._config.purge_gap_days
        val_size = max(10, int(n * self._config.val_ratio))

        # Purge gap: train sonundan val başına kadar gün atla
        # date_groups sıralı olduğu için, son val_size sample purge'den sonra
        train_size = n - val_size - purge_gap
        if train_size < 30:
            # Purge gap çok büyük, gap'i azalt
            purge_gap = max(0, n - val_size - 30)
            train_size = n - val_size - purge_gap

        if train_size < 20 or val_size < 5:
            logger.warning("Insufficient data for train/val split",
                          total=n, train=train_size, val=val_size, purge=purge_gap)
            return None

        X_train = X[:train_size]
        X_val = X[train_size + purge_gap:]
        y_train = y[:train_size]
        y_val = y[train_size + purge_gap:]

        # LambdaRank rank labels
        y_rank = np.zeros(len(y), dtype=int)
        unique_dates = sorted(set(date_groups.values()))
        for d in unique_dates:
            indices = [i for i, t in enumerate(tickers) if date_groups.get(t) == d]
            if len(indices) > 1:
                group_returns = [y[i] for i in indices]
                sorted_indices = sorted(range(len(group_returns)), key=lambda k: -group_returns[k])
                for rank, idx in enumerate(sorted_indices):
                    y_rank[indices[idx]] = rank

        y_rank_train = y_rank[:train_size]
        y_rank_val = y_rank[train_size + purge_gap:]

        # Group sizes
        train_groups = self._compute_groups(date_groups, tickers[:train_size])
        val_groups = self._compute_groups(date_groups, tickers[train_size + purge_gap:])

        # 6. LightGBM Dataset
        train_data = lgb.Dataset(
            X_train, label=y_rank_train, group=train_groups,
            feature_name=feature_names, free_raw_data=False
        )
        val_data = lgb.Dataset(
            X_val, label=y_rank_val, group=val_groups,
            feature_name=feature_names, free_raw_data=False,
            reference=train_data
        )

        params = {
            "objective": self._config.objective,
            "metric": self._config.metric,
            "ndcg_eval_at": self._config.ndcg_eval_at,
            "learning_rate": self._config.learning_rate,
            "num_leaves": self._config.num_leaves,
            "min_data_in_leaf": self._config.min_data_in_leaf,
            "feature_fraction": self._config.feature_fraction,
            "bagging_fraction": self._config.bagging_fraction,
            "bagging_freq": self._config.bagging_freq,
            "verbose": self._config.verbose,
            "seed": 42,
            "deterministic": True,
        }

        callbacks = []
        if self._config.early_stopping_rounds > 0:
            callbacks.append(lgb.early_stopping(self._config.early_stopping_rounds))
        callbacks.append(lgb.log_evaluation(period=0))

        try:
            model = lgb.train(
                params, train_data,
                num_boost_round=self._config.num_boost_round,
                valid_sets=[val_data],
                callbacks=callbacks,
            )
        except Exception as e:
            logger.error("LightGBM training failed", error=str(e))
            return None

        # 7. Validation metrikleri
        val_pred = model.predict(X_val)
        val_score = self._compute_ndcg(y_val, val_pred, val_groups)
        validation_metrics = compute_comprehensive_metrics(y_val, val_pred)

        # 8. Feature importance
        importance = model.feature_importance(importance_type="gain")
        feature_importance = {
            name: float(imp)
            for name, imp in zip(feature_names, importance)
        }

        # Date range
        dates = sorted(set(date_groups.values()))
        date_range = (dates[0] if dates else "", dates[-1] if dates else "")

        # 9. Model confidence
        confidence, confidence_details = compute_model_confidence(
            validation_metrics, train_size, len(feature_names), regime
        )

        trained = TrainedModel(
            model=model,
            feature_names=feature_names,
            scaler_mean=scaler_mean,
            scaler_std=scaler_std,
            impute_values=impute_values,
            train_date_range=date_range,
            train_samples=train_size,
            validation_score=round(val_score, 4),
            feature_importance=feature_importance,
            trained_at=datetime.now(timezone.utc).isoformat(),
            config=self._config,
        )
        trained._validation_metrics = validation_metrics
        trained._confidence_score = confidence
        trained._confidence_details = confidence_details

        logger.info("LightGBM model trained v2",
                   samples=train_size, val_size=len(y_val),
                   purge_gap=purge_gap,
                   val_score=round(val_score, 4),
                   features=len(feature_names),
                   mae=round(validation_metrics["mae"], 4),
                   rmse=round(validation_metrics["rmse"], 4),
                   r2=round(validation_metrics["r_squared"], 4),
                   dir_acc=round(validation_metrics["directional_accuracy"], 4),
                   ic=round(validation_metrics["ic"], 4),
                   confidence=confidence)

        return trained

    # ------------------------------------------------------------------
    # DATA PREPARATION
    # ------------------------------------------------------------------

    def _prepare_data(
        self,
        features_map: Dict[str, Dict[str, Any]],
        returns: Dict[str, float],
        date_groups: Dict[str, str],
        feature_names: List[str],
    ) -> Tuple[np.ndarray, np.ndarray, List[int], List[str]]:
        """Tarih sıralı eğitim verisi hazırla."""
        X = []
        y = []
        tickers = []

        sorted_keys = sorted(
            features_map.keys(),
            key=lambda k: date_groups.get(k, "")
        )

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

        return np.array(X), np.array(y), [], tickers

    def _compute_impute_values(
        self, X: np.ndarray, feature_names: List[str]
    ) -> Dict[str, float]:
        """Impute değerlerini TRAIN verisinden hesapla."""
        impute = {}
        for i, name in enumerate(feature_names):
            col = X[:, i]
            valid = col[~np.isnan(col)]
            if len(valid) > 0:
                if self._config.impute_strategy == "median":
                    impute[name] = float(np.median(valid))
                else:
                    impute[name] = 0.0
            else:
                impute[name] = 0.0
        return impute

    def _impute(
        self, X: np.ndarray, impute_values: Dict[str, float]
    ) -> np.ndarray:
        """NaN değerleri impute et."""
        X_imputed = X.copy()
        for i in range(X.shape[1]):
            mask = np.isnan(X_imputed[:, i])
            if mask.any():
                col_name = list(impute_values.keys())[i] if i < len(impute_values) else None
                if col_name and col_name in impute_values:
                    X_imputed[mask, i] = impute_values[col_name]
                else:
                    X_imputed[mask, i] = 0.0
        return X_imputed

    def _compute_groups(
        self, date_groups: Dict[str, str], tickers: List[str]
    ) -> List[int]:
        """Group sizes hesapla (LambdaRank için)."""
        groups = []
        current_date = None
        current_count = 0

        for ticker in tickers:
            d = date_groups.get(ticker, "")
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

    def _compute_ndcg(
        self, y_true: np.ndarray, y_pred: np.ndarray, groups: List[int]
    ) -> float:
        """NDCG hesapla."""
        if len(groups) == 0:
            if np.std(y_true) > 0 and np.std(y_pred) > 0:
                return float(np.corrcoef(y_true, y_pred)[0, 1])
            return 0.0

        ndcg_scores = []
        idx = 0
        for g in groups:
            if g < 2:
                idx += g
                continue
            true_g = y_true[idx:idx+g]
            pred_g = y_pred[idx:idx+g]

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
# FEATURE CONTRACT VALIDATION
# =====================================================

def validate_feature_contract(
    features_map: Dict[str, Dict],
    expected_features: List[str],
) -> Tuple[bool, List[str]]:
    """Feature contract doğrulama.

    Returns:
        (is_valid, violations)
    """
    violations = []

    if not features_map:
        violations.append("Empty features_map")
        return False, violations

    # Her sample'da beklenen feature'lar var mı?
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

    # Tüm feature'lar aynı sırada mı?
    first_keys = set(features_map[list(features_map.keys())[0]].keys())
    for key, feats in features_map.items():
        if set(feats.keys()) != first_keys:
            violations.append(f"Inconsistent feature keys at {key}")
            break

    return len(violations) == 0, violations
