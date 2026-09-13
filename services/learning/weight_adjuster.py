"""
ALPHA BIST — Dinamik Model Ağırlık Ayarlayıcısı (Dynamic Weight Adjuster v2.1)

Ensemble içerisindeki tahmin modellerinin (LightGBM, CatBoost, XGBoost vb.)
canlı piyasa ve backtest başarımlarına göre ağırlıklarını dinamik olarak optimize eder.
Sıcaklık ayarlı softmax normalizasyonu, asgari/azami ağırlık sınırlaması,
üstel sönümleme (exponential smoothing) ve genişleyen pencere (expanding window)
algoritmalarıyla rejim değişimlerine uyum sağlar.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class WeightAdjuster:
    """Modellerin ensemble ağırlıklarını performans metriklerine göre dinamik olarak optimize eden sınıf."""

    def __init__(
        self,
        min_weight: float = 0.05,
        max_weight: float = 0.60,
        decay_factor: float = 0.95,
        min_samples: int = 10,
    ) -> None:
        """Ensemble model ağırlık ayarlayıcısını min/max ağırlık ve sönümleme katsayısıyla başlatır.

        Args:
            min_weight: Bir modelin sahip olabileceği asgari ağırlık (varsayılan: 0.05).
            max_weight: Bir modelin sahip olabileceği azami ağırlık (varsayılan: 0.60).
            decay_factor: Üstel hareketli ortalama sönümleme katsayısı (varsayılan: 0.95).
            min_samples: Tam ağırlıklandırma için gereken asgari örnek sayısı (varsayılan: 10).
        """
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.decay_factor = decay_factor
        self.min_samples = min_samples
        self._lock = threading.Lock()
        self._weights: dict[str, float] = {}
        self._history: list[dict[str, Any]] = []
        self._model_outcomes: dict[str, list[dict[str, Any]]] = {}

    def __repr__(self) -> str:
        """Ağırlık ayarlayıcının okunabilir metin temsili."""
        with self._lock:
            active_models = list(self._weights.keys())
            return (
                f"WeightAdjuster(min_w={self.min_weight:.2f}, max_w={self.max_weight:.2f}, "
                f"decay={self.decay_factor:.2f}, models={active_models})"
            )

    def adjust_weights(
        self,
        model_metrics: dict[str, dict[str, float]],
        metric_key: str = "direction_accuracy",
    ) -> dict[str, float]:
        """Modellerin güncel performans metriklerine göre ensemble ağırlıklarını optimize eder.

        Args:
            model_metrics: Model adına göre metrik değerleri sözlüğü ({model_name: {metric: value}}).
            metric_key: Optimizasyonda maksimize edilecek metrik adı (varsayılan: 'direction_accuracy').

        Returns:
            dict[str, float]: Modellerin normalize edilmiş yeni ağırlıkları.
        """
        with self._lock:
            if not model_metrics:
                return self._weights.copy()

            # Skorları çıkar
            scores: dict[str, float] = {}
            for model, metrics in model_metrics.items():
                score = float(metrics.get(metric_key, 0.5))
                n_samples = int(metrics.get("n_resolved", 0))

                # Yetersiz örneği olan modelleri hafif cezalandır
                if n_samples < self.min_samples:
                    score *= 0.5

                scores[model] = max(0.01, score)

            # Sıcaklık ayarlı softmax normalizasyonu
            total_score = sum(scores.values())
            if total_score < 1e-10:
                n = len(scores)
                new_weights = {m: 1.0 / n for m in scores}
            else:
                temperature = 2.0
                exp_scores = {m: float(np.exp(s / temperature)) for m, s in scores.items()}
                total_exp = sum(exp_scores.values())
                new_weights = {m: es / total_exp for m, es in exp_scores.items()}

            # Asgari ve azami sınırları uygula
            for model in new_weights:
                new_weights[model] = max(self.min_weight, min(self.max_weight, new_weights[model]))

            # Sınırlandırma sonrası yeniden 1.0'a normalize et
            total = sum(new_weights.values())
            new_weights = {m: w / total for m, w in new_weights.items()}

            # Üstel hareketli ortalama ile yumuşak geçiş sağla
            if self._weights:
                for model in new_weights:
                    old = self._weights.get(model, new_weights[model])
                    new_weights[model] = old * self.decay_factor + new_weights[model] * (1.0 - self.decay_factor)

            self._weights = new_weights

            # Değişim geçmişine kaydet
            self._history.append(
                {
                    "timestamp": time.time(),
                    "weights": new_weights.copy(),
                    "metric_key": metric_key,
                }
            )

            logger.info("Ensemble ağırlıkları güncellendi", weights=new_weights)
            return new_weights.copy()

    def get_weights(self) -> dict[str, float]:
        """Mevcut model ağırlıklarının kopyasını döndürür.

        Returns:
            dict[str, float]: Model adına göre ağırlık sözlüğü.
        """
        with self._lock:
            return self._weights.copy()

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Ağırlık değişim geçmişini döndürür.

        Args:
            limit: Döndürülecek en son kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Tarihsel ağırlık güncellemeleri listesi.
        """
        with self._lock:
            return self._history[-limit:]

    def update_weights(
        self,
        model_metrics: dict[str, dict[str, float]] | None = None,
        metric_key: str = "direction_accuracy",
    ) -> dict[str, float]:
        """Mevcut model metriklerini kullanarak veya kapalı döngüden çekerek ağırlıkları günceller.

        Args:
            model_metrics: İsteğe bağlı metrik sözlüğü. Sağlanmazsa kapalı döngüden çekilir.
            metric_key: Optimizasyon metriği.

        Returns:
            dict[str, float]: Güncellenmiş ağırlıklar.
        """
        if model_metrics is None:
            try:
                from services.learning.closed_loop import closed_loop

                model_metrics = closed_loop.get_metrics()
            except Exception:
                logger.warning("Ağırlık ayarlama için metrik bulunamadı, mevcut ağırlıklar korunuyor")
                return self.get_weights()

        if not model_metrics:
            return self.get_weights()

        return self.adjust_weights(model_metrics, metric_key)

    def trigger_from_trade_result(
        self,
        model_id: str,
        prediction: float,
        actual_return: float,
        metric_key: str = "direction_accuracy",
    ) -> dict[str, float]:
        """Her işlem sonucu kapandıktan sonra ilgili modelin başarısına göre ağırlıkları günceller.

        Args:
            model_id: Tahminde bulunan model adı.
            prediction: Modelin ürettiği yön tahmini (0-1 olasılık veya yönlü skor).
            actual_return: Gerçekleşen getiri yüzdesi.
            metric_key: Güncelleme metriği.

        Returns:
            dict[str, float]: Güncellenmiş model ağırlıkları.
        """
        with self._lock:
            if model_id not in self._model_outcomes:
                self._model_outcomes[model_id] = []

            pred_dir = "UP" if prediction > 0.5 else "DOWN"
            act_dir = "UP" if actual_return > 0 else "DOWN"
            is_correct = pred_dir == act_dir

            self._model_outcomes[model_id].append(
                {
                    "prediction": prediction,
                    "actual_return": actual_return,
                    "is_correct": is_correct,
                    "timestamp": time.time(),
                }
            )

            # Son 200 sonucu sakla
            if len(self._model_outcomes[model_id]) > 200:
                self._model_outcomes[model_id] = self._model_outcomes[model_id][-200:]

            # Model metriklerini derle
            model_metrics: dict[str, dict[str, float]] = {}
            for mid, outcomes in self._model_outcomes.items():
                if len(outcomes) < 5:
                    continue

                recent = outcomes[-50:]
                accuracy = sum(1 for o in recent if o["is_correct"]) / len(recent)
                model_metrics[mid] = {
                    metric_key: float(accuracy),
                    "n_resolved": float(len(recent)),
                }

        if model_metrics:
            return self.adjust_weights(model_metrics, metric_key)

        return self.get_weights()

    def expanding_window_recalc(
        self,
        min_window: int = 100,
        metric_key: str = "direction_accuracy",
    ) -> dict[str, float]:
        """Genişleyen zaman penceresiyle tüm veri üzerinden periyodik ağırlık optimizasyonu yapar.

        Args:
            min_window: Optimizasyon için asgari işlem sonucu sayısı (varsayılan: 100).
            metric_key: Optimizasyon metriği.

        Returns:
            dict[str, float]: Güncellenmiş ağırlıklar.
        """
        with self._lock:
            model_metrics: dict[str, dict[str, float]] = {}

            for mid, outcomes in self._model_outcomes.items():
                if len(outcomes) < min_window:
                    continue

                accuracy = sum(1 for o in outcomes if o["is_correct"]) / len(outcomes)

                recent_n = min(50, len(outcomes))
                recent = outcomes[-recent_n:]
                recent_acc = sum(1 for o in recent if o["is_correct"]) / len(recent)

                # Ağırlıklı skor: %60 tüm geçmiş + %40 son dönem momentumu
                weighted_score = 0.6 * accuracy + 0.4 * recent_acc

                model_metrics[mid] = {
                    metric_key: float(weighted_score),
                    "n_resolved": float(len(outcomes)),
                }

        if model_metrics:
            return self.adjust_weights(model_metrics, metric_key)

        return self.get_weights()

    def get_weight_change_log(self, limit: int = 20) -> list[dict[str, Any]]:
        """Son ağırlık değişim loglarını döndürür.

        Args:
            limit: Döndürülecek log adedi.

        Returns:
            list[dict[str, Any]]: Güncelleme logları.
        """
        return self.get_history(limit=limit)


# Global Tekil Örnek
weight_adjuster = WeightAdjuster()
