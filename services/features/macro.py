# Macro Feature Engine
# Macro-economic feature computation for BIST analysis

from __future__ import annotations

import threading
from typing import Any

import numpy as np

# Varsayılan makro eşik sabitleri
DEFAULT_VIX_HIGH_THRESHOLD: float = 25.0
DEFAULT_USDTRY_CHANGE_THRESHOLD: float = 1.0
DEFAULT_BRENT_CHANGE_THRESHOLD: float = 3.0


class MacroFeatureEngine:
    """Makro-ekonomik feature hesaplama motoru.

    BIST piyasası için makro göstergelerden (USD/TRY, ABD 10Y, VIX, Brent, Altın)
    feature üretir.

    Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.
    """

    def __init__(self) -> None:
        """Makro feature motoru başlatıcısı.

        Boş bir makro önbellek oluşturur.
        """
        self._cache: dict[str, float] = {}
        self._lock = threading.Lock()

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
        usdtry = macro_data.get("usdtry", None)
        features["macro_usdtry_level"] = float(usdtry) if usdtry is not None else float("nan")
        features["macro_usdtry_change"] = float(macro_data.get("usdtry_change_pct", 0))

        # US 10Y yield
        us10y = macro_data.get("us10y", None)
        features["macro_us10y_level"] = float(us10y) if us10y is not None else float("nan")
        features["macro_us10y_change"] = float(macro_data.get("us10y_change_pct", 0))

        # VIX
        vix = macro_data.get("vix", None)
        features["macro_vix_level"] = float(vix) if vix is not None else float("nan")
        features["macro_vix_regime"] = 1.0 if (vix is not None and float(vix) > DEFAULT_VIX_HIGH_THRESHOLD) else 0.0

        # Brent crude
        brent = macro_data.get("brent_crude", None)
        features["macro_brent_level"] = float(brent) if brent is not None else float("nan")
        features["macro_brent_change"] = float(macro_data.get("brent_change_pct", 0))

        # Gold
        gold = macro_data.get("gold", None)
        features["macro_gold_level"] = float(gold) if gold is not None else float("nan")

        # Risk appetite composite
        risk_factors = [
            features.get("macro_vix_regime", 0),
            1.0 if features.get("macro_usdtry_change", 0) > DEFAULT_USDTRY_CHANGE_THRESHOLD else 0.0,
            1.0 if features.get("macro_brent_change", 0) > DEFAULT_BRENT_CHANGE_THRESHOLD else 0.0,
        ]
        features["macro_risk_score"] = float(np.mean(risk_factors))

        with self._lock:
            self._cache = features
        return features

    def get_cached(self) -> dict[str, float]:
        """Önbellekteki makro feature'ları döndür.

        Returns:
            Feature dict'inin kopyası.
        """
        with self._lock:
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
