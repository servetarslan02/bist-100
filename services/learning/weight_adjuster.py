# Weight Adjuster
# Dynamic model weight adjustment based on performance

from __future__ import annotations

import time
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class WeightAdjuster:
    """Dynamically adjusts model ensemble weights based on performance metrics."""

    def __init__(
        self,
        min_weight: float = 0.05,
        max_weight: float = 0.60,
        decay_factor: float = 0.95,
        min_samples: int = 10,
    ):
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.decay_factor = decay_factor
        self.min_samples = min_samples
        self._weights: dict[str, float] = {}
        self._history: list[dict[str, Any]] = []

    def adjust_weights(
        self,
        model_metrics: dict[str, dict[str, float]],
        metric_key: str = "direction_accuracy",
    ) -> dict[str, float]:
        """Adjust weights based on model performance.

        Args:
            model_metrics: {model_name: {metric_name: value}}
            metric_key: Which metric to optimize for

        Returns:
            Updated weights {model_name: weight}
        """
        if not model_metrics:
            return self._weights.copy()

        # Extract scores
        scores: dict[str, float] = {}
        for model, metrics in model_metrics.items():
            score = metrics.get(metric_key, 0.5)
            n_samples = metrics.get("n_resolved", 0)

            # Penalize models with too few samples
            if n_samples < self.min_samples:
                score *= 0.5

            scores[model] = max(0.01, score)

        # Softmax normalization with temperature
        total_score = sum(scores.values())
        if total_score < 1e-10:
            # Equal weights if no scores
            n = len(scores)
            new_weights = {m: 1.0 / n for m in scores}
        else:
            # Temperature-scaled softmax
            temperature = 2.0
            exp_scores = {m: np.exp(s / temperature) for m, s in scores.items()}
            total_exp = sum(exp_scores.values())
            new_weights = {m: es / total_exp for m, es in exp_scores.items()}

        # Apply min/max bounds
        for model in new_weights:
            new_weights[model] = max(self.min_weight, min(self.max_weight, new_weights[model]))

        # Renormalize after bounds
        total = sum(new_weights.values())
        new_weights = {m: w / total for m, w in new_weights.items()}

        # Smooth transition (exponential moving average)
        if self._weights:
            for model in new_weights:
                old = self._weights.get(model, new_weights[model])
                new_weights[model] = old * self.decay_factor + new_weights[model] * (1 - self.decay_factor)

        self._weights = new_weights

        # Record history
        self._history.append({
            "timestamp": time.time(),
            "weights": new_weights.copy(),
            "metric_key": metric_key,
        })

        logger.info("Weights adjusted", weights=new_weights)
        return new_weights.copy()

    def get_weights(self) -> dict[str, float]:
        """Get current weights."""
        return self._weights.copy()

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get weight adjustment history."""
        return self._history[-limit:]

    def update_weights(
        self,
        model_metrics: dict[str, dict[str, float]] | None = None,
        metric_key: str = "direction_accuracy",
    ) -> dict[str, float]:
        """Update weights based on current model metrics.

        Convenience method that fetches metrics if not provided.

        Returns:
            Updated weights.
        """
        if model_metrics is None:
            # Try to get metrics from closed loop learning
            try:
                from services.learning.closed_loop import closed_loop
                model_metrics = closed_loop.get_metrics()
            except Exception:
                logger.warning("No metrics available for weight adjustment")
                return self._weights.copy()

        if not model_metrics:
            return self._weights.copy()

        return self.adjust_weights(model_metrics, metric_key)


# Singleton
weight_adjuster = WeightAdjuster()
