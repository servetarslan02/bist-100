"""
ALPHA BIST — Hidden Markov Model (HMM) Piyasa Rejim Tespiti v3.0 (HMM Regime Detector)

BIST endeks ve pay senetlerinde piyasa dinamiklerini Gizli Markov Modelleri (HMM)
ve istatistiksel Gaussian karışım bileşenleri ile tespit eden kurumsal rejim motoru.

Özellikler:
  - 4 Temel Piyasa Rejimi: BULL (Boğa), BEAR (Ayı), HIGH_VOL (Yüksek Oynaklık), LOW_VOL (Düşük Oynaklık)
  - Çok Boyutlu Girdi: Günlük Getiri (Return) ve Volatilite (EWMA Volatility)
  - Çeyreklik (Quarterly / 63 İş Günü) Rolling Walk-Forward Yeniden Eğitim
  - Geçiş Olasılık Matrisi (Transition Matrix) ve Rejim Kalıcılık / Entropi Analizi
  - Güvenli Fallback: hmmlearn kütüphanesi yoksa veya veri yetersizse matematiksel kural tabanlı koruma
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import orjson
import structlog

logger = structlog.get_logger(__name__)

# hmmlearn kütüphanesini dinamik olarak yükle
try:
    from hmmlearn.hmm import GaussianHMM

    HMM_AVAILABLE = True
except ImportError:
    GaussianHMM = None  # type: ignore[assignment,misc]
    HMM_AVAILABLE = False
    logger.info("hmmlearn_bulunamadi_kural_tabanli_fallback_aktif")

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_N_REGIMES: int = 4
DEFAULT_ROLLING_WINDOW: int = 63  # 1 Çeyrek (Quarter)
DEFAULT_RETRAIN_INTERVAL: int = 63
DEFAULT_HMM_N_ITER: int = 100
DEFAULT_HMM_TOL: float = 1e-4
DEFAULT_RANDOM_STATE: int = 42
DEFAULT_MAX_HISTORY_LEN: int = 1000
DEFAULT_BULL_RETURN_THRESHOLD: float = 0.001
DEFAULT_BEAR_RETURN_THRESHOLD: float = -0.001
DEFAULT_LOW_VOL_THRESHOLD: float = 0.018
DEFAULT_HIGH_VOL_THRESHOLD: float = 0.025
DEFAULT_FALLBACK_CONFIDENCE: float = 0.60

REGIME_NAMES: list[str] = ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"]


@dataclass
class HMMRegimeResult:
    """HMM veya kural tabanlı piyasa rejimi tespit çıktısı.

    Attributes:
        regime: Aktif rejim adı ("BULL", "BEAR", "HIGH_VOL", "LOW_VOL", "UNKNOWN").
        confidence: Rejimin gerçekleşme güven / olasılık skoru [0.0, 1.0].
        probabilities: Tüm rejimlere ait olasılık dağılımı.
        regime_index: Rejim sayısal indeksi (0-3).
        transition_matrix: Geçiş olasılık matrisi (opsiyonel).
        timestamp: Analiz zaman damgası (UTC).
    """

    regime: str
    confidence: float
    probabilities: dict[str, float]
    regime_index: int
    transition_matrix: np.ndarray | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"<HMMRegimeResult regime={self.regime!r} conf={self.confidence:.2f} "
            f"idx={self.regime_index} ts={self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serileştirilebilir sözlük çıktısı döner."""
        return {
            "regime": self.regime,
            "confidence": round(self.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
            "regime_index": self.regime_index,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_json(self) -> str:
        """orjson ile yüksek performanslı JSON metni üretir."""
        return orjson.dumps(self.to_dict()).decode("utf-8")


class HMMRegimeDetector:
    """Gizli Markov Modeli (HMM) ve Gaussian Dağılımı ile BIST piyasa rejimi sınıflandırıcısı."""

    REGIME_NAMES: list[str] = REGIME_NAMES

    def __init__(
        self,
        n_regimes: int = DEFAULT_N_REGIMES,
        rolling_window: int = DEFAULT_ROLLING_WINDOW,
        retrain_interval: int = DEFAULT_RETRAIN_INTERVAL,
    ) -> None:
        """HMM Rejim Tespit Motorunu başlatır."""
        self.n_regimes = n_regimes
        self.rolling_window = rolling_window
        self.retrain_interval = retrain_interval

        self._model: Any = None
        self._is_fitted: bool = False
        self._last_train_size: int = 0
        self._last_retrain_index: int = 0
        self._regime_history: deque[HMMRegimeResult] = deque(maxlen=DEFAULT_MAX_HISTORY_LEN)
        self._transition_matrix: np.ndarray | None = None

    def __repr__(self) -> str:
        return (
            f"<HMMRegimeDetector n_regimes={self.n_regimes} window={self.rolling_window} "
            f"fitted={self._is_fitted} history={len(self._regime_history)}>"
        )

    def fit(self, returns: np.ndarray | list[float], volatility: np.ndarray | list[float]) -> bool:
        """HMM modelini geçmiş getiri ve volatilite matrisi ile eğitir.

        Args:
            returns: Günlük getiri serisi (dizi veya liste).
            volatility: Günlük volatilite serisi (dizi veya liste).

        Returns:
            bool: Eğitim başarılı olduysa True, fallback gerekiyorsa False.
        """
        if not HMM_AVAILABLE or GaussianHMM is None:
            logger.debug("hmmlearn_bulunamadi_fit_atlanarak_fallback_kullanilacak")
            return False

        r_arr = np.asarray(returns, dtype=float)
        v_arr = np.asarray(volatility, dtype=float)

        if len(r_arr) < self.rolling_window or len(v_arr) < self.rolling_window:
            logger.warning(
                "hmm_yetersiz_veri_egitimi",
                veri_boyutu=min(len(r_arr), len(v_arr)),
                gereken=self.rolling_window,
            )
            return False

        try:
            train_returns = r_arr[-self.rolling_window :]
            train_vol = v_arr[-self.rolling_window :]

            # 2D Özellik Matrisi: [Getiri, Volatilite]
            x_mat = np.column_stack([train_returns, train_vol])
            mask = np.isfinite(x_mat).all(axis=1)
            x_clean = x_mat[mask]

            if len(x_clean) < 20:
                logger.warning("hmm_gecerli_gozlem_yetersiz", gecerli_sayisi=len(x_clean))
                return False

            model = GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="diag",
                n_iter=DEFAULT_HMM_N_ITER,
                random_state=DEFAULT_RANDOM_STATE,
                tol=DEFAULT_HMM_TOL,
            )
            model.fit(x_clean)

            self._model = model
            self._is_fitted = True
            self._last_train_size = len(x_clean)
            self._transition_matrix = getattr(model, "transmat_", None)

            logger.info(
                "hmm_egitildi",
                rejim_sayisi=self.n_regimes,
                ornek_sayisi=len(x_clean),
                entropi=self._compute_transition_entropy(),
            )
            return True

        except Exception as e:
            logger.warning("hmm_egitim_hatasi", hata=str(e))
            self._is_fitted = False
            return False

    def predict_regime(
        self,
        returns: np.ndarray | list[float],
        volatility: np.ndarray | list[float],
    ) -> HMMRegimeResult:
        """Mevcut getiri ve volatilite verilerine göre aktif piyasa rejimini tahmin eder.

        Args:
            returns: Son dönem getiri serisi.
            volatility: Son dönem volatilite serisi.

        Returns:
            HMMRegimeResult: Belirlenen rejim ve olasılık değerleri.
        """
        r_arr = np.asarray(returns, dtype=float)
        v_arr = np.asarray(volatility, dtype=float)

        if not self._is_fitted or self._model is None:
            result = self._rule_based_fallback(r_arr, v_arr)
            self._regime_history.append(result)
            return result

        try:
            if len(r_arr) == 0 or len(v_arr) == 0:
                return self._rule_based_fallback(r_arr, v_arr)

            x_curr = np.column_stack([r_arr[-1:], v_arr[-1:]])
            if not np.isfinite(x_curr).all():
                return self._rule_based_fallback(r_arr, v_arr)

            regime_idx = int(self._model.predict(x_curr)[0])
            probs = self._model.predict_proba(x_curr)[0]

            regime_names = self._assign_regime_names(probs)
            active_name = regime_names[regime_idx] if regime_idx < len(regime_names) else "UNKNOWN"

            prob_dict = {
                regime_names[i]: float(probs[i])
                for i in range(min(len(regime_names), len(probs)))
            }

            result = HMMRegimeResult(
                regime=active_name,
                confidence=float(probs[regime_idx]),
                probabilities=prob_dict,
                regime_index=regime_idx,
                transition_matrix=self._transition_matrix,
            )
            self._regime_history.append(result)
            return result

        except Exception as e:
            logger.warning("hmm_tahmin_hatasi_fallbacke_geciliyor", hata=str(e))
            fallback_res = self._rule_based_fallback(r_arr, v_arr)
            self._regime_history.append(fallback_res)
            return fallback_res

    def rolling_detect(
        self,
        returns: np.ndarray | list[float],
        volatility: np.ndarray | list[float],
    ) -> list[HMMRegimeResult]:
        """Tüm zaman serisi boyunca çeyreklik aralıklarla HMM'i yeniden eğitip ardışık tahmin üretir.

        Args:
            returns: Tam getiri serisi.
            volatility: Tam volatilite serisi.

        Returns:
            list[HMMRegimeResult]: Sıralı rejim tahminleri dizisi.
        """
        r_arr = np.asarray(returns, dtype=float)
        v_arr = np.asarray(volatility, dtype=float)
        n = min(len(r_arr), len(v_arr))

        results: list[HMMRegimeResult] = []
        if n < self.rolling_window:
            logger.warning("rolling_tespit_icin_yetersiz_veri", boyut=n, gereken=self.rolling_window)
            return results

        for i in range(self.rolling_window, n):
            # Yeniden eğitim kontrolü
            if i - self._last_retrain_index >= self.retrain_interval:
                w_start = max(0, i - self.rolling_window)
                self.fit(r_arr[w_start:i], v_arr[w_start:i])
                self._last_retrain_index = i

            res = self.predict_regime(
                r_arr[max(0, i - 5) : i + 1],
                v_arr[max(0, i - 5) : i + 1],
            )
            results.append(res)

        logger.info(
            "rolling_tespit_tamamlandi",
            toplam_tahmin=len(results),
            yeniden_egitim_sayisi=(n - self.rolling_window) // self.retrain_interval,
        )
        return results

    def _assign_regime_names(self, probabilities: np.ndarray) -> list[str]:
        """HMM durum indekslerini getiri ve volatilite ortalamalarına göre finansal rejim isimlerine eşler."""
        if self._model is None or not hasattr(self._model, "means_"):
            return self.REGIME_NAMES[: len(probabilities)]

        try:
            # 0. Sütun: Ortalama Getiri
            means = self._model.means_[:, 0]
            sorted_indices = np.argsort(-means)

            name_mapping: dict[int, str] = {}
            # En yüksek getiri -> BULL
            name_mapping[int(sorted_indices[0])] = "BULL"
            # En düşük getiri -> BEAR
            name_mapping[int(sorted_indices[-1])] = "BEAR"

            # Aradaki rejimler: Volatiliteye göre ayrıştırılır
            remaining = [int(i) for i in sorted_indices[1:-1]]
            if len(remaining) >= 2:
                vol_means = self._model.means_[remaining, 1]
                if vol_means[0] > vol_means[1]:
                    name_mapping[remaining[0]] = "HIGH_VOL"
                    name_mapping[remaining[1]] = "LOW_VOL"
                else:
                    name_mapping[remaining[0]] = "LOW_VOL"
                    name_mapping[remaining[1]] = "HIGH_VOL"

            return [name_mapping.get(i, f"REGIME_{i}") for i in range(len(probabilities))]
        except Exception:
            return self.REGIME_NAMES[: len(probabilities)]

    def _rule_based_fallback(
        self,
        returns: np.ndarray,
        volatility: np.ndarray,
    ) -> HMMRegimeResult:
        """HMM mevcut olmadığında sağlam istatistiksel kural tabanlı rejim tespiti."""
        if len(returns) == 0:
            return HMMRegimeResult(
                regime="UNKNOWN",
                confidence=0.0,
                probabilities={name: 0.25 for name in self.REGIME_NAMES},
                regime_index=-1,
            )

        avg_return = float(np.mean(returns[-20:])) if len(returns) >= 20 else float(np.mean(returns))
        avg_vol = float(np.mean(volatility[-20:])) if len(volatility) >= 20 else float(np.mean(volatility))

        if avg_vol >= DEFAULT_HIGH_VOL_THRESHOLD:
            regime = "HIGH_VOL"
            confidence = 0.65
        elif avg_return > DEFAULT_BULL_RETURN_THRESHOLD and avg_vol < DEFAULT_LOW_VOL_THRESHOLD:
            regime = "BULL"
            confidence = 0.70
        elif avg_return < DEFAULT_BEAR_RETURN_THRESHOLD:
            regime = "BEAR"
            confidence = 0.65
        else:
            regime = "LOW_VOL"
            confidence = 0.60

        # Olasılık dağılımını toplamı 1.0 olacak şekilde normalize et
        other_prob = (1.0 - confidence) / max(len(self.REGIME_NAMES) - 1, 1)
        probs = {name: round(other_prob, 4) for name in self.REGIME_NAMES}
        probs[regime] = round(confidence, 4)

        reg_idx = self.REGIME_NAMES.index(regime) if regime in self.REGIME_NAMES else 0

        return HMMRegimeResult(
            regime=regime,
            confidence=confidence,
            probabilities=probs,
            regime_index=reg_idx,
        )

    def _compute_transition_entropy(self) -> float:
        """Geçiş olasılık matrisinin Shannon entropisini ve durağanlık derecesini hesaplar."""
        if self._transition_matrix is None:
            return 0.0

        entropy = 0.0
        for row in self._transition_matrix:
            for p in row:
                if p > 0:
                    entropy -= p * np.log2(p)
        max_entropy = np.log2(self.n_regimes) if self.n_regimes > 1 else 1.0
        return round(float(entropy / (self.n_regimes * max_entropy)), 4)

    def get_transition_matrix(self) -> dict[str, dict[str, float]] | None:
        """Okunabilir isimlerle yapılandırılmış rejim geçiş matrisini döner."""
        if self._transition_matrix is None:
            return None

        matrix: dict[str, dict[str, float]] = {}
        for i, from_name in enumerate(self.REGIME_NAMES):
            matrix[from_name] = {}
            for j, to_name in enumerate(self.REGIME_NAMES):
                if i < self._transition_matrix.shape[0] and j < self._transition_matrix.shape[1]:
                    matrix[from_name][to_name] = round(float(self._transition_matrix[i, j]), 4)
                else:
                    matrix[from_name][to_name] = 0.0
        return matrix

    def get_regime_duration_stats(self) -> dict[str, dict[str, float]]:
        """Geçmiş tahminlerde rejimlerin ortalama ve maksimum sürüş periyotlarını döner."""
        if not self._regime_history:
            return {}

        durations: dict[str, list[int]] = {}
        current_regime: str | None = None
        current_dur = 0

        for r in self._regime_history:
            if r.regime == current_regime:
                current_dur += 1
            else:
                if current_regime:
                    durations.setdefault(current_regime, []).append(current_dur)
                current_regime = r.regime
                current_dur = 1

        if current_regime:
            durations.setdefault(current_regime, []).append(current_dur)

        stats: dict[str, dict[str, float]] = {}
        for reg, durs in durations.items():
            if durs:
                stats[reg] = {
                    "avg_duration_days": round(float(np.mean(durs)), 1),
                    "max_duration_days": float(max(durs)),
                    "total_occurrences": float(len(durs)),
                }
        return stats

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Son kayıtlı rejim tahminlerini JSON serileştirilebilir liste halinde döner."""
        history = list(self._regime_history)[-limit:]
        return [r.to_dict() for r in history]

    @property
    def is_fitted(self) -> bool:
        """Modelin GaussianHMM ile başarıyla eğitilip eğitilmediğini belirtir."""
        return self._is_fitted

    @property
    def current_regime(self) -> str | None:
        """En son tespit edilen aktif piyasa rejimi."""
        if self._regime_history:
            return self._regime_history[-1].regime
        return None


# Singleton Örneği
hmm_regime_detector = HMMRegimeDetector()

__all__ = [
    "HMMRegimeDetector",
    "HMMRegimeResult",
    "hmm_regime_detector",
]
