"""
ALPHA BIST — Cross-Sectional + Temporal Model v1.0

ROADMAP v3.0:
- Cross-Sectional: Aynı gün diğer hisselerin durumu (sektör, BIST rank)
- Temporal: Zaman serisi (momentum, trend)
- Birleşik: Her iki boyut birlikte

KURAL: Hisse yalnız değil, bağlamında değerlendir!
"""

from collections import defaultdict
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


class CrossSectionalFeatures:
    """Cross-sectional (kesitsel) öznitelik hesaplayıcı.

    Hisseleri yalnız değil, aynı gün ve zaman diliminde yer aldıkları
    sektör ve genel endeks içerisindeki göreceli konumuyla değerlendirir.
    """

    def __init__(self) -> None:
        """CrossSectionalFeatures örneği oluşturur."""
        self._sector_data: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._market_data: dict[str, Any] = {}
        logger.info("CrossSectionalFeatures initialized")

    def __repr__(self) -> str:
        """CrossSectionalFeatures string temsili."""
        return f"CrossSectionalFeatures(sectors={len(self._sector_data)})"

    def calculate_sector_relative(
        self,
        ticker: str,
        features: dict[str, Any],
        sector_tickers: list[str],
        all_features: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Sektör bazlı göreceli feature'ları hesaplar.

        Args:
            ticker: Analiz edilen hisse sembolü.
            features: Hissenin mevcut ham öznitelik sözlüğü.
            sector_tickers: İlgili sektördeki tüm hisse sembolleri.
            all_features: Tüm hisselerin ham özniteliklerini içeren sözlük.

        Returns:
            Sektör z-skoru, yüzdelik dilimi, oranları ve sıralamasını içeren sözlük.
        """
        cs_features: dict[str, Any] = {}

        # Sektör ortalaması
        sector_values: dict[str, list[float]] = defaultdict(list)
        for t in sector_tickers:
            if t in all_features and t != ticker:
                for key, val in all_features[t].items():
                    if isinstance(val, (int, float)) and val is not None:
                        sector_values[key].append(float(val))

        # Göreceli feature'lar
        for key, raw_val in features.items():
            if isinstance(raw_val, (int, float)) and raw_val is not None and key in sector_values:
                val = float(raw_val)
                vals_list = sector_values[key]
                sector_avg = float(np.mean(vals_list)) if vals_list else val
                sector_std = float(np.std(vals_list)) if len(vals_list) > 1 else 1.0

                # Z-score (sektör içinde nerede?)
                cs_features[f"{key}_sector_zscore"] = round((val - sector_avg) / sector_std, 4) if sector_std else 0.0

                # Percentile (sektör içinde üst yüzde kaç?)
                if vals_list:
                    percentile = sum(1 for v in vals_list if v < val) / len(vals_list) * 100.0
                    cs_features[f"{key}_sector_pct"] = round(percentile, 2)

                # Sektör ortalamasına göre oran
                cs_features[f"{key}_sector_ratio"] = round(val / sector_avg, 4) if sector_avg else 1.0

        # Sektör içinde rank
        if "momentum_20d" in features and "momentum_20d" in sector_values:
            all_momentums = sector_values["momentum_20d"] + [float(features["momentum_20d"])]
            sorted_moms = sorted(all_momentums, reverse=True)
            rank = sorted_moms.index(float(features["momentum_20d"])) + 1
            cs_features["momentum_sector_rank"] = rank
            cs_features["momentum_sector_total"] = len(sorted_moms)

        return cs_features

    def calculate_market_relative(
        self,
        ticker: str,
        features: dict[str, Any],
        all_features: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Piyasa (BIST-100) bazlı göreceli feature'ları hesaplar.

        Args:
            ticker: Analiz edilen hisse sembolü.
            features: Hissenin mevcut ham öznitelik sözlüğü.
            all_features: Tüm piyasadaki hisselerin öznitelik haritası.

        Returns:
            Endeks geneli sıralama, yüzdelik dilim ve piyasa dağılım metrikleri.
        """
        market_features: dict[str, Any] = {}

        # Tüm hisselerin ortalaması
        market_values: dict[str, list[float]] = defaultdict(list)
        for t, feats in all_features.items():
            if t != ticker:
                for key, val in feats.items():
                    if isinstance(val, (int, float)) and val is not None:
                        market_values[key].append(float(val))

        # BIST-100 percentile
        for key, raw_val in features.items():
            if isinstance(raw_val, (int, float)) and raw_val is not None and key in market_values:
                val = float(raw_val)
                all_vals = market_values[key] + [val]
                sorted_vals = sorted(all_vals, reverse=True)
                rank = sorted_vals.index(val) + 1
                percentile = rank / len(sorted_vals) * 100.0

                market_features[f"{key}_bist_rank"] = rank
                market_features[f"{key}_bist_pct"] = round(percentile, 2)
                market_features[f"{key}_bist_total"] = len(sorted_vals)

        # BIST-100 ortalama momentum
        if "momentum_20d" in market_values:
            market_features["market_avg_momentum"] = round(float(np.mean(market_values["momentum_20d"])), 4)
            market_features["market_momentum_dispersion"] = round(float(np.std(market_values["momentum_20d"])), 4)

        # Breadth göstergeleri
        if "roc_5d" in market_values:
            positive_roc = sum(1 for v in market_values["roc_5d"] if v > 0)
            market_features["market_breadth_5d"] = round(positive_roc / len(market_values["roc_5d"]) * 100.0, 2)

        return market_features

    def calculate_peer_correlation(
        self,
        ticker: str,
        price_history: dict[str, list[float]],
        sector_tickers: list[str],
    ) -> dict[str, Any]:
        """Sektör akranları ile korelasyonu hesaplar.

        Args:
            ticker: Hedef hisse sembolü.
            price_history: {sembol: [fiyatlar]} geçmiş serisi.
            sector_tickers: Sektördeki hisselerin listesi.

        Returns:
            Ortalama, maksimum, minimum ve dağılım korelasyon metrikleri.
        """
        if ticker not in price_history or len(price_history[ticker]) < 2:
            return {}

        prices = np.array(price_history[ticker], dtype=float)
        ticker_returns = np.diff(prices) / prices[:-1]

        correlations: list[float] = []
        for peer in sector_tickers:
            if peer != ticker and peer in price_history and len(price_history[peer]) >= 2:
                peer_prices = np.array(price_history[peer], dtype=float)
                peer_returns = np.diff(peer_prices) / peer_prices[:-1]

                min_len = min(len(ticker_returns), len(peer_returns))
                if min_len > 10:
                    corr = float(np.corrcoef(ticker_returns[-min_len:], peer_returns[-min_len:])[0, 1])
                    if not np.isnan(corr):
                        correlations.append(corr)

        if not correlations:
            return {}

        return {
            "avg_peer_correlation": round(float(np.mean(correlations)), 4),
            "max_peer_correlation": round(float(np.max(correlations)), 4),
            "min_peer_correlation": round(float(np.min(correlations)), 4),
            "peer_correlation_dispersion": round(float(np.std(correlations)), 4),
        }


class TemporalFeatures:
    """Zaman serisi (temporal) trend ve rejim öznitelikleri motoru."""

    def __init__(self) -> None:
        """TemporalFeatures örneği oluşturur."""
        logger.info("TemporalFeatures initialized")

    def __repr__(self) -> str:
        """TemporalFeatures string temsili."""
        return "TemporalFeatures()"

    def calculate_trend_features(
        self,
        prices: list[float],
        volumes: list[float] | None = None,
    ) -> dict[str, Any]:
        """Fiyat ve hacim serilerinden trend özelliklerini hesaplar.

        Args:
            prices: Kapanış fiyatları zaman serisi.
            volumes: İşlem hacmi serisi (opsiyonel).

        Returns:
            Eğim, R2, momentum ivmesi ve hacim trend metrikleri.
        """
        if len(prices) < 20:
            return {}

        features: dict[str, Any] = {}

        # Lineer regresyon eğimi (trend gücü)
        x = np.arange(len(prices))
        slope, _ = np.polyfit(x, prices, 1)
        features["trend_slope"] = round(float(slope), 4)
        features["trend_r2"] = round(float(np.corrcoef(x, prices)[0, 1] ** 2), 4)

        # Hızlanma/ivme (momentum'un türevi)
        if len(prices) >= 40:
            mom_short = (prices[-1] - prices[-10]) / prices[-10] * 100.0
            mom_long = (prices[-1] - prices[-30]) / prices[-30] * 100.0
            features["momentum_acceleration"] = round(float(mom_short - mom_long / 3.0), 4)

        # Volatilite trendi
        if len(prices) >= 40:
            prices_arr = np.array(prices, dtype=float)
            vol_short = float(np.std(np.diff(prices_arr[-20:]) / prices_arr[-20:-1]))
            vol_long = float(np.std(np.diff(prices_arr[-40:]) / prices_arr[-40:-1]))
            features["volatility_trend"] = round(float((vol_short / vol_long - 1.0) * 100.0), 4) if vol_long else 0.0

        # Volume trend (hacim artıyor mu?)
        if volumes and len(volumes) >= 20:
            vol_recent = float(np.mean(volumes[-5:]))
            vol_old = float(np.mean(volumes[-20:-5]))
            features["volume_trend_pct"] = round(float((vol_recent / vol_old - 1.0) * 100.0), 4) if vol_old else 0.0

        return features

    def calculate_regime_features(
        self,
        prices: list[float],
        window: int = 60,
    ) -> dict[str, Any]:
        """Piyasa getirilerinin dağılım ve rejim özniteliklerini hesaplar.

        Args:
            prices: Kapanış fiyatları serisi.
            window: Hesaplama pencere boyutu (varsayılan: 60 gün).

        Returns:
            Çarpıklık (skewness), basıklık (kurtosis) ve ardışık yükseliş/düşüş günleri.
        """
        if len(prices) < window:
            return {}

        prices_arr = np.array(prices, dtype=float)
        returns = np.diff(prices_arr) / prices_arr[:-1]
        recent_returns = returns[-window:]

        std_dev = float(np.std(recent_returns))
        mean_val = float(np.mean(recent_returns))

        skew = float(np.mean((recent_returns - mean_val) ** 3) / (std_dev**3)) if std_dev > 0 else 0.0
        kurt = float(np.mean((recent_returns - mean_val) ** 4) / (std_dev**4)) if std_dev > 0 else 0.0

        return {
            "return_skewness": round(skew, 4),
            "return_kurtosis": round(kurt, 4),
            "max_consecutive_up": self._max_consecutive(recent_returns > 0),
            "max_consecutive_down": self._max_consecutive(recent_returns < 0),
        }

    def _max_consecutive(self, bool_array: np.ndarray) -> int:
        """Maksimum ardışık True sayısını hesaplar.

        Args:
            bool_array: Boole dizisi.

        Returns:
            En uzun ardışık True adedi.
        """
        max_count = 0
        current = 0
        for val in bool_array:
            if bool(val):
                current += 1
                max_count = max(max_count, current)
            else:
                current = 0
        return max_count


# Singleton örnekler
cross_sectional_features = CrossSectionalFeatures()
temporal_features = TemporalFeatures()

__all__ = [
    "CrossSectionalFeatures",
    "TemporalFeatures",
    "cross_sectional_features",
    "temporal_features",
]
