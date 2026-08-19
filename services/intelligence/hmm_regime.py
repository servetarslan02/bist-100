"""
ALPHA BIST — HMM Regime Detector v1.0

Hidden Markov Model ile matematiksel rejim tespiti.

Rolling HMM: Her 63 günde yeniden eğit (quarterly).
4 rejim: BULL, BEAR, HIGH_VOL, LOW_VOL
Feature: return + volatility (2D)

Fallback: hmmlearn yoksa rule-based detection.

Kaynaklar:
- Medium Kryptera (2026): Rolling HMM for Gold Market Regimes
- MDPI Regime-Aware LightGBM (2026): Rolling HMM her 63 günde yeniden eğitim
- arXiv RMATS (2026): Hierarchical HMM for regime boundary detection

Kullanım:
    detector = HMMRegimeDetector(n_regimes=4)
    detector.fit(returns, volatility)
    result = detector.predict_regime(returns, volatility)
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()

# hmmlearn opsiyonel — yoksa fallback
try:
    from hmmlearn.hmm import GaussianHMM
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.info("hmmlearn not installed, HMM regime detection uses rule-based fallback")


@dataclass
class HMMRegimeResult:
    """HMM rejim sonucu."""
    regime: str                      # BULL, BEAR, HIGH_VOL, LOW_VOL
    confidence: float                # En yüksek olasılık
    probabilities: Dict[str, float]  # Tüm rejim olasılıkları
    regime_index: int                # 0-3 arası rejim indeksi
    transition_matrix: Optional[np.ndarray] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HMMRegimeDetector:
    """
    Hidden Markov Model ile rejim tespiti.

    Args:
        n_regimes: Rejim sayısı (varsayılan: 4)
        rolling_window: Rolling eğitim window'u (varsayılan: 63 gün = quarterly)
        retrain_interval: Yeniden eğitim aralığı (varsayılan: 63 gün)
    """

    REGIME_NAMES = ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"]

    def __init__(
        self,
        n_regimes: int = 4,
        rolling_window: int = 63,
        retrain_interval: int = 63,
    ):
        self.n_regimes = n_regimes
        self.rolling_window = rolling_window
        self.retrain_interval = retrain_interval

        self._model: Optional[object] = None
        self._is_fitted: bool = False
        self._last_train_size: int = 0
        self._last_retrain_index: int = 0
        self._regime_history: List[HMMRegimeResult] = []
        self._transition_matrix: Optional[np.ndarray] = None

    def fit(self, returns: np.ndarray, volatility: np.ndarray) -> bool:
        """
        HMM modelini eğit.

        Args:
            returns: Günlük getiri serisi
            volatility: Günlük volatilite serisi

        Returns:
            True: Eğitim başarılı, False: Fallback kullanıldı
        """
        if not HMM_AVAILABLE:
            logger.debug("hmmlearn not available, using rule-based fallback")
            return False

        if len(returns) < self.rolling_window:
            logger.warning("Not enough data for HMM",
                          data_len=len(returns),
                          required=self.rolling_window)
            return False

        try:
            # Son rolling_window gözlemi kullan
            train_returns = returns[-self.rolling_window:]
            train_vol = volatility[-self.rolling_window:]

            # 2D feature matrix: [return, volatility]
            X = np.column_stack([train_returns, train_vol])

            # NaN/inf temizle
            mask = np.isfinite(X).all(axis=1)
            X = X[mask]

            if len(X) < 20:
                logger.warning("Too few valid observations for HMM", valid_len=len(X))
                return False

            # HMM eğit
            self._model = GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="diag",  # "full" yerine "diag" — daha robust
                n_iter=100,
                random_state=42,
                tol=1e-4,
            )
            self._model.fit(X)

            self._is_fitted = True
            self._last_train_size = len(X)

            # Transition matrix
            self._transition_matrix = self._model.transmat_

            logger.info("HMM fitted",
                       n_regimes=self.n_regimes,
                       train_size=len(X),
                       transition_entropy=self._compute_transition_entropy())

            return True

        except Exception as e:
            logger.warning("HMM fit failed, using fallback", error=str(e))
            self._is_fitted = False
            return False

    def predict_regime(
        self,
        returns: np.ndarray,
        volatility: np.ndarray,
    ) -> HMMRegimeResult:
        """
        Mevcut rejimi tahmin et.

        Args:
            returns: Son N günlük getiri
            volatility: Son N günlük volatilite

        Returns:
            HMMRegimeResult
        """
        if not self._is_fitted or self._model is None:
            result = self._rule_based_fallback(returns, volatility)
            self._regime_history.append(result)
            self._regime_history = self._regime_history[-500:]
            return result

        try:
            # Son gözlemleri al
            X = np.column_stack([returns[-1:], volatility[-1:]])

            # Rejim tahmini
            regime_idx = self._model.predict(X)[0]
            probs = self._model.predict_proba(X)[0]

            # Rejim adlarını eşle (en yüksek olasılığa göre)
            regime_names = self._assign_regime_names(probs)

            result = HMMRegimeResult(
                regime=regime_names[regime_idx],
                confidence=float(probs[regime_idx]),
                probabilities={
                    name: float(probs[i])
                    for i, name in enumerate(regime_names)
                },
                regime_index=int(regime_idx),
                transition_matrix=self._transition_matrix,
            )

            self._regime_history.append(result)
            self._regime_history = self._regime_history[-500:]

            return result

        except Exception as e:
            logger.warning("HMM predict failed, using fallback", error=str(e))
            return self._rule_based_fallback(returns, volatility)

    def rolling_detect(
        self,
        returns: np.ndarray,
        volatility: np.ndarray,
    ) -> List[HMMRegimeResult]:
        """
        Rolling rejim tespiti.

        Her retrain_interval günde yeniden eğit ve tahmin yap.

        Args:
            returns: Tüm getiri serisi
            volatility: Tüm volatilite serisi

        Returns:
            Tahmin listesi
        """
        results = []
        n = len(returns)

        if n < self.rolling_window:
            logger.warning("Not enough data for rolling detection")
            return results

        for i in range(self.rolling_window, n):
            # Yeniden eğitim gerekli mi?
            if i - self._last_retrain_index >= self.retrain_interval:
                train_returns = returns[max(0, i - self.rolling_window):i]
                train_vol = volatility[max(0, i - self.rolling_window):i]
                self.fit(train_returns, train_vol)
                self._last_retrain_index = i

            # Tahmin
            result = self.predict_regime(
                returns[max(0, i - 5):i + 1],
                volatility[max(0, i - 5):i + 1],
            )
            results.append(result)

        logger.info("Rolling detection completed",
                   total_predictions=len(results),
                   retrains=(n - self.rolling_window) // self.retrain_interval)

        return results

    def _assign_regime_names(self, probabilities: np.ndarray) -> List[str]:
        """
        Rejim indekslerini anlamlı isimlere eşle.

        Strateji: Return ortalamasına göre sırala.
        En yüksek return → BULL, en düşük → BEAR
        """
        if self._model is None:
            return self.REGIME_NAMES[:len(probabilities)]

        try:
            # Her rejimin ortalama return'ü
            means = self._model.means_[:, 0]  # İlk feature = return

            # Sırala: yüksek return → BULL, düşük → BEAR
            sorted_indices = np.argsort(-means)

            name_mapping = {}
            names = ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"]

            # BULL: en yüksek return
            name_mapping[sorted_indices[0]] = "BULL"
            # BEAR: en düşük return
            name_mapping[sorted_indices[-1]] = "BEAR"

            # Kalan ikisi: volatiliteye göre HIGH_VOL ve LOW_VOL
            remaining = [i for i in sorted_indices[1:-1]]
            if len(remaining) >= 2:
                vol_means = self._model.means_[remaining, 1]  # İkinci feature = vol
                if vol_means[0] > vol_means[1]:
                    name_mapping[remaining[0]] = "HIGH_VOL"
                    name_mapping[remaining[1]] = "LOW_VOL"
                else:
                    name_mapping[remaining[0]] = "LOW_VOL"
                    name_mapping[remaining[1]] = "HIGH_VOL"

            return [name_mapping.get(i, f"REGIME_{i}") for i in range(len(probabilities))]

        except Exception as e:
            return self.REGIME_NAMES[:len(probabilities)]

    def _rule_based_fallback(
        self,
        returns: np.ndarray,
        volatility: np.ndarray,
    ) -> HMMRegimeResult:
        """Rule-based fallback — HMM yoksa."""
        if len(returns) == 0:
            return HMMRegimeResult(
                regime="UNKNOWN", confidence=0.0,
                probabilities={}, regime_index=-1,
            )

        avg_return = float(np.mean(returns[-20:])) if len(returns) >= 20 else float(np.mean(returns))
        avg_vol = float(np.mean(volatility[-20:])) if len(volatility) >= 20 else float(np.mean(volatility))

        # Basit kural tabanlı
        if avg_return > 0.001 and avg_vol < 0.02:
            regime = "BULL"
            confidence = 0.6
        elif avg_return < -0.001 and avg_vol < 0.02:
            regime = "BEAR"
            confidence = 0.6
        elif avg_vol >= 0.025:
            regime = "HIGH_VOL"
            confidence = 0.5
        else:
            regime = "LOW_VOL"
            confidence = 0.5

        probs = {name: 0.1 for name in self.REGIME_NAMES}
        probs[regime] = confidence

        return HMMRegimeResult(
            regime=regime,
            confidence=confidence,
            probabilities=probs,
            regime_index=self.REGIME_NAMES.index(regime) if regime in self.REGIME_NAMES else -1,
        )

    def _compute_transition_entropy(self) -> float:
        """Geçiş matrisi entropisi — ne kadar kararlı."""
        if self._transition_matrix is None:
            return 0.0

        entropy = 0.0
        for row in self._transition_matrix:
            for p in row:
                if p > 0:
                    entropy -= p * np.log2(p)
        return round(float(entropy / self.n_regimes), 4)

    def get_transition_matrix(self) -> Optional[Dict[str, Dict[str, float]]]:
        """Geçiş matrisi (okunabilir format)."""
        if self._transition_matrix is None:
            return None

        matrix = {}
        for i, from_name in enumerate(self.REGIME_NAMES):
            matrix[from_name] = {}
            for j, to_name in enumerate(self.REGIME_NAMES):
                matrix[from_name][to_name] = round(float(self._transition_matrix[i, j]), 4)

        return matrix

    def get_regime_duration_stats(self) -> Dict[str, float]:
        """Rejim süre istatistikleri."""
        if not self._regime_history:
            return {}

        durations = {}
        current_regime = None
        current_duration = 0

        for result in self._regime_history:
            if result.regime == current_regime:
                current_duration += 1
            else:
                if current_regime and current_regime not in durations:
                    durations[current_regime] = []
                if current_regime:
                    durations[current_regime].append(current_duration)
                current_regime = result.regime
                current_duration = 1

        # Son rejimi de ekle
        if current_regime:
            if current_regime not in durations:
                durations[current_regime] = []
            durations[current_regime].append(current_duration)

        return {
            regime: {
                "avg_duration": round(np.mean(durs), 1),
                "max_duration": max(durs),
                "count": len(durs),
            }
            for regime, durs in durations.items()
        }

    def get_history(self, limit: int = 20) -> List[Dict]:
        """Son rejim tahminleri."""
        history = self._regime_history[-limit:]
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
    def current_regime(self) -> Optional[str]:
        """Mevcut rejim."""
        if self._regime_history:
            return self._regime_history[-1].regime
        return None


# Singleton
hmm_regime_detector = HMMRegimeDetector()
