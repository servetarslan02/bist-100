"""ALPHA BIST — Probability Calibration Engine (Nihai — ⭐⭐⭐⭐⭐).

Model çıktılarını (CatBoost, XGBoost, LightGBM) gerçek olasılıklara dönüştürür.
Platt Scaling (Sigmoid) ve Isotonic Regression destekler.
Brier Skoru ve ECE (Expected Calibration Error) hesaplayarak güvenilirliği doğrular.
"""

from typing import Any
import numpy as np
import structlog
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss

logger = structlog.get_logger()


def compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error (ECE) hesapla.
    
    Olasılıkları [0, 1] aralığında n_bins parçaya böler ve
    tahmin edilen güven ile gerçek doğruluk arasındaki farkın ağırlıklı ortalamasını alır.
    """
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_indices = np.digitize(y_prob, bins) - 1
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)

    ece = 0.0
    total_samples = len(y_prob)

    for i in range(n_bins):
        mask = bin_indices == i
        bin_count = np.sum(mask)
        if bin_count > 0:
            bin_acc = np.mean(y_true[mask])
            bin_conf = np.mean(y_prob[mask])
            ece += (bin_count / total_samples) * abs(bin_acc - bin_conf)

    return float(ece)


class ProbabilityCalibrator:
    """Sınıflandırıcı modellerin ham çıktılarını kalibre eder."""

    def __init__(self, method: str = "sigmoid"):
        """Args:
            method: 'sigmoid' (Platt scaling) veya 'isotonic'.
        """
        self.method = method
        self.calibrator: Any = None
        self.is_fitted = False
        self.raw_brier: float = 0.0
        self.calibrated_brier: float = 0.0
        self.raw_ece: float = 0.0
        self.calibrated_ece: float = 0.0

    def fit(self, y_raw_scores: np.ndarray, y_true: np.ndarray) -> "ProbabilityCalibrator":
        """Kalibratörü eğit ve Brier skoru ile ECE iyileşmesini kaydet."""
        y_raw = np.asarray(y_raw_scores, dtype=np.float64).flatten()
        y_label = np.asarray(y_true, dtype=np.int32).flatten()

        # Raw skorları [0, 1] sınırla
        y_raw_prob = np.clip(y_raw, 1e-4, 1.0 - 1e-4)
        self.raw_brier = float(brier_score_loss(y_label, y_raw_prob))
        self.raw_ece = compute_ece(y_label, y_raw_prob)

        if self.method == "sigmoid":
            # Platt Scaling: Logistic Regression
            lr = LogisticRegression(C=1.0, solver="lbfgs")
            X = y_raw.reshape(-1, 1)
            lr.fit(X, y_label)
            self.calibrator = lr
        elif self.method == "isotonic":
            # Isotonic Regression
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(y_raw, y_label)
            self.calibrator = iso
        else:
            raise ValueError(f"Bilinmeyen kalibrasyon yöntemi: {self.method}")

        self.is_fitted = True

        # Kalibre edilmiş metrikler
        y_cal_prob = self.calibrate(y_raw)
        self.calibrated_brier = float(brier_score_loss(y_label, y_cal_prob))
        self.calibrated_ece = compute_ece(y_label, y_cal_prob)

        logger.info(
            "model_probability_calibrated",
            method=self.method,
            raw_brier=round(self.raw_brier, 4),
            calibrated_brier=round(self.calibrated_brier, 4),
            raw_ece=round(self.raw_ece, 4),
            calibrated_ece=round(self.calibrated_ece, 4),
            ece_improvement_pct=round((1.0 - self.calibrated_ece / max(self.raw_ece, 1e-6)) * 100.0, 1),
        )

        return self

    def calibrate(self, y_raw_scores: np.ndarray) -> np.ndarray:
        """Ham model skorlarını kalibre edilmiş güven/olasılık değerine çevir."""
        if not self.is_fitted or self.calibrator is None:
            return np.clip(y_raw_scores, 0.0, 1.0)

        y_raw = np.asarray(y_raw_scores, dtype=np.float64).flatten()
        if self.method == "sigmoid":
            probs = self.calibrator.predict_proba(y_raw.reshape(-1, 1))[:, 1]
        else:
            probs = self.calibrator.predict(y_raw)

        return np.clip(probs, 0.0, 1.0)

    def get_metrics(self) -> dict[str, float]:
        """Kalibrasyon metriklerini döndür."""
        return {
            "method": self.method,
            "raw_brier": self.raw_brier,
            "calibrated_brier": self.calibrated_brier,
            "raw_ece": self.raw_ece,
            "calibrated_ece": self.calibrated_ece,
        }
