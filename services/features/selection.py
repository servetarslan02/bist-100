"""ALPHA BIST — Feature Selection Engine v1.0

Feature selection motoru — redundant ve düşük kaliteli feature'ları otomatik eler:
- Correlation filter (yüksek korelasyonlu çiftleri ele)
- Variance threshold (düşük varyanslı feature'ları ele)
- SHAP-based selection (en önemli K feature'ı seç)
- Mutual information tabanlı selection
- Combined pipeline (tüm filtreleri sırayla uygula)

Kullanım:
    from services.features.selection import feature_selector

    # Tüm filtreleri uygula
    selected = feature_selector.select(X, y, feature_names, model=lgbm_model)

    # Sadece correlation filter
    selected = feature_selector.correlation_filter(X, feature_names, threshold=0.95)

    # SHAP-based selection
    selected = feature_selector.shap_based_selection(X, y, feature_names, model=lgbm_model, top_k=50)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class SelectionResult:
    """Feature selection sonucu."""

    selected_features: list[str]
    removed_features: list[str]
    removal_reasons: dict[str, str]  # feature → reason
    n_original: int
    n_selected: int
    n_removed: int
    reduction_ratio: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class FeatureImportance:
    """Feature importance skoru."""

    feature_name: str
    importance: float
    rank: int


class FeatureSelector:
    """Feature selection motoru.

    Özellikler:
    - Correlation filter: Yüksek korelasyonlu feature çiftlerini ele
    - Variance threshold: Düşük varyanslı feature'ları ele
    - SHAP-based selection: SHAP importance'a göre en iyi K feature
    - Mutual information: Bilgi teorisine dayalı selection
    - Combined pipeline: Tüm filtreleri sırayla uygula
    """

    def __init__(
        self,
        correlation_threshold: float = 0.95,
        variance_threshold: float = 0.001,
        default_top_k: int = 50,
    ):
        """Otomatik eklendi."""
        self.correlation_threshold = correlation_threshold
        self.variance_threshold = variance_threshold
        self.default_top_k = default_top_k
        self._selection_history: list[SelectionResult] = []

    def select(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        model: Any | None = None,
        top_k: int | None = None,
    ) -> SelectionResult:
        """Tüm filtreleri sırayla uygula.

        Pipeline sırası:
        1. Variance threshold (düşük varyanslıları ele)
        2. Correlation filter (yüksek korelasyonlu çiftleri ele)
        3. SHAP-based selection (en önemli K feature)

        Args:
            X: Feature matrix (n_samples, n_features)
            y: Target array (n_samples,)
            feature_names: Feature isimleri listesi
            model: SHAP için model (opsiyonel)
            top_k: Seçilecek feature sayısı (None = default_top_k)

        Returns:
            SelectionResult
        """
        if top_k is None:
            top_k = self.default_top_k

        current_names = list(feature_names)
        current_X = X.copy()
        all_removed: dict[str, str] = {}

        # 1. Variance threshold
        var_result = self._apply_variance_threshold(current_X, current_names)
        current_names = var_result["kept"]
        current_X = current_X[:, var_result["kept_indices"]]
        all_removed.update(var_result["removed"])

        logger.info(
            "selection_variance_done",
            n_removed=len(var_result["removed"]),
            n_kept=len(current_names),
        )

        # 2. Correlation filter
        if len(current_names) > 1:
            corr_result = self._apply_correlation_filter(current_X, current_names)
            current_names = corr_result["kept"]
            current_X = current_X[:, corr_result["kept_indices"]]
            all_removed.update(corr_result["removed"])

            logger.info(
                "selection_correlation_done",
                n_removed=len(corr_result["removed"]),
                n_kept=len(current_names),
            )

        # 3. SHAP-based selection
        if model is not None and len(current_names) > top_k:
            shap_result = self._apply_shap_selection(current_X, y, current_names, model, top_k)
            current_names = shap_result["kept"]
            all_removed.update(shap_result["removed"])

            logger.info(
                "selection_shap_done",
                n_removed=len(shap_result["removed"]),
                n_kept=len(current_names),
            )

        result = SelectionResult(
            selected_features=current_names,
            removed_features=list(all_removed.keys()),
            removal_reasons=all_removed,
            n_original=len(feature_names),
            n_selected=len(current_names),
            n_removed=len(all_removed),
            reduction_ratio=round(1.0 - len(current_names) / max(len(feature_names), 1), 4),
        )

        self._selection_history.append(result)

        logger.info(
            "selection_complete",
            n_original=result.n_original,
            n_selected=result.n_selected,
            reduction=result.reduction_ratio,
        )

        return result

    def correlation_filter(
        self,
        X: np.ndarray,
        feature_names: list[str],
        threshold: float | None = None,
    ) -> SelectionResult:
        """Sadece correlation filter uygula.

        Args:
            X: Feature matrix
            feature_names: Feature isimleri
            threshold: Korelasyon eşiği (None = correlation_threshold)

        Returns:
            SelectionResult
        """
        if threshold is None:
            threshold = self.correlation_threshold

        result = self._apply_correlation_filter(X, feature_names, threshold)

        return SelectionResult(
            selected_features=result["kept"],
            removed_features=list(result["removed"].keys()),
            removal_reasons=result["removed"],
            n_original=len(feature_names),
            n_selected=len(result["kept"]),
            n_removed=len(result["removed"]),
            reduction_ratio=round(1.0 - len(result["kept"]) / max(len(feature_names), 1), 4),
        )

    def variance_threshold_filter(
        self,
        X: np.ndarray,
        feature_names: list[str],
        threshold: float | None = None,
    ) -> SelectionResult:
        """Sadece variance threshold uygula.

        Args:
            X: Feature matrix
            feature_names: Feature isimleri
            threshold: Varyans eşiği (None = variance_threshold)

        Returns:
            SelectionResult
        """
        if threshold is None:
            threshold = self.variance_threshold

        result = self._apply_variance_threshold(X, feature_names, threshold)

        return SelectionResult(
            selected_features=result["kept"],
            removed_features=list(result["removed"].keys()),
            removal_reasons=result["removed"],
            n_original=len(feature_names),
            n_selected=len(result["kept"]),
            n_removed=len(result["removed"]),
            reduction_ratio=round(1.0 - len(result["kept"]) / max(len(feature_names), 1), 4),
        )

    def shap_based_selection(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        model: Any,
        top_k: int | None = None,
    ) -> SelectionResult:
        """SHAP-based feature selection.

        Args:
            X: Feature matrix
            y: Target array
            feature_names: Feature isimleri
            model: sklearn-compatible model
            top_k: Seçilecek feature sayısı

        Returns:
            SelectionResult
        """
        if top_k is None:
            top_k = self.default_top_k

        result = self._apply_shap_selection(X, y, feature_names, model, top_k)

        return SelectionResult(
            selected_features=result["kept"],
            removed_features=list(result["removed"].keys()),
            removal_reasons=result["removed"],
            n_original=len(feature_names),
            n_selected=len(result["kept"]),
            n_removed=len(result["removed"]),
            reduction_ratio=round(1.0 - len(result["kept"]) / max(len(feature_names), 1), 4),
        )

    def get_feature_importances(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        model: Any,
    ) -> list[FeatureImportance]:
        """SHAP importance skorlarını döndür.

        Args:
            X: Feature matrix
            y: Target array
            feature_names: Feature isimleri
            model: sklearn-compatible model

        Returns:
            FeatureImportance listesi (importance'a göre sıralı)
        """
        importances = self._compute_shap_importance(X, y, feature_names, model)

        result = []
        for rank, (name, imp) in enumerate(sorted(importances.items(), key=lambda x: x[1], reverse=True), start=1):
            result.append(
                FeatureImportance(
                    feature_name=name,
                    importance=round(imp, 6),
                    rank=rank,
                )
            )

        return result

    def get_selection_history(self) -> list[SelectionResult]:
        """Selection history."""
        return self._selection_history

    # =====================================================
    # INTERNAL METHODS
    # =====================================================

    def _apply_variance_threshold(
        self,
        X: np.ndarray,
        feature_names: list[str],
        threshold: float | None = None,
    ) -> dict[str, Any]:
        """Düşük varyanslı feature'ları ele."""
        if threshold is None:
            threshold = self.variance_threshold

        kept_indices: list[int] = []
        removed: dict[str, str] = {}

        for i, name in enumerate(feature_names):
            col = X[:, i]
            valid = col[np.isfinite(col)]
            if len(valid) == 0:
                removed[name] = "All values are NaN/Inf"
                continue

            var = float(np.var(valid))
            if var < threshold:
                removed[name] = f"Variance {var:.6f} < threshold {threshold}"
                continue

            kept_indices.append(i)

        return {
            "kept": [feature_names[i] for i in kept_indices],
            "kept_indices": kept_indices,
            "removed": removed,
        }

    def _apply_correlation_filter(
        self,
        X: np.ndarray,
        feature_names: list[str],
        threshold: float | None = None,
    ) -> dict[str, Any]:
        """Yüksek korelasyonlu feature çiftlerini ele.

        Her çiftten daha düşük varyanslı olanı çıkar.
        """
        if threshold is None:
            threshold = self.correlation_threshold

        n_features = len(feature_names)
        if n_features < 2:
            return {"kept": feature_names, "kept_indices": list(range(n_features)), "removed": {}}

        # Korelasyon matrisi hesapla
        try:
            # NaN maskesi
            valid_mask = np.all(np.isfinite(X), axis=1)
            X_valid = X[valid_mask]

            if len(X_valid) < 10:
                return {"kept": feature_names, "kept_indices": list(range(n_features)), "removed": {}}

            corr_matrix = np.corrcoef(X_valid.T)
            corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
        except Exception as e:
            logger.warning("correlation_filter_failed", error=str(e))
            return {"kept": feature_names, "kept_indices": list(range(n_features)), "removed": {}}

        # Eleme: yüksek korelasyonlu çiftlerden birini çıkar
        removed_set: set[int] = set()
        removed: dict[str, str] = {}

        for i in range(n_features):
            if i in removed_set:
                continue
            for j in range(i + 1, n_features):
                if j in removed_set:
                    continue

                corr_val = abs(corr_matrix[i, j])
                if corr_val > threshold:
                    # Düşük varyanslı olanı çıkar
                    var_i = float(np.var(X_valid[:, i]))
                    var_j = float(np.var(X_valid[:, j]))

                    remove_idx = j if var_i >= var_j else i
                    keep_idx = i if remove_idx == j else j

                    removed_set.add(remove_idx)
                    removed[feature_names[remove_idx]] = (
                        f"Correlation {corr_val:.4f} with {feature_names[keep_idx]} > {threshold}"
                    )

        kept_indices = [i for i in range(n_features) if i not in removed_set]

        return {
            "kept": [feature_names[i] for i in kept_indices],
            "kept_indices": kept_indices,
            "removed": removed,
        }

    def _apply_shap_selection(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        model: Any,
        top_k: int,
    ) -> dict[str, Any]:
        """SHAP importance'a göre en iyi K feature'ı seç."""
        importances = self._compute_shap_importance(X, y, feature_names, model)

        # Importance'a göre sırala
        sorted_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)

        # Top K seç
        kept_names = set(name for name, _ in sorted_features[:top_k])

        kept = [name for name in feature_names if name in kept_names]
        removed: dict[str, str] = {}

        for name in feature_names:
            if name not in kept_names:
                imp = importances.get(name, 0.0)
                removed[name] = f"SHAP importance {imp:.6f} — not in top {top_k}"

        return {"kept": kept, "removed": removed}

    def _compute_shap_importance(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        model: Any,
    ) -> dict[str, float]:
        """SHAP importance hesapla."""
        importances: dict[str, float] = {}

        try:
            # Modeli eğit
            import copy

            import shap

            fitted_model = copy.deepcopy(model)
            fitted_model.fit(X, y)

            # SHAP explainer
            if hasattr(fitted_model, "predict_proba"):
                explainer = shap.TreeExplainer(fitted_model)
            else:
                explainer = shap.KernelExplainer(fitted_model.predict, X[:100])

            shap_values = explainer.shap_values(X[:500])  # Performans için subset

            if isinstance(shap_values, list):
                shap_values = shap_values[0]

            # Mean absolute SHAP values
            mean_shap = np.mean(np.abs(shap_values), axis=0)

            for i, name in enumerate(feature_names):
                if i < len(mean_shap):
                    importances[name] = float(mean_shap[i])

        except ImportError:
            logger.warning("shap_not_installed_fallback_to_permutation")
            importances = self._permutation_importance(X, y, feature_names, model)
        except Exception as e:
            logger.warning("shap_importance_failed", error=str(e))
            importances = self._permutation_importance(X, y, feature_names, model)

        return importances

    def _permutation_importance(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        model: Any,
    ) -> dict[str, float]:
        """Permutation importance (SHAP fallback)."""
        import copy

        try:
            fitted_model = copy.deepcopy(model)
            fitted_model.fit(X, y)

            # Baseline score
            if hasattr(fitted_model, "predict_proba"):
                baseline_preds = fitted_model.predict_proba(X)[:, 1]
            else:
                baseline_preds = fitted_model.predict(X)

            baseline_corr = abs(float(np.corrcoef(baseline_preds, y)[0, 1]))
            if not np.isfinite(baseline_corr):
                baseline_corr = 0.0

            importances: dict[str, float] = {}

            for i, name in enumerate(feature_names):
                X_permuted = X.copy()
                np.random.shuffle(X_permuted[:, i])

                if hasattr(fitted_model, "predict_proba"):
                    perm_preds = fitted_model.predict_proba(X_permuted)[:, 1]
                else:
                    perm_preds = fitted_model.predict(X_permuted)

                perm_corr = abs(float(np.corrcoef(perm_preds, y)[0, 1]))
                if not np.isfinite(perm_corr):
                    perm_corr = 0.0

                importances[name] = max(0.0, baseline_corr - perm_corr)

            return importances

        except Exception as e:
            logger.warning("permutation_importance_failed", error=str(e))
            return {name: 1.0 for name in feature_names}


# Singleton
feature_selector = FeatureSelector()
