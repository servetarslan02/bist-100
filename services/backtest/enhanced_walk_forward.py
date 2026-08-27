"""
ALPHA BIST — Enhanced Walk-Forward & Evaluation v1.0

Walk-Forward with purge + embargo:
- Purge: Gap between train end and test start (prevents leakage)
- Embargo: Gap between test end and next train start (prevents leakage)

Evaluation metrics:
- Alpha, Precision@K, IC, Hit Rate, Sharpe, Max DD, Turnover
- Deflated Sharpe Ratio (overfitting detection)

⚠️ PIT UYARISI: Bu modül pre-computed predictions üzerinde çalışır.
Modeli her fold'da YENİDEN EĞİTMEZ. Gerçek walk-forward doğrulama için
`walk_forward_runner.py` kullanılmalıdır — o modül her fold'da modeli
sıfırdan eğitir.

Bu modül sadece evaluation/metrik hesaplama amaçlıdır.

Kaynak: Du (2026), Huang (2026), Oxford (2023)
"""

from dataclasses import dataclass

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class WalkForwardFold:
    """Walk-forward fold sonucu."""

    fold_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_return: float
    test_return: float
    precision_at_5: float
    precision_at_10: float
    ic: float
    hit_rate: float
    sharpe: float
    max_drawdown: float
    turnover: float


@dataclass
class WalkForwardResult:
    """Walk-forward tam sonuç."""

    total_folds: int
    avg_test_return: float
    avg_test_sharpe: float
    avg_precision_at_5: float
    avg_precision_at_10: float
    avg_ic: float
    avg_hit_rate: float
    avg_max_drawdown: float
    avg_turnover: float
    stability_score: float
    deflated_sharpe: float
    folds: list[WalkForwardFold]


class PurgeEmbargoWalkForward:
    """Walk-forward with purge + embargo.

    Purge: train sonundan test başına kadar gap.
    Embargo: test sonundan bir sonraki train başına kadar gap.

    Bu, data leakage'ı önler.

    ⚠️ PIT UYARISI: Bu modül pre-computed predictions üzerinde çalışır.
    Modeli her fold'da YENİDEN EĞİTMEZ. Gerçek walk-forward doğrulama için
    `walk_forward_runner.py` kullanılmalıdır.
    """

    def __init__(
        self,
        train_days: int = 252,
        test_days: int = 63,
        step_days: int = 21,
        purge_days: int = 5,
        embargo_days: int = 5,
    ):
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days
        self.purge_days = purge_days
        self.embargo_days = embargo_days

    def split(
        self,
        n_days: int,
    ) -> list[tuple[int, int, int, int]]:
        """Walk-forward split üret.

        Returns:
            List of (train_start, train_end, test_start, test_end)
        """
        folds = []
        fold_id = 0

        current = 0
        while True:
            train_start = current
            train_end = current + self.train_days - 1

            # Purge gap
            test_start = train_end + self.purge_days + 1
            test_end = test_start + self.test_days - 1

            if test_end >= n_days:
                break

            folds.append((train_start, train_end, test_start, test_end))

            # Sonraki fold
            current = test_end + self.embargo_days + 1
            fold_id += 1

        return folds

    def run(
        self,
        predictions: np.ndarray,
        actuals: np.ndarray,
        tickers: np.ndarray,
        dates: np.ndarray,
    ) -> WalkForwardResult:
        """Walk-forward backtest çalıştır.

        Args:
            predictions: Model tahminleri (n_days × n_tickers)
            actuals: Gerçek getiriler (n_days × n_tickers)
            tickers: Hisse kodları
            dates: Tarihler
        """
        n_days = len(predictions)
        folds = self.split(n_days)

        if not folds:
            logger.warning("No walk-forward folds generated", n_days=n_days)
            return WalkForwardResult(
                total_folds=0,
                avg_test_return=0,
                avg_test_sharpe=0,
                avg_precision_at_5=0,
                avg_precision_at_10=0,
                avg_ic=0,
                avg_hit_rate=0,
                avg_max_drawdown=0,
                avg_turnover=0,
                stability_score=0,
                deflated_sharpe=0,
                folds=[],
            )

        fold_results = []

        for fold_id, (train_start, train_end, test_start, test_end) in enumerate(folds):
            # Test dönemindeki tahminler ve gerçekler
            test_preds = predictions[test_start : test_end + 1]
            test_actuals = actuals[test_start : test_end + 1]

            # Precision@K
            p_at_5 = self._precision_at_k(test_preds, test_actuals, k=5)
            p_at_10 = self._precision_at_k(test_preds, test_actuals, k=10)

            # Information Coefficient
            ic = self._compute_ic(test_preds, test_actuals)

            # Hit rate
            hit_rate = self._compute_hit_rate(test_preds, test_actuals)

            # Returns (top-K portfolio)
            test_return = self._compute_top_k_return(test_preds, test_actuals, k=10)

            # Sharpe
            daily_returns = self._compute_daily_returns(test_preds, test_actuals, k=10)
            sharpe = self._compute_sharpe(daily_returns)

            # Max drawdown
            max_dd = self._compute_max_drawdown(daily_returns)

            # Turnover
            turnover = self._compute_turnover(test_preds, test_actuals)

            # Train return (basit referans)
            train_preds = predictions[train_start : train_end + 1]
            train_actuals = actuals[train_start : train_end + 1]
            train_return = self._compute_top_k_return(train_preds, train_actuals, k=10)

            fold_results.append(
                WalkForwardFold(
                    fold_id=fold_id,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_return=round(train_return, 4),
                    test_return=round(test_return, 4),
                    precision_at_5=round(p_at_5, 4),
                    precision_at_10=round(p_at_10, 4),
                    ic=round(ic, 4),
                    hit_rate=round(hit_rate, 4),
                    sharpe=round(sharpe, 4),
                    max_drawdown=round(max_dd, 4),
                    turnover=round(turnover, 4),
                )
            )

        # Aggregate
        test_returns = [f.test_return for f in fold_results]
        test_sharpes = [f.sharpe for f in fold_results]

        # Stability: test return'lerin tutarlılığı
        if len(test_returns) > 1:
            mean_ret = np.mean(test_returns)
            std_ret = np.std(test_returns)
            stability = max(0, 1 - std_ret / (abs(mean_ret) + 0.001))
        else:
            stability = 0

        # Deflated Sharpe
        deflated = self._deflated_sharpe(test_sharpes, len(fold_results))

        return WalkForwardResult(
            total_folds=len(fold_results),
            avg_test_return=round(float(np.mean(test_returns)), 4),
            avg_test_sharpe=round(float(np.mean(test_sharpes)), 4),
            avg_precision_at_5=round(float(np.mean([f.precision_at_5 for f in fold_results])), 4),
            avg_precision_at_10=round(float(np.mean([f.precision_at_10 for f in fold_results])), 4),
            avg_ic=round(float(np.mean([f.ic for f in fold_results])), 4),
            avg_hit_rate=round(float(np.mean([f.hit_rate for f in fold_results])), 4),
            avg_max_drawdown=round(float(np.mean([f.max_drawdown for f in fold_results])), 4),
            avg_turnover=round(float(np.mean([f.turnover for f in fold_results])), 4),
            stability_score=round(float(stability), 4),
            deflated_sharpe=round(float(deflated), 4),
            folds=fold_results,
        )

    def _precision_at_k(self, predictions: np.ndarray, actuals: np.ndarray, k: int) -> float:
        """Precision@K: İlk K hisseden kaç tanesi gerçekten iyi?"""
        if len(predictions) == 0 or len(actuals) == 0:
            return 0.0

        # Her gün için
        precisions = []
        for day in range(len(predictions)):
            if len(predictions[day]) < k:
                continue

            # En iyi K tahmin
            top_k_indices = np.argsort(predictions[day])[-k:]

            # Gerçek getiriler
            day_actuals = actuals[day]
            if len(day_actuals) <= max(top_k_indices):
                continue

            # Kaç tanesi pozitif?
            correct = sum(1 for idx in top_k_indices if day_actuals[idx] > 0)
            precisions.append(correct / k)

        return float(np.mean(precisions)) if precisions else 0.0

    def _compute_ic(self, predictions: np.ndarray, actuals: np.ndarray) -> float:
        """Information Coefficient: model skoru ile gelecek getiri korelasyonu."""
        if len(predictions) == 0 or len(actuals) == 0:
            return 0.0

        correlations = []
        for day in range(len(predictions)):
            if len(predictions[day]) < 3:
                continue
            pred = predictions[day]
            actual = actuals[day]
            if len(pred) == len(actual) and np.std(pred) > 0 and np.std(actual) > 0:
                corr = np.corrcoef(pred, actual)[0, 1]
                if not np.isnan(corr):
                    correlations.append(corr)

        return float(np.mean(correlations)) if correlations else 0.0

    def _compute_hit_rate(self, predictions: np.ndarray, actuals: np.ndarray) -> float:
        """Hit rate: yön doğruluğu."""
        if len(predictions) == 0 or len(actuals) == 0:
            return 0.0

        correct = 0
        total = 0
        for day in range(len(predictions)):
            for i in range(min(len(predictions[day]), len(actuals[day]))):
                if (predictions[day][i] > 0) == (actuals[day][i] > 0):
                    correct += 1
                total += 1

        return correct / total if total > 0 else 0.0

    def _compute_top_k_return(self, predictions: np.ndarray, actuals: np.ndarray, k: int = 10) -> float:
        """Top-K portföy getirisi."""
        if len(predictions) == 0 or len(actuals) == 0:
            return 0.0

        total_return = 0.0
        for day in range(len(predictions)):
            if len(predictions[day]) < k:
                continue
            top_k = np.argsort(predictions[day])[-k:]
            day_return = np.mean([actuals[day][i] for i in top_k if i < len(actuals[day])])
            total_return += day_return

        return total_return

    def _compute_daily_returns(self, predictions: np.ndarray, actuals: np.ndarray, k: int = 10) -> list[float]:
        """Günlük getiri serisi."""
        returns = []
        for day in range(len(predictions)):
            if len(predictions[day]) < k:
                continue
            top_k = np.argsort(predictions[day])[-k:]
            day_return = np.mean([actuals[day][i] for i in top_k if i < len(actuals[day])])
            returns.append(day_return)
        return returns

    def _compute_sharpe(self, daily_returns: list[float], risk_free: float = 0) -> float:
        """Sharpe ratio."""
        if not daily_returns or len(daily_returns) < 2:
            return 0.0
        returns = np.array(daily_returns)
        excess = returns - risk_free / 252
        if np.std(excess) == 0:
            return 0.0
        return float(np.mean(excess) / np.std(excess) * np.sqrt(252))

    def _compute_max_drawdown(self, daily_returns: list[float]) -> float:
        """Max drawdown."""
        if not daily_returns:
            return 0.0
        equity = np.cumprod(1 + np.array(daily_returns))
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        return float(np.max(dd)) * 100

    def _compute_turnover(self, predictions: np.ndarray, actuals: np.ndarray, k: int = 10) -> float:
        """Turnover: portföy değişim hızı."""
        if len(predictions) < 2:
            return 0.0

        prev_top_k = set()
        turnovers = []
        for day in range(len(predictions)):
            if len(predictions[day]) < k:
                continue
            top_k = set(np.argsort(predictions[day])[-k:])
            if prev_top_k:
                changed = len(top_k - prev_top_k)
                turnovers.append(changed / k)
            prev_top_k = top_k

        return float(np.mean(turnovers)) if turnovers else 0.0

    def _deflated_sharpe(self, sharpes: list[float], n_trials: int) -> float:
        """Deflated Sharpe Ratio — overfitting tespiti.

        Backtest sayısı arttıkça Sharpe'ın güvenilirliği düşer.
        """
        if not sharpes or n_trials < 2:
            return 0.0

        observed_sharpe = np.mean(sharpes)
        sharpe_std = np.std(sharpes)

        if sharpe_std == 0:
            return 0.0

        # Expected maximum Sharpe under null hypothesis
        # E[max(SR)] ≈ sqrt(2 * log(n_trials))
        expected_max = np.sqrt(2 * np.log(n_trials))

        # Deflated Sharpe
        deflated = (observed_sharpe - expected_max) / sharpe_std if sharpe_std > 0 else 0

        return float(deflated)


# Singleton
purge_embargo_wf_engine = PurgeEmbargoWalkForward()
