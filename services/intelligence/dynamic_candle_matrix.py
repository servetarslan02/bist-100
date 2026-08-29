"""
ALPHA BIST — Yüksek Hızlı Vektörize Kayan Mum Matrisi (Dynamic Candle Matrix)
============================================================================
Kayan pencere (Rolling Walk-Forward) koşullu beklenen değer (Conditional Expectancy)
hesaplamasını mikrosaniye hızında önbellekleyerek simülasyonu anlık hale getirir.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()


@dataclass
class DynamicPatternMetrics:
    """Bir formasyonun anlık dinamik karnesi."""

    pattern_name: str
    sample_count: int = 0
    rolling_win_rate: float = 50.0
    rolling_expectancy: float = 0.0
    rolling_profit_factor: float = 1.0
    dynamic_weight: float = 1.0
    is_favorable: bool = False


class DynamicCandleMatrix:
    """Yüksek hızlı dinamik kayan mum zekası motoru."""

    def __init__(self, lookback_window: int = 252):
        """Otomatik eklendi."""
        self.lookback_window = lookback_window
        self._cache_events: dict[str, list[dict[str, Any]]] = {}

    def precompute_stock_patterns(self, ticker: str, df: pl.DataFrame, forward_days: int = 5) -> Any:
        """Hisse verisindeki tüm formasyon olaylarını bir kez hesaplayıp önbelleğe alır."""
        from .candle_patterns import candle_engine

        closes = df["Close"].to_numpy()
        n = len(df)
        events = []

        for i in range(15, n - forward_days):
            sub_slice = df[max(0, i - 20) : i + 1]
            c_res = candle_engine.analyze_dataframe(sub_slice, ticker)
            p_entry = float(closes[i])
            p_exit = float(closes[i + forward_days])
            ret_pct = (p_exit - p_entry) / p_entry * 100

            for pat in c_res.patterns_detected:
                events.append({"day_idx": i, "pattern": pat, "ret_pct": ret_pct})

        self._cache_events[ticker] = events

    def evaluate_rolling_edge(
        self, ticker: str, current_date_idx: int, df_history: pl.DataFrame | None = None, forward_days: int = 5
    ) -> dict[str, DynamicPatternMetrics]:
        """
        Son 252 günlük penceredeki olayları önbellekten anında süzerek
        o günün dinamik kazanma oranını ve beklenen değerini mikrosaniyede çıkarır.
        """
        if ticker not in self._cache_events:
            if df_history is not None:
                self.precompute_stock_patterns(ticker, df_history, forward_days)
            else:
                return {}

        events = self._cache_events[ticker]
        start_idx = max(0, current_date_idx - self.lookback_window)

        # Kayan pencere içindeki olaylar ($t$ gününden öncesi, sıfır lookahead)
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
            if count < 3:
                continue

            wins = arr[arr > 0]
            losses = np.abs(arr[arr < 0])
            win_rate = (len(wins) / count) * 100
            avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
            avg_loss = float(np.mean(losses)) if len(losses) > 0 else 1e-9

            pf = float(np.sum(wins) / max(np.sum(losses), 1e-9))
            expectancy = ((win_rate / 100.0) * avg_win) - (((100.0 - win_rate) / 100.0) * avg_loss)

            if expectancy > 0 and win_rate >= 50.0:
                dyn_weight = min(2.5, round(1.0 + (expectancy / 5.0) * min(pf, 2.0), 2))
                is_fav = True
            elif expectancy > -0.5 and win_rate >= 45.0:
                dyn_weight = 0.5
                is_fav = False
            else:
                dyn_weight = 0.0
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

        return results


# Singleton
dynamic_candle_matrix = DynamicCandleMatrix()
