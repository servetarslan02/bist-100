"""ALPHA BIST — Cross-Sectional Feature Engine.

BIST-100 evrenindeki hisseler arası cross-sectional feature hesaplama:
- Percentile rank (evren içinde sıralama)
- Z-score (standart sapma bazlı normalize)
- Piyasa genişliği göstergeleri (advance/decline, RSI, volatilite)
"""

from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Cross-sectional hesaplama için minimum ticker sayısı
DEFAULT_MIN_UNIVERSE_SIZE: int = 2

# RSI nötr değeri (bilgi yokken kullanılmaz, NaN döner)
DEFAULT_RSI_NEUTRAL: float = 50.0


class CrossSectionalEngine:
    """Cross-sectional feature hesaplama motoru.

    BIST-100 evrenindeki hisseler arasında sıralama, normalize
    ve piyasa genişliği feature'ları üretir.
    """

    def compute_all_cross_sectional(
        self,
        ticker: str,
        features: dict[str, float],
        universe_features: dict[str, dict[str, float]],
    ) -> dict[str, float]:
        """Bir hisse için tüm cross-sectional feature'ları hesapla.

        Her feature için evren içinde percentile rank ve z-score hesaplar.
        NaN/Inf değerler filtrelendikten sonra hesaplama yapılır.

        Args:
            ticker: Hedef hisse senedi kodu.
            features: Hedef hissenin feature'ları.
            universe_features: Evrendeki tüm hisselerin feature'ları.

        Returns:
            Cross-sectional feature adı → değer dict'i.
            cs_rank_ ve cs_zscore_ ön ekleri ile.
        """
        result: dict[str, float] = {}
        tickers = list(universe_features.keys())
        if len(tickers) < DEFAULT_MIN_UNIVERSE_SIZE:
            return result

        for fname in features:
            values = [
                universe_features[t].get(fname, float("nan"))
                for t in tickers
                if fname in universe_features[t]
            ]
            if not values:
                continue

            arr = np.array(values, dtype=float)
            arr = arr[np.isfinite(arr)]  # NaN/Inf filtrele
            if len(arr) < DEFAULT_MIN_UNIVERSE_SIZE:
                continue

            val = features[fname]
            if not np.isfinite(val):
                continue

            # Percentile rank
            rank = (
                float(np.sum(arr <= val)) / len(arr)
                if len(arr) > 1
                else 0.5
            )
            result[f"cs_rank_{fname}"] = rank

            # Z-score
            mean = np.mean(arr)
            std = np.std(arr)
            result[f"cs_zscore_{fname}"] = (
                float((val - mean) / std)
                if std > np.finfo(float).eps
                else 0.0
            )

        return result

    def compute_rank_features(
        self,
        ticker: str,
        features: dict[str, float],
        all_day_features: list[dict[str, float]],
    ) -> dict[str, float]:
        """Tarihsel cross-sectional veriyle rank feature'ları hesapla.

        Gün sonundaki tüm hisselerin feature'larını kullanarak
        her feature için percentile rank hesaplar.

        Args:
            ticker: Hedef hisse senedi kodu.
            features: Mevcut feature'lar.
            all_day_features: Gün sonundaki tüm hisselerin
                feature dict'lerinin listesi.

        Returns:
            Rank feature adı → değer dict'i. rank_ ön eki ile.
        """
        result: dict[str, float] = {}

        for fname, val in features.items():
            if not isinstance(val, (int, float)):
                continue

            values = [
                f.get(fname, float("nan"))
                for f in all_day_features
                if fname in f
            ]
            if len(values) < DEFAULT_MIN_UNIVERSE_SIZE:
                continue

            arr = np.array(values, dtype=float)
            arr = arr[np.isfinite(arr)]  # NaN/Inf filtrele
            if len(arr) < DEFAULT_MIN_UNIVERSE_SIZE:
                continue

            if not np.isfinite(val):
                continue

            # Percentile rank
            rank = float(np.sum(arr <= val)) / len(arr)
            result[f"rank_{fname}"] = rank

        return result

    def compute_market_breadth_features(
        self,
        all_day_features: list[dict[str, float]],
    ) -> dict[str, float]:
        """Piyasa genişliği göstergelerini hesapla.

        Advance/decline oranı, ortalama RSI ve volatilite
        yayılımı gibi piyasa geneli feature'lar üretir.

        Args:
            all_day_features: Gün sonundaki tüm hisselerin
                feature dict'lerinin listesi.

        Returns:
            Breadth feature adı → değer dict'i.
        """
        result: dict[str, float] = {}

        # Advance/Decline oranı
        momentum_values = [
            f.get("momentum", f.get("returns_1d", float("nan")))
            for f in all_day_features
        ]
        if momentum_values:
            arr = np.array(momentum_values, dtype=float)
            arr = arr[np.isfinite(arr)]  # NaN/Inf filtrele
            if len(arr) > 0:
                advancing = int(np.sum(arr > 0))
                declining = int(np.sum(arr < 0))
                total = len(arr)
                result["breadth_advance_ratio"] = (
                    advancing / total if total > 0 else 0.5
                )
                result["breadth_decline_ratio"] = (
                    declining / total if total > 0 else 0.5
                )
                result["breadth_ad_ratio"] = (
                    advancing / declining
                    if declining > 0
                    else float("nan")
                )

        # Ortalama RSI
        rsi_values = [
            f.get("rsi_14", float("nan"))
            for f in all_day_features
            if "rsi_14" in f
        ]
        if rsi_values:
            rsi_arr = np.array(rsi_values, dtype=float)
            rsi_arr = rsi_arr[np.isfinite(rsi_arr)]
            if len(rsi_arr) > 0:
                result["breadth_avg_rsi"] = float(np.mean(rsi_arr))

        # Volatilite yayılımı
        vol_values = [
            f.get("volatility", float("nan"))
            for f in all_day_features
            if "volatility" in f
        ]
        if vol_values:
            vol_arr = np.array(vol_values, dtype=float)
            vol_arr = vol_arr[np.isfinite(vol_arr)]
            if len(vol_arr) > 0:
                result["breadth_vol_spread"] = float(np.std(vol_arr))

        return result



    def __repr__(self) -> str:
        """CrossSectionalEngine kısa temsili.
    
        Returns:
            Sınıf bilgisi.
        """
        return f"CrossSectionalEngine()"
def __repr__(self) -> str:
        """CrossSectionalEngine kısa temsili.

        Returns:
            Sınıf adı.
        """
        return "CrossSectionalEngine()"
# Singleton
cross_sectional_engine = CrossSectionalEngine()
