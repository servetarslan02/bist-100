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
from typing import Any, Dict, List, Optional, Tuple
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
            # İlk hisseyi benchmark olarak kullan
            benchmark_ticker = list(market_data.keys())[0] if market_data else None

        if not benchmark_ticker:
            return RegimeState("UNKNOWN", 0, 0, {}, {})

        df = market_data[benchmark_ticker]
        close = df["Close"].values if "Close" in df.columns else np.array([])
        high = df["High"].values if "High" in df.columns else close.copy()
        low = df["Low"].values if "Low" in df.columns else close.copy()
        volume = df["Volume"].values if "Volume" in df.columns else np.ones(len(close))

        if len(close) < self.lookback_days:
            return RegimeState("UNKNOWN", 0, 0, {}, {})

        factors = {}

        # 1. TREND FAKTÖRÜ
        sma20 = np.mean(close[-20:])
        sma50 = np.mean(close[-50:]) if len(close) >= 50 else sma20
        sma200 = np.mean(close[-200:]) if len(close) >= 200 else sma50

        trend_score = 0
        if close[-1] > sma20:
            trend_score += 20
        if sma20 > sma50:
            trend_score += 20
        if sma50 > sma200:
            trend_score += 20
        if close[-1] > close[-20]:
            trend_score += 20
        if close[-1] > close[-60]:
            trend_score += 20

        factors["trend_score"] = trend_score

        # 2. VOLATİLİTE FAKTÖRÜ
        returns = np.diff(close[-60:]) / close[-60:-1]
        vol_20d = np.std(returns[-20:]) * np.sqrt(252) if len(returns) >= 20 else 0
        vol_60d = np.std(returns) * np.sqrt(252) if len(returns) >= 60 else 0

        vol_score = 0
        if vol_20d > 0.25:  # Yüksek volatilite
            vol_score = 100
        elif vol_20d > 0.15:
            vol_score = 50
        elif vol_20d < 0.10:  # Düşük volatilite
            vol_score = -50

        factors["volatility_score"] = vol_score
        factors["vol_20d_annual"] = round(vol_20d * 100, 2)
        factors["vol_60d_annual"] = round(vol_60d * 100, 2)

        # 3. MOMENTUM FAKTÖRÜ
        roc_20d = (close[-1] / close[-20] - 1) * 100 if len(close) >= 20 else 0
        roc_60d = (close[-1] / close[-60] - 1) * 100 if len(close) >= 60 else 0

        momentum_score = 0
        if roc_20d > 5:
            momentum_score += 50
        elif roc_20d < -5:
            momentum_score -= 50
        if roc_60d > 10:
            momentum_score += 50
        elif roc_60d < -10:
            momentum_score -= 50

        factors["momentum_score"] = momentum_score

        # 4. BREADTH FAKTÖRÜ
        # Tüm hisselerin yükselen/düşen sayısı
        advancing = 0
        declining = 0
        total = 0
        for ticker, tdf in market_data.items():
            if len(tdf) >= 2:
                tclose = tdf["Close"].values
                if tclose[-1] > tclose[-2]:
                    advancing += 1
                elif tclose[-1] < tclose[-2]:
                    declining += 1
                total += 1

        breadth = advancing / total if total > 0 else 0.5
        factors["breadth_score"] = round((breadth - 0.5) * 200, 2)
        factors["advancing_ratio"] = round(breadth, 4)

        # 5. KORELASYON FAKTÖRÜ
        # Hisse-hisse korelasyonu (düşük = dispersiyon yüksek)
        correlations = []
        tickers = list(market_data.keys())[:20]  # İlk 20 hisse
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

        avg_corr = np.mean(correlations) if correlations else 0.5
        factors["avg_correlation"] = round(avg_corr, 4)
        factors["dispersion_score"] = round((1 - avg_corr) * 100, 2)

        # 6. VOLUME FAKTÖRÜ
        vol_trend = 0
        if len(volume) >= 20:
            vol_recent = np.mean(volume[-5:])
            vol_prev = np.mean(volume[-20:-5])
            if vol_prev > 0:
                vol_trend = (vol_recent / vol_prev - 1) * 100

        factors["volume_trend"] = round(vol_trend, 2)

        # === REJİM KARARI ===
        # Çok faktörlü skorlama
        bull_score = 0
        bear_score = 0
        sideways_score = 0
        high_vol_score = 0
        low_vol_score = 0

        # Trend
        if trend_score > 60:
            bull_score += 40
        elif trend_score < 30:
            bear_score += 40
        else:
            sideways_score += 30

        # Momentum
        if momentum_score > 30:
            bull_score += 30
        elif momentum_score < -30:
            bear_score += 30

        # Volatilite
        if vol_score > 50:
            high_vol_score += 50
        elif vol_score < -30:
            sideways_score += 20
            low_vol_score += 40

        # Breadth
        if factors["breadth_score"] > 30:
            bull_score += 20
        elif factors["breadth_score"] < -30:
            bear_score += 20

        # Korelasyon
        if avg_corr > 0.8:
            bear_score += 10  # Yüksek korelasyon = panik
        elif avg_corr < 0.3:
            bull_score += 10  # Düşük korelasyon = seçicilik

        # Volume
        if vol_trend > 50:
            high_vol_score += 20

        scores = {
            "BULL": bull_score,
            "BEAR": bear_score,
            "SIDEWAYS": sideways_score,
            "HIGH_VOL": high_vol_score,
            "LOW_VOL": low_vol_score,
        }

        regime = max(scores, key=scores.get)
        confidence = scores[regime] / 100

        # Regime değişimi
        if regime != self._current_regime:
            self._regime_duration = 0
            self._current_regime = regime
        else:
            self._regime_duration += 1

        # Transition probability (basit Markov)
        transition_prob = self._estimate_transition_probability(regime)

        state = RegimeState(
            regime=regime,
            confidence=round(confidence, 4),
            duration_days=self._regime_duration,
            transition_probability=transition_prob,
            factors=factors,
        )

        self._regime_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regime": regime,
            "confidence": confidence,
            "factors": factors,
        })

        logger.info("Regime detected", regime=regime, confidence=round(confidence, 4),
                   duration=self._regime_duration)

        return state

    def _estimate_transition_probability(self, current_regime: str) -> Dict[str, float]:
        """Rejim geçiş olasılıklarını tahmin et."""
        # Basit geçiş matrisi (gerçek veri ile güncellenebilir)
        transition_matrix = {
            "BULL": {"BULL": 0.7, "BEAR": 0.15, "SIDEWAYS": 0.1, "HIGH_VOL": 0.05},
            "BEAR": {"BULL": 0.1, "BEAR": 0.6, "SIDEWAYS": 0.2, "HIGH_VOL": 0.1},
            "SIDEWAYS": {"BULL": 0.25, "BEAR": 0.25, "SIDEWAYS": 0.4, "HIGH_VOL": 0.1},
            "HIGH_VOL": {"BULL": 0.2, "BEAR": 0.3, "SIDEWAYS": 0.2, "HIGH_VOL": 0.3},
        }

        return transition_matrix.get(current_regime, {r: 0.25 for r in self.REGIMES})

    def get_regime_history(self) -> List[Dict]:
        return list(self._regime_history)


# Singleton
regime_detector = RegimeDetector()
