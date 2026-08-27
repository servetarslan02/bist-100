# Macro Feature Engine
# Macro-economic feature computation for BIST analysis

from __future__ import annotations

from typing import Any

import numpy as np


class MacroFeatureEngine:
    """Computes macro-economic features for market analysis."""

    def __init__(self):
        self._cache: dict[str, float] = {}

    def compute_features(
        self,
        macro_data: dict[str, Any],
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Compute macro features from economic indicators.

        Args:
            macro_data: Dict with macro indicators (usdtry, us10y, vix, brent, etc.)
            market_data: Optional market data for cross-asset features

        Returns:
            Dict of feature_name -> value
        """
        features: dict[str, float] = {}

        # USD/TRY features
        usdtry = macro_data.get("usdtry", 0)
        features["macro_usdtry_level"] = float(usdtry) if usdtry else 0.0
        features["macro_usdtry_change"] = float(macro_data.get("usdtry_change_pct", 0))

        # US 10Y yield
        us10y = macro_data.get("us10y", 0)
        features["macro_us10y_level"] = float(us10y) if us10y else 0.0
        features["macro_us10y_change"] = float(macro_data.get("us10y_change_pct", 0))

        # VIX
        vix = macro_data.get("vix", 0)
        features["macro_vix_level"] = float(vix) if vix else 0.0
        features["macro_vix_regime"] = 1.0 if (vix and float(vix) > 25) else 0.0

        # Brent crude
        brent = macro_data.get("brent_crude", 0)
        features["macro_brent_level"] = float(brent) if brent else 0.0
        features["macro_brent_change"] = float(macro_data.get("brent_change_pct", 0))

        # Gold
        gold = macro_data.get("gold", 0)
        features["macro_gold_level"] = float(gold) if gold else 0.0

        # Risk appetite composite
        risk_factors = [
            features.get("macro_vix_regime", 0),
            1.0 if features.get("macro_usdtry_change", 0) > 1.0 else 0.0,
            1.0 if features.get("macro_brent_change", 0) > 3.0 else 0.0,
        ]
        features["macro_risk_score"] = float(np.mean(risk_factors))

        self._cache = features
        return features

    def get_cached(self) -> dict[str, float]:
        """Get cached macro features."""
        return self._cache.copy()

    def compute_all_macro_features(
        self,
        macro_data: dict[str, Any],
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Backward-compatible wrapper — orchestrator bu metodu çağırır."""
        return self.compute_features(macro_data, market_data)


# Singleton
macro_feature_engine = MacroFeatureEngine()
