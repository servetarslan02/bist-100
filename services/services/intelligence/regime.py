"""
ALPHA BIST — Regime Engine v1.0

Piyasa rejimlerini feature-based olarak tespit eder:
- Threshold-based değil, çoklu feature'dan karar verir
- Regime transition probability matrix
- Regime-conditioned model weights
- Regime duration tracking

FAZ 3.2: Regime Engine
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


class Regime(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH-VOLATILITY"
    LOW_VOLATILITY = "LOW-VOLATILITY"
    RISK_ON = "RISK-ON"
    RISK_OFF = "RISK-OFF"
    CRISIS = "CRISIS"
    RECOVERY = "RECOVERY"
    MOMENTUM_EXPANSION = "MOMENTUM-EXPANSION"
    MOMENTUM_CONTRACTION = "MOMENTUM-CONTRACTION"


@dataclass
class RegimeState:
    """Rejim durumu."""
    regime: Regime
    confidence: float
    features_used: Dict[str, float]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_hours: float = 0.0


class RegimeEngine:
    """Feature-based regime detection.

    Threshold yerine çoklu feature'dan karar verir.
    """

    # Regime-feature ağırlıkları
    REGIME_FEATURES = {
        "breadth_pct": 0.20,          # Piyasa genişliği
        "momentum_avg": 0.15,         # Ortalama momentum
        "volatility_avg": 0.15,       # Ortalama volatilite
        "rsi_avg": 0.10,              # Ortalama RSI
        "risk_appetite": 0.15,        # Risk iştahı
        "usdtry_momentum": 0.10,      # Döviz momentum
        "vix_level": 0.10,            # VIX seviyesi
        "global_momentum": 0.05,      # Global piyasa momentum
    }

    def __init__(self, use_hmm: bool = True):
        self._current_regime: Optional[RegimeState] = None
        self._regime_history: List[RegimeState] = []
        self._transition_counts: Dict[str, Dict[str, int]] = {}
        self._use_hmm = use_hmm
        self._hmm_detector = None
        if use_hmm:
            try:
                from .hmm_regime import HMMRegimeDetector
                self._hmm_detector = HMMRegimeDetector(n_regimes=4, rolling_window=63)
            except Exception as e:
                self._hmm_detector = None

    def detect_regime(self, features: Dict[str, float]) -> RegimeState:
        """Feature'lardan rejim tespit et.

        Args:
            features: {
                "breadth_pct": 56.0,
                "momentum_avg": -1.62,
                "volatility_avg": 38.3,
                "rsi_avg": 52.0,
                "risk_appetite": 0.45,
                "usdtry_momentum": 3.2,
                "vix_level": 14.25,
                "global_momentum": 1.5,
            }
        """
        # Her rejim için skor hesapla
        scores = {}

        scores[Regime.BULL] = self._score_bull(features)
        scores[Regime.BEAR] = self._score_bear(features)
        scores[Regime.SIDEWAYS] = self._score_sideways(features)
        scores[Regime.HIGH_VOLATILITY] = self._score_high_vol(features)
        scores[Regime.LOW_VOLATILITY] = self._score_low_vol(features)
        scores[Regime.RISK_ON] = self._score_risk_on(features)
        scores[Regime.RISK_OFF] = self._score_risk_off(features)
        scores[Regime.CRISIS] = self._score_crisis(features)
        scores[Regime.RECOVERY] = self._score_recovery(features)
        scores[Regime.MOMENTUM_EXPANSION] = self._score_momentum_expansion(features)
        scores[Regime.MOMENTUM_CONTRACTION] = self._score_momentum_contraction(features)

        # HMM entegrasyonu — hybrid skor
        hmm_result = None
        if self._hmm_detector:
            try:
                # Features'tan return ve volatility üret
                returns = np.array([features.get("momentum_avg", 0) / 100] * 63)
                vol = np.array([features.get("volatility_avg", 20) / 100] * 63)
                hmm_result = self._hmm_detector.predict_regime(returns, vol)

                # HMM skorlarını rule-based skorlarla birleştir (ağırlıklı)
                hmm_weight = 0.3  # HMM %30, rule-based %70
                for regime_key in scores:
                    regime_name = regime_key.value
                    hmm_prob = hmm_result.probabilities.get(regime_name, 0.0)
                    scores[regime_key] = scores[regime_key] * (1 - hmm_weight) + hmm_prob * hmm_weight * 100
            except Exception as e:
                hmm_result = None

        # Macro regime entegrasyonu
        try:
            from services.macro.regime_detector import macro_regime_detector
            macro_regime = macro_regime_detector.detect_regime(features)
            if macro_regime.confidence > 0.3:
                # Macro regime skorlarını mevcut skorlarla birleştir
                macro_weight = 0.15  # Macro %15 ağırlık
                macro_mapping = {
                    "EXPANSION": [Regime.BULL, Regime.MOMENTUM_EXPANSION],
                    "CONTRACTION": [Regime.BEAR, Regime.MOMENTUM_CONTRACTION],
                    "STAGFLATION": [Regime.BEAR, Regime.HIGH_VOLATILITY],
                    "REFLATION": [Regime.RECOVERY, Regime.RISK_ON],
                    "RISK_ON": [Regime.RISK_ON, Regime.BULL],
                    "RISK_OFF": [Regime.RISK_OFF, Regime.BEAR],
                }
                for macro_name, target_regimes in macro_mapping.items():
                    macro_score = macro_regime.all_scores.get(macro_name, 0)
                    for target in target_regimes:
                        if target in scores:
                            scores[target] = scores[target] * (1 - macro_weight) + macro_score * macro_weight * 100
        except Exception as e:
            logger.debug("Handled exception", error=str(e), context="regime.py:146")
            pass

        # En yüksek skorlu rejimi seç
        best_regime = max(scores, key=scores.get)
        best_score = scores[best_regime]

        # Confidence: en yüksek skor ile ikinci arasındaki fark
        # Eşitlik durumunda makul bir confidence ver
        sorted_scores = sorted(scores.values(), reverse=True)
        if len(sorted_scores) >= 2:
            gap = sorted_scores[0] - sorted_scores[1]
            if gap < 0.01 and sorted_scores[0] > 0.5:
                # İki rejim eşit → belirsizlik yüksek ama skor yüksek → orta confidence
                confidence = 0.3
            else:
                confidence = min(1.0, max(0.0, gap))
        else:
            confidence = sorted_scores[0] if sorted_scores else 0.0

        # Regime değiştiyse duration sıfırla
        duration = 0.0
        if self._current_regime and self._current_regime.regime == best_regime:
            elapsed = (datetime.now(timezone.utc) - self._current_regime.timestamp).total_seconds() / 3600
            duration = self._current_regime.duration_hours + elapsed

        new_state = RegimeState(
            regime=best_regime,
            confidence=round(confidence, 4),
            features_used=features,
            duration_hours=round(duration, 2),
        )

        # Transition tracking
        if self._current_regime:
            old = self._current_regime.regime.value
            new = best_regime.value
            if old not in self._transition_counts:
                self._transition_counts[old] = {}
            self._transition_counts[old][new] = self._transition_counts[old].get(new, 0) + 1

        self._current_regime = new_state
        self._regime_history.append(new_state)

        # Son 1000 gözlem tut
        self._regime_history = self._regime_history[-1000:]

        logger.info("Regime detected", regime=best_regime.value, confidence=confidence, duration=duration)
        return new_state

    def _score_bull(self, f: Dict) -> float:
        """Bull market skoru — sürekli değerlerle."""
        score = 0.0
        breadth = f.get("breadth_pct", 50)
        if breadth > 60:
            score += min((breadth - 50) / 30, 0.3)  # 50-80 arası linear
        mom = f.get("momentum_avg", 0)
        if mom > 0:
            score += min(mom / 15, 0.3)  # 0-15 arası linear
        rsi = f.get("rsi_avg", 50)
        if rsi > 50:
            score += min((rsi - 50) / 40, 0.2)
        ra = f.get("risk_appetite", 0.5)
        if ra > 0.5:
            score += min((ra - 0.5) * 2, 0.2)
        return min(1.0, score)

    def _score_bear(self, f: Dict) -> float:
        score = 0.0
        breadth = f.get("breadth_pct", 50)
        if breadth < 50:
            score += min((50 - breadth) / 30, 0.3)
        mom = f.get("momentum_avg", 0)
        if mom < 0:
            score += min(abs(mom) / 15, 0.3)
        rsi = f.get("rsi_avg", 50)
        if rsi < 50:
            score += min((50 - rsi) / 30, 0.2)
        ra = f.get("risk_appetite", 0.5)
        if ra < 0.5:
            score += min((0.5 - ra) * 2, 0.2)
        return min(1.0, score)

    def _score_sideways(self, f: Dict) -> float:
        score = 0.0
        breadth = f.get("breadth_pct", 50)
        # 45-55 arası en yüksek
        breadth_score = max(0, 1 - abs(breadth - 50) / 10)
        score += breadth_score * 0.4
        mom = abs(f.get("momentum_avg", 0))
        score += max(0, 1 - mom / 5) * 0.3
        vol = f.get("volatility_avg", 20)
        if 10 < vol < 30:
            score += 0.3 * (1 - abs(vol - 20) / 10)
        return min(1.0, score)

    def _score_high_vol(self, f: Dict) -> float:
        score = 0.0
        vol = f.get("volatility_avg", 20)
        if vol > 20:
            score += min((vol - 20) / 30, 0.5)
        vix = f.get("vix_level", 15)
        if vix > 15:
            score += min((vix - 15) / 30, 0.3)
        fx = f.get("usdtry_momentum", 0)
        if fx > 0:
            score += min(fx / 15, 0.2)
        return min(1.0, score)

    def _score_low_vol(self, f: Dict) -> float:
        score = 0.0
        vol = f.get("volatility_avg", 20)
        if vol < 20:
            score += min((20 - vol) / 15, 0.5)
        vix = f.get("vix_level", 15)
        if vix < 20:
            score += min((20 - vix) / 15, 0.3)
        mom = abs(f.get("momentum_avg", 0))
        score += max(0, 1 - mom / 3) * 0.2
        return min(1.0, score)

    def _score_risk_on(self, f: Dict) -> float:
        score = 0.0
        ra = f.get("risk_appetite", 0.5)
        if ra > 0.5:
            score += min((ra - 0.5) * 2, 0.4)
        breadth = f.get("breadth_pct", 50)
        if breadth > 50:
            score += min((breadth - 50) / 30, 0.3)
        gm = f.get("global_momentum", 0)
        if gm > 0:
            score += min(gm / 5, 0.3)
        return min(1.0, score)

    def _score_risk_off(self, f: Dict) -> float:
        score = 0.0
        ra = f.get("risk_appetite", 0.5)
        if ra < 0.5:
            score += min((0.5 - ra) * 2, 0.4)
        vix = f.get("vix_level", 15)
        if vix > 15:
            score += min((vix - 15) / 30, 0.3)
        fx = f.get("usdtry_momentum", 0)
        if fx > 0:
            score += min(fx / 15, 0.3)
        return min(1.0, score)

    def _score_crisis(self, f: Dict) -> float:
        score = 0.0
        vol = f.get("volatility_avg", 20)
        if vol > 30:
            score += min((vol - 30) / 20, 0.3)
        breadth = f.get("breadth_pct", 50)
        if breadth < 30:
            score += min((30 - breadth) / 20, 0.3)
        vix = f.get("vix_level", 15)
        if vix > 25:
            score += min((vix - 25) / 25, 0.2)
        fx = f.get("usdtry_momentum", 0)
        if fx > 5:
            score += min((fx - 5) / 15, 0.2)
        return min(1.0, score)

    def _score_recovery(self, f: Dict) -> float:
        score = 0.0
        breadth = f.get("breadth_pct", 50)
        if 35 < breadth < 60:
            score += 0.3 * (1 - abs(breadth - 47.5) / 12.5)
        mom = f.get("momentum_avg", 0)
        if 0 < mom < 5:
            score += 0.3 * (mom / 5)
        ra = f.get("risk_appetite", 0.5)
        if ra > 0.4:
            score += min((ra - 0.4) * 2, 0.2)
        vol = f.get("volatility_avg", 20)
        if vol < 30:
            score += min((30 - vol) / 20, 0.2)
        return min(1.0, score)

    def _score_momentum_expansion(self, f: Dict) -> float:
        score = 0.0
        breadth = f.get("breadth_pct", 50)
        if breadth > 60:
            score += min((breadth - 60) / 20, 0.3)
        mom = f.get("momentum_avg", 0)
        if mom > 3:
            score += min((mom - 3) / 10, 0.3)
        rsi = f.get("rsi_avg", 50)
        if rsi > 55:
            score += min((rsi - 55) / 30, 0.2)
        vol = f.get("volatility_avg", 20)
        if vol > 15:
            score += min((vol - 15) / 20, 0.2)
        return min(1.0, score)

    def _score_momentum_contraction(self, f: Dict) -> float:
        score = 0.0
        breadth = f.get("breadth_pct", 50)
        if breadth < 45:
            score += min((45 - breadth) / 25, 0.3)
        mom = f.get("momentum_avg", 0)
        if mom < 0:
            score += min(abs(mom) / 10, 0.3)
        vol = f.get("volatility_avg", 20)
        if vol > 20:
            score += min((vol - 20) / 20, 0.2)
        ra = f.get("risk_appetite", 0.5)
        if ra < 0.5:
            score += min((0.5 - ra) * 2, 0.2)
        return min(1.0, score)

    @property
    def current_regime(self) -> Optional[RegimeState]:
        """Mevcut rejim durumunu dondur."""
        return self._current_regime

    def get_regime_weights(self, regime: Regime) -> Dict[str, float]:
        """Rejime göre model ağırlıkları döndür.

        Farklı rejimlerde farklı stratejilerin ağırlıkları değişir.
        """
        weights = {
            Regime.BULL: {"momentum": 0.35, "breakout": 0.25, "value": 0.15, "mean_reversion": 0.10, "defensive": 0.15},
            Regime.BEAR: {"momentum": 0.10, "breakout": 0.10, "value": 0.20, "mean_reversion": 0.25, "defensive": 0.35},
            Regime.SIDEWAYS: {"momentum": 0.15, "breakout": 0.15, "value": 0.25, "mean_reversion": 0.30, "defensive": 0.15},
            Regime.HIGH_VOLATILITY: {"momentum": 0.15, "breakout": 0.20, "value": 0.15, "mean_reversion": 0.20, "defensive": 0.30},
            Regime.LOW_VOLATILITY: {"momentum": 0.30, "breakout": 0.25, "value": 0.20, "mean_reversion": 0.15, "defensive": 0.10},
            Regime.RISK_ON: {"momentum": 0.35, "breakout": 0.25, "value": 0.15, "mean_reversion": 0.10, "defensive": 0.15},
            Regime.RISK_OFF: {"momentum": 0.10, "breakout": 0.10, "value": 0.20, "mean_reversion": 0.20, "defensive": 0.40},
            Regime.CRISIS: {"momentum": 0.05, "breakout": 0.05, "value": 0.15, "mean_reversion": 0.15, "defensive": 0.60},
            Regime.RECOVERY: {"momentum": 0.25, "breakout": 0.20, "value": 0.25, "mean_reversion": 0.15, "defensive": 0.15},
            Regime.MOMENTUM_EXPANSION: {"momentum": 0.40, "breakout": 0.25, "value": 0.10, "mean_reversion": 0.10, "defensive": 0.15},
            Regime.MOMENTUM_CONTRACTION: {"momentum": 0.10, "breakout": 0.10, "value": 0.25, "mean_reversion": 0.25, "defensive": 0.30},
        }
        return weights.get(regime, weights[Regime.SIDEWAYS])

    def get_transition_matrix(self) -> Dict[str, Dict[str, float]]:
        """Regime geçiş olasılıkları matrisi."""
        matrix = {}
        for from_regime, to_counts in self._transition_counts.items():
            total = sum(to_counts.values())
            if total > 0:
                matrix[from_regime] = {to: count / total for to, count in to_counts.items()}
        return matrix

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Son regime değişimleri."""
        history = self._regime_history[-limit:]
        return [
            {
                "regime": s.regime.value,
                "confidence": s.confidence,
                "duration_hours": s.duration_hours,
                "timestamp": s.timestamp.isoformat(),
            }
            for s in history
        ]


# Singleton
regime_engine = RegimeEngine()
