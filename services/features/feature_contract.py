"""
ALPHA BIST — Feature Data Contract v1.0

Her feature için:
- value: sayısal değer (float veya None)
- availability_ts: bu bilginin gerçek dünyada kullanılabildiği timestamp
- source: veri kaynağı (calculator, motor1, kap, yfinance, vb.)
- status: MISSING | UNKNOWN | STALE | FRESH

Kurallar:
- MISSING: veri hiç çekilmedi veya provider yok
- UNKNOWN: veri çekildi ama bu ticker için mevcut değil
- STALE: veri var ama belirli bir eşiğin eski
- FRESH: veri güncel ve kullanılabilir

Point-in-time güvenlik:
- availability_ts, bilginin model tarafından kullanılabileceği en erken tarihtir
- Backtest'te t < availability_ts ise o feature kullanılamaz
- publication_date ≠ availability_date (KAP açıklaması gün sonunda yayınlanabilir
  ama ertesi gün piyasaya yansır)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone


class FeatureStatus(str, Enum):
    MISSING = "MISSING"      # Veri hiç yok
    UNKNOWN = "UNKNOWN"      # Veri çekildi ama bu ticker için mevcut değil
    STALE = "STALE"          # Veri var ama eski
    FRESH = "FRESH"          # Veri güncel


@dataclass
class FeatureDataPoint:
    """Tek bir feature veri noktası — metadata dahil."""
    value: Optional[float]
    availability_ts: Optional[str]  # ISO-8601
    source: str
    status: FeatureStatus

    def to_value(self, default: float = 0.0) -> float:
        """Raw değer — eksikse default döner."""
        if self.value is not None and self.status == FeatureStatus.FRESH:
            return self.value
        return default

    def is_usable(self) -> bool:
        """Model tarafından kullanılabilir mi?"""
        return self.status == FeatureStatus.FRESH and self.value is not None


@dataclass
class TickerFeatureContract:
    """Tek bir ticker için tüm feature'ların kontratlı hali."""
    ticker: str
    timestamp: str  # Feature'ların hesaplandığı tarih
    features: Dict[str, FeatureDataPoint] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_value(self, key: str, default: float = 0.0) -> float:
        """Feature değeri al — eksikse default."""
        dp = self.features.get(key)
        if dp is None:
            return default
        return dp.to_value(default)

    def get_raw_dict(self) -> Dict[str, float]:
        """Tüm feature'ları raw float dict olarak döndür (backward compatible).
        MISSING/UNKNOWN feature'lar default 0 ile döner.
        """
        return {k: dp.to_value(0.0) for k, dp in self.features.items()}

    def get_usable_dict(self) -> Dict[str, float]:
        """Sadece FRESH feature'ları döndür — eksikler hariç."""
        return {k: dp.value for k, dp in self.features.items()
                if dp.is_usable()}

    def get_availability_report(self) -> Dict[str, str]:
        """Her feature'ın durumunu raporla."""
        return {k: dp.status.value for k, dp in self.features.items()}


def make_fresh(value: float, source: str, ts: Optional[str] = None) -> FeatureDataPoint:
    """FRESH feature veri noktası oluştur."""
    return FeatureDataPoint(
        value=value,
        availability_ts=ts or datetime.now(timezone.utc).isoformat(),
        source=source,
        status=FeatureStatus.FRESH,
    )


def make_missing(source: str) -> FeatureDataPoint:
    """MISSING feature veri noktası oluştur."""
    return FeatureDataPoint(
        value=None,
        availability_ts=None,
        source=source,
        status=FeatureStatus.MISSING,
    )


def make_unknown(source: str) -> FeatureDataPoint:
    """UNKNOWN feature veri noktası oluştur."""
    return FeatureDataPoint(
        value=None,
        availability_ts=None,
        source=source,
        status=FeatureStatus.UNKNOWN,
    )


def make_stale(value: float, source: str, ts: str) -> FeatureDataPoint:
    """STALE feature veri noktası oluştur."""
    return FeatureDataPoint(
        value=value,
        availability_ts=ts,
        source=source,
        status=FeatureStatus.STALE,
    )


def features_to_contract(
    ticker: str,
    raw_features: Dict[str, float],
    source: str,
    timestamp: Optional[str] = None,
) -> TickerFeatureContract:
    """Raw feature dict'i kontratlı forma çevir.

    Mevcut calculator/motor çıktılarını sarmalamak için kullanılır.
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    contract = TickerFeatureContract(ticker=ticker, timestamp=ts)
    for key, val in raw_features.items():
        if key.startswith("_"):
            # Meta feature'lar (_feature_count, _mask_valid_pct vb.)
            contract.metadata[key] = val
            continue
        if isinstance(val, float) and (val != val):  # NaN check
            contract.features[key] = make_missing(source)
        else:
            contract.features[key] = make_fresh(val, source, ts)
    return contract


def merge_feature_dicts(
    base: Dict[str, float],
    overlay: Dict[str, float],
    overlay_source: str = "overlay",
) -> Dict[str, float]:
    """Feature dict'leri birleştir — overlay base'i ezer.

    NOT: Bu fonksiyon sadece backward compatibility için.
    Yeni kod TickerFeatureContract kullanmalı.
    """
    merged = dict(base)
    merged.update(overlay)
    return merged
