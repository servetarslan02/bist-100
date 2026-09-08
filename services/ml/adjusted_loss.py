"""ALPHA BIST — Asimetrik Yön Cezalı Kayıp Fonksiyonu (Adjusted MSE Loss v2.0).

BIST Pay Piyasası modellerinde yanlış yön tahminlerini (ters pozisyon alma riski)
normal MSE hatalarına kıyasla katbekat daha ağır cezalandıran asimetrik kayıp motorudur.

Finansal Gerekçe:
- BIST piyasasında yön hatası (örneğin düşüş beklerken yükseliş veya yükseliş beklerken düşüş),
  büyüklük hatasından çok daha maliyetlidir (sermaye kaybı, stop-out).
- Yanlış yön tahminlerine uygulanan asimetrik ceza çarpanı modelin yön doğruluğunu
  ve nihai Sharpe oranını belirgin biçimde artırır.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Final

import numpy as np
import orjson
import structlog

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)

DEFAULT_WRONG_DIRECTION_PENALTY: Final[float] = 11.0


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


class AdjustedMSELoss:
    """Yanlış yön tahminlerini asimetrik olarak cezalandıran MSE kayıp motoru."""

    def __init__(self, wrong_direction_penalty: float = DEFAULT_WRONG_DIRECTION_PENALTY) -> None:
        """AdjustedMSELoss başlatıcı.

        Args:
            wrong_direction_penalty: Yanlış yön ceza çarpanı (varsayılan: 11.0).

        Raises:
            ValueError: Ceza çarpanı 1.0'dan küçük ise.
        """
        if wrong_direction_penalty < 1.0:
            raise ValueError(f"Ceza çarpanı 1.0'dan küçük olamaz: {wrong_direction_penalty}")

        self._lock = threading.RLock()
        self._penalty = float(wrong_direction_penalty)
        logger.info("asimetrik_kayip_motoru_baslatildi", ceza_carpani=self._penalty)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return f"AdjustedMSELoss(ceza_carpani={self._penalty}x)"

    @property
    def penalty(self) -> float:
        """Aktif ceza çarpanını döner."""
        with self._lock:
            return self._penalty

    def to_dict(self) -> dict[str, Any]:
        """Kayıp fonksiyonu yapılandırmasını sözlük formatında döner."""
        with self._lock:
            return {
                "name": "AdjustedMSELoss",
                "wrong_direction_penalty": self._penalty,
            }

    def to_orjson_bytes(self) -> bytes:
        """Kayıp fonksiyonu yapılandırmasını ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def calculate(
        self,
        predictions: np.ndarray | list[float],
        actuals: np.ndarray | list[float],
    ) -> dict[str, float]:
        """Tahmin ve gerçek değerler için asimetrik MSE metriklerini hesaplar.

        Yanlış Yön: (pred > 0 ve actual < 0) veya (pred < 0 ve actual > 0)
        → Hata karesi * ceza_carpani

        Doğru Yön: Aynı işaretli tahminler
        → Standart hata karesi

        Args:
            predictions: Model tahminleri vektörü.
            actuals: Gerçekleşen getiri değerleri vektörü.

        Returns:
            dict[str, float]: Hesaplanan metrikler sözlüğü.

        Raises:
            ValueError: Girdi boyutları eşleşmiyorsa.
        """
        with self._lock:
            preds_arr = np.asarray(predictions, dtype=np.float64)
            acts_arr = np.asarray(actuals, dtype=np.float64)

            if preds_arr.shape != acts_arr.shape:
                raise ValueError(
                    f"Tahmin ve gerçek değer boyutları uyuşmuyor: {preds_arr.shape} != {acts_arr.shape}"
                )

            total = len(preds_arr)
            if total == 0:
                return {
                    "simple_mse": 0.0,
                    "adjusted_mse": 0.0,
                    "wrong_direction_count": 0.0,
                    "wrong_direction_pct": 0.0,
                    "penalty_applied": self._penalty,
                    "direction_accuracy": 0.0,
                }

            # NaN ve Inf temizliği / doğrulaması
            valid_mask = np.isfinite(preds_arr) & np.isfinite(acts_arr)
            if not np.all(valid_mask):
                preds_arr = preds_arr[valid_mask]
                acts_arr = acts_arr[valid_mask]
                total = len(preds_arr)
                if total == 0:
                    return {
                        "simple_mse": 0.0,
                        "adjusted_mse": 0.0,
                        "wrong_direction_count": 0.0,
                        "wrong_direction_pct": 0.0,
                        "penalty_applied": self._penalty,
                        "direction_accuracy": 0.0,
                    }

            # Standart MSE
            errors = (preds_arr - acts_arr) ** 2
            simple_mse = float(np.mean(errors))

            # Yön kontrolü
            pred_direction = np.sign(preds_arr)
            actual_direction = np.sign(acts_arr)

            wrong_direction = (pred_direction != actual_direction) & (acts_arr != 0.0)

            # Asimetrik kayıp
            errors_adjusted = errors.copy()
            errors_adjusted[wrong_direction] *= self._penalty
            adjusted_mse = float(np.mean(errors_adjusted))

            wrong_count = int(np.sum(wrong_direction))
            accuracy = round((total - wrong_count) / total * 100.0, 2) if total > 0 else 0.0
            wrong_pct = round(wrong_count / total * 100.0, 2) if total > 0 else 0.0

            return {
                "simple_mse": simple_mse,
                "adjusted_mse": adjusted_mse,
                "wrong_direction_count": float(wrong_count),
                "wrong_direction_pct": wrong_pct,
                "penalty_applied": self._penalty,
                "direction_accuracy": accuracy,
            }

    def calculate_per_sample(
        self,
        prediction: float,
        actual: float,
    ) -> dict[str, float]:
        """Tek bir tahmin örneği için asimetrik kaybı hesaplar.

        Args:
            prediction: Tekil tahmin değeri.
            actual: Tekil gerçek değer.

        Returns:
            dict[str, float]: Örnek bazlı kayıp ayrıntıları.
        """
        with self._lock:
            pred_f = float(prediction)
            act_f = float(actual)

            if not np.isfinite(pred_f) or not np.isfinite(act_f):
                return {
                    "prediction": pred_f,
                    "actual": act_f,
                    "error": 0.0,
                    "is_wrong_direction": 0.0,
                    "penalty_applied": 1.0,
                }

            error = (pred_f - act_f) ** 2
            pred_dir = np.sign(pred_f)
            act_dir = np.sign(act_f)

            is_wrong = (pred_dir != act_dir) and (act_f != 0.0)
            if is_wrong:
                error *= self._penalty

            return {
                "prediction": pred_f,
                "actual": act_f,
                "error": float(error),
                "is_wrong_direction": 1.0 if is_wrong else 0.0,
                "penalty_applied": self._penalty if is_wrong else 1.0,
            }

    def get_gradient(
        self,
        predictions: np.ndarray,
        actuals: np.ndarray,
    ) -> np.ndarray:
        """Model eğitimi için birinci mertebeden gradyan (dL/dy_pred) hesaplar.

        Args:
            predictions: Model tahminleri.
            actuals: Gerçek değerler.

        Returns:
            np.ndarray: Hesaplanan gradyan vektörü.
        """
        with self._lock:
            preds_arr = np.asarray(predictions, dtype=np.float64)
            acts_arr = np.asarray(actuals, dtype=np.float64)

            if preds_arr.shape != acts_arr.shape:
                raise ValueError(
                    f"Tahmin ve gerçek değer boyutları uyuşmuyor: {preds_arr.shape} != {acts_arr.shape}"
                )

            preds_arr = np.nan_to_num(preds_arr, nan=0.0, posinf=0.0, neginf=0.0)
            acts_arr = np.nan_to_num(acts_arr, nan=0.0, posinf=0.0, neginf=0.0)

            pred_direction = np.sign(preds_arr)
            actual_direction = np.sign(acts_arr)
            wrong_direction = (pred_direction != actual_direction) & (acts_arr != 0.0)

            # dL/dy = 2 * (y_pred - y_true) * penalty (yanlış yön ise)
            gradient = 2.0 * (preds_arr - acts_arr)
            gradient[wrong_direction] *= self._penalty
            return gradient

    def get_hessian(
        self,
        predictions: np.ndarray,
        actuals: np.ndarray,
    ) -> np.ndarray:
        """Model eğitimi (LightGBM/XGBoost) için ikinci mertebeden gradyan (Hessian) hesaplar.

        Args:
            predictions: Model tahminleri.
            actuals: Gerçek değerler.

        Returns:
            np.ndarray: Hesaplanan Hessian vektörü.
        """
        with self._lock:
            preds_arr = np.asarray(predictions, dtype=np.float64)
            acts_arr = np.asarray(actuals, dtype=np.float64)

            if preds_arr.shape != acts_arr.shape:
                raise ValueError(
                    f"Tahmin ve gerçek değer boyutları uyuşmuyor: {preds_arr.shape} != {acts_arr.shape}"
                )

            preds_arr = np.nan_to_num(preds_arr, nan=0.0, posinf=0.0, neginf=0.0)
            acts_arr = np.nan_to_num(acts_arr, nan=0.0, posinf=0.0, neginf=0.0)

            pred_direction = np.sign(preds_arr)
            actual_direction = np.sign(acts_arr)
            wrong_direction = (pred_direction != actual_direction) & (acts_arr != 0.0)

            # d2L/dy2 = 2 * penalty (yanlış yön ise) aksi halde 2
            hessian = np.full_like(preds_arr, 2.0)
            hessian[wrong_direction] *= self._penalty
            return hessian

    def custom_objective(
        self,
        predictions: np.ndarray,
        actuals: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Gradient boosting modelleri için özel amaç fonksiyonu çiftini (grad, hess) döner.

        Args:
            predictions: Model tahminleri.
            actuals: Gerçek değerler.

        Returns:
            tuple[np.ndarray, np.ndarray]: (gradient, hessian).
        """
        return self.get_gradient(predictions, actuals), self.get_hessian(predictions, actuals)

    def calculate_polars(
        self,
        df: pl.DataFrame,
        pred_col: str,
        actual_col: str,
    ) -> dict[str, float]:
        """Polars DataFrame sütunları üzerinden doğrudan asimetrik MSE hesaplar.

        Args:
            df: Veri içeren Polars DataFrame.
            pred_col: Tahmin sütunu adı.
            actual_col: Gerçek değer sütunu adı.

        Returns:
            dict[str, float]: Hesaplanan kayıp metrikleri.

        Raises:
            KeyError: Belirtilen sütunlar tabloda mevcut değilse.
        """
        if pred_col not in df.columns or actual_col not in df.columns:
            raise KeyError(f"Sütunlar bulunamadı: {pred_col}, {actual_col} (Mevcut: {df.columns})")

        preds = df[pred_col].to_numpy()
        actuals = df[actual_col].to_numpy()
        return self.calculate(preds, actuals)


# Singleton Örneği
adjusted_loss: Final[AdjustedMSELoss] = AdjustedMSELoss()

__all__: Final[list[str]] = [
    "AdjustedMSELoss",
    "DEFAULT_WRONG_DIRECTION_PENALTY",
    "adjusted_loss",
    "to_orjson_bytes",
]
