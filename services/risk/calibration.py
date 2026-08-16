"""
ALPHA BIST — Score Calibration v1.0

Ranking model skorunu gercek win_probability'ye donusturur.
Platt Scaling (logistic regression) veya Isotonic Regression kullanir.

KURAL: Score != win_probability. Calibration gerekli.
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class CalibrationParams:
    """Calibration parametreleri."""
    method: str = "platt"  # platt | isotonic | empirical
    a: float = 1.0         # Platt: scale
    b: float = 0.0         # Platt: shift
    empirical_bins: Dict[str, float] = None  # Bin bazli mapping


class ScoreCalibrator:
    """Ranking score -> win_probability kalibrasyonu."""

    def __init__(self):
        self.params = CalibrationParams()
        self._trade_history: List[Dict] = []  # Historical OOS trades
        self._fitted = False

    def fit_from_trades(self, trades: List[Dict]):
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

            logger.info("Calibration fitted",
                       trades=len(trades),
                       a=round(self.params.a, 4),
                       b=round(self.params.b, 4))

    def calibrate(self, score: float) -> float:
        """Score -> win_probability.

        LambdaRank semantigi: dusuk score = iyi.
        Score'lari historical dagilima gore percentile'e cevir.
        """
        if not self._fitted:
            # Fitted degilse: score'u historical dagilima gore normalize et
            if self._trade_history:
                hist_scores = np.array([t["score"] for t in self._trade_history])
                # Percentile: dusuk score = yuksek percentile (iyi)
                percentile = (hist_scores >= score).mean()
                p = 0.5 + percentile * 0.5  # 0.5 - 1.0 arasi
                return float(np.clip(p, 0.05, 0.95))
            else:
                # Hic trade yok: sigmoid fallback
                # score ~0 -> p~0.9, score ~10 -> p~0.5
                p = 1.0 / (1.0 + np.exp(0.5 * score - 2.5))
                return float(np.clip(p, 0.05, 0.95))

        # Platt scaling
        log_odds = self.params.a * score + self.params.b
        p = 1.0 / (1.0 + np.exp(-log_odds))
        return float(np.clip(p, 0.05, 0.95))

    def add_trade(self, score: float, return_pct: float, ticker: str, date: str):
        """Yeni trade ekle (online learning)."""
        self._trade_history.append({
            "score": score,
            "return_pct": return_pct,
            "ticker": ticker,
            "date": date,
        })

        # Her 30 trade'te bir refit (minimum threshold)
        if len(self._trade_history) >= 30 and len(self._trade_history) % 10 == 0:
            self.fit_from_trades(self._trade_history)

    def debug_fit(self):
        """Debug: fit_from_trades adimlarini logla."""
        trades = self._trade_history
        print(f"\n[CALIBRATOR DEBUG] trades={len(trades)}, fitted={self._fitted}")

        if len(trades) < 30:
            print(f"  -> SKIP: len(trades)={len(trades)} < 30")
            return

        scores = np.array([t["score"] for t in trades])
        returns = np.array([t["return_pct"] for t in trades])

        print(f"  scores: min={scores.min():.4f}, max={scores.max():.4f}, mean={scores.mean():.4f}, std={scores.std():.4f}")
        print(f"  returns: min={returns.min():.4f}, max={returns.max():.4f}, mean={returns.mean():.4f}")
        print(f"  win_count={(returns>0).sum()}, loss_count={(returns<0).sum()}")

        # Decile bazli win rate
        deciles = np.percentile(scores, np.linspace(0, 100, 11))
        print(f"  deciles: {deciles}")

        bin_centers = []
        win_rates = []

        for i in range(len(deciles) - 1):
            mask = (scores >= deciles[i]) & (scores < deciles[i + 1])
            if mask.sum() > 0:
                bin_win_rate = (returns[mask] > 0).mean()
                bin_centers.append((deciles[i] + deciles[i + 1]) / 2)
                win_rates.append(bin_win_rate)
                print(f"    bin {i}: center={bin_centers[-1]:.4f}, win_rate={bin_win_rate:.4f}, n={mask.sum()}")

        print(f"  bin_centers: {bin_centers}")
        print(f"  win_rates: {win_rates}")

        if len(bin_centers) >= 3:
            x = np.array(bin_centers)
            y = np.array(win_rates)
            y_clipped = np.clip(y, 0.01, 0.99)
            log_odds = np.log(y_clipped / (1 - y_clipped))
            print(f"  y_clipped: {y_clipped}")
            print(f"  log_odds: {log_odds}")

            A = np.vstack([x, np.ones(len(x))]).T
            a, b = np.linalg.lstsq(A, log_odds, rcond=None)[0]
            print(f"  Platt fit: a={a:.6f}, b={b:.6f}")

            # Test prediction
            test_score = scores.mean()
            log_odds_pred = a * test_score + b
            p_pred = 1.0 / (1.0 + np.exp(-log_odds_pred))
            print(f"  Test: score={test_score:.4f} -> log_odds={log_odds_pred:.4f} -> p={p_pred:.4f}")
        else:
            print(f"  -> SKIP: len(bin_centers)={len(bin_centers)} < 3")

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


# Singleton
calibrator = ScoreCalibrator()
