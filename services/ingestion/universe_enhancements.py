"""
ALPHA BIST — BIST Universe Enhancements v1.0

- Likidite skoru
- Market cap bilgisi
- Listing status
- Survivorship bias koruması
- Cross-source reconciliation
- Outlier detection
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class InstrumentInfo:
    """Enstrüman bilgisi."""
    ticker: str
    name: str
    sector: str
    market_cap: float = 0.0
    avg_volume_20d: float = 0.0
    liquidity_score: float = 0.0
    listing_status: str = "ACTIVE"  # ACTIVE, SUSPENDED, DELISTED
    isin: str = ""
    currency: str = "TRY"


class UniverseEnhancements:
    """BIST Universe geliştirmeleri."""

    def compute_liquidity_score(self, avg_volume: float, avg_spread_pct: float, market_cap: float) -> float:
        """Likidite skoru hesapla (0-100)."""
        score = 50.0

        # Volume component
        if avg_volume > 1000000:
            score += 25
        elif avg_volume > 500000:
            score += 15
        elif avg_volume > 100000:
            score += 5
        elif avg_volume < 10000:
            score -= 25

        # Spread component
        if avg_spread_pct < 0.1:
            score += 15
        elif avg_spread_pct < 0.3:
            score += 5
        elif avg_spread_pct > 1.0:
            score -= 15

        # Market cap component
        if market_cap > 10e9:
            score += 10
        elif market_cap > 1e9:
            score += 5
        elif market_cap < 100e6:
            score -= 10

        return max(0, min(100, score))

    def classify_listing_status(self, ticker: str, last_trade_date: Optional[str] = None, has_suspension: bool = False) -> str:
        """Listing status sınıflandır."""
        if has_suspension:
            return "SUSPENDED"

        if last_trade_date:
            try:
                last = datetime.fromisoformat(last_trade_date)
                days_since = (datetime.now(timezone.utc) - last.replace(tzinfo=timezone.utc)).days
                if days_since > 30:
                    return "DELISTED"
                elif days_since > 5:
                    return "SUSPENDED"
            except:
                pass

        return "ACTIVE"


class CrossSourceReconciliation:
    """Çapraz kaynak doğrulama."""

    def reconcile_price(self, sources: Dict[str, float], tolerance_pct: float = 2.0) -> Dict[str, Any]:
        """Fiyat kaynaklarını doğrula.

        Args:
            sources: {"yfinance": 305.25, "kap": 305.30, "matriks": 305.20}
            tolerance_pct: Kabul edilebilir fark yüzdesi
        """
        if not sources:
            return {"status": "NO_DATA", "consensus_price": 0}

        prices = list(sources.values())
        mean_price = np.mean(prices)
        std_price = np.std(prices)

        # Tolerance check
        max_diff_pct = max(abs(p / mean_price - 1) * 100 for p in prices) if mean_price > 0 else 0

        if max_diff_pct > tolerance_pct * 3:
            status = "MAJOR_CONFLICT"
        elif max_diff_pct > tolerance_pct:
            status = "MINOR_CONFLICT"
        else:
            status = "CONSISTENT"

        # Outlier detection
        outliers = []
        for source, price in sources.items():
            zscore = abs(price - mean_price) / std_price if std_price > 0 else 0
            if zscore > 2.0:
                outliers.append({"source": source, "price": price, "zscore": round(zscore, 2)})

        return {
            "status": status,
            "consensus_price": round(float(mean_price), 4),
            "std": round(float(std_price), 4),
            "max_diff_pct": round(max_diff_pct, 2),
            "outliers": outliers,
            "source_count": len(sources),
        }


class OutlierDetector:
    """Anomali/aykırı değer tespiti."""

    def detect_zscore_outliers(self, values: List[float], threshold: float = 4.0) -> List[int]:
        """Z-score ile outlier tespit et."""
        if len(values) < 5:
            return []

        arr = np.array(values)
        mean = np.mean(arr)
        std = np.std(arr)

        if std == 0:
            return []

        zscores = np.abs((arr - mean) / std)
        return [i for i, z in enumerate(zscores) if z > threshold]

    def detect_iqr_outliers(self, values: List[float]) -> List[int]:
        """IQR ile outlier tespit et."""
        if len(values) < 5:
            return []

        arr = np.array(values)
        q1 = np.percentile(arr, 25)
        q3 = np.percentile(arr, 75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        return [i for i, v in enumerate(arr) if v < lower or v > upper]


class SurvivorshipBiasProtection:
    """Survivorship bias koruması."""

    def __init__(self):
        self._delisted: Dict[str, Dict] = {}

    def mark_delisted(self, ticker: str, delist_date: str, reason: str = ""):
        """Şirketi delisted olarak işaretle."""
        self._delisted[ticker] = {
            "delist_date": delist_date,
            "reason": reason,
            "marked_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("Company marked delisted", ticker=ticker, date=delist_date)

    def is_delisted(self, ticker: str, as_of_date: Optional[str] = None) -> bool:
        """Belirli bir tarihte delisted mi?"""
        info = self._delisted.get(ticker)
        if not info:
            return False

        if as_of_date:
            return info["delist_date"] <= as_of_date
        return True

    def get_active_universe(self, all_tickers: List[str], as_of_date: str) -> List[str]:
        """Belirli bir tarihte aktif olan hisseleri döndür (survivorship bias koruması)."""
        return [t for t in all_tickers if not self.is_delisted(t, as_of_date)]

    def get_delisted(self) -> Dict[str, Dict]:
        """Delisted şirketleri döndür."""
        return dict(self._delisted)


# Singletons
universe_enhancements = UniverseEnhancements()
cross_source_reconciliation = CrossSourceReconciliation()
outlier_detector = OutlierDetector()
survivorship_bias = SurvivorshipBiasProtection()
