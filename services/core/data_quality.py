"""
ALPHA BIST — Data Quality Gate v2.0

P0-2 düzeltmeleri:
- Stale detection: .seconds → total_seconds()
- Duplicate protection: distributed-safe (time-windowed)
- Missing != 0: explicit VALID/MISSING/STALE/INVALID states
- Out-of-order detection
- Future timestamp detection
- Tick validation BEFORE state update
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


class DataValidity(str, Enum):
    """Veri geçerlilik durumu — missing != 0 != invalid."""
    VALID = "VALID"
    MISSING = "MISSING"      # Veri yok
    STALE = "STALE"          # Veri çok eski
    INVALID = "INVALID"      # Veri mantıksız (negatif fiyat vb.)
    DUPLICATE = "DUPLICATE"  # Aynı veri tekrar gelmiş
    OUT_OF_ORDER = "OUT_OF_ORDER"  # Zaman sırası bozuk
    FUTURE = "FUTURE"        # Gelecekten timestamp


@dataclass
class QualityCheck:
    """Veri kalite kontrol sonucu."""
    passed: bool
    validity: DataValidity
    score: float  # 0-1
    issues: list = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DataQualityGate:
    """Veri kalite kapısı — her veri buradan geçer.

    Kritik: Validate → Accept → State Update sırası.
    Geçersiz tick mevcut state'i DEĞİŞTİRMEMELİ.
    """

    # Stale threshold
    STALE_THRESHOLD_SECONDS = 300  # 5 dakika
    MAX_PRICE_CHANGE_PCT = 20.0     # Tek tick'te max %20 değişim
    LARGE_PRICE_CHANGE_PCT = 10.0
    DUPLICATE_WINDOW_SECONDS = 60   # 1 dakika içinde aynı hash = duplicate
    MAX_FUTURE_DRIFT_SECONDS = 5    # 5 saniye gelecek toleransı

    def __init__(self):
        self._last_tick_time: Dict[str, datetime] = {}
        self._last_price: Dict[str, float] = {}
        # Duplicate protection: ticker+hash → timestamp (time-windowed)
        self._recent_hashes: Dict[str, datetime] = {}
        self._tick_counts: Dict[str, int] = {}
        self._rejected_counts: Dict[str, int] = {}

    def check_tick(
        self,
        ticker: str,
        price: float,
        volume: int,
        timestamp: datetime,
        bid: float = 0,
        ask: float = 0,
    ) -> QualityCheck:
        """Tick verisini doğrula.

        Kritik: Bu fonksiyon state güncellemeden ÖNCE çağrılmalıdır.
        Geçersiz tick → state güncellenmez.
        """
        issues = []
        score = 1.0
        validity = DataValidity.VALID
        now = datetime.now(timezone.utc)

        # Timestamp timezone-aware yap
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        # 0. Future timestamp kontrolü
        future_drift = (timestamp - now).total_seconds()
        if future_drift > self.MAX_FUTURE_DRIFT_SECONDS:
            issues.append(f"future_timestamp_{future_drift:.0f}s")
            validity = DataValidity.FUTURE
            score -= 0.8

        # 1. Fiyat kontrolü
        if price <= 0:
            issues.append("invalid_price")
            validity = DataValidity.INVALID
            score -= 0.5

        if price < 0:
            issues.append("negative_price")
            validity = DataValidity.INVALID
            score -= 0.5

        # 2. Volume kontrolü
        if volume < 0:
            issues.append("negative_volume")
            validity = DataValidity.INVALID
            score -= 0.5

        # 3. Duplicate kontrolü (time-windowed)
        tick_hash = f"{ticker}:{price}:{volume}:{timestamp.isoformat()[:19]}"
        last_seen = self._recent_hashes.get(tick_hash)
        if last_seen:
            time_since = abs((timestamp - last_seen).total_seconds())
            if time_since < self.DUPLICATE_WINDOW_SECONDS:
                issues.append("duplicate_tick")
                validity = DataValidity.DUPLICATE
                score -= 0.5
        self._recent_hashes[tick_hash] = timestamp

        # Duplicate hash cache temizliği
        if len(self._recent_hashes) > 50000:
            cutoff = now - timedelta(seconds=self.DUPLICATE_WINDOW_SECONDS * 2)
            self._recent_hashes = {
                k: v for k, v in self._recent_hashes.items()
                if v > cutoff
            }

        # 4. Out-of-order kontrolü
        last_time = self._last_tick_time.get(ticker)
        if last_time and timestamp < last_time:
            drift = (last_time - timestamp).total_seconds()
            if drift > 10:  # 10 saniyeden fazla geriye gitme
                issues.append(f"out_of_order_{drift:.0f}s")
                validity = DataValidity.OUT_OF_ORDER
                score -= 0.3

        # 5. Stale price kontrolü (total_seconds kullan!)
        last_price = self._last_price.get(ticker)
        if last_price and price == last_price and last_time:
            stale_seconds = abs((timestamp - last_time).total_seconds())
            if stale_seconds > self.STALE_THRESHOLD_SECONDS:
                issues.append(f"stale_price_{stale_seconds:.0f}s")
                validity = DataValidity.STALE
                score -= 0.3

        # 6. Ani fiyat değişimi kontrolü
        if last_price and last_price > 0 and price > 0:
            change_pct = abs(price / last_price - 1) * 100
            if change_pct > self.MAX_PRICE_CHANGE_PCT:
                issues.append(f"extreme_price_change_{change_pct:.1f}%")
                score -= 0.4
            elif change_pct > self.LARGE_PRICE_CHANGE_PCT:
                issues.append(f"large_price_change_{change_pct:.1f}%")
                score -= 0.2

        # 7. Bid/Ask spread kontrolü
        if bid > 0 and ask > 0:
            if ask < bid:
                issues.append("inverted_bid_ask")
                score -= 0.5
            if price > 0:
                spread_pct = (ask - bid) / price * 100
                if spread_pct > 5:
                    issues.append(f"wide_spread_{spread_pct:.1f}%")
                    score -= 0.2

        # 8. Clock drift kontrolü (total_seconds!)
        drift = abs((now - timestamp).total_seconds())
        if drift > 60 and validity == DataValidity.VALID:
            issues.append(f"clock_drift_{drift:.0f}s")
            score -= 0.2

        # Sadece VALID tick'ler state'i güncellemeli
        passed = score >= 0.5 and validity == DataValidity.VALID

        # İstatistik
        self._tick_counts[ticker] = self._tick_counts.get(ticker, 0) + 1
        if not passed:
            self._rejected_counts[ticker] = self._rejected_counts.get(ticker, 0) + 1

        # State güncelleme SADECE passed=True ise yapılmalı
        if passed:
            self._last_tick_time[ticker] = timestamp
            self._last_price[ticker] = price

        return QualityCheck(
            passed=passed,
            validity=validity,
            score=max(0, score),
            issues=issues,
            metadata={
                "ticker": ticker,
                "price": price,
                "volume": volume,
                "timestamp": timestamp.isoformat(),
            },
        )

    def check_bar(
        self,
        ticker: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: int,
    ) -> QualityCheck:
        """OHLC bar doğrula."""
        issues = []
        score = 1.0
        validity = DataValidity.VALID

        # Negatif değerler
        if any(v < 0 for v in [open_, high, low, close]):
            issues.append("negative_price")
            validity = DataValidity.INVALID
            score -= 0.5

        # OHLC mantığı
        if high < low:
            issues.append("high_less_than_low")
            validity = DataValidity.INVALID
            score -= 0.5

        if high < open_ or high < close:
            issues.append("high_inconsistent")
            score -= 0.3

        if low > open_ or low > close:
            issues.append("low_inconsistent")
            score -= 0.3

        if volume < 0:
            issues.append("negative_volume")
            validity = DataValidity.INVALID
            score -= 0.5

        if volume == 0:
            issues.append("zero_volume")
            score -= 0.1

        passed = score >= 0.5 and validity in (DataValidity.VALID,)
        return QualityCheck(
            passed=passed,
            validity=validity,
            score=max(0, score),
            issues=issues,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Kalite istatistikleri."""
        return {
            "tracked_tickers": len(self._last_price),
            "total_ticks_processed": sum(self._tick_counts.values()),
            "total_rejected": sum(self._rejected_counts.values()),
            "recent_duplicate_hashes": len(self._recent_hashes),
            "rejected_by_ticker": dict(self._rejected_counts),
        }


# Singleton
data_quality_gate = DataQualityGate()
