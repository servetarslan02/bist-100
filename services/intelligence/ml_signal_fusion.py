"""
ALPHA BIST — ML Signal Fusion v1.0

ML-optimized sinyal birleştirme:
- SHAP-based weight optimization
- Regime-specific dynamic weights
- Conflict detection improvements
- Self-check mechanism

Kullanım:
    fusion = MLSignalFusion()
    result = fusion.fuse(ticker, signals, regime="BULL", historical_data=...)
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class MLFusedSignal:
    """ML-optimized birleştirilmiş sinyal."""

    ticker: str
    regime: str

    # Bileşen skorları
    component_scores: dict[str, float] = field(default_factory=dict)
    component_directions: dict[str, str] = field(default_factory=dict)

    # Optimized ağırlıklar
    optimized_weights: dict[str, float] = field(default_factory=dict)
    default_weights: dict[str, float] = field(default_factory=dict)

    # Sonuç
    fused_score: float = 50.0
    fused_direction: str = "NEUTRAL"
    fused_confidence: float = 0.0

    # Çelişki
    has_conflict: bool = False
    conflict_details: list[str] = field(default_factory=list)

    # Self-check
    self_check_passed: bool = True
    self_check_warnings: list[str] = field(default_factory=list)

    # Metadata
    weights_source: str = "default"  # "default", "optimized", "regime_override"
    n_models_used: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class MLSignalFusion:
    """
    ML-optimized sinyal birleştirme.

    SHAP importance ile optimal ağırlıkları bulur.
    Rejime göre ağırlıkları dinamik olarak değiştirir.
    """

    COMPONENTS = ["technical", "fundamental", "momentum", "sentiment", "macro", "valuation", "ai"]

    # Varsayılan ağırlıklar
    DEFAULT_WEIGHTS = {
        "technical": 0.15,
        "fundamental": 0.15,
        "momentum": 0.20,
        "sentiment": 0.10,
        "macro": 0.10,
        "valuation": 0.15,
        "ai": 0.15,
    }

    # Rejime göre ağırlık override'ları
    REGIME_OVERRIDES = {
        "BULL": {"momentum": 0.30, "technical": 0.20, "sentiment": 0.05},
        "BEAR": {"fundamental": 0.25, "valuation": 0.25, "macro": 0.20},
        "HIGH_VOLATILITY": {"macro": 0.25, "valuation": 0.20, "momentum": 0.10},
        "LOW_VOLATILITY": {"momentum": 0.25, "technical": 0.20, "fundamental": 0.15},
        "RISK_ON": {"momentum": 0.30, "sentiment": 0.15, "technical": 0.15},
        "RISK_OFF": {"macro": 0.25, "valuation": 0.25, "fundamental": 0.20},
        "CRISIS": {"macro": 0.30, "valuation": 0.20, "fundamental": 0.20},
        "RECOVERY": {"fundamental": 0.25, "valuation": 0.20, "sentiment": 0.15},
        "SIDEWAYS": {"mean_reversion": 0.25, "valuation": 0.20, "fundamental": 0.20},
        "MOMENTUM_EXPANSION": {"momentum": 0.35, "technical": 0.20, "ai": 0.10},
        "MOMENTUM_CONTRACTION": {"fundamental": 0.25, "valuation": 0.25, "macro": 0.15},
    }

    def __init__(self):
        """Otomatik eklendi."""
        self._optimized_weights: dict[str, dict[str, float]] = {}  # regime → weights
        self._weight_history: list[dict] = []

    def fuse(
        self,
        ticker: str,
        signals: dict[str, dict[str, Any]],
        regime: str = "UNKNOWN",
        historical_signals: list[dict] | None = None,
        historical_outcomes: list[float] | None = None,
    ) -> MLFusedSignal:
        """
        ML-optimized sinyal birleştirme.

        Args:
            ticker: Hisse kodu
            signals: {component: {"direction": "LONG", "score": 70}}
            regime: Mevcut rejim
            historical_signals: Geçmiş sinyaller (SHAP optimizasyonu için)
            historical_outcomes: Geçmiş sonuçlar

        Returns:
            MLFusedSignal
        """
        result = MLFusedSignal(ticker=ticker, regime=regime)

        # Bileşen skorları ve yönleri
        for comp in self.COMPONENTS:
            comp_data = signals.get(comp, {})
            result.component_scores[comp] = comp_data.get("score", 50)
            result.component_directions[comp] = comp_data.get("direction", "NEUTRAL")

        # Ağırlıkları belirle
        weights = self._determine_weights(regime, historical_signals, historical_outcomes)
        result.default_weights = dict(self.DEFAULT_WEIGHTS)
        result.optimized_weights = dict(weights)

        # Ağırlıklı skor
        total_weight = 0
        weighted_score = 0
        for comp in self.COMPONENTS:
            score = result.component_scores.get(comp, 50)
            w = weights.get(comp, 1.0 / len(self.COMPONENTS))
            weighted_score += score * w
            total_weight += w

        result.fused_score = round(weighted_score / max(total_weight, 0.001), 2)

        # Yön belirleme
        long_weight = 0
        short_weight = 0
        for comp in self.COMPONENTS:
            direction = result.component_directions.get(comp, "NEUTRAL")
            score = result.component_scores.get(comp, 50)
            w = weights.get(comp, 0) * (score / 100)
            if direction == "LONG":
                long_weight += w
            elif direction == "SHORT":
                short_weight += w

        if long_weight > short_weight * 1.3:
            result.fused_direction = "LONG"
        elif short_weight > long_weight * 1.3:
            result.fused_direction = "SHORT"
        else:
            result.fused_direction = "NEUTRAL"

        # Confidence
        direction_agreement = abs(long_weight - short_weight) / max(long_weight + short_weight, 0.01)
        result.fused_confidence = round(min(direction_agreement, 0.95), 4)

        # Çelişki tespiti
        result.has_conflict, result.conflict_details = self._detect_conflicts(signals)

        # Self-check
        result.self_check_passed, result.self_check_warnings = self._self_check(result, signals)

        return result

    def _determine_weights(
        self,
        regime: str,
        historical_signals: list[dict] | None,
        historical_outcomes: list[float] | None,
    ) -> dict[str, float]:
        """Ağırlıkları belirle (SHAP > regime override > default)."""

        # 1. SHAP-optimized weights (en iyi)
        if historical_signals and historical_outcomes and len(historical_signals) >= 30:
            optimized = self._optimize_weights_shap(historical_signals, historical_outcomes, regime)
            if optimized:
                return optimized

        # 2. Rejime göre override
        if regime in self.REGIME_OVERRIDES:
            weights = dict(self.DEFAULT_WEIGHTS)
            weights.update(self.REGIME_OVERRIDES[regime])
            return weights

        # 3. Daha önce optimize edilmiş ağırlıklar
        if regime in self._optimized_weights:
            return self._optimized_weights[regime]

        # 4. Default
        return dict(self.DEFAULT_WEIGHTS)

    def _optimize_weights_shap(
        self,
        historical_signals: list[dict],
        historical_outcomes: list[float],
        regime: str,
    ) -> dict[str, float] | None:
        """SHAP importance ile optimal ağırlıkları bul."""
        try:
            from sklearn.ensemble import GradientBoostingRegressor

            # Feature matrix
            X = np.array([[s.get(comp, 50) for comp in self.COMPONENTS] for s in historical_signals])
            y = np.array(historical_outcomes)

            # NaN temizle
            mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
            X = X[mask]
            y = y[mask]

            if len(X) < 30:
                return None

            # Model eğit
            model = GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=42)
            model.fit(X, y)

            # Feature importance (SHAP yoksa built-in importance)
            try:
                import shap

                explainer = shap.TreeExplainer(model)
                shap_values = explainer.shap_values(X)
                importance = np.abs(shap_values).mean(axis=0)
            except ImportError:
                importance = model.feature_importances_

            # Normalize
            total = importance.sum()
            if total > 0:
                weights = {comp: float(imp / total) for comp, imp in zip(self.COMPONENTS, importance, strict=False)}
            else:
                return None

            # Cache
            self._optimized_weights[regime] = weights
            self._weight_history.append(
                {
                    "regime": regime,
                    "weights": weights,
                    "n_samples": len(X),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            if len(self._weight_history) > 1000:
                self._weight_history = self._weight_history[-1000:]

            logger.info(
                "SHAP weights optimized", regime=regime, n_samples=len(X), top_component=max(weights, key=weights.get)
            )

            return weights

        except ImportError:
            logger.debug("sklearn not available for SHAP optimization")
            return None
        except Exception as e:
            logger.warning("SHAP optimization failed", error=str(e))
            return None

    def _detect_conflicts(self, signals: dict) -> tuple[bool, list[str]]:
        """Çelişki tespiti."""
        conflicts = []
        directions = {}
        for comp in self.COMPONENTS:
            d = signals.get(comp, {}).get("direction", "NEUTRAL")
            if d != "NEUTRAL":
                directions[comp] = d

        long_comps = [k for k, v in directions.items() if v == "LONG"]
        short_comps = [k for k, v in directions.items() if v == "SHORT"]

        if long_comps and short_comps:
            conflicts.append(f"Çelişki: {', '.join(long_comps)} LONG vs {', '.join(short_comps)} SHORT")

        return len(conflicts) > 0, conflicts

    def _self_check(self, result: MLFusedSignal, signals: dict) -> tuple[bool, list[str]]:
        """Self-check mekanizması."""
        warnings = []

        # Çok yüksek confidence şüpheli
        if result.fused_confidence > 0.9:
            warnings.append("Confidence çok yüksek (>0.9) — şüpheli")

        # Tüm bileşenler nötr ama yüksek skor
        all_neutral = all(result.component_directions.get(c, "NEUTRAL") == "NEUTRAL" for c in self.COMPONENTS)
        if all_neutral and result.fused_score > 70:
            warnings.append("Tüm bileşenler nötr ama yüksek skor")

        # Veri kalitesi
        n_active = sum(1 for c in self.COMPONENTS if result.component_scores.get(c, 50) != 50)
        if n_active < 3:
            warnings.append(f"Az aktif bileşen ({n_active}/7)")

        return len(warnings) == 0, warnings

    def get_optimized_weights(self, regime: str) -> dict[str, float] | None:
        """Optimize edilmiş ağırlıkları getir."""
        return self._optimized_weights.get(regime)

    def get_weight_history(self) -> list[dict]:
        """Ağırlık optimizasyon geçmişi."""
        return self._weight_history


# Singleton
ml_signal_fusion = MLSignalFusion()
