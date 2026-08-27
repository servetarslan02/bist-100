"""ALPHA BIST — Model Comparator (Nihai).

IC, Precision@K, Hit Rate, Sharpe Ratio, Max Drawdown, Calibration Score.
Faz 2 gereksinimleri: kapsamlı model karşılaştırma.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class ModelResult:
    """Model karşılaştırma sonucu."""
    name: str
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    ic: float = 0.0               # Information Coefficient (Spearman correlation)
    precision_at_k: float = 0.0   # Top-K'taki isabet oranı
    hit_rate: float = 0.0         # Yön doğruluğu
    sharpe_ratio: float = 0.0     # Risk-ayarlı getiri
    max_drawdown: float = 0.0     # Maksimum düşüş
    calibration_score: float = 0.0 # Brier score (düşük = iyi)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "ic": round(self.ic, 4),
            "precision_at_k": round(self.precision_at_k, 4),
            "hit_rate": round(self.hit_rate, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "calibration_score": round(self.calibration_score, 4),
        }

    @property
    def composite_score(self) -> float:
        """Ağırlıklı bileşik skor (karşılaştırma için)."""
        return (
            self.ic * 0.25
            + self.precision_at_k * 0.20
            + self.hit_rate * 0.15
            + self.sharpe_ratio * 0.15
            + (1.0 - self.calibration_score) * 0.10
            + self.f1 * 0.10
            + self.accuracy * 0.05
        )


class ModelComparator:
    """Kapsamlı model karşılaştırma — IC, Precision@K, Sharpe, drawdown, calibration."""

    def __init__(self, k: int = 10, annualization_factor: float = 252):
        """
        Args:
            k: Precision@K için top-K parametresi
            annualization_factor: Sharpe için yıllıklaştırma (252 iş günü)
        """
        self.k = k
        self.annualization_factor = annualization_factor

    def compare(
        self,
        models: dict[str, Callable],
        X_test: np.ndarray,
        y_test: np.ndarray,
        returns: np.ndarray | None = None,
        y_prob: dict[str, np.ndarray] | None = None,
    ) -> list[ModelResult]:
        """Modelleri kapsamlı karşılaştır.

        Args:
            models: {model_name: predict_fn} sözlüğü
            X_test: Test特征leri
            y_test: Gerçek etiketler (0/1 veya getiri)
            returns: Gerçek getiriler (Sharpe/drawdown için, opsiyonel)
            y_prob: {model_name: probabilities} Kalibrasyon skoru için (opsiyonel)

        Returns:
            Sıralı ModelResult listesi (composite_score'a göre)
        """
        results = []

        for name, predict_fn in models.items():
            try:
                preds = predict_fn(X_test)
                result = self._evaluate_model(
                    name=name,
                    preds=preds,
                    y_test=y_test,
                    returns=returns,
                    probabilities=y_prob.get(name) if y_prob else None,
                )
                results.append(result)
            except Exception as e:
                logger.warning("model_comparison_failed", model=name, error=str(e))
                results.append(ModelResult(name=name))

        # Composite score'a göre sırala (yüksek = iyi)
        results.sort(key=lambda r: r.composite_score, reverse=True)
        return results

    def _evaluate_model(
        self,
        name: str,
        preds: np.ndarray,
        y_test: np.ndarray,
        returns: np.ndarray | None = None,
        probabilities: np.ndarray | None = None,
    ) -> ModelResult:
        """Tek bir modeli değerlendir."""

        # Binary predictions
        binary_preds = (preds > 0.5).astype(int)
        binary_true = (y_test > 0.5).astype(int) if np.max(y_test) <= 1.0 else y_test.astype(int)

        # 1. Accuracy
        accuracy = float(np.mean(binary_preds == binary_true))

        # 2. Precision, Recall, F1
        tp = int(np.sum((binary_preds == 1) & (binary_true == 1)))
        fp = int(np.sum((binary_preds == 1) & (binary_true == 0)))
        fn = int(np.sum((binary_preds == 0) & (binary_true == 1)))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        # 3. IC (Information Coefficient — Spearman rank correlation)
        ic = 0.0
        if len(np.unique(preds)) > 1 and len(np.unique(y_test)) > 1:
            try:
                from scipy.stats import spearmanr
                ic_val, _ = spearmanr(preds, y_test)
                ic = float(ic_val) if not np.isnan(ic_val) else 0.0
            except Exception:
                try:
                    ic = float(np.corrcoef(preds, y_test)[0, 1])
                    if np.isnan(ic):
                        ic = 0.0
                except Exception:
                    ic = 0.0

        # 4. Precision@K
        precision_at_k = self._precision_at_k(preds, y_test, self.k)

        # 5. Hit Rate (yön doğruluğu)
        hit_rate = self._hit_rate(preds, y_test)

        # 6. Sharpe Ratio
        sharpe_ratio = 0.0
        if returns is not None:
            sharpe_ratio = self._sharpe_ratio(preds, returns)

        # 7. Max Drawdown
        max_drawdown = 0.0
        if returns is not None:
            max_drawdown = self._max_drawdown(preds, returns)

        # 8. Calibration Score (Brier score)
        calibration_score = 0.0
        if probabilities is not None:
            calibration_score = self._calibration_score(y_test, probabilities)

        return ModelResult(
            name=name,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1=f1,
            ic=ic,
            precision_at_k=precision_at_k,
            hit_rate=hit_rate,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            calibration_score=calibration_score,
        )

    def _precision_at_k(self, preds: np.ndarray, y_test: np.ndarray, k: int) -> float:
        """Top-K tahminlerdeki isabet oranı.

        En yüksek K tahmini al, bunların kaçta kaçı gerçekten pozitif?
        """
        if len(preds) < k:
            k = max(len(preds) // 5, 1)

        top_k_indices = np.argsort(preds)[-k:]
        top_k_true = y_test[top_k_indices]
        return float(np.mean(top_k_true > 0)) if len(top_k_true) > 0 else 0.0

    def _hit_rate(self, preds: np.ndarray, y_test: np.ndarray) -> float:
        """Yön doğruluğu — tahmin yönü ile gerçek yön uyuşma oranı.

        Hem pozitif hem negatif sınıflar için yön doğruluğunu hesaplar.
        """
        if len(preds) == 0 or len(y_test) == 0:
            return 0.0

        # Tahmin yönü ve gerçek yön
        pred_direction = (preds > 0.5).astype(int)
        true_direction = (y_test > 0.5).astype(int) if np.max(y_test) <= 1.0 else (y_test > 0).astype(int)

        return float(np.mean(pred_direction == true_direction))

    def _sharpe_ratio(self, preds: np.ndarray, returns: np.ndarray) -> float:
        """Tahmin bazlı Sharpe ratio.

        Model'in BUY dediği hisselerin ortalama getirisi / std.
        """
        if len(preds) == 0 or len(returns) == 0:
            return 0.0

        # BUY sinyali veren hisselerin getirisi
        buy_mask = preds > 0.5
        if not np.any(buy_mask):
            return 0.0

        buy_returns = returns[buy_mask]
        mean_ret = float(np.mean(buy_returns))
        std_ret = float(np.std(buy_returns))

        if std_ret < 1e-8:
            return 0.0

        # Yıllıklaştırılmış Sharpe (risk-free rate = 0 varsayımı)
        return round((mean_ret / std_ret) * np.sqrt(self.annualization_factor), 4)

    def _max_drawdown(self, preds: np.ndarray, returns: np.ndarray) -> float:
        """Tahmin bazlı max drawdown.

        Model'in portföyünün kümülatif getirisinden max drawdown.
        """
        if len(preds) == 0 or len(returns) == 0:
            return 0.0

        # BUY sinyali veren hisselerin eşit ağırlıklı portföy getirisi
        buy_mask = preds > 0.5
        if not np.any(buy_mask):
            return 0.0

        portfolio_returns = returns[buy_mask]
        cumulative = np.cumsum(portfolio_returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max

        max_dd = float(np.min(drawdown))
        return round(abs(max_dd), 4)

    def _calibration_score(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        """Brier score — kalibrasyon kalitesi (düşük = iyi)."""
        try:
            from sklearn.metrics import brier_score_loss
            return float(brier_score_loss(y_true, y_prob))
        except Exception:
            return 0.5  # Varsayılan: kötü kalibrasyon


# Singleton
model_comparator = ModelComparator()
