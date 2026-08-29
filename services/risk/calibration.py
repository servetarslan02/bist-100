"""
ALPHA BIST — Score Calibration v1.0

Ranking model skorunu gercek win_probability'ye donusturur.
Platt Scaling (logistic regression) veya Isotonic Regression kullanir.

KURAL: Score != win_probability. Calibration gerekli.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class CalibrationParams:
    """Calibration parametreleri."""

    method: str = "platt"  # platt | isotonic | empirical
    a: float = 1.0  # Platt: scale
    b: float = 0.0  # Platt: shift
    empirical_bins: dict[str, float] = None  # Bin bazli mapping


class ScoreCalibrator:
    """Ranking score -> win_probability kalibrasyonu."""

    def __init__(self):
        """Otomatik eklendi."""
        self.params = CalibrationParams()
        self._trade_history: list[dict] = []  # Historical OOS trades
        self._fitted = False
        self._brier_scores: list[float] = []  # Brier score geçmişi
        self._calibration_curve: dict[str, list] = {"predicted": [], "actual": []}

    def fit_from_trades(self, trades: list[dict]) -> Any:
        """Historical OOS trades'ten calibration fit et.

        trades: [{score, return_pct, ticker, date}, ...]
        """
        if len(trades) < 30:
            logger.warning("Insufficient trades for calibration", n=len(trades))
            return

        # Score'lara gore bin'le (decile)
        scores = np.array([t["score"] for t in trades])
        returns = np.array([t["return_pct"] for t in trades])

        # Decile bazli win rate
        deciles = np.percentile(scores, np.linspace(0, 100, 11))
        bin_centers = []
        win_rates = []

        for i in range(len(deciles) - 1):
            mask = (scores >= deciles[i]) & (scores < deciles[i + 1])
            if mask.sum() > 0:
                bin_win_rate = (returns[mask] > 0).mean()
                bin_centers.append((deciles[i] + deciles[i + 1]) / 2)
                win_rates.append(bin_win_rate)

        # Platt scaling fit: p = 1 / (1 + exp(a*score + b))
        # Linear least squares on log-odds
        if len(bin_centers) >= 3:
            x = np.array(bin_centers)
            y = np.array(win_rates)
            # Clip to avoid log(0)
            y_clipped = np.clip(y, 0.01, 0.99)
            log_odds = np.log(y_clipped / (1 - y_clipped))

            # Linear fit: log_odds = a*score + b
            A = np.vstack([x, np.ones(len(x))]).T
            self.params.a, self.params.b = np.linalg.lstsq(A, log_odds, rcond=None)[0]
            self._fitted = True

            logger.info("Calibration fitted", trades=len(trades), a=round(self.params.a, 4), b=round(self.params.b, 4))

    def calibrate(self, score: float) -> float:
        """Score -> win_probability."""
        if not self._fitted:
            # Fitted degilse: sigmoid ile gerceklestir
            # Score dusuk = iyi (LambdaRank), bu yuzden ters cevir
            # score ~0 -> p~0.9, score ~10 -> p~0.5
            p = 1.0 / (1.0 + np.exp(0.5 * score - 2.5))
            return float(np.clip(p, 0.05, 0.95))

        # Platt scaling
        log_odds = self.params.a * score + self.params.b
        p = 1.0 / (1.0 + np.exp(-log_odds))
        return float(np.clip(p, 0.05, 0.95))

    def add_trade(self, score: float, return_pct: float, ticker: str, date: str) -> Any:
        """Yeni trade ekle (online learning)."""
        self._trade_history.append(
            {
                "score": score,
                "return_pct": return_pct,
                "ticker": ticker,
                "date": date,
            }
        )
        if len(self._trade_history) > 5000:
            self._trade_history = self._trade_history[-5000:]

        # Her 50 trade'te bir refit
        if len(self._trade_history) % 50 == 0:
            self.fit_from_trades(self._trade_history)

    def get_avg_win_loss(self) -> tuple:
        """Historical trades'ten avg_win ve avg_loss dondur."""
        if not self._trade_history:
            return 0.05, 0.05  # Default

        returns = np.array([t["return_pct"] for t in self._trade_history])
        wins = returns[returns > 0]
        losses = returns[returns < 0]

        avg_win = float(wins.mean()) if len(wins) > 0 else 0.05
        avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.05

        return avg_win, avg_loss

    def compute_brier_score(self, trades: list[dict] = None) -> float:
        """Brier score hesapla — kalibrasyon kalitesi ölçümü.

        Brier = (1/N) * Σ(predicted - actual)²
        0 = mükemmel, 1 = kötü

        Args:
            trades: Trade listesi. None ise kendi geçmişini kullan.

        Returns:
            Brier score (0-1)
        """
        if trades is None:
            trades = self._trade_history

        if len(trades) < 10:
            return -1.0  # Yetersiz veri

        scores = np.array([t["score"] for t in trades])
        outcomes = np.array([1.0 if t["return_pct"] > 0 else 0.0 for t in trades])

        # Tahmin olasılıkları
        predicted = np.array([self.calibrate(s) for s in scores])

        # Brier score
        brier = float(np.mean((predicted - outcomes) ** 2))

        self._brier_scores.append(brier)
        if len(self._brier_scores) > 1000:
            self._brier_scores = self._brier_scores[-1000:]

        logger.info("Brier score computed", brier=round(brier, 4), n_trades=len(trades))

        return brier

    def get_calibration_curve(self, n_bins: int = 10) -> dict[str, list]:
        """Kalibrasyon eğrisi — tahmin vs gerçek.

        Args:
            n_bins: Bin sayısı

        Returns:
            {"predicted": [...], "actual": [...], "bin_centers": [...]}
        """
        if len(self._trade_history) < 20:
            return {"predicted": [], "actual": [], "bin_centers": []}

        scores = np.array([t["score"] for t in self._trade_history])
        outcomes = np.array([1.0 if t["return_pct"] > 0 else 0.0 for t in self._trade_history])
        predicted = np.array([self.calibrate(s) for s in scores])

        # Bin'le
        bin_edges = np.linspace(0, 1, n_bins + 1)
        bin_centers = []
        actual_rates = []
        predicted_rates = []

        for i in range(n_bins):
            mask = (predicted >= bin_edges[i]) & (predicted < bin_edges[i + 1])
            if mask.sum() > 0:
                bin_centers.append(round((bin_edges[i] + bin_edges[i + 1]) / 2, 2))
                actual_rates.append(round(float(outcomes[mask].mean()), 3))
                predicted_rates.append(round(float(predicted[mask].mean()), 3))

        self._calibration_curve = {
            "predicted": predicted_rates,
            "actual": actual_rates,
            "bin_centers": bin_centers,
        }

        return self._calibration_curve

    def get_brier_history(self) -> list[float]:
        """Brier score geçmişini döndür."""
        return self._brier_scores.copy()

    def get_calibration_quality(self) -> dict[str, Any]:
        """Kalibrasyon kalitesi özeti."""
        brier = self.compute_brier_score() if len(self._trade_history) >= 10 else -1

        quality = "UNKNOWN"
        if brier >= 0:
            if brier < 0.1:
                quality = "EXCELLENT"
            elif brier < 0.2:
                quality = "GOOD"
            elif brier < 0.3:
                quality = "FAIR"
            else:
                quality = "POOR"

        return {
            "brier_score": round(brier, 4) if brier >= 0 else None,
            "quality": quality,
            "n_trades": len(self._trade_history),
            "fitted": self._fitted,
            "brier_history_count": len(self._brier_scores),
        }


# Singleton
calibrator = ScoreCalibrator()
