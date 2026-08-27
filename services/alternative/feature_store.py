"""
ALPHA BIST — Feature Store Integration v1.0

Alternative data feature'ları için feature store entegrasyonu.

Özellikler:
- Feature versioning
- Point-in-time correctness
- Backtest compatibility
- Feature manifest
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()


@dataclass
class FeatureManifest:
    """Feature manifest — feature metadata."""
    feature_name: str
    version: str
    source: str
    description: str
    dtype: str  # float, int, bool
    range_min: float
    range_max: float
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "feature_name": self.feature_name,
            "version": self.version,
            "source": self.source,
            "description": self.description,
            "dtype": self.dtype,
            "range_min": self.range_min,
            "range_max": self.range_max,
            "created_at": self.created_at,
            "dependencies": self.dependencies,
        }


class FeatureStore:
    """Feature store — feature versioning ve point-in-time correctness.

    Özellikler:
    - Her feature için manifest (metadata)
    - Feature versioning (v1, v2, ...)
    - Point-in-time sorgu (backtest'te gelecek veri sızıntısı yok)
    - Feature lineage (hangi kaynaktan geliyor)
    """

    def __init__(self, store_path: str | None = None):
        self._store_path = store_path
        self._manifests: dict[str, FeatureManifest] = {}
        self._feature_values: dict[str, dict[str, dict[str, float]]] = {}  # date → ticker → features

    def register_feature(self, manifest: FeatureManifest):
        """Feature kaydet."""
        self._manifests[manifest.feature_name] = manifest
        logger.debug("Feature registered", name=manifest.feature_name, version=manifest.version)

    def put(
        self,
        ticker: str,
        date: str,
        features: dict[str, float],
        source: str = "alternative",
    ):
        """Feature değerleri yaz.

        Args:
            ticker: Hisse kodu
            date: Tarih (YYYY-MM-DD)
            features: Feature değerleri
            source: Kaynak adı
        """
        if date not in self._feature_values:
            self._feature_values[date] = {}
        if ticker not in self._feature_values[date]:
            self._feature_values[date][ticker] = {}

        self._feature_values[date][ticker].update(features)

        # Manifest'leri otomatik oluştur
        for name, _value in features.items():
            if name not in self._manifests:
                self.register_feature(FeatureManifest(
                    feature_name=name,
                    version="v1",
                    source=source,
                    description=f"Auto-registered from {source}",
                    dtype="float",
                    range_min=-1000,
                    range_max=1000,
                ))

    def get(
        self,
        ticker: str,
        date: str,
        feature_names: list[str] | None = None,
    ) -> dict[str, float]:
        """Feature değerleri oku (point-in-time).

        Args:
            ticker: Hisse kodu
            date: Tarih (YYYY-MM-DD) — bu tarihe kadar olan veriler
            feature_names: İstenen feature'lar (None = tümü)

        Returns:
            Feature dict
        """
        if date not in self._feature_values:
            return {}
        if ticker not in self._feature_values[date]:
            return {}

        features = self._feature_values[date][ticker]

        if feature_names:
            return {k: v for k, v in features.items() if k in feature_names}

        return features

    def get_latest(
        self,
        ticker: str,
        before_date: str,
        feature_names: list[str] | None = None,
    ) -> dict[str, float]:
        """En son feature değerlerini getir (point-in-time).

        Backtest'te kullanılır — gelecek veri sızıntısı yok.

        Args:
            ticker: Hisse kodu
            before_date: Bu tarihten önceki en son veri
            feature_names: İstenen feature'lar

        Returns:
            Feature dict
        """
        # Tarihleri sırala
        dates = sorted([d for d in self._feature_values if d <= before_date])

        if not dates:
            return {}

        latest_date = dates[-1]
        return self.get(ticker, latest_date, feature_names)

    def get_feature_manifest(self, feature_name: str) -> FeatureManifest | None:
        """Feature manifest getir."""
        return self._manifests.get(feature_name)

    def list_features(self, source: str | None = None) -> list[str]:
        """Feature'ları listele."""
        if source:
            return [
                name for name, m in self._manifests.items()
                if m.source == source
            ]
        return list(self._manifests.keys())

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler."""
        total_values = sum(
            len(ticker_features)
            for date_data in self._feature_values.values()
            for ticker_features in date_data.values()
        )

        return {
            "total_features": len(self._manifests),
            "total_dates": len(self._feature_values),
            "total_values": total_values,
            "sources": list(set(m.source for m in self._manifests.values())),
        }

    def save(self, path: str | None = None):
        """Feature store'u dosyaya kaydet."""
        save_path = path or self._store_path
        if not save_path:
            return

        data = {
            "manifests": {k: v.to_dict() for k, v in self._manifests.items()},
            "values": self._feature_values,
            "saved_at": datetime.now(UTC).isoformat(),
        }

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str).decode())

        logger.info("Feature store saved", path=save_path)

    def load(self, path: str | None = None):
        """Feature store'u dosyadan yükle."""
        load_path = path or self._store_path
        if not load_path or not Path(load_path).exists():
            return

        try:
            with open(load_path) as f:
                data = orjson.loads(f.read())

            # Manifest'leri yükle
            for name, m_dict in data.get("manifests", {}).items():
                self._manifests[name] = FeatureManifest(**m_dict)

            # Değerleri yükle
            self._feature_values = data.get("values", {})

            logger.info("Feature store loaded", path=load_path)
        except Exception as e:
            logger.warning("Failed to load feature store", path=load_path, error=str(e))


    def __del__(self):
        """Auto-save on garbage collection."""
        try:
            if self._store_path and (self._manifests or self._feature_values):
                self.save()
        except Exception as e:
            logger.debug("feature_store_autosave_failed", error=str(e))

    def shutdown(self):
        """Explicit save and cleanup."""
        try:
            if self._store_path:
                self.save()
                logger.info("Feature store shutdown complete", path=self._store_path)
        except Exception as e:
            logger.warning("Feature store shutdown failed", error=str(e))


# Singleton
feature_store = FeatureStore()
