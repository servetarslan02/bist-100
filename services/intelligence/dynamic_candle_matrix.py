"""
ALPHA BIST — Yüksek Hızlı Vektörize Kayan Mum Matrisi (Dynamic Candle Matrix)
============================================================================
Kayan pencere (Rolling Walk-Forward) koşullu beklenen değer (Conditional Expectancy)
hesaplamasını mikrosaniye hızında önbellekleyerek simülasyonu anlık hale getirir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_LOOKBACK_WINDOW: int = 252          # İş günü (1 yıl)
DEFAULT_FORWARD_DAYS: int = 5               # İleriye bakış periyodu
MIN_SLICE_LENGTH: int = 15                  # Formasyon tespiti için minimum mum
FORMATION_LOOKBACK: int = 20                # Her adımda formasyon penceresi
MIN_SAMPLE_COUNT: int = 3                   # Edge hesaplama minimum örnek
DEFAULT_WIN_RATE: float = 50.0              # Varsayılan kazanma oranı
FAVORABLE_WIN_RATE: float = 50.0            # Favori eşik kazanma oranı
MARGINAL_WIN_RATE: float = 45.0             # Marjinal eşik kazanma比率
MARGINAL_EXPECTANCY: float = -0.5           # Marjinal expectancy eşiği
FAVORABLE_EXPECTANCY: float = 0.0           # Favori expectancy eşiği
DYN_WEIGHT_BASE: float = 1.0               # Dinamik ağırlık tabanı
DYN_WEIGHT_MAX: float = 2.5                # Dinamik ağırlık üst sınır
DYN_WEIGHT_FACTOR: float = 5.0             # Expectancy normalizasyon
DYN_WEIGHT_PF_CAP: float = 2.0             # Profit factor üst sınırı
DYN_WEIGHT_MARGINAL: float = 0.5           # Marjinal durum ağırlığı
DYN_WEIGHT_UNFAVORABLE: float = 0.0        # Olumsuz durum ağırlığı
EPSILON: float = 1e-9                       # Sıfıra bölmeyi önleme

__all__ = [
    "DynamicPatternMetrics",
    "DynamicCandleMatrix",
    "dynamic_candle_matrix",
]


@dataclass
class DynamicPatternMetrics:
    """Bir formasyonun anlık dinamik karnesi.

    Kayan penceredeki kazanma oranı, expectancy ve dinamik ağırlık bilgisi.
    """

    pattern_name: str
    sample_count: int = 0
    rolling_win_rate: float = DEFAULT_WIN_RATE
    rolling_expectancy: float = 0.0
    rolling_profit_factor: float = 1.0
    dynamic_weight: float = DYN_WEIGHT_BASE
    is_favorable: bool = False

    def __repr__(self) -> str:
        return (
            f"<DynamicPatternMetrics pattern={self.pattern_name!r} "
            f"wr={self.rolling_win_rate:.1f}% exp={self.rolling_expectancy:.2f} "
            f"pf={self.rolling_profit_factor:.2f} w={self.dynamic_weight:.2f}>"
        )


class DynamicCandleMatrix:
    """Yüksek hızlı dinamik kayan mum zekası motoru.

    Formasyon bazlı rolling edge hesaplaması yapar ve sonuçları önbellekler.
    """

    def __repr__(self) -> str:
        tickers = list(self._cache_events.keys())
        return f"<DynamicCandleMatrix lookback={self.lookback_window} cached_tickers={tickers}>"

    def __init__(self, lookback_window: int = DEFAULT_LOOKBACK_WINDOW) -> None:
        """Motoru başlat.

        Args:
            lookback_window: Kayan pencere uzunluğu (iş günü).
        """
        self.lookback_window = lookback_window
        self._cache_events: dict[str, list[dict[str, Any]]] = {}

    def precompute_stock_patterns(
        self, ticker: str, df: pl.DataFrame, forward_days: int = DEFAULT_FORWARD_DAYS
    ) -> None:
        """Hisse verisindeki tüm formasyon olaylarını bir kez hesaplayıp önbelleğe al.

        Args:
            ticker: Varlık kodu.
            df: OHLCV Polars DataFrame'i.
            forward_days: İleriye bakış periyodu.

        Raises:
            ValueError: Gerekli kolonlar eksikse.
        """
        required_cols = {"Close"}
        if not required_cols.issubset(set(df.columns)):
            raise ValueError(f"Eksik kolonlar: {required_cols - set(df.columns)}")

        from .candle_patterns import candle_engine

        closes = df["Close"].to_numpy()
        n = len(df)
        events: list[dict[str, Any]] = []

        for i in range(MIN_SLICE_LENGTH, n - forward_days):
            sub_slice = df[max(0, i - FORMATION_LOOKBACK) : i + 1]
            c_res = candle_engine.analyze_dataframe(sub_slice, ticker)
            p_entry = float(closes[i])
            p_exit = float(closes[i + forward_days])
            ret_pct = (p_exit - p_entry) / p_entry * 100

            for pat in c_res.patterns_detected:
                events.append({"day_idx": i, "pattern": pat, "ret_pct": ret_pct})

        self._cache_events[ticker] = events
        logger.info("pattern_ondbellek_hazir", ticker=ticker, event_count=len(events))

    def evaluate_rolling_edge(
        self,
        ticker: str,
        current_date_idx: int,
        df_history: pl.DataFrame | None = None,
        forward_days: int = DEFAULT_FORWARD_DAYS,
    ) -> dict[str, DynamicPatternMetrics]:
        """Kayan penceredeki dinamik edge'i hesapla.

        Son lookback_window günündeki olayları süzerek formasyon bazlı
        kazanma oranı ve beklenen değer üretir.

        Args:
            ticker: Varlık kodu.
            current_date_idx: Mevcut gün indeksi.
            df_history: Geçmiş veri (önbellek yoksa hesaplanır).
            forward_days: İleriye bakış periyodu.

        Returns:
            Formasyon adı → DynamicPatternMetrics sözlüğü.
        """
        if ticker not in self._cache_events:
            if df_history is not None:
                self.precompute_stock_patterns(ticker, df_history, forward_days)
            else:
                logger.warning("ondbellek_bos", ticker=ticker)
                return {}

        events = self._cache_events[ticker]
        start_idx = max(0, current_date_idx - self.lookback_window)

        # Kayan pencere içindeki olaylar
        window_events: dict[str, list[float]] = {}
        for ev in events:
            if start_idx <= ev["day_idx"] < current_date_idx:
                pat = ev["pattern"]
                if pat not in window_events:
                    window_events[pat] = []
                window_events[pat].append(ev["ret_pct"])

        results: dict[str, DynamicPatternMetrics] = {}
        for pat, returns in window_events.items():
            arr = np.array(returns)
            count = len(arr)
            if count < MIN_SAMPLE_COUNT:
                continue

            wins = arr[arr > FAVORABLE_EXPECTANCY]
            losses = np.abs(arr[arr < FAVORABLE_EXPECTANCY])
            win_rate = (len(wins) / count) * 100
            avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
            avg_loss = float(np.mean(losses)) if len(losses) > 0 else EPSILON

            pf = float(np.sum(wins) / max(np.sum(losses), EPSILON))
            expectancy = ((win_rate / 100.0) * avg_win) - (((100.0 - win_rate) / 100.0) * avg_loss)

            if expectancy > FAVORABLE_EXPECTANCY and win_rate >= FAVORABLE_WIN_RATE:
                dyn_weight = min(
                    DYN_WEIGHT_MAX,
                    round(DYN_WEIGHT_BASE + (expectancy / DYN_WEIGHT_FACTOR) * min(pf, DYN_WEIGHT_PF_CAP), 2),
                )
                is_fav = True
            elif expectancy > MARGINAL_EXPECTANCY and win_rate >= MARGINAL_WIN_RATE:
                dyn_weight = DYN_WEIGHT_MARGINAL
                is_fav = False
            else:
                dyn_weight = DYN_WEIGHT_UNFAVORABLE
                is_fav = False

            results[pat] = DynamicPatternMetrics(
                pattern_name=pat,
                sample_count=count,
                rolling_win_rate=round(win_rate, 1),
                rolling_expectancy=round(expectancy, 2),
                rolling_profit_factor=round(pf, 2),
                dynamic_weight=dyn_weight,
                is_favorable=is_fav,
            )

        logger.info(
            "rolling_edge_hesaplandi",
            ticker=ticker,
            patterns=len(results),
            favorable=sum(1 for v in results.values() if v.is_favorable),
        )
        return results


# Singleton
dynamic_candle_matrix = DynamicCandleMatrix()
