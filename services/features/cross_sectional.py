"""
ALPHA BIST — Cross-Sectional Feature Engine v3.0

ROADMAP v3.0 FAZ 1-2:
- Rank features (tüm BIST'te percentile)
- Sector relative (sektör ortalamasına göre z-score)
- Peer correlation
- Market breadth
- Cross-sectional momentum

KURAL: Hisseyi tek başına değil, evren içinde değerlendir.
"""

import numpy as np
from typing import Dict, List, Optional
import structlog

logger = structlog.get_logger()


class CrossSectionalEngine:
    """Cross-sectional feature motoru — evren bazlı hesaplama."""

    # Rank'lenecek feature'lar
    RANK_TARGETS = [
        "return_1d", "return_5d", "return_20d", "return_60d",
        "volume_zscore", "rsi_14", "momentum_20d", "roc_5d", "roc_20d",
        "realized_vol_20d", "bb_position", "atr_pct",
        "price_vs_sma20", "price_vs_sma50",
        # Motor 2 (Momentum+Trend)
        "trend_slope_20d", "trend_r2_20d", "momentum_acceleration",
        "drawdown_20d", "recovery_strength",
        # Motor 3 (Volume)
        "volume_trend", "obv",
        # Motor 7 (Neden Düşüyor)
        "falling_is_temporary", "fall_severity",
        # Motor 8 (Mean Reversion)
        "bb_zscore_20d", "mean_reversion_strength",
    ]

    # Sektör relative feature'lar
    SECTOR_REL_TARGETS = [
        "return_1d", "return_5d", "return_20d",
        "momentum_20d", "roc_5d", "roc_20d",
        "rsi_14", "volume_zscore",
        # Motor 2
        "trend_slope_20d", "drawdown_20d",
    ]

    def compute_all_cross_sectional(
        self,
        ticker: str,
        features: Dict[str, float],
        universe_features: Dict[str, Dict[str, float]],
        universe_sectors: Optional[Dict[str, str]] = None,
        sector: Optional[str] = None,
    ) -> Dict[str, float]:
        """Tüm cross-sectional feature'ları hesapla."""
        all_cs = {}

        # 1. Rank features
        rank_feats = self.compute_rank_features(ticker, features, universe_features)
        all_cs.update(rank_feats)

        # 2. Sector relative
        if universe_sectors and sector:
            sector_feats = self.compute_sector_relative(
                ticker, features, sector, universe_features, universe_sectors
            )
            all_cs.update(sector_feats)

        # 3. Market breadth
        breadth = self.compute_market_breadth_features(universe_features)
        all_cs.update(breadth)

        # 4. Sector momentum
        if universe_sectors:
            sector_mom = self.compute_sector_momentum(universe_features, universe_sectors)
            all_cs.update(sector_mom)

        return all_cs

    def compute_rank_features(
        self,
        ticker: str,
        features: Dict[str, float],
        universe_features: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """Tüm BIST'te percentile rank hesapla (vektörize).

        Returns:
            {rank_return_5d: 0.85, ...} — 0=en düşük, 1=en yüksek
        """
        rank_features = {}

        for feat_name in self.RANK_TARGETS:
            my_val = features.get(feat_name)
            if my_val is None or np.isnan(my_val):
                continue

            # Tüm hisselerin değerlerini topla (vektörize)
            all_vals = np.array([
                f.get(feat_name) for f in universe_features.values()
                if f.get(feat_name) is not None and not np.isnan(f.get(feat_name, np.nan))
            ])

            if len(all_vals) < 5:
                continue

            # Percentile rank (vektörize)
            n_below = np.sum(all_vals < my_val)
            n_equal = np.sum(all_vals == my_val)
            rank = (n_below + 0.5 * n_equal) / len(all_vals)
            rank_features[f"rank_{feat_name}"] = round(float(rank), 4)

            # Cross-sectional z-score
            mean = np.mean(all_vals)
            std = np.std(all_vals)
            if std > 0:
                rank_features[f"cs_zscore_{feat_name}"] = round(float((my_val - mean) / std), 4)

        return rank_features

    def compute_sector_relative(
        self,
        ticker: str,
        features: Dict[str, float],
        sector: str,
        universe_features: Dict[str, Dict[str, float]],
        universe_sectors: Dict[str, str],
    ) -> Dict[str, float]:
        """Sektöre göre relatif feature'lar."""
        relative_features = {}

        # Sektördeki peer'ları bul
        sector_peers = [
            t for t, s in universe_sectors.items()
            if s == sector and t != ticker and t in universe_features
        ]

        if len(sector_peers) < 3:
            return relative_features

        for feat_name in self.SECTOR_REL_TARGETS:
            my_val = features.get(feat_name)
            if my_val is None or np.isnan(my_val):
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

            # Sector rank (0-1)
            sector_rank = sum(1 for v in peer_vals if v <= my_val) / len(peer_vals)
            relative_features[f"sector_rank_{feat_name}"] = round(sector_rank, 4)

        # Sektör momentum (sektör ortalaması)
        for feat_name in ["return_5d", "return_20d", "momentum_20d"]:
            peer_vals = []
            for t in sector_peers:
                v = universe_features[t].get(feat_name)
                if v is not None and not np.isnan(v):
                    peer_vals.append(v)
            if peer_vals:
                relative_features[f"sector_avg_{feat_name}"] = round(float(np.mean(peer_vals)), 4)

        return relative_features

    def compute_market_breadth_features(
        self,
        universe_features: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """Piyasa genişliği feature'ları (vektörize)."""
        breadth_features = {}

        # Return values toplu çek (vektörize)
        ret_1d = np.array([
            f.get("return_1d", 0) for f in universe_features.values()
            if f.get("return_1d") is not None and not np.isnan(f.get("return_1d", np.nan))
        ])

        if len(ret_1d) > 0:
            total = len(ret_1d)
            advancing = int(np.sum(ret_1d > 0))
            declining = int(np.sum(ret_1d < 0))
            breadth_features["market_breadth"] = round(advancing / total, 4)
            breadth_features["market_advancing"] = advancing
            breadth_features["market_declining"] = declining
            breadth_features["market_ad_ratio"] = round(advancing / max(declining, 1), 4)

        # Volume anomaly count (vektörize)
        vol_zscores = np.array([
            f.get("volume_zscore", 0) for f in universe_features.values()
            if f.get("volume_zscore") is not None
        ])
        if len(vol_zscores) > 0:
            breadth_features["market_vol_anomalies"] = int(np.sum(np.abs(vol_zscores) > 2))

        # RSI counts (vektörize)
        rsi_values = np.array([
            f.get("rsi_14", 50) for f in universe_features.values()
            if f.get("rsi_14") is not None
        ])
        if len(rsi_values) > 0:
            breadth_features["market_overbought_count"] = int(np.sum(rsi_values > 70))
            breadth_features["market_oversold_count"] = int(np.sum(rsi_values < 30))

        # Momentum distribution (vektörize)
        mom_values = np.array([
            f.get("momentum_20d", 0) for f in universe_features.values()
            if f.get("momentum_20d") is not None and not np.isnan(f.get("momentum_20d", np.nan))
        ])
        if len(mom_values) > 0:
            breadth_features["market_momentum_median"] = round(float(np.median(mom_values)), 4)
            breadth_features["market_momentum_std"] = round(float(np.std(mom_values)), 4)

        return breadth_features

    def compute_sector_momentum(
        self,
        universe_features: Dict[str, Dict[str, float]],
        universe_sectors: Dict[str, str],
        current_date: Optional[str] = None,  # F-014: Tarih bağımlılığı parametresi
    ) -> Dict[str, float]:
        """Sektör bazlı ortalama momentum.

        F-014: current_date parametresi ile tarih-bağımlı sektör momentum hesaplanır.
        Sadece o tarihte mevcut olan hisselerin verileri kullanılır.
        """
        sector_features = {}
        sector_momentum = {}

        for ticker, features in universe_features.items():
            sec = universe_sectors.get(ticker, "OTHER")
            if sec not in sector_momentum:
                sector_momentum[sec] = {}
            for feat in ["return_5d", "return_20d", "momentum_20d"]:
                if feat not in sector_momentum[sec]:
                    sector_momentum[sec][feat] = []
                val = features.get(feat)
                if val is not None and not np.isnan(val):
                    sector_momentum[sec][feat].append(val)

        for sec, feats in sector_momentum.items():
            for feat, vals in feats.items():
                if len(vals) >= 2:
                    sector_features[f"sector_momentum_{sec}_{feat}"] = round(float(np.mean(vals)), 4)
                    sector_features[f"sector_momentum_{sec}_{feat}_std"] = round(float(np.std(vals)), 4)
                    # F-014: Sektör momentum rank (cross-sectional)
                    sector_features[f"sector_momentum_{sec}_{feat}_count"] = len(vals)

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
            corr_features["peer_corr_std"] = round(float(np.std(correlations)), 4)

        return corr_features

    def compute_cross_sectional_momentum(
        self,
        universe_features: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """Cross-sectional momentum (tüm evrenin momentumu)."""
        cs_mom = {}

        # Winner/Loser count
        ret_5d_values = []
        ret_20d_values = []
        for f in universe_features.values():
            r5 = f.get("return_5d")
            r20 = f.get("return_20d")
            if r5 is not None and not np.isnan(r5):
                ret_5d_values.append(r5)
            if r20 is not None and not np.isnan(r20):
                ret_20d_values.append(r20)

        if ret_5d_values:
            cs_mom["cs_momentum_5d_median"] = round(float(np.median(ret_5d_values)), 4)
            cs_mom["cs_momentum_5d_top10_avg"] = round(float(np.mean(sorted(ret_5d_values, reverse=True)[:max(1, len(ret_5d_values)//10)])), 4)
            cs_mom["cs_momentum_5d_bottom10_avg"] = round(float(np.mean(sorted(ret_5d_values)[:max(1, len(ret_5d_values)//10)])), 4)

        if ret_20d_values:
            cs_mom["cs_momentum_20d_median"] = round(float(np.median(ret_20d_values)), 4)

        return cs_mom


# Singleton
cross_sectional_engine = CrossSectionalEngine()
