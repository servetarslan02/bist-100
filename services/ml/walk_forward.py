"""
ALPHA BIST — Walk-Forward Validation v1.0

ROADMAP v3.0:
- Purge: Train/test arasına boşluk (look-ahead bias önleme)
- Embargo: Test sonrası boşluk (information leakage önleme)
- Expanding window: Her adımda daha fazla veri

KURAL: Gelecekten bilgi sızdırma!
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class WFResult:
    """Walk-forward sonuç."""

    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_size: int
    test_size: int
    metrics: dict[str, float]
    predictions: list[dict]
    actuals: list[float]


class WalkForwardValidation:
    """Walk-forward validasyon motoru."""

    def __init__(
        self,
        train_size: int = 252,  # 1 yıl günlük
        test_size: int = 21,  # 1 ay günlük
        purge_size: int = 5,  # Train/test arası boşluk
        embargo_size: int = 5,  # Test sonrası boşluk
        step_size: int = 21,  # Her adımda ilerleme
    ):
        """Otomatik eklendi."""
        self._train_size = train_size
        self._test_size = test_size
        self._purge_size = purge_size
        self._embargo_size = embargo_size
        self._step_size = step_size
        logger.info("WalkForwardValidation initialized", train=train_size, test=test_size, purge=purge_size)

    def generate_splits(
        self,
        dates: list[datetime],
    ) -> list[dict[str, Any]]:
        """Train/test split'leri oluştur."""

        splits = []
        total = len(dates)

        # İlk train başlangıcı
        start_idx = self._train_size

        while start_idx + self._test_size + self._embargo_size <= total:
            # Train: [start_idx - train_size, start_idx - purge_size)
            train_start = start_idx - self._train_size
            train_end = start_idx - self._purge_size

            # Test: [start_idx, start_idx + test_size)
            test_start = start_idx
            test_end = start_idx + self._test_size

            split = {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "train_dates": dates[train_start:train_end],
                "test_dates": dates[test_start:test_end],
            }
            splits.append(split)

            # İlerle
            start_idx += self._step_size

        logger.info(f"Generated {len(splits)} walk-forward splits")
        return splits

    def evaluate(
        self,
        data: dict[str, Any],
        model_fn: Callable,
        feature_fn: Callable,
    ) -> list[WFResult]:
        """Walk-forward evaluasyon."""

        dates = data.get("dates", [])
        splits = self.generate_splits(dates)

        results = []

        for i, split in enumerate(splits):
            logger.info(f"Evaluating split {i + 1}/{len(splits)}")

            # Train verisi
            train_data = {k: v[split["train_start"] : split["train_end"]] for k, v in data.items() if k != "dates"}

            # Test verisi
            test_data = {k: v[split["test_start"] : split["test_end"]] for k, v in data.items() if k != "dates"}

            # Feature hesapla
            train_features = feature_fn(train_data)
            test_features = feature_fn(test_data)

            # F-008 düzeltmesi: Train feature'larının son purge_days barını hariç tut.
            # Bu, train feature'ları ile test label'ları arasındaki look-ahead bias'ı önler.
            if self._purge_size > 0:
                if isinstance(train_features, dict):
                    for key in train_features:
                        val = train_features[key]
                        if isinstance(val, np.ndarray) and len(val) > self._purge_size:
                            train_features[key] = val[: -self._purge_size]
                elif isinstance(train_features, np.ndarray) and len(train_features) > self._purge_size:
                    train_features = train_features[: -self._purge_size]

            # Model eğit
            model = model_fn()
            model.train(train_features)

            # Tahmin
            predictions = model.predict(test_features)
            actuals = test_data.get("returns", [])

            # Metrikler
            metrics = self._calculate_metrics(predictions, actuals)

            result = WFResult(
                train_start=split["train_dates"][0],
                train_end=split["train_dates"][-1],
                test_start=split["test_dates"][0],
                test_end=split["test_dates"][-1],
                train_size=len(split["train_dates"]),
                test_size=len(split["test_dates"]),
                metrics=metrics,
                predictions=predictions,
                actuals=actuals,
            )
            results.append(result)

        return results

    def _calculate_metrics(
        self,
        predictions: list[dict],
        actuals: list[float],
    ) -> dict[str, float]:
        """Metrik hesapla."""

        if not predictions or not actuals:
            return {}

        pred_values = [p.get("score", 0) for p in predictions]

        # Korelasyon
        corr = np.corrcoef(pred_values, actuals)[0, 1] if len(pred_values) > 1 else 0
        if np.isnan(corr):
            corr = 0

        # Yön doğruluğu
        pred_dir = np.sign(pred_values)
        actual_dir = np.sign(actuals)
        direction_accuracy = np.mean(pred_dir == actual_dir) * 100

        # RMSE
        rmse = np.sqrt(np.mean((np.array(pred_values) - np.array(actuals)) ** 2))

        return {
            "correlation": round(float(corr), 4),
            "direction_accuracy": round(float(direction_accuracy), 2),
            "rmse": round(float(rmse), 4),
        }

    def get_aggregated_metrics(self, results: list[WFResult]) -> dict[str, Any]:
        """Tüm split'lerin aggregate metrikleri."""

        if not results:
            return {}

        correlations = [r.metrics.get("correlation", 0) for r in results]
        accuracies = [r.metrics.get("direction_accuracy", 0) for r in results]

        return {
            "avg_correlation": round(np.mean(correlations), 4),
            "std_correlation": round(np.std(correlations), 4),
            "avg_direction_accuracy": round(np.mean(accuracies), 2),
            "std_direction_accuracy": round(np.std(accuracies), 2),
            "total_splits": len(results),
            "avg_train_size": round(np.mean([r.train_size for r in results]), 0),
            "avg_test_size": round(np.mean([r.test_size for r in results]), 0),
        }


# Singleton
wf_validator = WalkForwardValidation()
