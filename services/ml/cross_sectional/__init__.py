"""
ALPHA BIST — Cross-Sectional + Temporal Model v1.0

ROADMAP v3.0:
- Cross-Sectional: Aynı gün diğer hisselerin durumu (sektör, BIST rank)
- Temporal: Zaman serisi (momentum, trend)
- Birleşik: Her iki boyut birlikte

KURAL: Hisse yalnız değil, bağlamında değerlendir!
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np
import structlog

logger = structlog.get_logger()

class CrossSectionalFeatures:
    """Cross-sectional feature hesaplama."""

    def __init__(self):
        self._sector_data: dict[str, list[dict]] = defaultdict(list)
        self._market_data: dict[str, Any] = {}
        logger.info("CrossSectionalFeatures initialized")

    def calculate_sector_relative(
        self,
        ticker: str,
        features: dict[str, Any],
        sector_tickers: list[str],
        all_features: dict[str, dict],
    ) -> dict[str, Any]:
        """Sektör bazlı göreceli feature'lar."""

        cs_features = {}

        # Sektör ortalaması
        sector_values = defaultdict(list)
        for t in sector_tickers:
            if t in all_features and t != ticker:
                for key, val in all_features[t].items():
                    if isinstance(val, (int, float)) and val is not None:
                        sector_values[key].append(val)

        # Göreceli feature'lar
        for key, val in features.items():
            if isinstance(val, (int, float)) and val is not None and key in sector_values:
                sector_avg = np.mean(sector_values[key]) if sector_values[key] else val
                sector_std = np.std(sector_values[key]) if len(sector_values[key]) > 1 else 1

                # Z-score (sektör içinde nerede?)
                cs_features[f"{key}_sector_zscore"] = round((val - sector_avg) / sector_std, 4) if sector_std else 0

                # Percentile (sektör içinde üst yüzde kaç?)
                if sector_values[key]:
                    percentile = sum(1 for v in sector_values[key] if v < val) / len(sector_values[key]) * 100
                    cs_features[f"{key}_sector_pct"] = round(percentile, 2)

                # Sektör ortalamasına göre oran
                cs_features[f"{key}_sector_ratio"] = round(val / sector_avg, 4) if sector_avg else 1.0

        # Sektör içinde rank
        if "momentum_20d" in features and "momentum_20d" in sector_values:
            all_momentums = sector_values["momentum_20d"] + [features["momentum_20d"]]
            sorted_moms = sorted(all_momentums, reverse=True)
            rank = sorted_moms.index(features["momentum_20d"]) + 1
            cs_features["momentum_sector_rank"] = rank
            cs_features["momentum_sector_total"] = len(sorted_moms)

        return cs_features

    def calculate_market_relative(
        self,
        ticker: str,
        features: dict[str, Any],
        all_features: dict[str, dict],
    ) -> dict[str, Any]:
        """Piyasa (BIST-100) bazlı göreceli feature'lar."""

        market_features = {}

        # Tüm hisselerin ortalaması
        market_values = defaultdict(list)
        for t, feats in all_features.items():
            if t != ticker:
                for key, val in feats.items():
                    if isinstance(val, (int, float)) and val is not None:
                        market_values[key].append(val)

        # BIST-100 percentile
        for key, val in features.items():
            if isinstance(val, (int, float)) and val is not None and key in market_values:
                all_vals = market_values[key] + [val]
                sorted_vals = sorted(all_vals, reverse=True)
                rank = sorted_vals.index(val) + 1
                percentile = rank / len(sorted_vals) * 100

                market_features[f"{key}_bist_rank"] = rank
                market_features[f"{key}_bist_pct"] = round(percentile, 2)
                market_features[f"{key}_bist_total"] = len(sorted_vals)

        # BIST-100 ortalama momentum
        if "momentum_20d" in market_values:
            market_features["market_avg_momentum"] = round(np.mean(market_values["momentum_20d"]), 4)
            market_features["market_momentum_dispersion"] = round(np.std(market_values["momentum_20d"]), 4)

        # Breadth göstergeleri
        if "roc_5d" in market_values:
            positive_roc = sum(1 for v in market_values["roc_5d"] if v > 0)
            market_features["market_breadth_5d"] = round(positive_roc / len(market_values["roc_5d"]) * 100, 2)

        return market_features

    def calculate_peer_correlation(
        self,
        ticker: str,
        price_history: dict[str, list[float]],
        sector_tickers: list[str],
    ) -> dict[str, Any]:
        """Sektör arkadaşları ile korelasyon."""

        if ticker not in price_history:
            return {}

        ticker_returns = np.diff(price_history[ticker]) / price_history[ticker][:-1]

        correlations = []
        for peer in sector_tickers:
            if peer != ticker and peer in price_history:
                peer_returns = np.diff(price_history[peer]) / price_history[peer][:-1]

                min_len = min(len(ticker_returns), len(peer_returns))
                if min_len > 10:
                    corr = np.corrcoef(ticker_returns[-min_len:], peer_returns[-min_len:])[0, 1]
                    if not np.isnan(corr):
                        correlations.append(corr)

        if not correlations:
            return {}

        return {
            "avg_peer_correlation": round(np.mean(correlations), 4),
            "max_peer_correlation": round(np.max(correlations), 4),
            "min_peer_correlation": round(np.min(correlations), 4),
            "peer_correlation_dispersion": round(np.std(correlations), 4),
        }

class TemporalFeatures:
    """Temporal (zaman serisi) feature'lar."""

    def __init__(self):
        logger.info("TemporalFeatures initialized")

    def calculate_trend_features(
        self,
        prices: list[float],
        volumes: list[float] | None = None,
    ) -> dict[str, Any]:
        """Trend feature'ları."""

        if len(prices) < 20:
            return {}

        features = {}

        # Lineer regresyon eğimi (trend gücü)
        x = np.arange(len(prices))
        slope, intercept = np.polyfit(x, prices, 1)
        features["trend_slope"] = round(slope, 4)
        features["trend_r2"] = round(np.corrcoef(x, prices)[0, 1] ** 2, 4)

        # Hızlanma/ivme (momentum'un türevi)
        if len(prices) >= 40:
            mom_short = (prices[-1] - prices[-10]) / prices[-10] * 100
            mom_long = (prices[-1] - prices[-30]) / prices[-30] * 100
            features["momentum_acceleration"] = round(mom_short - mom_long / 3, 4)

        # Volatilite trendi
        if len(prices) >= 40:
            vol_short = np.std(np.diff(prices[-20:]) / prices[-20:-1])
            vol_long = np.std(np.diff(prices[-40:]) / prices[-40:-1])
            features["volatility_trend"] = round((vol_short / vol_long - 1) * 100, 4) if vol_long else 0

        # Volume trend (hacim artıyor mu?)
        if volumes and len(volumes) >= 20:
            vol_recent = np.mean(volumes[-5:])
            vol_old = np.mean(volumes[-20:-5])
            features["volume_trend_pct"] = round((vol_recent / vol_old - 1) * 100, 4) if vol_old else 0

        return features

    def calculate_regime_features(
        self,
        prices: list[float],
        window: int = 60,
    ) -> dict[str, Any]:
        """Regime feature'ları."""

        if len(prices) < window:
            return {}

        returns = np.diff(prices) / prices[:-1]
        recent_returns = returns[-window:]

        return {
            "return_skewness": round(float(np.mean((recent_returns - np.mean(recent_returns))**3) / np.std(recent_returns)**3), 4) if np.std(recent_returns) > 0 else 0,
            "return_kurtosis": round(float(np.mean((recent_returns - np.mean(recent_returns))**4) / np.std(recent_returns)**4), 4) if np.std(recent_returns) > 0 else 0,
            "max_consecutive_up": self._max_consecutive(returns[-window:] > 0),
            "max_consecutive_down": self._max_consecutive(returns[-window:] < 0),
        }

    def _max_consecutive(self, bool_array: np.ndarray) -> int:
        """Maksimum ardışık True sayısı."""
        max_count = 0
        current = 0
        for val in bool_array:
            if val:
                current += 1
                max_count = max(max_count, current)
            else:
                current = 0
        return max_count

# Singleton
cross_sectional_features = CrossSectionalFeatures()
temporal_features = TemporalFeatures()
