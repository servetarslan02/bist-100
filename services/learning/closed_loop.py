# Closed-Loop Learning System
# Continuous learning from prediction outcomes

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PredictionRecord:
    """Record of a single prediction and its outcome."""

    ticker: str
    prediction: float
    confidence: float
    timestamp: float
    actual_outcome: float | None = None
    outcome_timestamp: float | None = None
    model_name: str = ""
    features: dict[str, float] = field(default_factory=dict)


class ClosedLoopLearning:
    """Closed-loop learning system that tracks predictions and learns from outcomes."""

    def __init__(self, max_history: int = 10000):
        """Otomatik eklendi."""
        self.max_history = max_history
        self._predictions: list[PredictionRecord] = []
        self._model_metrics: dict[str, dict[str, float]] = {}

    def record_prediction(
        self,
        ticker: str,
        prediction: float,
        confidence: float,
        model_name: str = "",
        features: dict[str, float] | None = None,
    ) -> None:
        """Record a new prediction."""
        record = PredictionRecord(
            ticker=ticker,
            prediction=prediction,
            confidence=confidence,
            timestamp=time.time(),
            model_name=model_name,
            features=features or {},
        )
        self._predictions.append(record)

        # Trim history
        if len(self._predictions) > self.max_history:
            self._predictions = self._predictions[-self.max_history :]

    def record_outcome(
        self,
        ticker: str,
        actual_outcome: float,
        lookback_seconds: float = 86400,
    ) -> int:
        """Record actual outcome and match to recent predictions.

        Returns number of predictions matched.
        """
        now = time.time()
        matched = 0

        for record in reversed(self._predictions):
            if record.ticker != ticker:
                continue
            if record.actual_outcome is not None:
                continue
            if now - record.timestamp > lookback_seconds:
                break

            record.actual_outcome = actual_outcome
            record.outcome_timestamp = now
            matched += 1

        if matched > 0:
            self._update_metrics(ticker)
            logger.info("Recorded outcomes", ticker=ticker, matched=matched)

        return matched

    def _update_metrics(self, ticker: str) -> None:
        """Update model metrics based on resolved predictions."""
        resolved = [r for r in self._predictions if r.ticker == ticker and r.actual_outcome is not None]

        if not resolved:
            return

        predictions = np.array([r.prediction for r in resolved])
        outcomes = np.array([r.actual_outcome for r in resolved])

        # Direction accuracy
        pred_direction = predictions > 0
        actual_direction = outcomes > 0
        direction_accuracy = float(np.mean(pred_direction == actual_direction))

        # Brier score (for probabilistic predictions)
        confidence = np.array([r.confidence for r in resolved])
        brier = float(np.mean((confidence - (outcomes > 0).astype(float)) ** 2))

        # Mean absolute error
        mae = float(np.mean(np.abs(predictions - outcomes)))

        self._model_metrics[ticker] = {
            "direction_accuracy": direction_accuracy,
            "brier_score": brier,
            "mae": mae,
            "n_resolved": len(resolved),
            "last_update": time.time(),
        }

    def get_metrics(self, ticker: str | None = None) -> dict[str, Any]:
        """Get learning metrics."""
        if ticker:
            return self._model_metrics.get(ticker, {})
        return self._model_metrics.copy()

    def get_pending_count(self) -> int:
        """Get count of predictions awaiting outcome."""
        return sum(1 for r in self._predictions if r.actual_outcome is None)

    def evaluate_recent_predictions(self, lookback_seconds: float = 86400) -> dict[str, Any]:
        """Evaluate recent predictions and update metrics.

        Returns:
            Dict with evaluation results per ticker.
        """
        now = time.time()
        results: dict[str, Any] = {}

        # Group by ticker
        tickers = set(r.ticker for r in self._predictions if r.actual_outcome is None)
        for ticker in tickers:
            pending = [
                r
                for r in self._predictions
                if r.ticker == ticker and r.actual_outcome is None and now - r.timestamp <= lookback_seconds
            ]
            if pending:
                results[ticker] = {
                    "pending_count": len(pending),
                    "avg_confidence": float(np.mean([r.confidence for r in pending])),
                }

        logger.info("Evaluated recent predictions", tickers=len(results))
        return results


# Singleton
closed_loop = ClosedLoopLearning()
