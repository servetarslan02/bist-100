"""
ALPHA BIST — Feature Store v1.0

Tüm feature'ların canonical kaynağı:
- Versioned storage (v1, v2, ...)
- Redis hot cache
- DB persistence
- Feature history
- Feature metadata

FAZ 2.5: Feature Store + Versioning
"""

import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import structlog

logger = structlog.get_logger()


class FeatureValue:
    """Tek bir feature değeri."""

    def __init__(self, name: str, value: float, ticker: str,
                 version: str = "v1", timestamp: Optional[datetime] = None,
                 source: str = "feature_engine", confidence: float = 1.0):
        self.name = name
        self.value = value
        self.ticker = ticker
        self.version = version
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.source = source
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "ticker": self.ticker,
            "version": self.version,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "confidence": self.confidence,
        }


class FeatureStore:
    """Feature Store — tüm feature'ların canonical kaynağı.

    Versioned: her feature grubu version'lanır.
    Hot cache: Redis'te tutulur.
    Persistent: DB'ye yazılır.
    """

    def __init__(self):
        # In-memory store (production'da Redis + DB)
        self._store: Dict[str, Dict[str, Dict[str, float]]] = {}  # ticker -> version -> {name: value}
        self._metadata: Dict[str, Dict[str, Any]] = {}  # ticker -> metadata
        self._versions: Dict[str, Dict[str, str]] = {}  # feature_group -> {version: formula}
        self._history: Dict[str, List[Dict]] = {}  # ticker -> [{timestamp, features}]

    def get(self, ticker: str, feature_name: str, version: str = "latest") -> Optional[float]:
        """Feature değeri getir."""
        ticker_features = self._store.get(ticker, {})

        if version == "latest":
            # En son version'ı bul
            for v in sorted(ticker_features.keys(), reverse=True):
                if feature_name in ticker_features[v]:
                    return ticker_features[v][feature_name]
        else:
            if version in ticker_features and feature_name in ticker_features[version]:
                return ticker_features[version][feature_name]

        return None

    def get_all(self, ticker: str, version: str = "latest") -> Dict[str, float]:
        """Tüm feature'ları getir."""
        ticker_features = self._store.get(ticker, {})

        if version == "latest":
            # En son version'ın tüm feature'larını birleştir
            result = {}
            for v in sorted(ticker_features.keys()):
                result.update(ticker_features[v])
            return result
        else:
            return ticker_features.get(version, {})

    def set(self, ticker: str, features: Dict[str, float], version: str = "v1",
            source: str = "feature_engine", confidence: float = 1.0):
        """Feature'ları kaydet."""
        if ticker not in self._store:
            self._store[ticker] = {}
        if version not in self._store[ticker]:
            self._store[ticker][version] = {}

        self._store[ticker][version].update(features)

        # Metadata güncelle
        self._metadata[ticker] = {
            "last_update": datetime.now(timezone.utc).isoformat(),
            "version": version,
            "feature_count": len(self._store[ticker][version]),
            "source": source,
        }

        # History ekle
        if ticker not in self._history:
            self._history[ticker] = []
        self._history[ticker].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": version,
            "feature_count": len(features),
        })
        # Son 100 snapshot tut
        self._history[ticker] = self._history[ticker][-100:]

        logger.debug("Features stored", ticker=ticker, version=version, count=len(features))

    def get_history(self, ticker: str, limit: int = 10) -> List[Dict]:
        """Feature güncelleme geçmişi."""
        return self._history.get(ticker, [])[-limit:]

    def get_metadata(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Feature metadata."""
        return self._metadata.get(ticker)

    def register_version(self, feature_group: str, version: str, formula: str):
        """Feature version kaydet."""
        if feature_group not in self._versions:
            self._versions[feature_group] = {}
        self._versions[feature_group][version] = formula
        logger.info("Feature version registered", group=feature_group, version=version)

    def get_version_info(self, feature_group: str) -> Dict[str, str]:
        """Feature version bilgisi."""
        return self._versions.get(feature_group, {})

    def get_feature_hash(self, ticker: str, version: str = "latest") -> str:
        """Feature set'in hash'i (cache invalidation için)."""
        features = self.get_all(ticker, version)
        feature_str = json.dumps(features, sort_keys=True)
        return hashlib.sha256(feature_str.encode()).hexdigest()[:16]

    def get_stats(self) -> Dict[str, Any]:
        """Store istatistikleri."""
        total_tickers = len(self._store)
        total_features = sum(
            sum(len(v) for v in versions.values())
            for versions in self._store.values()
        )
        return {
            "total_tickers": total_tickers,
            "total_features": total_features,
            "total_versions": sum(len(v) for v in self._versions.values()),
        }

    def clear(self, ticker: Optional[str] = None):
        """Store temizle."""
        if ticker:
            self._store.pop(ticker, None)
            self._metadata.pop(ticker, None)
            self._history.pop(ticker, None)
        else:
            self._store.clear()
            self._metadata.clear()
            self._history.clear()


# Singleton
feature_store = FeatureStore()
