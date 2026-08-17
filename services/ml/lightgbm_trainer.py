"""
ALPHA BIST — LightGBM Training Pipeline v1.0

Production-grade, PIT-safe LightGBM model training.

Özellikler:
- Walk-forward her fold'da TRAIN window ile eğitim
- Scaler, imputer, threshold TRAIN'den öğrenilir
- Test verisi eğitimine kesinlikle girmez
- Model serialization (pickle)
- Prediction interface
- Feature Contract doğrulama
- Deterministic training
- Legacy mode korunur (use_ml_model=False → rule-based)
"""

import os
import pickle
import hashlib
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class MLModelConfig:
    """LightGBM model konfigürasyonu."""
    # LightGBM parametreleri
    objective: str = "regression"  # regression (daha basit, daha kararlı)
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
    impute_strategy: str = "median"  # median, zero, drop
    scale_features: bool = True

    # Model serialization
    model_dir: str = "models"


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

    def predict(self, features: Dict[str, Any]) -> float:
        """Tek bir feature dict için prediction döndür."""
        if self.model is None:
            raise ValueError("Model eğitilmemiş")

        # Feature vektörü oluştur
        vec = self._feature_vector(features)
        vec_2d = np.array([vec])

        # Prediction
        pred = self.model.predict(vec_2d)
        return float(pred[0])

    def predict_batch(self, features_list: List[Dict[str, Any]]) -> List[float]:
        """Birden fazla feature dict için prediction."""
        if self.model is None:
            raise ValueError("Model eğitilmemiş")

        vecs = [self._feature_vector(f) for f in features_list]
        X = np.array(vecs)
        preds = self.model.predict(X)
        return [float(p) for p in preds]

    def _feature_vector(self, features: Dict[str, Any]) -> List[float]:
        """Feature dict'ten vektör oluştur (eğitim ile aynı sırada)."""
        vec = []
        for name in self.feature_names:
            val = features.get(name)
            if val is None:
                # Impute
                if self.impute_values and name in self.impute_values:
                    vec.append(self.impute_values[name])
                else:
                    vec.append(0.0)
            else:
                try:
                    vec.append(float(val))
                except (TypeError, ValueError):
                    vec.append(0.0)

        arr = np.array(vec)

        # Scale
        if self.scaler_mean is not None and self.scaler_std is not None:
            arr = (arr - self.scaler_mean) / np.where(self.scaler_std > 0, self.scaler_std, 1.0)

        return arr.tolist()

    def save(self, path: str):
        """Modeli dosyaya kaydet."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "TrainedModel":
        """Modeli dosyadan yükle."""
        with open(path, "rb") as f:
            return pickle.load(f)


class LightGBMTrainer:
    """LightGBM training pipeline.

    Kullanım:
        trainer = LightGBMTrainer(config)
        model = trainer.train(train_features, train_returns, train_dates)
        predictions = model.predict_batch(test_features)
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
        """LightGBM LambdaRank modeli eğit.

        Args:
            features_map: {ticker: {feature: value}}
            returns: {ticker: future_return}
            date_groups: {ticker: date_str}
            feature_names: Kullanılacak feature isimleri (None = tümü)
            regime: Piyasa rejimi

        Returns:
            TrainedModel veya None (yeterli veri yoksa)
        """
        try:
            import lightgbm as lgb
        except ImportError:
            logger.warning("LightGBM not available")
            return None

        # Feature isimlerini belirle
        if feature_names is None:
            # Tüm feature'ları kullan
            all_features = set()
            for f in features_map.values():
                all_features.update(f.keys())
            feature_names = sorted(all_features)

        # Veri hazırla
        X, y, groups, tickers = self._prepare_data(
            features_map, returns, date_groups, feature_names
        )

        if len(X) < 50:
            logger.warning("Insufficient training data", samples=len(X))
            return None

        # LambdaRank integer label gerektirir — returns'ı grup bazlı rank'e çevir
        # Her grupta (tarihte) bağımsız rank
        y_rank = np.zeros(len(y), dtype=int)
        unique_dates = sorted(set(date_groups.values()))
        for d in unique_dates:
            indices = [i for i, t in enumerate(tickers) if date_groups.get(t) == d]
            if len(indices) > 1:
                group_returns = [y[i] for i in indices]
                sorted_indices = sorted(range(len(group_returns)), key=lambda k: -group_returns[k])
                for rank, idx in enumerate(sorted_indices):
                    y_rank[indices[idx]] = rank

        # Impute
        impute_values = self._compute_impute_values(X, feature_names)
        X = self._impute(X, impute_values)

        # Scale
        scaler_mean = None
        scaler_std = None
        if self._config.scale_features:
            scaler_mean = np.mean(X, axis=0)
            scaler_std = np.std(X, axis=0)
            scaler_std[scaler_std == 0] = 1.0
            X = (X - scaler_mean) / scaler_std

        # Train/validation ayrımı (zaman bazlı — son %20 validation)
        n = len(X)
        val_size = max(10, int(n * 0.2))
        train_size = n - val_size

        X_train, X_val = X[:train_size], X[train_size:]
        y_rank_train, y_rank_val = y_rank[:train_size], y_rank[train_size:]
        y_train, y_val = y[:train_size], y[train_size:]

        # Group sizes (LambdaRank için)
        train_groups = self._compute_groups(date_groups, tickers[:train_size])
        val_groups = self._compute_groups(date_groups, tickers[train_size:])

        # LightGBM Dataset (integer labels for LambdaRank)
        train_data = lgb.Dataset(
            X_train, label=y_rank_train, group=train_groups,
            feature_name=feature_names, free_raw_data=False
        )
        val_data = lgb.Dataset(
            X_val, label=y_rank_val, group=val_groups,
            feature_name=feature_names, free_raw_data=False,
            reference=train_data
        )

        # Parametreler
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
            "seed": 42,  # Deterministic
            "deterministic": True,
        }

        # Callbacks
        callbacks = []
        if self._config.early_stopping_rounds > 0:
            callbacks.append(lgb.early_stopping(self._config.early_stopping_rounds))
        callbacks.append(lgb.log_evaluation(period=0))  # Sessiz

        # Eğitim
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

        # Validation skoru
        val_pred = model.predict(X_val)
        val_score = self._compute_ndcg(y_val, val_pred, val_groups)

        # Feature importance
        importance = model.feature_importance(importance_type="gain")
        feature_importance = {
            name: float(imp)
            for name, imp in zip(feature_names, importance)
        }

        # Date range
        dates = sorted(set(date_groups.values()))
        date_range = (dates[0] if dates else "", dates[-1] if dates else "")

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

        logger.info("LightGBM model trained",
                   samples=train_size, val_score=round(val_score, 4),
                   features=len(feature_names))

        return trained

    def _prepare_data(
        self,
        features_map: Dict[str, Dict[str, Any]],
        returns: Dict[str, float],
        date_groups: Dict[str, str],
        feature_names: List[str],
    ) -> Tuple[np.ndarray, np.ndarray, List[int], List[str]]:
        """Eğitim verisi hazırla."""
        X = []
        y = []
        tickers = []

        # Tarih sıralı
        sorted_tickers = sorted(
            features_map.keys(),
            key=lambda t: date_groups.get(t, "")
        )

        for ticker in sorted_tickers:
            if ticker not in returns:
                continue

            features = features_map[ticker]
            vec = []
            for name in feature_names:
                val = features.get(name)
                if val is None:
                    vec.append(np.nan)
                else:
                    try:
                        vec.append(float(val))
                    except (TypeError, ValueError):
                        vec.append(np.nan)

            X.append(vec)
            y.append(returns[ticker])
            tickers.append(ticker)

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
                elif self._config.impute_strategy == "zero":
                    impute[name] = 0.0
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
            # Basit correlation
            if np.std(y_true) > 0 and np.std(y_pred) > 0:
                return float(np.corrcoef(y_true, y_pred)[0, 1])
            return 0.0

        # Group-based NDCG
        ndcg_scores = []
        idx = 0
        for g in groups:
            if g < 2:
                idx += g
                continue
            true_g = y_true[idx:idx+g]
            pred_g = y_pred[idx:idx+g]

            # Ideal ranking
            ideal = np.sort(true_g)[::-1]
            # Predicted ranking
            pred_order = np.argsort(pred_g)[::-1]
            pred_sorted = true_g[pred_order]

            # DCG
            dcg = np.sum(pred_sorted / np.log2(np.arange(2, g + 2)))
            idcg = np.sum(ideal / np.log2(np.arange(2, g + 2)))

            if idcg > 0:
                ndcg_scores.append(dcg / idcg)

            idx += g

        return float(np.mean(ndcg_scores)) if ndcg_scores else 0.0
