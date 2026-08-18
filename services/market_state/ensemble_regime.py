"""ALPHA BIST — Ensemble Regime Detection v2.0

3 yöntemle ensemble rejim tespiti:
1. HMM (hmm_regime.py) — Matematiksel, probabilistik
2. Skor bazlı (regime.py) — Yorumlanabilir, esnek
3. GMM — Gaussian Mixture Model (Two Sigma yaklaşımı)

Karar mekanizması: Weighted voting (ağırlıklı oylama)

Kaynaklar:
- Gupta et al. (2025): Multi-model ensemble-HMM voting framework
- Two Sigma: ML Approach to Regime Modeling (GMM)
- Springer (2026): Regime-Aware Adaptive Forecasting

Rejimler (11):
BULL, BEAR, SIDEWAYS, HIGH_VOLATILITY, LOW_VOLATILITY,
RISK_ON, RISK_OFF, CRISIS, RECOVERY,
MOMENTUM_EXPANSION, MOMENTUM_CONTRACTION
"""

import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class EnsembleResult:
    """Ensemble rejim tespiti sonucu."""
    regime: str
    confidence: float
    consensus: bool                          # Tüm yöntemler aynı sonuca mı vardı?
    method_count: int                        # Kaç yöntem çalıştı
    regime_scores: Dict[str, float] = field(default_factory=dict)  # Her rejim için ağırlıklı skor
    method_details: Dict[str, Dict] = field(default_factory=dict)  # Her yöntemin detayı
    hmm_probabilities: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "confidence": round(self.confidence, 4),
            "consensus": self.consensus,
            "method_count": self.method_count,
            "regime_scores": {k: round(v, 4) for k, v in self.regime_scores.items()},
            "method_details": self.method_details,
            "hmm_probabilities": self.hmm_probabilities,
            "timestamp": self.timestamp.isoformat(),
        }


class EnsembleRegimeDetector:
    """Ensemble Regime Detection — 3 yöntem weighted voting.

    Ağırlıklar (varsayılan):
    - Skor bazlı: %50 (yorumlanabilir, BIST-specific)
    - HMM: %30 (matematiksel, probabilistik)
    - GMM: %20 (hızlı, factor-level)

    Kullanım:
        detector = EnsembleRegimeDetector()
        result = detector.detect(features, returns, volatility)
    """

    def __init__(
        self,
        score_weight: float = 0.50,
        hmm_weight: float = 0.30,
        gmm_weight: float = 0.20,
        rolling_window: int = 63,
    ):
        self._score_weight = score_weight
        self._hmm_weight = hmm_weight
        self._gmm_weight = gmm_weight
        self._rolling_window = rolling_window

        # Lazy init — import edilemezse fallback
        self._score_engine = None
        self._hmm_detector = None
        self._gmm_detector = None
        self._init_failed = False

    def _ensure_engines(self):
        """Engine'leri lazy init et."""
        if self._init_failed:
            return

        try:
            from services.intelligence.regime import RegimeEngine
            self._score_engine = RegimeEngine()
        except Exception as e:
            logger.warning("Failed to init RegimeEngine", error=str(e))

        try:
            from services.intelligence.hmm_regime import HMMRegimeDetector
            self._hmm_detector = HMMRegimeDetector(
                n_regimes=4, rolling_window=self._rolling_window
            )
        except Exception as e:
            logger.warning("Failed to init HMMRegimeDetector", error=str(e))

        # GMM opsiyonel
        try:
            from sklearn.mixture import GaussianMixture
            self._gmm_available = True
        except ImportError:
            self._gmm_available = False
            logger.info("sklearn not available, GMM regime detection disabled")

    def detect(
        self,
        features: Dict[str, float],
        returns: Optional[np.ndarray] = None,
        volatility: Optional[np.ndarray] = None,
    ) -> EnsembleResult:
        """Ensemble rejim tespiti.

        Args:
            features: Feature dict (breadth_pct, momentum_avg, volatility_avg, rsi_avg, ...)
            returns: Günlük getiri serisi (HMM ve GMM için)
            volatility: Günlük volatilite serisi (HMM ve GMM için)

        Returns:
            EnsembleResult
        """
        self._ensure_engines()

        results = {}
        method_details = {}

        # 1. Skor bazlı (her zaman çalışır)
        if self._score_engine:
            try:
                score_result = self._score_engine.detect_regime(features)
                results["score"] = {
                    "regime": score_result.regime.value,
                    "confidence": score_result.confidence,
                    "weight": self._score_weight,
                }
                method_details["score"] = {
                    "regime": score_result.regime.value,
                    "confidence": round(score_result.confidence, 4),
                }
            except Exception as e:
                logger.warning("Score-based regime detection failed", error=str(e))

        # 2. HMM (yeterli veri varsa)
        if self._hmm_detector and returns is not None and len(returns) >= self._rolling_window:
            try:
                # Fit + predict
                self._hmm_detector.fit(returns, volatility)
                hmm_result = self._hmm_detector.predict_regime(returns, volatility)
                results["hmm"] = {
                    "regime": hmm_result.regime,
                    "confidence": hmm_result.confidence,
                    "weight": self._hmm_weight,
                }
                method_details["hmm"] = {
                    "regime": hmm_result.regime,
                    "confidence": round(hmm_result.confidence, 4),
                    "probabilities": hmm_result.probabilities,
                }
            except Exception as e:
                logger.warning("HMM regime detection failed", error=str(e))

        # 3. GMM (opsiyonel, sklearn varsa)
        if self._gmm_available and returns is not None and len(returns) >= 63:
            try:
                gmm_result = self._detect_gmm(returns, volatility)
                results["gmm"] = {
                    "regime": gmm_result["regime"],
                    "confidence": gmm_result["confidence"],
                    "weight": self._gmm_weight,
                }
                method_details["gmm"] = gmm_result
            except Exception as e:
                logger.warning("GMM regime detection failed", error=str(e))

        # Hiçbir yöntem çalışmadıysa
        if not results:
            logger.error("All regime detection methods failed")
            return EnsembleResult(
                regime="UNKNOWN",
                confidence=0.0,
                consensus=False,
                method_count=0,
            )

        # Weighted voting
        return self._weighted_vote(results, method_details)

    def _detect_gmm(
        self,
        returns: np.ndarray,
        volatility: Optional[np.ndarray] = None,
    ) -> Dict:
        """Gaussian Mixture Model ile rejim tespiti.

        Two Sigma yaklaşımı: factor-level regime detection.
        """
        from sklearn.mixture import GaussianMixture

        # Feature matrix
        if volatility is not None and len(volatility) == len(returns):
            X = np.column_stack([returns[-self._rolling_window:], volatility[-self._rolling_window:]])
        else:
            X = returns[-self._rolling_window:].reshape(-1, 1)

        # NaN/inf temizle
        mask = np.isfinite(X).all(axis=1)
        X = X[mask]

        if len(X) < 20:
            return {"regime": "UNKNOWN", "confidence": 0.0}

        # GMM eğit (4 component)
        gmm = GaussianMixture(
            n_components=4,
            covariance_type="full",
            n_init=5,
            random_state=42,
        )
        gmm.fit(X)

        # Son gözlemi tahmin et
        last_obs = X[-1:].reshape(1, -1)
        regime_idx = gmm.predict(last_obs)[0]
        probs = gmm.predict_proba(last_obs)[0]

        # Rejim isimlerini ata (HMM ile aynı strateji)
        regime_names = self._assign_gmm_regime_names(gmm, X)

        regime = regime_names[regime_idx]
        confidence = float(probs[regime_idx])

        return {
            "regime": regime,
            "confidence": round(confidence, 4),
            "probabilities": {
                name: round(float(probs[i]), 4)
                for i, name in enumerate(regime_names)
            },
        }

    def _assign_gmm_regime_names(self, gmm, X: np.ndarray) -> List[str]:
        """GMM component'lerine isim ata.

        Return ortalamasına göre sırala:
        En yüksek → BULL, en düşük → BEAR
        Kalan ikisi volatiliteye göre HIGH_VOL / LOW_VOL
        """
        means = gmm.means_

        if means.shape[1] >= 2:
            # Return'e göre sırala
            return_means = means[:, 0]
            sorted_indices = np.argsort(-return_means)

            names = [""] * 4
            names[sorted_indices[0]] = "BULL"
            names[sorted_indices[-1]] = "BEAR"

            # Kalan ikisi: volatiliteye göre
            remaining = [i for i in sorted_indices[1:-1]]
            if len(remaining) >= 2:
                vol_means = means[remaining, 1]
                if vol_means[0] > vol_means[1]:
                    names[remaining[0]] = "HIGH_VOLATILITY"
                    names[remaining[1]] = "LOW_VOLATILITY"
                else:
                    names[remaining[0]] = "LOW_VOLATILITY"
                    names[remaining[1]] = "HIGH_VOLATILITY"

            return names
        else:
            return ["BULL", "BEAR", "HIGH_VOLATILITY", "LOW_VOLATILITY"]

    def _weighted_vote(
        self,
        results: Dict[str, Dict],
        method_details: Dict[str, Dict],
    ) -> EnsembleResult:
        """Ağırlıklı oylama ile final karar.

        Her rejim için: weight * confidence topla
        En yüksek skorlu rejim kazanır.
        """
        # Rejim skorlarını topla
        regime_scores: Dict[str, float] = {}

        for method, result in results.items():
            regime = result["regime"]
            weight = result["weight"]
            confidence = result["confidence"]

            if regime not in regime_scores:
                regime_scores[regime] = 0.0
            regime_scores[regime] += weight * confidence

        # Normalize et (toplam ağırlık 1 olmayabilir)
        total_weight = sum(r["weight"] for r in results.values())
        if total_weight > 0:
            regime_scores = {k: v / total_weight for k, v in regime_scores.items()}

        # En yüksek skorlu rejim
        final_regime = max(regime_scores, key=regime_scores.get)
        final_confidence = regime_scores[final_regime]

        # Consensus kontrolü
        regimes = [r["regime"] for r in results.values()]
        consensus = len(set(regimes)) == 1

        # HMM probabilities (varsa)
        hmm_probs = method_details.get("hmm", {}).get("probabilities", {})

        logger.info(
            "Ensemble regime detected",
            regime=final_regime,
            confidence=round(final_confidence, 3),
            consensus=consensus,
            methods=list(results.keys()),
        )

        return EnsembleResult(
            regime=final_regime,
            confidence=round(final_confidence, 4),
            consensus=consensus,
            method_count=len(results),
            regime_scores=regime_scores,
            method_details=method_details,
            hmm_probabilities=hmm_probs,
        )

    def update_weights(
        self,
        score_weight: float = None,
        hmm_weight: float = None,
        gmm_weight: float = None,
    ):
        """Ağırlıkları güncelle (backtest optimizasyonu sonrası)."""
        if score_weight is not None:
            self._score_weight = score_weight
        if hmm_weight is not None:
            self._hmm_weight = hmm_weight
        if gmm_weight is not None:
            self._gmm_weight = gmm_weight

        # Normalize
        total = self._score_weight + self._hmm_weight + self._gmm_weight
        if total > 0:
            self._score_weight /= total
            self._hmm_weight /= total
            self._gmm_weight /= total

    def get_regime_adapted_weights(self, preliminary_regime: str) -> Dict[str, float]:
        """Rejime göre ağırlık adaptasyonu.

        Crisis/High-Vol rejimlerde HMM ağırlığı artar (matematiksel model daha güvenilir).
        Bull/Sideways rejimlerde skor ağırlığı artar (yorumlanabilirlik daha önemli).

        Args:
            preliminary_regime: İlk tespit edilen rejim

        Returns:
            Adapted weights {score, hmm, gmm}
        """
        # Varsayılan ağırlıklar
        weights = {
            "score": self._score_weight,
            "hmm": self._hmm_weight,
            "gmm": self._gmm_weight,
        }

        # Crisis/High-Vol: HMM ağırlığı artsın
        crisis_regimes = {"CRISIS", "HIGH_VOLATILITY", "RISK_OFF", "BEAR"}
        if preliminary_regime in crisis_regimes:
            weights = {
                "score": 0.35,
                "hmm": 0.45,  # HMM daha güvenilir
                "gmm": 0.20,
            }

        # Bull/Sideways: Skor ağırlığı artsın
        calm_regimes = {"BULL", "SIDEWAYS", "LOW_VOLATILITY", "RISK_ON"}
        if preliminary_regime in calm_regimes:
            weights = {
                "score": 0.60,  # Yorumlanabilirlik daha önemli
                "hmm": 0.25,
                "gmm": 0.15,
            }

        # Momentum: GMM ağırlığı artsın
        momentum_regimes = {"MOMENTUM_EXPANSION", "MOMENTUM_CONTRACTION"}
        if preliminary_regime in momentum_regimes:
            weights = {
                "score": 0.45,
                "hmm": 0.30,
                "gmm": 0.25,  # GMM momentum değişimi yakalar
            }

        return weights
