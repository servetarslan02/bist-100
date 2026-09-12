"""
ALPHA BIST — BIST Universe Enhancements v1.0

- Likidite skoru
- Market cap bilgisi
- Listing status
- Survivorship bias koruması
- Cross-source reconciliation
- Outlier detection
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Likidite skoru eşikleri
DEFAULT_LIQ_VOLUME_HIGH: float = 1_000_000
DEFAULT_LIQ_VOLUME_MED: float = 500_000
DEFAULT_LIQ_VOLUME_LOW: float = 100_000
DEFAULT_LIQ_VOLUME_VERY_LOW: float = 10_000
DEFAULT_LIQ_SPREAD_TIGHT: float = 0.1
DEFAULT_LIQ_SPREAD_MED: float = 0.3
DEFAULT_LIQ_SPREAD_WIDE: float = 1.0
DEFAULT_LIQ_CAP_LARGE: float = 10e9
DEFAULT_LIQ_CAP_MED: float = 1e9
DEFAULT_LIQ_CAP_SMALL: float = 100e6


@dataclass
class InstrumentInfo:
    """Enstrüman bilgisi.

    Attributes:
        ticker: Hisse sembolü.
        name: Şirket adı.
        sector: Sektör.
        market_cap: Piyasa değeri.
        avg_volume_20d: 20 günlük ortalama hacim.
        liquidity_score: Likidite skoru (0-100).
        listing_status: Listeleme durumu (ACTIVE, SUSPENDED, DELISTED).
        isin: ISIN kodu.
        currency: Para birimi.
    """

    ticker: str
    name: str
    sector: str
    market_cap: float = 0.0
    avg_volume_20d: float = 0.0
    liquidity_score: float = 0.0
    listing_status: str = "ACTIVE"
    isin: str = ""
    currency: str = "TRY"

    def __repr__(self) -> str:
        return (
            f"InstrumentInfo(ticker={self.ticker!r}, "
            f"sector={self.sector!r}, "
            f"status={self.listing_status!r})"
        )


class UniverseEnhancements:
    """BIST Universe geliştirmeleri.

    Likidite skoru, listing status ve outlier detection
    fonksiyonları sağlar.
    """

    def __repr__(self) -> str:
        """UniverseEnhancements string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return "UniverseEnhancements()"

    def compute_liquidity_score(self, avg_volume: float, avg_spread_pct: float, market_cap: float) -> float:
        """Likidite skoru hesaplar (0-100).

        Args:
            avg_volume: Ortalama günlük hacim.
            avg_spread_pct: Ortalama spread yüzdesi.
            market_cap: Piyasa değeri.

        Returns:
            Likidite skoru (0.0-100.0).
        """
        score = 50.0

        # Volume component
        if avg_volume > DEFAULT_LIQ_VOLUME_HIGH:
            score += 25
        elif avg_volume > DEFAULT_LIQ_VOLUME_MED:
            score += 15
        elif avg_volume > DEFAULT_LIQ_VOLUME_LOW:
            score += 5
        elif avg_volume < DEFAULT_LIQ_VOLUME_VERY_LOW:
            score -= 25

        # Spread component
        if avg_spread_pct < DEFAULT_LIQ_SPREAD_TIGHT:
            score += 15
        elif avg_spread_pct < DEFAULT_LIQ_SPREAD_MED:
            score += 5
        elif avg_spread_pct > DEFAULT_LIQ_SPREAD_WIDE:
            score -= 15

        # Market cap component
        if market_cap > DEFAULT_LIQ_CAP_LARGE:
            score += 10
        elif market_cap > DEFAULT_LIQ_CAP_MED:
            score += 5
        elif market_cap < DEFAULT_LIQ_CAP_SMALL:
            score -= 10

        return max(0, min(100, score))

    def classify_listing_status(
        self,
        ticker: str,
        last_trade_date: str | None = None,
        has_suspension: bool = False,
    ) -> str:
        """Listing status sınıflandırır.

        Args:
            ticker: Hisse sembolü.
            last_trade_date: Son işlem tarihi (ISO format).
            has_suspension: Askıya alınmış mı.

        Returns:
            Durum string'i: "ACTIVE", "SUSPENDED" veya "DELISTED".
        """
        if has_suspension:
            return "SUSPENDED"

        if last_trade_date:
            try:
                last = datetime.fromisoformat(last_trade_date)
                days_since = (datetime.now(UTC) - last.replace(tzinfo=UTC)).days
                if days_since > 30:
                    return "DELISTED"
                elif days_since > 5:
                    return "SUSPENDED"
            except Exception as exc:
                logger.warning("Listing status tarih parse hatası", ticker=ticker, error=str(exc))

        return "ACTIVE"


class CrossSourceReconciliation:
    """Çapraz kaynak doğrulama.

    Not: Bu sınıf `reconciliation.py`'deki `SourceReconciler` ile
    benzer işlevsellik sağlar. Farklı scope'larda kullanılırlar:
    - `SourceReconciler`: ingestion pipeline içinde (ağırlıklı ortalama)
    - `CrossSourceReconciliation`: bağımsız doğrulama (z-score outlier)
    """

    def __repr__(self) -> str:
        """CrossSourceReconciliation string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return "CrossSourceReconciliation()"

    def reconcile_price(self, sources: dict[str, float], tolerance_pct: float = 2.0) -> dict[str, Any]:
        """Fiyat kaynaklarını doğrular.

        Args:
            sources: {"yfinance": 305.25, "kap": 305.30, "matriks": 305.20}
            tolerance_pct: Kabul edilebilir fark yüzdesi.

        Returns:
            Doğrulama sonucu: status, consensus_price, std, outliers.
        """
        if not sources:
            return {"status": "NO_DATA", "consensus_price": 0}

        prices = list(sources.values())
        mean_price = np.mean(prices)
        std_price = np.std(prices)

        max_diff_pct = max(abs(p / mean_price - 1) * 100 for p in prices) if mean_price > 0 else 0

        if max_diff_pct > tolerance_pct * 3:
            status = "MAJOR_CONFLICT"
        elif max_diff_pct > tolerance_pct:
            status = "MINOR_CONFLICT"
        else:
            status = "CONSISTENT"

        outliers: list[dict[str, Any]] = []
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
    """Anomali/aykırı değer tespiti.

    Z-score ve IQR yöntemleriyle outlier tespiti sağlar.
    """

    def __repr__(self) -> str:
        """OutlierDetector string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return "OutlierDetector()"

    def detect_zscore_outliers(self, values: list[float], threshold: float = 4.0) -> list[int]:
        """Z-score ile outlier tespit eder.

        Args:
            values: Sayısal değer listesi.
            threshold: Z-score eşik değeri.

        Returns:
            Outlier indeks listesi.
        """
        if len(values) < 5:
            return []

        arr = np.array(values)
        mean = np.mean(arr)
        std = np.std(arr)

        if std == 0:
            return []

        zscores = np.abs((arr - mean) / std)
        return [i for i, z in enumerate(zscores) if z > threshold]

    def detect_iqr_outliers(self, values: list[float]) -> list[int]:
        """IQR ile outlier tespit eder.

        Args:
            values: Sayısal değer listesi.

        Returns:
            Outlier indeks listesi.
        """
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
    """Survivorship bias koruması.

    Backtest'te delisted şirketleri hariç tutarak
    gerçekçi performans ölçümü sağlar.
    """

    def __init__(self) -> None:
        """SurvivorshipBiasProtection örneği oluşturur."""
        self._delisted: dict[str, dict[str, str]] = {}

    def __repr__(self) -> str:
        """SurvivorshipBiasProtection string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return f"SurvivorshipBiasProtection(delisted={len(self._delisted)})"

    def mark_delisted(self, ticker: str, delist_date: str, reason: str = "") -> None:
        """Şirketi delisted olarak işaretler.

        Args:
            ticker: Hisse sembolü.
            delist_date: Delist tarihi (ISO format).
            reason: Delist sebebi.
        """
        self._delisted[ticker] = {
            "delist_date": delist_date,
            "reason": reason,
            "marked_at": datetime.now(UTC).isoformat(),
        }
        logger.info("Company marked delisted", ticker=ticker, date=delist_date)

    def is_delisted(self, ticker: str, as_of_date: str | None = None) -> bool:
        """Belirli bir tarihte delisted mi kontrol eder.

        Args:
            ticker: Hisse sembolü.
            as_of_date: Kontrol tarihi (ISO format). None = şu an.

        Returns:
            True: Delisted, False: Aktif.
        """
        info = self._delisted.get(ticker)
        if not info:
            return False

        if as_of_date:
            return info["delist_date"] <= as_of_date
        return True

    def get_active_universe(self, all_tickers: list[str], as_of_date: str) -> list[str]:
        """Belirli bir tarihte aktif olan hisseleri döndürür.

        Survivorship bias koruması: backtest'te delisted şirketleri hariç tutar.

        Args:
            all_tickers: Tüm hisse listesi.
            as_of_date: Kontrol tarihi (ISO format).

        Returns:
            Aktif hisse listesi.
        """
        return [t for t in all_tickers if not self.is_delisted(t, as_of_date)]

    def get_delisted(self) -> dict[str, dict[str, str]]:
        """Delisted şirketleri döndürür.

        Returns:
            {ticker: delist_bilgisi} sözlüğü.
        """
        return dict(self._delisted)


# Singletons
universe_enhancements = UniverseEnhancements()
cross_source_reconciliation = CrossSourceReconciliation()
outlier_detector = OutlierDetector()
survivorship_bias = SurvivorshipBiasProtection()


__all__ = [
    "InstrumentInfo",
    "UniverseEnhancements",
    "CrossSourceReconciliation",
    "OutlierDetector",
    "SurvivorshipBiasProtection",
    "universe_enhancements",
    "cross_source_reconciliation",
    "outlier_detector",
    "survivorship_bias",
]
