"""
ALPHA BIST — Kapalı Çevrim Öğrenme Sistemi (Closed-Loop Learning System v2.0)

Tahmin sonuçlarını, model başarımlarını ve gerçekleşen piyasa getirilerini
eşleştirerek modellerin canlı performans metriklerini hesaplar.
Brier skoru, yön doğruluğu (direction accuracy), MAE ve hata tamponunu
izleyerek model ağırlıklandırma mekanizmalarına geri besleme sağlar.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PredictionRecord:
    """Tekil model tahmini ve gerçekleşen getiri sonucu kaydı."""

    ticker: str
    prediction: float
    confidence: float
    timestamp: float
    actual_outcome: float | None = None
    outcome_timestamp: float | None = None
    model_name: str = ""
    features: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Tahmin kaydının okunabilir metin temsili."""
        status = f"actual={self.actual_outcome:+.4f}" if self.actual_outcome is not None else "pending"
        return (
            f"PredictionRecord(ticker='{self.ticker}', model='{self.model_name}', "
            f"pred={self.prediction:+.4f}, conf={self.confidence:.2f}, {status})"
        )


class ClosedLoopLearning:
    """Tahminleri izleyen ve gerçekleşen piyasa sonuçlarından öğrenen kapalı döngü sistemi."""

    def __init__(self, max_history: int = 10000) -> None:
        """Kapalı döngü öğrenme sistemini ve tahmin kayıt tamponunu başlatır.

        Args:
            max_history: Bellekte tutulacak maksimum tahmin kaydı sayısı (varsayılan: 10000).
        """
        self.max_history = max_history
        self._lock = threading.Lock()
        self._predictions: list[PredictionRecord] = []
        self._model_metrics: dict[str, dict[str, float]] = {}

    def __repr__(self) -> str:
        """Kapalı döngü öğrenme sisteminin okunabilir metin temsili."""
        with self._lock:
            pending = sum(1 for r in self._predictions if r.actual_outcome is None)
            return (
                f"ClosedLoopLearning(total={len(self._predictions)}, "
                f"pending={pending}, tracked_tickers={len(self._model_metrics)})"
            )

    def record_prediction(
        self,
        ticker: str,
        prediction: float,
        confidence: float,
        model_name: str = "",
        features: dict[str, float] | None = None,
    ) -> None:
        """Yeni bir model tahminini sisteme kaydeder.

        Args:
            ticker: Sembol kodu.
            prediction: Modelin ürettiği beklenen getiri/yön değeri.
            confidence: Model güven katsayısı (0.0 - 1.0).
            model_name: Tahmini üreten model adı.
            features: Tahmin anındaki özellik vektörü.
        """
        record = PredictionRecord(
            ticker=ticker,
            prediction=prediction,
            confidence=confidence,
            timestamp=time.time(),
            model_name=model_name,
            features=features or {},
        )
        with self._lock:
            self._predictions.append(record)
            if len(self._predictions) > self.max_history:
                self._predictions = self._predictions[-self.max_history :]

    def record_outcome(
        self,
        ticker: str,
        actual_outcome: float,
        lookback_seconds: float = 86400,
    ) -> int:
        """Gerçekleşen piyasa getirisini kaydeder ve bekleyen tahminlerle eşleştirir.

        Args:
            ticker: Sembol kodu.
            actual_outcome: Gerçekleşen getiri oranı.
            lookback_seconds: Eşleştirme yapılacak geçmiş saniye penceresi (varsayılan: 86400).

        Returns:
            int: Eşleşen ve sonuçlandırılan tahmin adedi.
        """
        now = time.time()
        matched = 0

        with self._lock:
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
                self._update_metrics_locked(ticker)

        if matched > 0:
            logger.info("Kapalı döngü getiri eşleştirildi", ticker=ticker, matched=matched)

        return matched

    def _update_metrics_locked(self, ticker: str) -> None:
        """Kilit altında çözümlenmiş tahminler üzerinden performans metriklerini günceller.

        Args:
            ticker: Sembol kodu.
        """
        resolved = [r for r in self._predictions if r.ticker == ticker and r.actual_outcome is not None]

        if not resolved:
            return

        predictions = np.array([r.prediction for r in resolved])
        outcomes = np.array([r.actual_outcome for r in resolved])

        pred_direction = predictions > 0
        actual_direction = outcomes > 0
        direction_accuracy = float(np.mean(pred_direction == actual_direction))

        confidence = np.array([r.confidence for r in resolved])
        brier = float(np.mean((confidence - (outcomes > 0).astype(float)) ** 2))

        mae = float(np.mean(np.abs(predictions - outcomes)))

        self._model_metrics[ticker] = {
            "direction_accuracy": direction_accuracy,
            "brier_score": brier,
            "mae": mae,
            "n_resolved": float(len(resolved)),
            "last_update": time.time(),
        }

    def get_metrics(self, ticker: str | None = None) -> dict[str, Any]:
        """Öğrenme ve başarı metriklerini döndürür.

        Args:
            ticker: İsteğe bağlı sembol filtresi.

        Returns:
            dict[str, Any]: Sembol bazlı veya toplu metrik sözlüğü.
        """
        with self._lock:
            if ticker:
                return self._model_metrics.get(ticker, {}).copy()
            return self._model_metrics.copy()

    def get_pending_count(self) -> int:
        """Sonuçlanmayı bekleyen açık tahmin sayısını döndürür.

        Returns:
            int: Açık tahmin adedi.
        """
        with self._lock:
            return sum(1 for r in self._predictions if r.actual_outcome is None)

    def evaluate_recent_predictions(self, lookback_seconds: float = 86400) -> dict[str, Any]:
        """Son dönemdeki tahminlerin durumunu inceler ve açık pozisyon metriklerini özetler.

        Args:
            lookback_seconds: İnceleme zaman penceresi (saniye).

        Returns:
            dict[str, Any]: Sembol bazında açık tahmin sayısı ve ortalama güven değerleri.
        """
        now = time.time()
        results: dict[str, Any] = {}

        with self._lock:
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

        logger.info("Son tahminler değerlendirildi", tickers=len(results))
        return results


# Global Tekil Örnek
closed_loop = ClosedLoopLearning()
