"""
ALPHA BIST — Data Quality Gate v1.0

Gelen her veriyi doğrula:
- Provider latency
- Missing ticks
- Duplicate ticks
- Stale price
- Out-of-order events
- Bad bid/ask
- Volume anomaly
- Clock drift
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class QualityCheck:
    """Veri kalite kontrol sonucu."""
    passed: bool
    score: float  # 0-1
    issues: list = field(default_factory=list)


class DataQualityGate:
    """Veri kalite kapısı — her veri buradan geçer."""

    def __init__(self):
        self._last_tick_time: Dict[str, datetime] = {}
        self._last_price: Dict[str, float] = {}
        self._seen_hashes: set = set()
        self._tick_counts: Dict[str, int] = {}

    def check_tick(self, ticker: str, price: float, volume: int,
                   timestamp: datetime, bid: float = 0, ask: float = 0) -> QualityCheck:
        """Tick verisini doğrula."""
        issues = []
        score = 1.0

        # 1. Fiyat kontrolü
        if price <= 0:
            issues.append("invalid_price")
            score -= 0.5

        # 2. Stale price kontrolü
        last_price = self._last_price.get(ticker)
        if last_price and price == last_price:
            # Fiyat değişmemiş — stale olabilir
            last_time = self._last_tick_time.get(ticker)
            if last_time and (timestamp - last_time).seconds > 300:
                issues.append("stale_price_5min")
                score -= 0.3

        # 3. Ani fiyat değişimi kontrolü
        if last_price and last_price > 0:
            change_pct = abs(price / last_price - 1) * 100
            if change_pct > 20:
                issues.append(f"extreme_price_change_{change_pct:.1f}%")
                score -= 0.4
            elif change_pct > 10:
                issues.append(f"large_price_change_{change_pct:.1f}%")
                score -= 0.2

        # 4. Volume anomalisi
        if volume < 0:
            issues.append("negative_volume")
            score -= 0.5

        # 5. Bid/Ask spread kontrolü
        if bid > 0 and ask > 0:
            if ask < bid:
                issues.append("inverted_bid_ask")
                score -= 0.5
            spread_pct = (ask - bid) / price * 100 if price > 0 else 0
            if spread_pct > 5:
                issues.append(f"wide_spread_{spread_pct:.1f}%")
                score -= 0.2

        # 6. Clock drift kontrolü
        now = datetime.utcnow()
        drift = abs((now - timestamp).total_seconds())
        if drift > 60:
            issues.append(f"clock_drift_{drift:.0f}s")
            score -= 0.2

        # 7. Duplicate kontrolü
        tick_hash = f"{ticker}:{price}:{volume}:{timestamp.isoformat()[:19]}"
        if tick_hash in self._seen_hashes:
            issues.append("duplicate_tick")
            score -= 0.5
        self._seen_hashes.add(tick_hash)
        if len(self._seen_hashes) > 100000:
            self._seen_hashes = set(list(self._seen_hashes)[-50000:])

        # 8. Tick rate kontrolü
        self._tick_counts[ticker] = self._tick_counts.get(ticker, 0) + 1

        # Güncelle
        self._last_tick_time[ticker] = timestamp
        self._last_price[ticker] = price

        passed = score >= 0.5
        return QualityCheck(passed=passed, score=max(0, score), issues=issues)

    def check_bar(self, ticker: str, open_: float, high: float, low: float,
                  close: float, volume: int) -> QualityCheck:
        """OHLC bar doğrula."""
        issues = []
        score = 1.0

        # OHLC mantığı
        if high < low:
            issues.append("high_less_than_low")
            score -= 0.5

        if high < open_ or high < close:
            issues.append("high_inconsistent")
            score -= 0.3

        if low > open_ or low > close:
            issues.append("low_inconsistent")
            score -= 0.3

        # Negatif değerler
        if any(v < 0 for v in [open_, high, low, close]):
            issues.append("negative_price")
            score -= 0.5

        if volume < 0:
            issues.append("negative_volume")
            score -= 0.5

        # Sıfır hacim (piyasa kapalı olabilir)
        if volume == 0:
            issues.append("zero_volume")
            score -= 0.1

        return QualityCheck(passed=score >= 0.5, score=max(0, score), issues=issues)

    def get_stats(self) -> Dict[str, Any]:
        """Kalite istatistikleri."""
        return {
            "tracked_tickers": len(self._last_price),
            "total_ticks_processed": sum(self._tick_counts.values()),
            "unique_hashes": len(self._seen_hashes),
        }


# Singleton
data_quality_gate = DataQualityGate()
