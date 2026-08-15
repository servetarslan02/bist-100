"""
ALPHA BIST — Cross-Sectional Feature Engine v1.0

Her hisseyi tek başına değil, tüm BIST evreni içinde değerlendirir.

Cross-sectional features:
- Rank (tüm BIST'te percentile)
- Sector relative (sektör ortalamasına göre)
- Peer relative (aynı sektördeki hisselere göre)
- Market breadth contribution

Kaynak: Oxford (2023) — spatio-temporal momentum, cross-sectional features
"""

import numpy as np
from typing import Dict, List, Optional
import structlog

logger = structlog.get_logger()


class CrossSectionalEngine:
    """Cross-sectional feature motoru."""

    def compute_rank_features(
        self,
        ticker: str,
        features: Dict[str, float],
        universe_features: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """Tüm BIST'te rank feature'ları hesapla.

        Args:
            ticker: Hisse kodu
            features: Bu hissenin feature'ları
            universe_features: Tüm hisselerin feature'ları {ticker: {feature: value}}
        """
        rank_features = {}

        # Rank'lenecek feature'lar
        rank_targets = [
            "return_1d", "return_5d", "return_20d",
            "volume_zscore", "rsi_14", "momentum_20d",
            "realized_vol_20d", "bb_position",
        ]

        for feat_name in rank_targets:
            my_val = features.get(feat_name)
            if my_val is None:
                continue

            # Tüm hisselerin bu feature'daki değerlerini topla
            all_vals = []
            for t, f in universe_features.items():
                v = f.get(feat_name)
                if v is not None and not np.isnan(v):
                    all_vals.append(v)

            if len(all_vals) < 5:
                continue

            # Percentile rank (0-1)
            rank = sum(1 for v in all_vals if v <= my_val) / len(all_vals)
            rank_features[f"rank_{feat_name}"] = round(rank, 4)

        return rank_features

    def compute_sector_relative(
        self,
        ticker: str,
        features: Dict[str, float],
        sector: str,
        universe_features: Dict[str, Dict[str, float]],
        universe_sectors: Dict[str, str],
    ) -> Dict[str, float]:
        """Sektöre göre relatif feature'lar.

        Args:
            ticker: Hisse kodu
            features: Bu hissenin feature'ları
            sector: Sektör kodu
            universe_features: Tüm hisselerin feature'ları
            universe_sectors: Tüm hisselerin sektörleri
        """
        relative_features = {}

        # Sektördeki diğer hisseleri bul
        sector_peers = [
            t for t, s in universe_sectors.items()
            if s == sector and t != ticker and t in universe_features
        ]

        if len(sector_peers) < 3:
            return relative_features

        # Sektör ortalaması hesapla
        rel_targets = ["return_1d", "return_5d", "return_20d", "momentum_20d", "rsi_14"]

        for feat_name in rel_targets:
            my_val = features.get(feat_name)
            if my_val is None:
                continue

            peer_vals = []
            for t in sector_peers:
                v = universe_features[t].get(feat_name)
                if v is not None and not np.isnan(v):
                    peer_vals.append(v)

            if len(peer_vals) < 3:
                continue

            sector_mean = np.mean(peer_vals)
            sector_std = np.std(peer_vals)

            # Relative: hisse - sektör ortalaması
            relative_features[f"sector_rel_{feat_name}"] = round(float(my_val - sector_mean), 4)

            # Z-score within sector
            if sector_std > 0:
                relative_features[f"sector_zscore_{feat_name}"] = round(float((my_val - sector_mean) / sector_std), 4)

            # Sector rank
            sector_rank = sum(1 for v in peer_vals if v <= my_val) / len(peer_vals)
            relative_features[f"sector_rank_{feat_name}"] = round(sector_rank, 4)

        return relative_features

    def compute_market_breadth_features(
        self,
        universe_features: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """Piyasa genişliği feature'ları (tüm BIST için)."""
        breadth_features = {}

        # Advancing / Declining
        advancing = 0
        declining = 0
        total = 0

        for ticker, features in universe_features.items():
            ret = features.get("return_1d", 0)
            if ret is not None:
                total += 1
                if ret > 0:
                    advancing += 1
                elif ret < 0:
                    declining += 1

        if total > 0:
            breadth_features["market_breadth"] = round(advancing / total, 4)
            breadth_features["market_advancing"] = advancing
            breadth_features["market_declining"] = declining

        # Volume anomaly count
        vol_anomaly_count = sum(
            1 for f in universe_features.values()
            if f.get("volume_zscore", 0) and abs(f.get("volume_zscore", 0)) > 2
        )
        breadth_features["market_vol_anomalies"] = vol_anomaly_count

        # High RSI count (overbought)
        high_rsi_count = sum(
            1 for f in universe_features.values()
            if f.get("rsi_14", 50) and f.get("rsi_14", 50) > 70
        )
        breadth_features["market_overbought_count"] = high_rsi_count

        # Low RSI count (oversold)
        low_rsi_count = sum(
            1 for f in universe_features.values()
            if f.get("rsi_14", 50) and f.get("rsi_14", 50) < 30
        )
        breadth_features["market_oversold_count"] = low_rsi_count

        return breadth_features

    def compute_sector_momentum(
        self,
        universe_features: Dict[str, Dict[str, float]],
        universe_sectors: Dict[str, str],
    ) -> Dict[str, float]:
        """Sektör bazlı ortalama momentum."""
        sector_features = {}
        sector_momentum = {}
        for ticker, features in universe_features.items():
            sector = universe_sectors.get(ticker, "OTHER")
            mom = features.get("momentum_20d", 0)
            if sector not in sector_momentum:
                sector_momentum[sector] = []
            sector_momentum[sector].append(mom)

        for sector, moms in sector_momentum.items():
            if len(moms) >= 2:
                sector_features[f"sector_momentum_{sector}"] = round(float(np.mean(moms)), 4)

        return sector_features

    def compute_peer_correlation(
        self,
        ticker: str,
        returns: np.ndarray,
        peer_returns: Dict[str, np.ndarray],
        window: int = 60,
    ) -> Dict[str, float]:
        """Peer korelasyon feature'ları."""
        corr_features = {}

        if len(returns) < window:
            return corr_features

        my_returns = returns[-window:]

        # Peer'larla ortalama korelasyon
        correlations = []
        for peer_ticker, peer_ret in peer_returns.items():
            if len(peer_ret) >= window:
                peer_window = peer_ret[-window:]
                if np.std(my_returns) > 0 and np.std(peer_window) > 0:
                    corr = np.corrcoef(my_returns, peer_window)[0, 1]
                    if not np.isnan(corr):
                        correlations.append(corr)

        if correlations:
            corr_features["peer_corr_mean"] = round(float(np.mean(correlations)), 4)
            corr_features["peer_corr_max"] = round(float(np.max(correlations)), 4)
            corr_features["peer_corr_min"] = round(float(np.min(correlations)), 4)

        return corr_features


# Singleton
cross_sectional_engine = CrossSectionalEngine()
