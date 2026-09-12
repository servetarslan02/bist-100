"""
ALPHA BIST — HMM Regime Detector v1.1

Hidden Markov Model ile matematiksel rejim tespiti.

Rolling HMM: Her 63 günde yeniden eğit (quarterly).
4 rejim: BULL, BEAR, HIGH_VOL, LOW_VOL
Feature: return + volatility (2D)

Fallback: hmmlearn yoksa rule-based detection.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# hmmlearn opsiyonel
try:
    from hmmlearn.hmm import GaussianHMM

    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.info("hmmlearn_yuklu_degil", msg="Rule-based fallback kullanılacak")

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_N_REGIMES: int = 4
DEFAULT_ROLLING_WINDOW: int = 63           # Quarterly
DEFAULT_RETRAIN_INTERVAL: int = 63
MAX_HISTORY_SIZE: int = 500
HISTORY_TRIM_SIZE: int = 1000
MIN_TRAIN_OBSERVATIONS: int = 20
HMM_N_ITER: int = 100
HMM_RANDOM_STATE: int = 42
HMM_TOLERANCE: float = 1e-4
FALLBACK_LOOKBACK: int = 20
FALLBACK_RETURN_POSITIVE: float = 0.001
FALLBACK_RETURN_NEGATIVE: float = -0.001
FALLBACK_VOL_HIGH: float = 0.025
FALLBACK_VOL_LOW: float = 0.02
FALLBACK_CONF_HIGH: float = 0.6
FALLBACK_CONF_LOW: float = 0.5
FALLBACK_UNIFORM_PROB: float = 0.1
PREDICT_LOOKBACK: int = 5

__all__ = [
    "HMMRegimeResult",
    "HMMRegimeDetector",
    "hmm_regime_detector",
]


@dataclass
class HMMRegimeResult:
    """HMM rejim sonucu.

    Tahmin edilen rejim, olasılıklar ve geçiş matrisi bilgisi.
    """

    regime: str
    confidence: float
    probabilities: dict[str, float]
    regime_index: int
    transition_matrix: np.ndarray | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"<HMMRegimeResult regime={self.regime!r} conf={self.confidence:.3f} "
            f"idx={self.regime_index}>"
        )


class HMMRegimeDetector:
    """Hidden Markov Model ile rejim tespiti.

    Args:
        n_regimes: Rejim sayısı.
        rolling_window: Rolling eğitim penceresi (gün).
        retrain_interval: Yeniden eğitim aralığı (gün).
    """

    REGIME_NAMES: list[str] = ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"]

    def __repr__(self) -> str:
        return (
            f"<HMMRegimeDetector regimes={self.n_regimes} "
            f"fitted={self._is_fitted} history={len(self._regime_history)}>"
        )

    def __init__(
        self,
        n_regimes: int = DEFAULT_N_REGIMES,
        rolling_window: int = DEFAULT_ROLLING_WINDOW,
        retrain_interval: int = DEFAULT_RETRAIN_INTERVAL,
    ) -> None:
        """HMM rejim dedektörünü başlat.

        Args:
            n_regimes: Rejim sayısı.
            rolling_window: Rolling eğitim penceresi.
            retrain_interval: Yeniden eğitim aralığı.
        """
        self.n_regimes = n_regimes
        self.rolling_window = rolling_window
        self.retrain_interval = retrain_interval

        self._model: object | None = None
        self._is_fitted: bool = False
        self._last_train_size: int = 0
        self._last_retrain_index: int = 0
        self._regime_history: deque[HMMRegimeResult] = deque(maxlen=MAX_HISTORY_SIZE)
        self._transition_matrix: np.ndarray | None = None

    def fit(self, returns: np.ndarray, volatility: np.ndarray) -> bool:
        """HMM modelini eğit.

        Args:
            returns: Günlük getiri serisi.
            volatility: Günlük volatilite serisi.

        Returns:
            True: Eğitim başarılı, False: Fallback kullanıldı.
        """
        if not HMM_AVAILABLE:
            logger.debug("hmmlearn_bulunamadi", msg="Rule-based fallback")
            return False

        if len(returns) < self.rolling_window:
            logger.warning("hmm_veri_yetersiz", data_len=len(returns), required=self.rolling_window)
            return False

        try:
            train_returns = returns[-self.rolling_window:]
            train_vol = volatility[-self.rolling_window:]
            X = np.column_stack([train_returns, train_vol])

            # NaN/inf temizle
            mask = np.isfinite(X).all(axis=1)
            X = X[mask]

            if len(X) < MIN_TRAIN_OBSERVATIONS:
                logger.warning("hmm_gecerli_gozlem_yetersiz", valid_len=len(X))
                return False

            self._model = GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="diag",
                n_iter=HMM_N_ITER,
                random_state=HMM_RANDOM_STATE,
                tol=HMM_TOLERANCE,
            )
            self._model.fit(X)

            self._is_fitted = True
            self._last_train_size = len(X)
            self._transition_matrix = self._model.transmat_

            logger.info(
                "hmm_egitildi",
                n_regimes=self.n_regimes,
                train_size=len(X),
                transition_entropy=self._compute_transition_entropy(),
            )
            return True

        except Exception as e:
            logger.warning("hmm_egitim_hatasi", error=str(e))
            self._is_fitted = False
            return False

    def predict_regime(self, returns: np.ndarray, volatility: np.ndarray) -> HMMRegimeResult:
        """Mevcut rejimi tahmin et.

        Args:
            returns: Son N günlük getiri.
            volatility: Son N günlük volatilite.

        Returns:
            HMMRegimeResult: Tahmin sonucu.
        """
        if not self._is_fitted or self._model is None:
            result = self._rule_based_fallback(returns, volatility)
            self._append_history(result)
            return result

        try:
            X = np.column_stack([returns[-1:], volatility[-1:]])
            regime_idx = self._model.predict(X)[0]
            probs = self._model.predict_proba(X)[0]
            regime_names = self._assign_regime_names(probs)

            result = HMMRegimeResult(
                regime=regime_names[regime_idx],
                confidence=float(probs[regime_idx]),
                probabilities={name: float(probs[i]) for i, name in enumerate(regime_names)},
                regime_index=int(regime_idx),
                transition_matrix=self._transition_matrix,
            )
            self._append_history(result)
            return result

        except Exception as e:
            logger.warning("hmm_tahmin_hatasi", error=str(e))
            return self._rule_based_fallback(returns, volatility)

    def rolling_detect(self, returns: np.ndarray, volatility: np.ndarray) -> list[HMMRegimeResult]:
        """Rolling rejim tespiti.

        Her retrain_interval günde yeniden eğit ve tahmin yap.

        Args:
            returns: Tüm getiri serisi.
            volatility: Tüm volatilite serisi.

        Returns:
            Tahmin listesi.
        """
        results: list[HMMRegimeResult] = []
        n = len(returns)

        if n < self.rolling_window:
            logger.warning("rolling_icin_veri_yetersiz", n=n, required=self.rolling_window)
            return results

        for i in range(self.rolling_window, n):
            if i - self._last_retrain_index >= self.retrain_interval:
                train_returns = returns[max(0, i - self.rolling_window):i]
                train_vol = volatility[max(0, i - self.rolling_window):i]
                self.fit(train_returns, train_vol)
                self._last_retrain_index = i

            result = self.predict_regime(
                returns[max(0, i - PREDICT_LOOKBACK):i + 1],
                volatility[max(0, i - PREDICT_LOOKBACK):i + 1],
            )
            results.append(result)

        logger.info(
            "rolling_tespit_tamamlandi",
            total_predictions=len(results),
            retrains=(n - self.rolling_window) // self.retrain_interval,
        )
        return results

    def _assign_regime_names(self, probabilities: np.ndarray) -> list[str]:
        """Rejim indekslerini anlamlı isimlere eşle.

        Args:
            probabilities: Rejim olasılıkları dizisi.

        Returns:
            Rejim adları listesi.
        """
        if self._model is None:
            return self.REGIME_NAMES[:len(probabilities)]

        try:
            means = self._model.means_[:, 0]
            sorted_indices = np.argsort(-means)
            name_mapping: dict[int, str] = {}

            name_mapping[sorted_indices[0]] = "BULL"
            name_mapping[sorted_indices[-1]] = "BEAR"

            remaining = list(sorted_indices[1:-1])
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
            return self.REGIME_NAMES[:len(probabilities)]

    def _rule_based_fallback(self, returns: np.ndarray, volatility: np.ndarray) -> HMMRegimeResult:
        """Rule-based fallback — HMM yoksa.

        Args:
            returns: Getiri serisi.
            volatility: Volatilite serisi.

        Returns:
            HMMRegimeResult: Kural tabanlı tahmin.
        """
        if len(returns) == 0:
            return HMMRegimeResult(
                regime="UNKNOWN", confidence=0.0, probabilities={}, regime_index=-1,
            )

        avg_return = float(np.mean(returns[-FALLBACK_LOOKBACK:])) if len(returns) >= FALLBACK_LOOKBACK else float(np.mean(returns))
        avg_vol = float(np.mean(volatility[-FALLBACK_LOOKBACK:])) if len(volatility) >= FALLBACK_LOOKBACK else float(np.mean(volatility))

        if avg_return > FALLBACK_RETURN_POSITIVE and avg_vol < FALLBACK_VOL_LOW:
            regime, confidence = "BULL", FALLBACK_CONF_HIGH
        elif avg_return < FALLBACK_RETURN_NEGATIVE and avg_vol < FALLBACK_VOL_LOW:
            regime, confidence = "BEAR", FALLBACK_CONF_HIGH
        elif avg_vol >= FALLBACK_VOL_HIGH:
            regime, confidence = "HIGH_VOL", FALLBACK_CONF_LOW
        else:
            regime, confidence = "LOW_VOL", FALLBACK_CONF_LOW

        probs = {name: FALLBACK_UNIFORM_PROB for name in self.REGIME_NAMES}
        probs[regime] = confidence

        return HMMRegimeResult(
            regime=regime,
            confidence=confidence,
            probabilities=probs,
            regime_index=self.REGIME_NAMES.index(regime) if regime in self.REGIME_NAMES else -1,
        )

    def _append_history(self, result: HMMRegimeResult) -> None:
        """Sonucu geçmişe ekle ve boyut kontrolü yap.

        Args:
            result: Eklenecek sonuç.
        """
        self._regime_history.append(result)
        if len(self._regime_history) > HISTORY_TRIM_SIZE:
            # Deque'yi kırp (deque→list dönüşümü yok, maxlen ile yönet)
            trimmed = deque(list(self._regime_history)[-HISTORY_TRIM_SIZE:], maxlen=MAX_HISTORY_SIZE)
            self._regime_history = trimmed

    def _compute_transition_entropy(self) -> float:
        """Geçiş matrisi entropisi — ne kadar kararlı.

        Returns:
            Normalize edilmiş entropi (0-1).
        """
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
        """Geçiş matrisi (okunabilir format).

        Returns:
            Rejim adı → {hedef rejim: olasılık} sözlüğü.
        """
        if self._transition_matrix is None:
            return None

        matrix: dict[str, dict[str, float]] = {}
        for i, from_name in enumerate(self.REGIME_NAMES):
            matrix[from_name] = {}
            for j, to_name in enumerate(self.REGIME_NAMES):
                matrix[from_name][to_name] = round(float(self._transition_matrix[i, j]), 4)
        return matrix

    def get_regime_duration_stats(self) -> dict[str, dict[str, Any]]:
        """Rejim süre istatistikleri.

        Returns:
            Rejim adı → {avg_duration, max_duration, count} sözlüğü.
        """
        if not self._regime_history:
            return {}

        durations: dict[str, list[int]] = {}
        current_regime: str | None = None
        current_duration = 0

        for result in self._regime_history:
            if result.regime == current_regime:
                current_duration += 1
            else:
                if current_regime is not None:
                    durations.setdefault(current_regime, []).append(current_duration)
                current_regime = result.regime
                current_duration = 1

        if current_regime is not None:
            durations.setdefault(current_regime, []).append(current_duration)

        return {
            regime: {
                "avg_duration": round(float(np.mean(durs)), 1),
                "max_duration": max(durs),
                "count": len(durs),
            }
            for regime, durs in durations.items()
        }

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Son rejim tahminleri.

        Args:
            limit: Döndürülecek kayıt sayısı.

        Returns:
            Son tahminlerin sözlük listesi.
        """
        history = list(self._regime_history)[-limit:]
        return [
            {
                "regime": r.regime,
                "confidence": r.confidence,
                "probabilities": r.probabilities,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in history
        ]

    @property
    def is_fitted(self) -> bool:
        """Model eğitilmiş mi?"""
        return self._is_fitted

    @property
    def current_regime(self) -> str | None:
        """Mevcut rejim."""
        if self._regime_history:
            return self._regime_history[-1].regime
        return None


# Singleton
hmm_regime_detector = HMMRegimeDetector()
