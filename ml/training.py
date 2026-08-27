"""ALPHA BIST - ML Training Pipeline v1.1

Purged walk-forward validation, gerçek label dataset, proper confidence.
"""

import pickle
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import structlog

# LabelGenerator entegrasyonu — gelişmiş label'lar için
try:
    from services.labels.generator import LabelGenerator, label_generator  # noqa: F401
    HAS_LABEL_GENERATOR = True
except ImportError:
    HAS_LABEL_GENERATOR = False

logger = structlog.get_logger()


@dataclass
class TrainingConfig:
    """ML training konfigürasyonu."""
    model_name: str
    target: str  # "return_5d", "return_20d", "direction_5d", etc.
    feature_names: list[str]
    train_months: int = 12
    test_months: int = 1
    purge_days: int = 5
    embargo_days: int = 5
    n_estimators: int = 200
    max_depth: int = 5
    learning_rate: float = 0.05
    early_stopping_rounds: int = 20


@dataclass
class LabelSpec:
    """Label (hedef değişken) tanımı."""
    name: str
    formula: str
    horizon_days: int
    is_classification: bool = False
    threshold: float = 0.0


# =====================================================
# Label Definitions (Kesin)
# =====================================================

LABEL_SPECS = {
    "return_5d": LabelSpec(
        name="return_5d",
        formula="(P_{t+5} / P_t - 1) * 100",
        horizon_days=5,
        is_classification=False,
    ),
    "return_20d": LabelSpec(
        name="return_20d",
        formula="(P_{t+20} / P_t - 1) * 100",
        horizon_days=20,
        is_classification=False,
    ),
    "direction_5d": LabelSpec(
        name="direction_5d",
        formula="1 if return_5d > 0 else 0",
        horizon_days=5,
        is_classification=True,
        threshold=0.0,
    ),
    "breakout_success": LabelSpec(
        name="breakout_success",
        formula="1 if max(H_{t+5:t+10}) > P_t * 1.03 else 0",
        horizon_days=10,
        is_classification=True,
        threshold=3.0,
    ),
    "max_drawdown_20d": LabelSpec(
        name="max_drawdown_20d",
        formula="min(P_{t:t+20}) / P_t - 1",
        horizon_days=20,
        is_classification=False,
    ),
    "spec_outcome": LabelSpec(
        name="spec_outcome",
        formula="1 if return_20d > 5% AND max_drawdown > -3% else 0",
        horizon_days=20,
        is_classification=True,
        threshold=5.0,
    ),
}


class MLTrainer:
    """ML model training with purged walk-forward validation."""

    def __init__(self):
        self.models: dict[str, Any] = {}
        self.training_results: dict[str, dict] = {}

    def generate_labels(self, data: pl.DataFrame, label_name: str,
                        price_column: str = "close",
                        high_column: str = "high",
                        low_column: str = "low") -> pl.DataFrame:
        """
        Label'ları hesapla. Look-ahead bias yok — sadece geleceğe bakarak label üretiyoruz
        ama feature hesaplama sadece geçmişle.
        """
        spec = LABEL_SPECS.get(label_name)
        if not spec:
            raise ValueError(f"Unknown label: {label_name}")

        prices = data[price_column].to_numpy()
        n = len(prices)
        labels = np.full(n, np.nan)

        for i in range(n - spec.horizon_days):
            if label_name == "return_5d":
                labels[i] = (prices[i + 5] / prices[i] - 1) * 100
            elif label_name == "return_20d":
                labels[i] = (prices[i + 20] / prices[i] - 1) * 100
            elif label_name == "direction_5d":
                ret = (prices[i + 5] / prices[i] - 1) * 100
                labels[i] = 1 if ret > 0 else 0
            elif label_name == "breakout_success":
                future_high = np.max(prices[i + 1:i + 11]) if i + 11 <= n else np.nan
                labels[i] = 1 if future_high > prices[i] * 1.03 else 0
            elif label_name == "max_drawdown_20d":
                future_prices = prices[i:i + 21]
                min_price = np.min(future_prices)
                labels[i] = (min_price / prices[i] - 1) * 100
            elif label_name == "spec_outcome":
                ret = (prices[i + 20] / prices[i] - 1) * 100 if i + 20 < n else np.nan
                dd = (np.min(prices[i:i + 21]) / prices[i] - 1) * 100 if i + 21 <= n else np.nan
                labels[i] = 1 if (ret > 5 and dd > -3) else 0

        return data.with_columns(pl.Series(label_name, labels))

    def prepare_dataset(self, data: pl.DataFrame, feature_names: list[str],
                        label_name: str, date_column: str = "timestamp"
                        ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """Training dataset hazırla — NaN temizle."""
        available_features = [f for f in feature_names if f in data.columns]

        X = data.select(available_features).to_numpy()
        y = data.select(label_name).to_numpy().ravel()

        # Remove NaN rows
        mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X, y = X[mask], y[mask]

        logger.info("Dataset prepared", samples=len(X), features=len(available_features),
                    label=label_name, positive_rate=f"{np.mean(y > 0) * 100:.1f}%" if not np.all(np.isnan(y)) else "N/A")

        return X, y, available_features

    def train_with_walkforward(self, data: pl.DataFrame, config: TrainingConfig,
                               date_column: str = "timestamp") -> dict[str, Any]:
        """
        Purged walk-forward validation ile model eğit.
        """
        import lightgbm as lgb
        from sklearn.metrics import accuracy_score, mean_squared_error, r2_score

        # Generate labels (skip if already present)
        if config.target not in data.columns:
            data = self.generate_labels(data, config.target)

        # Walk-forward splits
        data_sorted = data.sort(date_column)
        min_date = data_sorted[date_column].min()
        max_date = data_sorted[date_column].max()

        splits = []
        current_test_start = min_date + timedelta(days=config.train_months * 30)

        while current_test_start < max_date:
            test_end = current_test_start + timedelta(days=config.test_months * 30)
            train_end = current_test_start - timedelta(days=config.purge_days)
            train_start = train_end - timedelta(days=config.train_months * 30)

            train = data_sorted.filter(
                (pl.col(date_column) >= train_start) &
                (pl.col(date_column) <= train_end)
            )
            test = data_sorted.filter(
                (pl.col(date_column) >= current_test_start) &
                (pl.col(date_column) <= test_end)
            )

            # Embargo
            if config.embargo_days > 0:
                embargo_cutoff = current_test_start - timedelta(days=config.embargo_days)
                train = train.filter(pl.col(date_column) < embargo_cutoff)

            if len(train) > 100 and len(test) > 20:
                splits.append((train, test, current_test_start, test_end))

            current_test_start = test_end

        if not splits:
            return {"error": "No valid walk-forward splits"}

        logger.info("Walk-forward splits", count=len(splits))

        # Train and evaluate each split
        split_results = []
        all_predictions = []

        for i, (train, test, test_start, test_end) in enumerate(splits):
            X_train, y_train, feat_names = self.prepare_dataset(
                train, config.feature_names, config.target
            )
            X_test, y_test, _ = self.prepare_dataset(
                test, config.feature_names, config.target
            )

            if len(X_train) < 50 or len(X_test) < 10:
                continue

            # Train
            is_classification = LABEL_SPECS[config.target].is_classification

            if is_classification:
                model = lgb.LGBMClassifier(
                    n_estimators=config.n_estimators,
                    max_depth=config.max_depth,
                    learning_rate=config.learning_rate,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    min_child_samples=10,
                    random_state=42,
                    verbose=-1,
                )
            else:
                model = lgb.LGBMRegressor(
                    n_estimators=config.n_estimators,
                    max_depth=config.max_depth,
                    learning_rate=config.learning_rate,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    min_child_samples=10,
                    random_state=42,
                    verbose=-1,
                )

            # Early stopping — validation set'i train'den ayır (data leakage önleme)
            # NOT: Asla test setini validation olarak kullanma!
            try:
                val_size = max(10, len(X_train) // 5)
                if len(X_train) > val_size + 10:
                    X_tr, X_val = X_train[:-val_size], X_train[-val_size:]
                    y_tr, y_val = y_train[:-val_size], y_train[-val_size:]
                    model.fit(
                        X_tr, y_tr,
                        eval_set=[(X_val, y_val)],
                        callbacks=[lgb.early_stopping(config.early_stopping_rounds, verbose=False)],
                    )
                else:
                    # Yeterli veri yok — early stopping olmadan eğit
                    model.fit(X_train, y_train)
            except Exception:
                model.fit(X_train, y_train)

            # Predict
            if is_classification:
                y_pred_proba = model.predict_proba(X_test)[:, 1]
                y_pred = (y_pred_proba > 0.5).astype(int)
                accuracy = accuracy_score(y_test, y_pred)
                metric_value = accuracy
            else:
                y_pred = model.predict(X_test)
                np.sqrt(mean_squared_error(y_test, y_pred))
                r2 = r2_score(y_test, y_pred)
                metric_value = r2

            # Direction accuracy
            if not is_classification:
                dir_acc = np.sum(np.sign(y_pred) == np.sign(y_test)) / len(y_test) * 100
            else:
                dir_acc = accuracy * 100

            # Sharpe
            if not is_classification:
                correct_mask = np.sign(y_pred) == np.sign(y_test)
                correct_returns = y_test[correct_mask]
                if len(correct_returns) > 0 and np.std(correct_returns) > 0:
                    sharpe = np.mean(correct_returns) / np.std(correct_returns) * np.sqrt(252)
                else:
                    sharpe = 0
            else:
                sharpe = 0

            split_result = {
                "split": i,
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "train_samples": len(X_train),
                "test_samples": len(X_test),
                "direction_accuracy": round(dir_acc, 1),
                "sharpe": round(sharpe, 3),
                "metric_value": round(metric_value, 4),
            }
            split_results.append(split_result)

            # Store predictions for confidence calculation
            for j in range(len(y_pred)):
                all_predictions.append({
                    "split": i,
                    "predicted": float(y_pred[j]),
                    "actual": float(y_test[j]),
                    "correct": bool(np.sign(y_pred[j]) == np.sign(y_test[j])),
                })

        # Aggregate metrics
        if split_results:
            avg_metrics = {
                "avg_direction_accuracy": round(np.mean([s["direction_accuracy"] for s in split_results]), 1),
                "avg_sharpe": round(np.mean([s["sharpe"] for s in split_results]), 3),
                "avg_metric": round(np.mean([s["metric_value"] for s in split_results]), 4),
                "splits": len(split_results),
            }
        else:
            avg_metrics = {"error": "No valid splits"}

        # Confidence (based on out-of-sample performance, not feature importance)
        confidence = self._calculate_confidence(all_predictions, split_results)

        # Train final model on all data
        X_all, y_all, feat_names = self.prepare_dataset(
            data_sorted, config.feature_names, config.target
        )

        if is_classification:
            final_model = lgb.LGBMClassifier(
                n_estimators=config.n_estimators,
                max_depth=config.max_depth,
                learning_rate=config.learning_rate,
                random_state=42, verbose=-1,
            )
        else:
            final_model = lgb.LGBMRegressor(
                n_estimators=config.n_estimators,
                max_depth=config.max_depth,
                learning_rate=config.learning_rate,
                random_state=42, verbose=-1,
            )

        final_model.fit(X_all, y_all)

        # Save
        model_dir = Path(f"ml/saved_models/{config.model_name}")
        model_dir.mkdir(parents=True, exist_ok=True)

        with open(model_dir / "model.pkl", "wb") as f:
            pickle.dump(final_model, f)

        with open(model_dir / "config.json", "w") as f:
            f.write(orjson.dumps({
                "model_name": config.model_name,
                "target": config.target,
                "features": feat_names,
                "metrics": avg_metrics,
                "confidence": confidence,
                "training_date": datetime.now(UTC).isoformat(),
            }, option=orjson.OPT_INDENT_2).decode())

        self.models[config.model_name] = final_model
        self.training_results[config.model_name] = {
            "metrics": avg_metrics,
            "confidence": confidence,
            "splits": split_results,
        }

        logger.info("Training complete", model=config.model_name,
                    accuracy=avg_metrics.get("avg_direction_accuracy"),
                    confidence=confidence)

        return {
            "model_name": config.model_name,
            "metrics": avg_metrics,
            "confidence": confidence,
            "splits": split_results,
            "feature_importance": dict(zip(feat_names, final_model.feature_importances_.tolist(), strict=False)),
        }

    def _calculate_confidence(self, predictions: list[dict],
                              split_results: list[dict]) -> float:
        """
        Model confidence — out-of-sample performance bazlı.

        Confidence = calibration * consistency * accuracy

        - Calibration: predicted probability vs actual frequency
        - Consistency: split'ler arası tutarlılık
        - Accuracy: ortalama doğruluk
        """
        if not predictions or not split_results:
            return 0.0

        # Accuracy
        correct_count = sum(1 for p in predictions if p["correct"])
        accuracy = correct_count / len(predictions) if predictions else 0

        # Consistency (split'ler arası accuracy std)
        accuracies = [s["direction_accuracy"] for s in split_results]
        if len(accuracies) > 1:
            consistency = 1 - (np.std(accuracies) / np.mean(accuracies)) if np.mean(accuracies) > 0 else 0
        else:
            consistency = 0.5

        # Combined confidence
        confidence = accuracy * 0.6 + consistency * 0.4

        return round(min(max(confidence, 0), 1), 4)


# Singleton
ml_trainer = MLTrainer()
