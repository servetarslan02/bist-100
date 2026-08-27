# Cross-Sectional Feature Engine
# Calculates cross-sectional features across BIST universe

from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class CrossSectionalEngine:
    """Cross-sectional feature computation engine for BIST universe."""

    def compute_all_cross_sectional(
        self,
        ticker: str,
        features: dict[str, float],
        universe_features: dict[str, dict[str, float]],
    ) -> dict[str, float]:
        """Compute all cross-sectional features for a ticker.

        Args:
            ticker: Target ticker
            features: Features of the target ticker
            universe_features: Features of all tickers in universe

        Returns:
            Dict of cross-sectional feature_name -> value
        """
        result: dict[str, float] = {}
        tickers = list(universe_features.keys())
        if len(tickers) < 2:
            return result

        for fname in features:
            values = [universe_features[t].get(fname, 0.0) for t in tickers if fname in universe_features[t]]
            if not values:
                continue

            arr = np.array(values)
            val = features[fname]

            # Percentile rank
            rank = float(np.sum(arr <= val)) / len(arr) if len(arr) > 1 else 0.5
            result[f"cs_rank_{fname}"] = rank

            # Z-score
            mean = np.mean(arr)
            std = np.std(arr)
            result[f"cs_zscore_{fname}"] = float((val - mean) / std) if std > 1e-10 else 0.0

        return result

    def compute_rank_features(
        self,
        ticker: str,
        features: dict[str, float],
        all_day_features: list[dict[str, float]],
    ) -> dict[str, float]:
        """Compute rank-based features using historical cross-sectional data.

        Args:
            ticker: Target ticker
            features: Current features
            all_day_features: List of feature dicts from all tickers for the day

        Returns:
            Dict of rank feature_name -> value
        """
        result: dict[str, float] = {}

        for fname, val in features.items():
            if not isinstance(val, (int, float)):
                continue

            values = [f.get(fname, 0.0) for f in all_day_features if fname in f]
            if len(values) < 2:
                continue

            arr = np.array(values, dtype=float)
            arr = arr[~np.isnan(arr)]
            if len(arr) < 2:
                continue

            # Percentile rank
            rank = float(np.sum(arr <= val)) / len(arr)
            result[f"rank_{fname}"] = rank

        return result

    def compute_market_breadth_features(
        self,
        all_day_features: list[dict[str, float]],
    ) -> dict[str, float]:
        """Compute market breadth indicators.

        Args:
            all_day_features: List of feature dicts from all tickers

        Returns:
            Dict of breadth feature_name -> value
        """
        result: dict[str, float] = {}

        # Advance/Decline ratio
        momentum_values = [f.get("momentum", f.get("returns_1d", 0.0)) for f in all_day_features]
        if momentum_values:
            arr = np.array(momentum_values, dtype=float)
            arr = arr[~np.isnan(arr)]
            if len(arr) > 0:
                advancing = int(np.sum(arr > 0))
                declining = int(np.sum(arr < 0))
                total = len(arr)
                result["breadth_advance_ratio"] = advancing / total if total > 0 else 0.5
                result["breadth_decline_ratio"] = declining / total if total > 0 else 0.5
                result["breadth_ad_ratio"] = advancing / declining if declining > 0 else float(advancing)

        # Average RSI
        rsi_values = [f.get("rsi_14", 50.0) for f in all_day_features if "rsi_14" in f]
        if rsi_values:
            result["breadth_avg_rsi"] = float(np.mean(rsi_values))

        # Volatility spread
        vol_values = [f.get("volatility", 0.0) for f in all_day_features if "volatility" in f]
        if vol_values:
            result["breadth_vol_spread"] = float(np.std(vol_values))

        return result


# Singleton
cross_sectional_engine = CrossSectionalEngine()
