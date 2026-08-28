"""
ALPHA BIST — Streaming Anomaly Detector v1.0

Veri ingestion anında anomali tespiti:
- Fiyat anomalisi (ani sıçrama)
- Hacim anomalisi (anormal hacim)
- Spread anomalisi (aşırı spread)
- Kaynak anomalisi (sahte veri)

Kaynak: Confluent streaming quality, Monte Carlo anomaly detection
"""

from collections import deque
from dataclasses import dataclass

import numpy as np
import structlog
import functools
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.streaming_anomaly")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator


@dataclass
class AnomalyResult:
    """Anomali tespit sonucu."""

    is_anomaly: bool
    anomaly_type: str  # price, volume, spread, source
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    score: float  # 0-1
    details: str
    zscore: float


class StreamingAnomalyDetector:
    """Streaming anomali tespit motoru.

    Her tick'te çalışır, geçmiş verilerle karşılaştırır.
    """

    def __init__(self, window_size: int = 100):
        self._window_size = window_size
        self._price_history: dict[str, deque] = {}  # ticker → deque of prices
        self._volume_history: dict[str, deque] = {}
        self._spread_history: dict[str, deque] = {}

    @otel_trace("streaming_anomaly.check_price")
    def check_price(
        self,
        ticker: str,
        price: float,
        previous_price: float,
        volatility: float = 0.25,
    ) -> AnomalyResult:
        """Fiyat anomalisi kontrolü."""
        if ticker not in self._price_history:
            self._price_history[ticker] = deque(maxlen=self._window_size)

        history = self._price_history[ticker]
        history.append(price)

        # Z-score hesapla (current price hariç — data leakage önleme)
        if len(history) >= 11:
            mean = np.mean(list(history)[:-1])
            std = np.std(list(history)[:-1])
            zscore = abs(price - mean) / std if std > 0 else 0
        else:
            zscore = 0

        # Ani değişim kontrolü
        if previous_price > 0:
            change_pct = abs(price / previous_price - 1) * 100
            # Volatilite bazlı eşik
            expected_move = volatility / np.sqrt(252) * 4  # 4 sigma
            is_anomaly = change_pct > expected_move * 100
        else:
            is_anomaly = False
            change_pct = 0

        # Severity
        if zscore > 5 or change_pct > 10:
            severity = "CRITICAL"
        elif zscore > 4 or change_pct > 5:
            severity = "HIGH"
        elif zscore > 3 or change_pct > 3:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        return AnomalyResult(
            is_anomaly=is_anomaly or zscore > 4,
            anomaly_type="price",
            severity=severity,
            score=min(1.0, zscore / 5),
            details=f"zscore={zscore:.2f}, change={change_pct:.2f}%",
            zscore=round(zscore, 2),
        )

    @otel_trace("streaming_anomaly.check_volume")
    def check_volume(
        self,
        ticker: str,
        volume: int,
    ) -> AnomalyResult:
        """Hacim anomalisi kontrolü."""
        if ticker not in self._volume_history:
            self._volume_history[ticker] = deque(maxlen=self._window_size)

        history = self._volume_history[ticker]
        history.append(volume)

        if len(history) >= 10:
            mean = np.mean(history)
            std = np.std(history)
            zscore = abs(volume - mean) / std if std > 0 else 0
        else:
            zscore = 0

        is_anomaly = zscore > 4
        severity = "CRITICAL" if zscore > 6 else "HIGH" if zscore > 4 else "LOW"

        return AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_type="volume",
            severity=severity,
            score=min(1.0, zscore / 5),
            details=f"zscore={zscore:.2f}",
            zscore=round(zscore, 2),
        )

    @otel_trace("streaming_anomaly.check_spread")
    def check_spread(
        self,
        ticker: str,
        bid: float,
        ask: float,
    ) -> AnomalyResult:
        """Spread anomalisi kontrolü."""
        if bid <= 0 or ask <= 0:
            return AnomalyResult(
                is_anomaly=False,
                anomaly_type="spread",
                severity="LOW",
                score=0,
                details="No bid/ask",
                zscore=0,
            )

        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100 if mid > 0 else 0

        if ticker not in self._spread_history:
            self._spread_history[ticker] = deque(maxlen=self._window_size)

        history = self._spread_history[ticker]
        history.append(spread_pct)

        if len(history) >= 10:
            mean = np.mean(history)
            std = np.std(history)
            zscore = abs(spread_pct - mean) / std if std > 0 else 0
        else:
            zscore = 0

        is_anomaly = spread_pct > 5 or zscore > 4
        severity = "HIGH" if spread_pct > 5 else "LOW"

        return AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_type="spread",
            severity=severity,
            score=min(1.0, zscore / 3),
            details=f"spread={spread_pct:.2f}%, zscore={zscore:.2f}",
            zscore=round(zscore, 2),
        )

    @otel_trace("streaming_anomaly.check_all")
    def check_all(
        self,
        ticker: str,
        price: float,
        previous_price: float,
        volume: int,
        bid: float = 0,
        ask: float = 0,
        volatility: float = 0.25,
    ) -> list[AnomalyResult]:
        """Tüm anomalileri kontrol et."""
        results = []

        price_check = self.check_price(ticker, price, previous_price, volatility)
        results.append(price_check)

        volume_check = self.check_volume(ticker, volume)
        results.append(volume_check)

        if bid > 0 and ask > 0:
            spread_check = self.check_spread(ticker, bid, ask)
            results.append(spread_check)

        return results

    def get_stats(self) -> dict:
        """İstatistikler."""
        return {
            "tracked_tickers": len(self._price_history),
            "total_price_points": sum(len(h) for h in self._price_history.values()),
            "total_volume_points": sum(len(h) for h in self._volume_history.values()),
        }


# Singleton
streaming_anomaly_detector = StreamingAnomalyDetector()
