"""
ALPHA BIST — SHAP Helpers

SHAP-based feature importance hesaplama yardımcıları.
LightGBM, XGBoost, CatBoost için optimize edilmiş.

KURAL: Hızlı, memory-efficient, production-ready.
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import structlog

logger = structlog.get_logger()


@dataclass
class SHAPResult:
    """SHAP hesaplama sonucu."""
    feature_names: List[str]
    shap_values: np.ndarray  # (n_samples, n_features)
    base_value: float
    feature_importance: Dict[str, float]  # mean |SHAP|
    top_features: List[Tuple[str, float]]  # (feature, importance)


@dataclass
class SHAPInteractionResult:
    """SHAP interaction sonucu."""
    feature_pairs: List[Tuple[str, str]]
    interaction_values: np.ndarray
    top_interactions: List[Dict]


class SHAPHelpers:
    """SHAP hesaplama yardımcıları."""

    @staticmethod
    def compute_shap_values(
        model: Any,
        X: np.ndarray,
        feature_names: List[str],
        sample_size: Optional[int] = None,
    ) -> SHAPResult:
        """SHAP values hesapla.

        Args:
            model: Eğitilmiş model (LightGBM, XGBoost, vb.)
            X: Feature matrix
            feature_names: Feature isimleri
            sample_size: Sample boyutu (None = tüm veri)

        Returns:
            SHAPResult
        """
        try:
            import shap

            # Sample (büyük veri setleri için)
            if sample_size and len(X) > sample_size:
                indices = np.random.choice(len(X), sample_size, replace=False)
                X_sample = X[indices]
            else:
                X_sample = X

            # TreeExplainer (LightGBM, XGBoost için optimize)
            try:
                explainer = shap.TreeExplainer(model)
            except Exception:
                # Fallback: KernelExplainer (yavaş ama genel)
                logger.warning("TreeExplainer failed, falling back to KernelExplainer")
                background = shap.sample(X_sample, min(100, len(X_sample)))
                explainer = shap.KernelExplainer(model.predict, background)

            shap_values = explainer.shap_values(X_sample)

            # Multi-class durumunda (list of arrays)
            if isinstance(shap_values, list):
                # Pozitif class için SHAP values
                shap_values = shap_values[1] if len(shap_values) > 1 else shap_values[0]

            # Base value
            if hasattr(explainer, 'expected_value'):
                base_value = explainer.expected_value
                if isinstance(base_value, np.ndarray):
                    base_value = float(base_value[1] if len(base_value) > 1 else base_value[0])
                else:
                    base_value = float(base_value)
            else:
                base_value = 0.0

            # Feature importance (mean |SHAP|)
            mean_abs_shap = np.abs(shap_values).mean(axis=0)
            feature_importance = {
                name: round(float(imp), 6)
                for name, imp in zip(feature_names, mean_abs_shap)
            }

            # Top features
            top_indices = np.argsort(mean_abs_shap)[::-1]
            top_features = [
                (feature_names[i], round(float(mean_abs_shap[i]), 6))
                for i in top_indices
            ]

            return SHAPResult(
                feature_names=feature_names,
                shap_values=shap_values,
                base_value=base_value,
                feature_importance=feature_importance,
                top_features=top_features,
            )

        except ImportError:
            logger.warning("SHAP not installed, using model.feature_importances_")
            return SHAPHelpers._fallback_importance(model, X, feature_names)

        except Exception as e:
            logger.error("SHAP computation failed", error=str(e))
            return SHAPHelpers._fallback_importance(model, X, feature_names)

    @staticmethod
    def _fallback_importance(
        model: Any,
        X: np.ndarray,
        feature_names: List[str],
    ) -> SHAPResult:
        """Fallback: model.feature_importances_ kullan."""
        try:
            importances = model.feature_importances_
        except AttributeError:
            importances = np.ones(len(feature_names)) / len(feature_names)

        feature_importance = {
            name: round(float(imp), 6)
            for name, imp in zip(feature_names, importances)
        }

        top_indices = np.argsort(importances)[::-1]
        top_features = [
            (feature_names[i], round(float(importances[i]), 6))
            for i in top_indices
        ]

        return SHAPResult(
            feature_names=feature_names,
            shap_values=np.zeros((len(X), len(feature_names))),
            base_value=0.0,
            feature_importance=feature_importance,
            top_features=top_features,
        )

    @staticmethod
    def compute_feature_interactions(
        model: Any,
        X: np.ndarray,
        feature_names: List[str],
        top_n: int = 10,
    ) -> SHAPInteractionResult:
        """SHAP interaction values hesapla.

        Feature çiftleri arasındaki etkileşimleri bulur.

        Args:
            model: Eğitilmiş model
            X: Feature matrix
            feature_names: Feature isimleri
            top_n: En güçlü N etkileşim

        Returns:
            SHAPInteractionResult
        """
        try:
            import shap

            explainer = shap.TreeExplainer(model)
            interaction_values = explainer.shap_interaction_values(X)

            if isinstance(interaction_values, list):
                interaction_values = interaction_values[1] if len(interaction_values) > 1 else interaction_values[0]

            # Mean absolute interaction values
            mean_interactions = np.abs(interaction_values).mean(axis=0)

            # Top interactions (diagonal hariç)
            pairs = []
            for i in range(len(feature_names)):
                for j in range(i + 1, len(feature_names)):
                    pairs.append({
                        "feature_1": feature_names[i],
                        "feature_2": feature_names[j],
                        "interaction_strength": round(float(mean_interactions[i, j]), 6),
                    })

            pairs.sort(key=lambda x: x["interaction_strength"], reverse=True)
            top_pairs = pairs[:top_n]

            return SHAPInteractionResult(
                feature_pairs=[(p["feature_1"], p["feature_2"]) for p in top_pairs],
                interaction_values=interaction_values,
                top_interactions=top_pairs,
            )

        except Exception as e:
            logger.error("SHAP interaction computation failed", error=str(e))
            return SHAPInteractionResult(
                feature_pairs=[],
                interaction_values=np.array([]),
                top_interactions=[],
            )

    @staticmethod
    def compute_regime_shap(
        model: Any,
        X_by_regime: Dict[str, np.ndarray],
        feature_names: List[str],
        sample_size: int = 500,
    ) -> Dict[str, Dict[str, float]]:
        """Rejim-specific SHAP importance.

        Her rejim için ayrı feature importance hesaplar.

        Args:
            model: Eğitilmiş model
            X_by_regime: {regime: X_matrix}
            feature_names: Feature isimleri
            sample_size: Sample boyutu

        Returns:
            {regime: {feature: importance}}
        """
        regime_importance = {}

        for regime, X in X_by_regime.items():
            if len(X) < 10:
                continue

            result = SHAPHelpers.compute_shap_values(
                model, X, feature_names, sample_size=sample_size
            )
            regime_importance[regime] = result.feature_importance

        return regime_importance

    @staticmethod
    def explain_single_prediction(
        model: Any,
        X_single: np.ndarray,
        feature_names: List[str],
    ) -> Dict[str, Any]:
        """Tek prediction için SHAP explanation.

        Args:
            model: Eğitilmiş model
            X_single: Tek örnek (1, n_features)
            feature_names: Feature isimleri

        Returns:
            Explanation dict
        """
        try:
            import shap

            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_single)

            if isinstance(shap_values, list):
                shap_values = shap_values[1] if len(shap_values) > 1 else shap_values[0]

            # Feature contributions
            contributions = []
            for name, value, shap_val in zip(feature_names, X_single[0], shap_values[0]):
                contributions.append({
                    "feature": name,
                    "feature_value": round(float(value), 4),
                    "shap_value": round(float(shap_val), 4),
                    "abs_shap": round(float(abs(shap_val)), 4),
                })

            contributions.sort(key=lambda x: x["abs_shap"], reverse=True)

            base_value = explainer.expected_value
            if isinstance(base_value, np.ndarray):
                base_value = float(base_value[1] if len(base_value) > 1 else base_value[0])

            return {
                "base_value": round(float(base_value), 4),
                "prediction": round(float(base_value + sum(c["shap_value"] for c in contributions)), 4),
                "top_contributions": contributions[:10],
                "all_contributions": contributions,
            }

        except Exception as e:
            logger.error("SHAP explanation failed", error=str(e))
            return {"error": str(e)}


# Singleton
shap_helpers = SHAPHelpers()
