"""
ALPHA BIST — Regime Detector v3.0

ROADMAP v3.0:
- Multi-factor regime detection (trend, volatilite, korelasyon, breadth)
- Regime transition probability
- Regime duration tracking
- Forward-looking regime prediction

KURAL: BULL'da momentum, BEAR'da quality, SIDEWAYS'da mean reversion.
"""

import numpy as np
from typing import Any, Dict, List
from dataclasses import dataclass
from collections import deque
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class RegimeState:
    """Regim durumu."""
    regime: str  # BULL, BEAR, SIDEWAYS, HIGH_VOL, LOW_VOL
    confidence: float
    duration_days: int
    transition_probability: Dict[str, float]
    factors: Dict[str, float]


class RegimeDetector:
    """Çok faktörlü piyasa rejimi tespiti."""

    REGIMES = ["BULL", "BEAR", "SIDEWAYS", "HIGH_VOL", "LOW_VOL"]

    def __init__(self, lookback_days: int = 60):
        self.lookback_days = lookback_days
        self._regime_history: deque = deque(maxlen=252)
        self._current_regime = "UNKNOWN"
        self._regime_duration = 0

    def detect_regime(
        self,
        market_data: Dict[str, Any],  # {ticker: DataFrame}
        benchmark_ticker: str = "XU100",
    ) -> RegimeState:
        """Piyasa rejimini tespit et."""
        if benchmark_ticker not in market_data:
            benchmark_ticker = list(market_data.keys())[0] if market_data else None
        if not benchmark_ticker:
            return RegimeState("UNKNOWN", 0, 0, {}, {})

        df = market_data[benchmark_ticker]
        close = df["Close"].values if "Close" in df.columns else np.array([])
        volume = df["Volume"].values if "Volume" in df.columns else np.ones(len(close))

        if len(close) < self.lookback_days:
            return RegimeState("UNKNOWN", 0, 0, {}, {})

        factors = {}
        factors["trend_score"] = self._calc_trend_score(close)
        factors.update(self._calc_volatility_factors(close))
        factors["momentum_score"] = self._calc_momentum_score(close)
        factors.update(self._calc_breadth_factors(market_data))
        avg_corr = self._calc_correlation(market_data)
        factors["avg_correlation"] = round(avg_corr, 4)
        factors["dispersion_score"] = round((1 - avg_corr) * 100, 2)
        factors["volume_trend"] = self._calc_volume_trend(volume)

        regime, confidence = self._decide_regime(factors, avg_corr)
        self._update_regime_state(regime, confidence, factors)

        return RegimeState(
            regime=regime,
            confidence=round(confidence, 4),
            duration_days=self._regime_duration,
            transition_probability=self._estimate_transition_probability(regime),
            factors=factors,
        )

    def _calc_trend_score(self, close) -> int:
        """Trend faktörünü hesapla (0-100)."""
        has_200 = len(close) >= 200
        has_50 = len(close) >= 50
        has_60 = len(close) >= 60

        sma20 = np.mean(close[-20:])
        sma50 = np.mean(close[-50:]) if has_50 else sma20
        sma200 = np.mean(close[-200:]) if has_200 else sma50

        score = 0
        points = 0

        points += 20
        if close[-1] > sma20:
            score += 20

        if has_50:
            points += 20
            if sma20 > sma50:
                score += 20

        if has_200:
            points += 20
            if sma50 > sma200:
                score += 20
        elif has_50:
            points += 20
            if close[-1] > sma50:
                score += 20

        points += 20
        if close[-1] > close[-20]:
            score += 20

        if has_60:
            points += 20
            if close[-1] > close[-60]:
                score += 20

        return int(round((score / points) * 100)) if points > 0 else 0

    def _calc_volatility_factors(self, close) -> dict:
        """Volatilite faktörlerini hesapla."""
        returns = np.diff(close[-60:]) / close[-60:-1]
        vol_20d = np.std(returns[-20:]) * np.sqrt(252) if len(returns) >= 20 else 0
        vol_60d = np.std(returns) * np.sqrt(252) if len(returns) >= 60 else 0

        vol_score = 0
        if vol_20d > 0.25:
            vol_score = 100
        elif vol_20d > 0.15:
            vol_score = 50
        elif vol_20d < 0.10:
            vol_score = -50

        return {
            "volatility_score": vol_score,
            "vol_20d_annual": round(vol_20d * 100, 2),
            "vol_60d_annual": round(vol_60d * 100, 2),
        }

    def _calc_momentum_score(self, close) -> int:
        """Momentum faktörünü hesapla."""
        roc_20d = (close[-1] / close[-20] - 1) * 100 if len(close) >= 20 else 0
        roc_60d = (close[-1] / close[-60] - 1) * 100 if len(close) >= 60 else 0

        score = 0
        if roc_20d > 5:
            score += 50
        elif roc_20d < -5:
            score -= 50
        if roc_60d > 10:
            score += 50
        elif roc_60d < -10:
            score -= 50
        return score

    def _calc_breadth_factors(self, market_data) -> dict:
        """Breadth (piyasa genişliği) faktörlerini hesapla."""
        advancing = 0
        total = 0
        for ticker, tdf in market_data.items():
            if len(tdf) >= 2:
                tclose = tdf["Close"].values
                if tclose[-1] > tclose[-2]:
                    advancing += 1
                total += 1

        breadth = advancing / total if total > 0 else 0.5
        return {
            "breadth_score": round((breadth - 0.5) * 200, 2),
            "advancing_ratio": round(breadth, 4),
        }

    def _calc_correlation(self, market_data) -> float:
        """Hisse-hisse ortalama korelasyonu hesapla."""
        correlations = []
        tickers = list(market_data.keys())[:20]
        for i, t1 in enumerate(tickers):
            for t2 in tickers[i+1:]:
                if t1 in market_data and t2 in market_data:
                    c1 = market_data[t1]["Close"].values[-20:]
                    c2 = market_data[t2]["Close"].values[-20:]
                    if len(c1) == len(c2) and len(c1) >= 10:
                        r1 = np.diff(c1) / c1[:-1]
                        r2 = np.diff(c2) / c2[:-1]
                        if np.std(r1) > 0 and np.std(r2) > 0:
                            corr = np.corrcoef(r1, r2)[0, 1]
                            if not np.isnan(corr):
                                correlations.append(corr)
        return np.mean(correlations) if correlations else 0.5

    def _calc_volume_trend(self, volume) -> float:
        """Hacim trendini hesapla."""
        if len(volume) < 20:
            return 0.0
        vol_recent = np.mean(volume[-5:])
        vol_prev = np.mean(volume[-20:-5])
        return round(((vol_recent / vol_prev - 1) * 100) if vol_prev > 0 else 0.0, 2)

    def _decide_regime(self, factors: dict, avg_corr: float) -> tuple:
        """Çok faktörlü skorlamaya göre rejim kararı."""
        bull = bear = sideways = high_vol = low_vol = 0

        ts = factors.get("trend_score", 50)
        if ts > 60:
            bull += 40
        elif ts < 30:
            bear += 40
        else:
            sideways += 30

        ms = factors.get("momentum_score", 0)
        if ms > 30:
            bull += 30
        elif ms < -30:
            bear += 30

        vs = factors.get("volatility_score", 0)
        if vs > 50:
            high_vol += 50
        elif vs < -30:
            sideways += 20
            low_vol += 40

        bs = factors.get("breadth_score", 0)
        if bs > 30:
            bull += 20
        elif bs < -30:
            bear += 20

        if avg_corr > 0.8:
            bear += 10
        elif avg_corr < 0.3:
            bull += 10

        if factors.get("volume_trend", 0) > 50:
            high_vol += 20

        scores = {
            "BULL": bull, "BEAR": bear, "SIDEWAYS": sideways,
            "HIGH_VOL": high_vol, "LOW_VOL": low_vol,
        }
        regime = max(scores, key=scores.get)
        return regime, scores[regime] / 100

    def _update_regime_state(self, regime: str, confidence: float, factors: dict) -> None:
        """Rejim durumunu güncelle ve geçmişe kaydet."""
        if regime != self._current_regime:
            self._regime_duration = 0
            self._current_regime = regime
        else:
            self._regime_duration += 1

        self._regime_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regime": regime,
            "confidence": confidence,
            "factors": factors,
        })
        if len(self._regime_history) > 1000:
            self._regime_history = self._regime_history[-1000:]

        logger.info("Regime detected", regime=regime, confidence=round(confidence, 4),
                   duration=self._regime_duration)

    def _estimate_transition_probability(self, current_regime: str) -> Dict[str, float]:
        """Rejim geçiş olasılıklarını tahmin et."""
        # Basit geçiş matrisi (gerçek veri ile güncellenebilir)
        transition_matrix = {
            "BULL": {"BULL": 0.65, "BEAR": 0.15, "SIDEWAYS": 0.1, "HIGH_VOL": 0.05, "LOW_VOL": 0.05},
            "BEAR": {"BULL": 0.1, "BEAR": 0.55, "SIDEWAYS": 0.2, "HIGH_VOL": 0.1, "LOW_VOL": 0.05},
            "SIDEWAYS": {"BULL": 0.2, "BEAR": 0.2, "SIDEWAYS": 0.4, "HIGH_VOL": 0.1, "LOW_VOL": 0.1},
            "HIGH_VOL": {"BULL": 0.15, "BEAR": 0.3, "SIDEWAYS": 0.2, "HIGH_VOL": 0.3, "LOW_VOL": 0.05},
            "LOW_VOL": {"BULL": 0.2, "BEAR": 0.15, "SIDEWAYS": 0.15, "HIGH_VOL": 0.1, "LOW_VOL": 0.4},
        }

        return transition_matrix.get(current_regime, {r: 0.2 for r in self.REGIMES})

    def get_regime_history(self) -> List[Dict]:
        return list(self._regime_history)


# Singleton
regime_detector = RegimeDetector()
