"""ALPHA BIST - Feature Discovery Pipeline v1.1

Binlerce değişken arasındaki ilişkileri keşfeden pipeline.
"""

import numpy as np
import polars as pl
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import structlog

logger = structlog.get_logger()


@dataclass
class FeatureDiscoveryResult:
    """Feature discovery sonucu."""
    selected_features: List[str]
    feature_importance: Dict[str, float]
    feature_interactions: List[Dict[str, Any]]
    stability_scores: Dict[str, float]
    leakage_flags: Dict[str, bool]
    regime_importance: Dict[str, Dict[str, float]]


class FeatureDiscoveryPipeline:
    """Feature discovery and selection pipeline."""

    def __init__(self):
        self.raw_features: List[str] = []
        self.candidate_features: List[str] = []
        self.selected_features: List[str] = []

    def discover(
        self,
        feature_data: pl.DataFrame,
        target: pl.Series,
        feature_names: List[str],
        regime_labels: Optional[pl.Series] = None,
    ) -> FeatureDiscoveryResult:
        """
        Run full feature discovery pipeline.

        1. Generate feature interactions
        2. Mutual Information filtering
        3. Correlation filter
        4. Permutation Importance
        5. SHAP values
        6. Feature stability
        7. Leakage detection
        8. Regime-conditioned importance
        """
        logger.info("Starting feature discovery", initial_features=len(feature_names))

        # Step 1: Generate interactions
        expanded_data, expanded_names = self._generate_interactions(
            feature_data, feature_names
        )
        logger.info("Interactions generated", total_features=len(expanded_names))

        # Step 2: Mutual Information
        mi_scores = self._mutual_information(expanded_data, target, expanded_names)
        mi_selected = [
            name for name, score in mi_scores.items() if score > 0.01
        ]
        logger.info("MI filtering", selected=len(mi_selected))

        # Step 3: Correlation filter
        corr_filtered = self._correlation_filter(
            expanded_data.select(mi_selected), mi_selected, threshold=0.95
        )
        logger.info("Correlation filter", selected=len(corr_filtered))

        # Step 4: Permutation Importance
        perm_importance = self._permutation_importance(
            expanded_data.select(corr_filtered), target, corr_filtered
        )
        logger.info("Permutation importance computed")

        # Step 5: SHAP (simplified)
        shap_importance = self._shap_importance(
            expanded_data.select(corr_filtered), target, corr_filtered
        )
        logger.info("SHAP importance computed")

        # Step 6: Feature stability
        stability = self._feature_stability(
            expanded_data.select(corr_filtered), target, corr_filtered
        )
        logger.info("Feature stability computed")

        # Step 7: Leakage detection
        leakage = self._detect_leakage(
            expanded_data.select(corr_filtered), target, corr_filtered
        )
        logger.info("Leakage detection done", flagged=sum(leakage.values()))

        # Step 8: Regime-conditioned importance
        regime_imp = {}
        if regime_labels is not None:
            regime_imp = self._regime_conditioned_importance(
                expanded_data.select(corr_filtered), target, corr_filtered, regime_labels
            )
            logger.info("Regime importance computed")

        # Final selection: combine all signals
        final_features = self._final_selection(
            corr_filtered, perm_importance, shap_importance,
            stability, leakage
        )

        # Combined importance
        combined_importance = {}
        for f in final_features:
            combined_importance[f] = (
                perm_importance.get(f, 0) * 0.4
                + shap_importance.get(f, 0) * 0.3
                + stability.get(f, 0) * 0.2
                + mi_scores.get(f, 0) * 0.1
            )

        logger.info("Feature discovery complete", final_features=len(final_features))

        return FeatureDiscoveryResult(
            selected_features=final_features,
            feature_importance=combined_importance,
            feature_interactions=[],  # TODO
            stability_scores=stability,
            leakage_flags=leakage,
            regime_importance=regime_imp,
        )

    # =====================================================
    # Step 1: Feature Interaction Generation
    # =====================================================

    def _generate_interactions(
        self, data: pl.DataFrame, feature_names: List[str]
    ) -> Tuple[pl.DataFrame, List[str]]:
        """Generate pairwise feature interactions."""
        new_data = data.clone()
        new_names = list(feature_names)

        # Limit to top features to avoid explosion
        top_features = feature_names[:20]

        for i, f1 in enumerate(top_features):
            for f2 in top_features[i + 1:]:
                # Product
                prod_name = f"{f1}_x_{f2}"
                new_data = new_data.with_columns(
                    (pl.col(f1) * pl.col(f2)).alias(prod_name)
                )
                new_names.append(prod_name)

                # Ratio (avoid division by zero)
                ratio_name = f"{f1}_div_{f2}"
                new_data = new_data.with_columns(
                    pl.when(pl.col(f2).abs() > 1e-10)
                    .then(pl.col(f1) / pl.col(f2))
                    .otherwise(0)
                    .alias(ratio_name)
                )
                new_names.append(ratio_name)

                # Difference
                diff_name = f"{f1}_minus_{f2}"
                new_data = new_data.with_columns(
                    (pl.col(f1) - pl.col(f2)).alias(diff_name)
                )
                new_names.append(diff_name)

        return new_data, new_names

    # =====================================================
    # Step 2: Mutual Information
    # =====================================================

    def _mutual_information(
        self, data: pl.DataFrame, target: pl.Series, feature_names: List[str]
    ) -> Dict[str, float]:
        """Compute mutual information between features and target."""
        from sklearn.feature_selection import mutual_info_regression

        X = data.select(feature_names).to_numpy()
        y = target.to_numpy()

        # Handle NaN
        mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X, y = X[mask], y[mask]

        if len(X) < 50:
            return {f: 0.0 for f in feature_names}

        mi_scores = mutual_info_regression(X, y, random_state=42, n_neighbors=5)

        return dict(zip(feature_names, mi_scores))

    # =====================================================
    # Step 3: Correlation Filter
    # =====================================================

    def _correlation_filter(
        self, data: pl.DataFrame, feature_names: List[str], threshold: float = 0.95
    ) -> List[str]:
        """Remove highly correlated features."""
        corr_matrix = data.to_pandas().corr().abs()

        # Find pairs to drop
        to_drop = set()
        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                if corr_matrix.iloc[i, j] > threshold:
                    # Drop the one with lower mean correlation to all others
                    mean_i = corr_matrix.iloc[i].mean()
                    mean_j = corr_matrix.iloc[j].mean()
                    if mean_i > mean_j:
                        to_drop.add(corr_matrix.columns[j])
                    else:
                        to_drop.add(corr_matrix.columns[i])

        return [f for f in feature_names if f not in to_drop]

    # =====================================================
    # Step 4: Permutation Importance
    # =====================================================

    def _permutation_importance(
        self, data: pl.DataFrame, target: pl.Series, feature_names: List[str]
    ) -> Dict[str, float]:
        """Compute permutation importance using LightGBM."""
        import lightgbm as lgb
        from sklearn.model_selection import cross_val_score

        X = data.select(feature_names).to_numpy()
        y = target.to_numpy()

        mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X, y = X[mask], y[mask]

        if len(X) < 100:
            return {f: 0.0 for f in feature_names}

        # Train model
        model = lgb.LGBMRegressor(n_estimators=100, max_depth=5, random_state=42, verbose=-1)
        model.fit(X, y)

        # Permutation importance
        from sklearn.inspection import permutation_importance
        result = permutation_importance(model, X, y, n_repeats=5, random_state=42)

        return dict(zip(feature_names, result.importances_mean))

    # =====================================================
    # Step 5: SHAP (Simplified)
    # =====================================================

    def _shap_importance(
        self, data: pl.DataFrame, target: pl.Series, feature_names: List[str]
    ) -> Dict[str, float]:
        """Compute SHAP-based feature importance."""
        import lightgbm as lgb

        X = data.select(feature_names).to_numpy()
        y = target.to_numpy()

        mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X, y = X[mask], y[mask]

        if len(X) < 100:
            return {f: 0.0 for f in feature_names}

        # Train model
        model = lgb.LGBMRegressor(n_estimators=100, max_depth=5, random_state=42, verbose=-1)
        model.fit(X, y)

        # SHAP TreeExplainer (fast for tree models)
        try:
            import shap
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X[:500])  # sample for speed
            mean_abs_shap = np.abs(shap_values).mean(axis=0)
            return dict(zip(feature_names, mean_abs_shap))
        except ImportError:
            # Fallback: use built-in feature importance
            importance = model.feature_importances_
            return dict(zip(feature_names, importance))

    # =====================================================
    # Step 6: Feature Stability
    # =====================================================

    def _feature_stability(
        self, data: pl.DataFrame, target: pl.Series, feature_names: List[str]
    ) -> Dict[str, float]:
        """Check if feature importance is stable across time periods."""
        import lightgbm as lgb

        X = data.select(feature_names).to_numpy()
        y = target.to_numpy()

        mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X, y = X[mask], y[mask]

        if len(X) < 200:
            return {f: 1.0 for f in feature_names}

        # Split into 3 time periods
        n = len(X)
        third = n // 3

        importances = []
        for i in range(3):
            start = i * third
            end = (i + 1) * third if i < 2 else n
            X_seg, y_seg = X[start:end], y[start:end]

            model = lgb.LGBMRegressor(n_estimators=50, max_depth=5, random_state=42, verbose=-1)
            model.fit(X_seg, y_seg)
            importances.append(model.feature_importances_)

        # Stability = 1 - std(importances) / mean(importances)
        imp_array = np.array(importances)
        stability = {}
        for idx, f in enumerate(feature_names):
            mean_imp = imp_array[:, idx].mean()
            std_imp = imp_array[:, idx].std()
            if mean_imp > 0:
                stability[f] = max(0, 1 - std_imp / mean_imp)
            else:
                stability[f] = 0.0

        return stability

    # =====================================================
    # Step 7: Leakage Detection
    # =====================================================

    def _detect_leakage(
        self, data: pl.DataFrame, target: pl.Series, feature_names: List[str]
    ) -> Dict[str, bool]:
        """Detect if any feature leaks future information."""
        # Simple heuristic: if a feature has suspiciously high correlation with future target
        # it might be leaking

        leakage = {}
        X = data.to_pandas()
        y = target.to_numpy()

        for f in feature_names:
            try:
                # Correlation with current target
                corr_current = np.corrcoef(X[f].fillna(0), y)[0, 1]

                # If correlation is extremely high (>0.9), flag as potential leakage
                if abs(corr_current) > 0.9:
                    leakage[f] = True
                    logger.warning("Potential leakage detected", feature=f, correlation=corr_current)
                else:
                    leakage[f] = False
            except:
                leakage[f] = False

        return leakage

    # =====================================================
    # Step 8: Regime-Conditioned Importance
    # =====================================================

    def _regime_conditioned_importance(
        self,
        data: pl.DataFrame,
        target: pl.Series,
        feature_names: List[str],
        regime_labels: pl.Series,
    ) -> Dict[str, Dict[str, float]]:
        """Compute feature importance per market regime."""
        import lightgbm as lgb

        regimes = regime_labels.unique().to_list()
        result = {}

        for regime in regimes:
            mask = regime_labels == regime
            X_regime = data.filter(mask).select(feature_names).to_numpy()
            y_regime = target.filter(mask).to_numpy()

            nan_mask = ~(np.isnan(X_regime).any(axis=1) | np.isnan(y_regime))
            X_regime, y_regime = X_regime[nan_mask], y_regime[nan_mask]

            if len(X_regime) < 50:
                continue

            model = lgb.LGBMRegressor(n_estimators=50, max_depth=5, random_state=42, verbose=-1)
            model.fit(X_regime, y_regime)

            importance = model.feature_importances_
            result[str(regime)] = dict(zip(feature_names, importance))

        return result

    # =====================================================
    # Final Selection
    # =====================================================

    def _final_selection(
        self,
        features: List[str],
        perm_importance: Dict[str, float],
        shap_importance: Dict[str, float],
        stability: Dict[str, float],
        leakage: Dict[str, bool],
    ) -> List[str]:
        """Final feature selection combining all signals."""
        selected = []

        for f in features:
            # Skip leaked features
            if leakage.get(f, False):
                continue

            # Must have some importance
            perm = perm_importance.get(f, 0)
            shap = shap_importance.get(f, 0)
            stab = stability.get(f, 0)

            # Combined score
            score = perm * 0.4 + shap * 0.3 + stab * 0.3

            if score > 0.001:  # minimum threshold
                selected.append(f)

        return selected


# Singleton
feature_discovery = FeatureDiscoveryPipeline()
