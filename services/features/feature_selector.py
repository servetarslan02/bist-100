"""
ALPHA BIST — Feature Selector

Feature seçme ve filtreleme:
- SHAP-based feature importance
- Correlation-based filtering
- Variance threshold
"""

import numpy as np
from typing import Dict, Any, List, Optional, Tuple
import structlog

logger = structlog.get_logger()


class FeatureSelector:
    """Feature seçme ve filtreleme."""

    def select_by_correlation(
        self,
        X: np.ndarray,
        feature_names: List[str],
        threshold: float = 0.95,
    ) -> Tuple[np.ndarray, List[str]]:
        """Korelasyon-based feature filtreleme.

        Yüksek korelasyonlu feature'lardan birini kaldır.

        Args:
            X: Feature matrix (n_samples, n_features)
            feature_names: Feature isimleri
            threshold: Korelasyon eşiği (0-1)
        """
        if X.shape[1] != len(feature_names):
            raise ValueError("X columns and feature_names length must match")

        corr_matrix = np.corrcoef(X.T)
        to_drop = set()

        for i in range(len(feature_names)):
            if i in to_drop:
                continue
            for j in range(i + 1, len(feature_names)):
                if j in to_drop:
                    continue
                if abs(corr_matrix[i, j]) > threshold:
                    to_drop.add(j)

        keep_indices = [i for i in range(len(feature_names)) if i not in to_drop]
        selected_names = [feature_names[i] for i in keep_indices]
        selected_X = X[:, keep_indices]

        logger.info("Feature correlation filter",
                    original=len(feature_names),
                    removed=len(to_drop),
                    remaining=len(selected_names))

        return selected_X, selected_names

    def select_by_variance(
        self,
        X: np.ndarray,
        feature_names: List[str],
        threshold: float = 0.01,
    ) -> Tuple[np.ndarray, List[str]]:
        """Variance-based feature filtreleme.

        Düşük varyanslı feature'ları kaldır.

        Args:
            X: Feature matrix
            feature_names: Feature isimleri
            threshold: Minimum varyans eşiği
        """
        variances = np.var(X, axis=0)
        keep_indices = [i for i in range(len(feature_names)) if variances[i] > threshold]
        selected_names = [feature_names[i] for i in keep_indices]
        selected_X = X[:, keep_indices]

        logger.info("Feature variance filter",
                    original=len(feature_names),
                    removed=len(feature_names) - len(selected_names),
                    remaining=len(selected_names))

        return selected_X, selected_names

    def rank_by_importance(
        self,
        importances: np.ndarray,
        feature_names: List[str],
        top_n: int = 20,
    ) -> List[Tuple[str, float]]:
        """Feature importance sıralaması.

        Args:
            importances: Feature importance değerleri
            feature_names: Feature isimleri
            top_n: İlk N feature
        """
        paired = list(zip(feature_names, importances))
        paired.sort(key=lambda x: abs(x[1]), reverse=True)
        return paired[:top_n]


# Singleton
feature_selector = FeatureSelector()
