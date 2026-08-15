"""
ALPHA BIST — Walk-Forward Validation v1.0

Model/strateji değerlendirmesi:
- Rolling window train/test
- Out-of-sample performance
- Stability check

FAZ 12: Walk-Forward Validation
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class WalkForwardFold:
    """Tek bir walk-forward fold sonucu."""
    fold_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_return: float
    test_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    trades: int


@dataclass
class WalkForwardResult:
    """Walk-forward validation sonucu."""
    total_folds: int
    avg_test_return: float
    avg_test_sharpe: float
    avg_test_drawdown: float
    avg_win_rate: float
    stability_score: float    # Fold'lar arası tutarlılık
    worst_fold_return: float
    best_fold_return: float
    folds: List[WalkForwardFold]


class WalkForwardEngine:
    """Walk-forward validation motoru."""

    def run_walk_forward(
        self,
        signals: List[Dict[str, Any]],
        price_data: Dict[str, List[Dict]],
        train_days: int = 252,    # 1 yıl
        test_days: int = 63,      # 3 ay
        step_days: int = 21,      # 1 ay
    ) -> WalkForwardResult:
        """Walk-forward validation çalıştır.

        Args:
            signals: Tüm sinyaller (tarih sıralı)
            train_days: Eğitim penceresi (iş günü)
            test_days: Test penceresi (iş günü)
            step_days: Kaydırma adımı (iş günü)
        """
        folds = []
        fold_id = 0

        # Tarih listesi (unique, sorted)
        dates = sorted(set(s.get("date", "") for s in signals if s.get("date")))
        if len(dates) < train_days + test_days:
            logger.warning("Not enough data for walk-forward", dates=len(dates))
            return WalkForwardResult(
                total_folds=0, avg_test_return=0, avg_test_sharpe=0,
                avg_test_drawdown=0, avg_win_rate=0, stability_score=0,
                worst_fold_return=0, best_fold_return=0, folds=[],
            )

        # Rolling window
        i = 0
        while i + train_days + test_days <= len(dates):
            train_start = dates[i]
            train_end = dates[i + train_days - 1]
            test_start = dates[i + train_days]
            test_end_idx = min(i + train_days + test_days - 1, len(dates) - 1)
            test_end = dates[test_end_idx]

            # Train sinyalleri
            train_signals = [s for s in signals if train_start <= s.get("date", "") <= train_end]
            test_signals = [s for s in signals if test_start <= s.get("date", "") <= test_end]

            # Basit metrikler
            train_wins = sum(1 for s in train_signals if s.get("pnl", 0) > 0)
            test_wins = sum(1 for s in test_signals if s.get("pnl", 0) > 0)

            train_return = sum(s.get("pnl_pct", 0) for s in train_signals)
            test_return = sum(s.get("pnl_pct", 0) for s in test_signals)

            test_returns = [s.get("pnl_pct", 0) for s in test_signals]
            test_sharpe = (np.mean(test_returns) / np.std(test_returns) * np.sqrt(252)) if test_returns and np.std(test_returns) > 0 else 0

            test_win_rate = test_wins / len(test_signals) if test_signals else 0

            fold_id += 1
            folds.append(WalkForwardFold(
                fold_id=fold_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                train_return=round(train_return, 2),
                test_return=round(test_return, 2),
                sharpe=round(float(test_sharpe), 2),
                max_drawdown=0.0,
                win_rate=round(test_win_rate, 4),
                trades=len(test_signals),
            ))

            i += step_days

        # Aggregate
        if folds:
            avg_test_return = np.mean([f.test_return for f in folds])
            avg_test_sharpe = np.mean([f.sharpe for f in folds])
            avg_win_rate = np.mean([f.win_rate for f in folds])

            # Stability: test return'lerin std'si düşükse stabil
            test_returns = [f.test_return for f in folds]
            stability = 1.0 - min(np.std(test_returns) / (abs(np.mean(test_returns)) + 0.01), 1.0)
        else:
            avg_test_return = 0
            avg_test_sharpe = 0
            avg_win_rate = 0
            stability = 0

        return WalkForwardResult(
            total_folds=len(folds),
            avg_test_return=round(float(avg_test_return), 2),
            avg_test_sharpe=round(float(avg_test_sharpe), 2),
            avg_test_drawdown=0.0,
            avg_win_rate=round(float(avg_win_rate), 4),
            stability_score=round(float(stability), 4),
            worst_fold_return=round(min(f.test_return for f in folds), 2) if folds else 0,
            best_fold_return=round(max(f.test_return for f in folds), 2) if folds else 0,
            folds=folds,
        )


# Singleton
walk_forward_engine = WalkForwardEngine()
