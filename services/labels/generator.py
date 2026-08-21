"""
ALPHA BIST — Label Generation Pipeline v1.0

Gelecek getiri → target label üretir.

Label'lar (target'lar):
- y_5d: Gelecek 5 gün getiri (%)
- y_20d: Gelecek 20 gün getiri (%)
- y_5d_rank: 5 gün getiri cross-sectional rank (0-1)
- y_20d_rank: 20 gün getiri cross-sectional rank (0-1)
- y_5d_binary: 5 gün pozitif mi? (0/1)
- y_20d_binary: 20 gün pozitif mi? (0/1)
- y_5d_vs_sector: Sektöre göre fazla getiri
- y_20d_vs_sector: Sektöre göre fazla getiri
- y_outperform: BIST'i geçti mi? (0/1)

Kritik: Label'lar sadece GELECEK veri kullanılarak üretilir.
Look-ahead bias = ölüm.

Kaynak: Du (2026) — target variable design, cross-sectional ranking
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class LabelResult:
    """Label sonucu."""
    ticker: str
    labels: Dict[str, np.ndarray]  # label_name → values
    valid_mask: np.ndarray          # Label hesaplanabilir mi?
    stats: Dict[str, float]         # İstatistikler


class LabelGenerator:
    """Label generation pipeline."""

    # Forward return periods
    FORWARD_PERIODS = [1, 5, 10, 20]

    def generate_labels(
        self,
        ticker: str,
        close: np.ndarray,
        mask: np.ndarray,
        sector_returns: Optional[np.ndarray] = None,
        benchmark_returns: Optional[np.ndarray] = None,
        purge_days: int = 0,
    ) -> LabelResult:
        """Tek hisse için tüm label'ları üret.

        Args:
            ticker: Hisse kodu
            close: Kapanış fiyatları (mask-aware)
            mask: Tradability mask (1=valid, 0=invalid)
            sector_returns: Sektör getiri serisi (cross-sectional için)
            benchmark_returns: BIST100 getiri serisi (relative için)
        """
        n = len(close)
        labels = {}
        valid_mask = np.ones(n, dtype=bool)

        # Log returns
        log_returns = np.full(n, np.nan)
        for i in range(1, n):
            if mask[i] == 1 and mask[i - 1] == 1 and close[i] > 0 and close[i - 1] > 0:
                log_returns[i] = np.log(close[i] / close[i - 1])

        # Forward return'ler (gelecek getiri)
        for period in self.FORWARD_PERIODS:
            forward_ret = np.full(n, np.nan)
            for i in range(n - period):
                if mask[i] == 1 and mask[i + period] == 1 and close[i] > 0 and close[i + period] > 0:
                    forward_ret[i] = (close[i + period] / close[i] - 1) * 100

            labels[f"y_{period}d"] = forward_ret

            # Binary: pozitif mi?
            labels[f"y_{period}d_binary"] = np.where(forward_ret > 0, 1, 0).astype(float)
            labels[f"y_{period}d_binary"] = np.where(np.isnan(forward_ret), np.nan, labels[f"y_{period}d_binary"])

            # Sektöre göre fazla getiri
            if sector_returns is not None and len(sector_returns) == n:
                sector_fwd = np.full(n, np.nan)
                for i in range(n - period):
                    if mask[i] == 1 and not np.isnan(sector_returns[i]) and not np.isnan(forward_ret[i]):
                        sector_fwd[i] = forward_ret[i] - sector_returns[i] * period
                labels[f"y_{period}d_vs_sector"] = sector_fwd

            # BIST'e göre fazla getiri
            if benchmark_returns is not None and len(benchmark_returns) == n:
                bench_fwd = np.full(n, np.nan)
                for i in range(n - period):
                    if mask[i] == 1 and not np.isnan(benchmark_returns[i]) and not np.isnan(forward_ret[i]):
                        bench_fwd[i] = forward_ret[i] - benchmark_returns[i] * period
                labels[f"y_{period}d_vs_benchmark"] = bench_fwd
                labels[f"y_{period}d_outperform"] = np.where(bench_fwd > 0, 1, 0).astype(float)
                labels[f"y_{period}d_outperform"] = np.where(np.isnan(bench_fwd), np.nan, labels[f"y_{period}d_outperform"])

        # Max drawdown (forward 20 gün)
        max_dd = np.full(n, np.nan)
        for i in range(n - 20):
            if mask[i] == 1:
                future_prices = close[i:i + 21]
                valid_prices = future_prices[~np.isnan(future_prices)]
                if len(valid_prices) > 1:
                    peak = np.maximum.accumulate(valid_prices)
                    dd = (peak - valid_prices) / peak
                    max_dd[i] = float(np.max(dd)) * 100
        labels["y_max_dd_20d"] = max_dd

        # Volatilite (forward 20 gün)
        fwd_vol = np.full(n, np.nan)
        for i in range(n - 20):
            period_returns = log_returns[i + 1:i + 21]
            valid_returns = period_returns[~np.isnan(period_returns)]
            if len(valid_returns) >= 10:
                fwd_vol[i] = float(np.std(valid_returns) * np.sqrt(252) * 100)
        labels["y_volatility_20d"] = fwd_vol

        # Purge gap: Feature hesaplama penceresinin son purge_days barını label'dan hariç tut
        # Bu, label ile feature arasında sızıntıyı (look-ahead bias) önler.
        # F-006 düzeltmesi: purge_days > 0 ise, her label'ın son purge_days barını NaN yap.
        # Ayrıca feature penceresi ile label arasında purge gap uygula.
        if purge_days > 0:
            for label_name, label_values in labels.items():
                # Son purge_days barını NaN yap (gelecek bilgi sızıntısını önle)
                label_values[-purge_days:] = np.nan
                labels[label_name] = label_values
            # Feature penceresinin son purge_days barını da valid_mask'dan hariç tut
            valid_mask[-purge_days:] = False

        # Valid mask (en az bir label hesaplanabilir mi?)
        for label_name, label_values in labels.items():
            valid_mask = valid_mask & ~np.isnan(label_values)

        # İstatistikler
        stats = {}
        for label_name, label_values in labels.items():
            valid_values = label_values[~np.isnan(label_values)]
            if len(valid_values) > 0:
                stats[label_name] = {
                    "mean": round(float(np.mean(valid_values)), 4),
                    "std": round(float(np.std(valid_values)), 4),
                    "min": round(float(np.min(valid_values)), 4),
                    "max": round(float(np.max(valid_values)), 4),
                    "count": len(valid_values),
                }

        return LabelResult(
            ticker=ticker,
            labels=labels,
            valid_mask=valid_mask,
            stats=stats,
        )

    def generate_cross_sectional_ranks(
        self,
        all_labels: Dict[str, np.ndarray],
        label_name: str = "y_5d",
    ) -> Dict[str, np.ndarray]:
        """Tüm hisseler için cross-sectional rank üret.

        Args:
            all_labels: {ticker: label_values} — her hissenin label dizisi
            label_name: Rank'lenecek label

        Returns:
            {ticker: rank_values} — her hissenin rank dizisi (0-1)
        """
        if label_name not in next(iter(all_labels.values()), {}):
            return {}

        # Tüm hisselerin label'larını birleştir
        tickers = list(all_labels.keys())
        n_tickers = len(tickers)
        if n_tickers == 0:
            return {}

        # Ortak uzunluk bul
        min_len = min(len(all_labels[t]) for t in tickers)

        ranks = {}
        for i in range(min_len):
            # Bu gün için tüm hisselerin değerlerini topla
            values = []
            valid_tickers = []
            for t in tickers:
                label_vals = all_labels[t].get(label_name)
                if label_vals is not None and i < len(label_vals) and not np.isnan(label_vals[i]):
                    values.append(label_vals[i])
                    valid_tickers.append(t)

            if len(values) < 2:
                continue

            # Rank hesapla (0-1 arası)
            sorted_indices = np.argsort(values)
            n_valid = len(values)
            for rank_idx, orig_idx in enumerate(sorted_indices):
                ticker = valid_tickers[orig_idx]
                if ticker not in ranks:
                    ranks[ticker] = np.full(min_len, np.nan)
                ranks[ticker][i] = rank_idx / (n_valid - 1) if n_valid > 1 else 0.5

        return ranks

    def get_label_names(self) -> List[str]:
        """Tüm label isimlerini döndür."""
        names = []
        for period in self.FORWARD_PERIODS:
            names.extend([
                f"y_{period}d",
                f"y_{period}d_binary",
                f"y_{period}d_vs_sector",
                f"y_{period}d_vs_benchmark",
                f"y_{period}d_outperform",
            ])
        names.extend(["y_max_dd_20d", "y_volatility_20d"])
        return names


# Singleton
label_generator = LabelGenerator()
