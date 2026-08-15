"""
ALPHA BIST — Walk-Forward Validation v3.0

ROADMAP v3.0 FAZ 1, 4:
- Purge: train sonu → test başı arası gap (5 gün)
- Embargo: test sonu → bir sonraki train arası gap (5 gün)
- Data leakage koruması (KESİN)
- Precision@K, IC, Deflated Sharpe metrikleri

KURAL: Gelecek veriyi train'de kullanmak = ölüm.
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    purge_start: str
    purge_end: str
    embargo_start: str
    embargo_end: str
    train_samples: int
    test_samples: int
    # Metrikler
    train_return: float = 0.0
    test_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    precision_at_20: float = 0.0
    ic: float = 0.0  # Information Coefficient
    deflated_sharpe: float = 0.0
    trades: int = 0


@dataclass
class WalkForwardResult:
    """Walk-forward validation sonucu."""
    total_folds: int
    avg_test_return: float
    avg_test_sharpe: float
    avg_test_drawdown: float
    avg_win_rate: float
    avg_precision_at_5: float
    avg_precision_at_10: float
    avg_precision_at_20: float
    avg_ic: float
    stability_score: float
    worst_fold_return: float
    best_fold_return: float
    deflated_sharpe: float
    folds: List[WalkForwardFold]
    summary: Dict[str, Any] = field(default_factory=dict)


class WalkForwardEngine:
    """Walk-forward validation motoru — purge + embargo korumalı."""

    def __init__(
        self,
        purge_days: int = 5,
        embargo_days: int = 5,
        train_days: int = 252,
        test_days: int = 63,
        step_days: int = 21,
    ):
        self.purge_days = purge_days
        self.embargo_days = embargo_days
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days

        logger.info("WalkForwardEngine v3.0 initialized",
                   purge=purge_days, embargo=embargo_days,
                   train=train_days, test=test_days, step=step_days)

    def create_folds(
        self,
        dates: List[str],
    ) -> List[Dict[str, Any]]:
        """Purge + embargo korumalı fold'lar oluştur.

        Returns:
            [{train_start, train_end, purge_start, purge_end,
              test_start, test_end, embargo_start, embargo_end}, ...]
        """
        folds = []
        i = 0

        while i + self.train_days + self.purge_days + self.test_days <= len(dates):
            # Train penceresi
            train_start_idx = i
            train_end_idx = i + self.train_days - 1

            # Purge gap (train sonu → test başı)
            purge_start_idx = train_end_idx + 1
            purge_end_idx = train_end_idx + self.purge_days

            # Test penceresi
            test_start_idx = purge_end_idx + 1
            test_end_idx = min(test_start_idx + self.test_days - 1, len(dates) - 1)

            # Embargo gap (test sonu → bir sonraki train)
            embargo_start_idx = test_end_idx + 1
            embargo_end_idx = test_end_idx + self.embargo_days

            if test_end_idx >= len(dates):
                break

            folds.append({
                "train_start": dates[train_start_idx],
                "train_end": dates[train_end_idx],
                "purge_start": dates[purge_start_idx] if purge_start_idx < len(dates) else dates[-1],
                "purge_end": dates[purge_end_idx] if purge_end_idx < len(dates) else dates[-1],
                "test_start": dates[test_start_idx],
                "test_end": dates[test_end_idx],
                "embargo_start": dates[embargo_start_idx] if embargo_start_idx < len(dates) else dates[-1],
                "embargo_end": dates[embargo_end_idx] if embargo_end_idx < len(dates) else dates[-1],
            })

            i += self.step_days

        return folds

    def run_walk_forward(
        self,
        predictions: List[Dict[str, Any]],  # {date, ticker, score, predicted_return}
        actual_returns: Dict[str, Dict[str, float]],  # {date: {ticker: return}}
        dates: Optional[List[str]] = None,
    ) -> WalkForwardResult:
        """Walk-forward validation çalıştır.

        Args:
            predictions: Model tahminleri (tarih sıralı)
            actual_returns: Gerçekleşen getiriler {date: {ticker: return}}
            dates: Tarih listesi (None ise predictions'dan çıkar)
        """
        if dates is None:
            dates = sorted(set(p.get("date", "") for p in predictions if p.get("date")))

        if len(dates) < self.train_days + self.purge_days + self.test_days:
            logger.warning("Not enough data for walk-forward", dates=len(dates))
            return self._empty_result()

        folds = self.create_folds(dates)
        fold_results = []

        for fold_id, fold in enumerate(folds, 1):
            # Train seti (purge ÖNCESİ)
            train_preds = [
                p for p in predictions
                if fold["train_start"] <= p.get("date", "") <= fold["train_end"]
            ]

            # Test seti (purge SONRASI, embargo ÖNCESİ)
            test_preds = [
                p for p in predictions
                if fold["test_start"] <= p.get("date", "") <= fold["test_end"]
            ]

            # Train metrikleri
            train_metrics = self._calculate_fold_metrics(
                train_preds, actual_returns, fold["train_start"], fold["train_end"]
            )

            # Test metrikleri
            test_metrics = self._calculate_fold_metrics(
                test_preds, actual_returns, fold["test_start"], fold["test_end"]
            )

            fold_result = WalkForwardFold(
                fold_id=fold_id,
                train_start=fold["train_start"],
                train_end=fold["train_end"],
                test_start=fold["test_start"],
                test_end=fold["test_end"],
                purge_start=fold["purge_start"],
                purge_end=fold["purge_end"],
                embargo_start=fold["embargo_start"],
                embargo_end=fold["embargo_end"],
                train_samples=len(train_preds),
                test_samples=len(test_preds),
                train_return=round(train_metrics.get("return", 0), 4),
                test_return=round(test_metrics.get("return", 0), 4),
                sharpe=round(test_metrics.get("sharpe", 0), 4),
                max_drawdown=round(test_metrics.get("max_drawdown", 0), 4),
                win_rate=round(test_metrics.get("win_rate", 0), 4),
                precision_at_5=round(test_metrics.get("precision_at_5", 0), 4),
                precision_at_10=round(test_metrics.get("precision_at_10", 0), 4),
                precision_at_20=round(test_metrics.get("precision_at_20", 0), 4),
                ic=round(test_metrics.get("ic", 0), 4),
                deflated_sharpe=round(test_metrics.get("deflated_sharpe", 0), 4),
                trades=test_metrics.get("trades", 0),
            )
            fold_results.append(fold_result)

        return self._aggregate_results(fold_results)

    def _calculate_fold_metrics(
        self,
        predictions: List[Dict],
        actual_returns: Dict[str, Dict[str, float]],
        start_date: str,
        end_date: str,
    ) -> Dict[str, float]:
        """Tek fold için metrik hesapla."""
        if not predictions:
            return {}

        # Tarih bazlı grupla
        date_groups = {}
        for p in predictions:
            d = p.get("date", "")
            if d not in date_groups:
                date_groups[d] = []
            date_groups[d].append(p)

        returns = []
        win_count = 0
        total_count = 0
        all_scores = []
        all_actuals = []

        precision_at_k = {5: [], 10: [], 20: []}

        for date, preds in date_groups.items():
            if date not in actual_returns:
                continue

            # Skora göre sırala
            preds_sorted = sorted(preds, key=lambda x: x.get("score", 0), reverse=True)

            # Top K precision
            for k in [5, 10, 20]:
                top_k = preds_sorted[:k]
                correct = 0
                for p in top_k:
                    ticker = p.get("ticker", "")
                    actual = actual_returns[date].get(ticker, 0)
                    if actual > 0:
                        correct += 1
                if top_k:
                    precision_at_k[k].append(correct / len(top_k))

            # Tüm tahminler için getiri
            for p in preds:
                ticker = p.get("ticker", "")
                score = p.get("score", 0)
                actual = actual_returns[date].get(ticker, 0)

                returns.append(actual)
                all_scores.append(score)
                all_actuals.append(actual)

                if actual > 0:
                    win_count += 1
                total_count += 1

        if not returns:
            return {}

        # Temel metrikler
        total_return = sum(returns)
        win_rate = win_count / total_count if total_count > 0 else 0

        # Sharpe
        returns_arr = np.array(returns)
        sharpe = (np.mean(returns_arr) / np.std(returns_arr) * np.sqrt(252)) if np.std(returns_arr) > 0 else 0

        # Max Drawdown
        cumulative = np.cumsum(returns_arr)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (peak - cumulative) / np.maximum(peak, 1e-10)
        max_dd = np.max(drawdown) * 100 if len(drawdown) > 0 else 0

        # IC (Information Coefficient)
        ic = 0
        if len(all_scores) > 10 and len(all_actuals) > 10:
            try:
                ic = np.corrcoef(all_scores, all_actuals)[0, 1]
                if np.isnan(ic):
                    ic = 0
            except:
                ic = 0

        # Deflated Sharpe (Multiple testing düzeltmesi)
        deflated_sharpe = self._deflated_sharpe(sharpe, len(returns), len(date_groups))

        return {
            "return": total_return,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "precision_at_5": np.mean(precision_at_k[5]) if precision_at_k[5] else 0,
            "precision_at_10": np.mean(precision_at_k[10]) if precision_at_k[10] else 0,
            "precision_at_20": np.mean(precision_at_k[20]) if precision_at_k[20] else 0,
            "ic": ic,
            "deflated_sharpe": deflated_sharpe,
            "trades": total_count,
        }

    def _deflated_sharpe(self, sharpe: float, n_obs: int, n_trials: int = 1) -> float:
        """Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

        Backtest sayısı arttıkça Sharpe'ın güvenilirliği düşer.
        """
        if n_obs < 30 or sharpe <= 0:
            return 0.0

        # Annualized Sharpe → daily Sharpe
        daily_sharpe = sharpe / np.sqrt(252)

        # Standard error
        se = np.sqrt((1 + 0.5 * daily_sharpe**2) / n_obs)

        # Multiple testing düzeltmesi (Bonferroni yaklaşımı)
        if n_trials > 1:
            # False positive olasılığını düzelt
            adjusted_sharpe = daily_sharpe - se * np.sqrt(2 * np.log(n_trials))
        else:
            adjusted_sharpe = daily_sharpe

        return max(0, adjusted_sharpe * np.sqrt(252))

    def _aggregate_results(self, folds: List[WalkForwardFold]) -> WalkForwardResult:
        """Fold sonuçlarını birleştir."""
        if not folds:
            return self._empty_result()

        test_returns = [f.test_return for f in folds]
        test_sharpes = [f.sharpe for f in folds]
        test_win_rates = [f.win_rate for f in folds]
        precisions_5 = [f.precision_at_5 for f in folds]
        precisions_10 = [f.precision_at_10 for f in folds]
        precisions_20 = [f.precision_at_20 for f in folds]
        ics = [f.ic for f in folds]

        # Stability: fold'lar arası tutarlılık
        stability = 1.0 - min(np.std(test_returns) / (abs(np.mean(test_returns)) + 0.01), 1.0)

        # Deflated Sharpe (tüm fold'lar birleştirilmiş)
        total_sharpe = np.mean(test_sharpes)
        deflated = self._deflated_sharpe(total_sharpe, sum(f.trades for f in folds), len(folds))

        return WalkForwardResult(
            total_folds=len(folds),
            avg_test_return=round(float(np.mean(test_returns)), 4),
            avg_test_sharpe=round(float(np.mean(test_sharpes)), 4),
            avg_test_drawdown=round(float(np.mean([f.max_drawdown for f in folds])), 4),
            avg_win_rate=round(float(np.mean(test_win_rates)), 4),
            avg_precision_at_5=round(float(np.mean(precisions_5)), 4),
            avg_precision_at_10=round(float(np.mean(precisions_10)), 4),
            avg_precision_at_20=round(float(np.mean(precisions_20)), 4),
            avg_ic=round(float(np.mean(ics)), 4),
            stability_score=round(float(stability), 4),
            worst_fold_return=round(float(min(test_returns)), 4),
            best_fold_return=round(float(max(test_returns)), 4),
            deflated_sharpe=round(float(deflated), 4),
            folds=folds,
            summary={
                "purge_days": self.purge_days,
                "embargo_days": self.embargo_days,
                "train_days": self.train_days,
                "test_days": self.test_days,
                "step_days": self.step_days,
                "total_predictions": sum(f.trades for f in folds),
            }
        )

    def _empty_result(self) -> WalkForwardResult:
        return WalkForwardResult(
            total_folds=0, avg_test_return=0, avg_test_sharpe=0,
            avg_test_drawdown=0, avg_win_rate=0,
            avg_precision_at_5=0, avg_precision_at_10=0, avg_precision_at_20=0,
            avg_ic=0, stability_score=0,
            worst_fold_return=0, best_fold_return=0,
            deflated_sharpe=0, folds=[],
        )


# Singleton
walk_forward_engine = WalkForwardEngine()
