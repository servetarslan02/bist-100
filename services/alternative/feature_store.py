"""
ALPHA BIST — Feature Store Integration v2.0

Alternative data feature'ları için kurumsal feature store entegrasyonu.

Özellikler:
- Feature versioning ve manifest yönetimi
- Point-in-time correctness (PIT — geleceğe sızıntısız backtest)
- Thread-safe operasyonlar (RLock)
- DuckDB analitik ve kalıcılık entegrasyonu (SQLite yasaktır)
- Context manager desteği (with FeatureStore(...) as fs:)
- Polars DataFrame çıktısı desteği
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "FeatureManifest",
    "FeatureStore",
    "feature_store",
]


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

    def to_dict(self) -> dict[str, Any]:
        """Manifest'i sözlük formatına çevir."""
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

    def to_json(self) -> str:
        """Manifest'i JSON formatına çevir."""
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        return (
            f"FeatureManifest(name={self.feature_name!r}, version={self.version!r}, "
            f"source={self.source!r}, dtype={self.dtype!r})"
        )


class FeatureStore:
    """Feature store — feature versioning, point-in-time correctness ve DuckDB kalıcılığı.

    Özellikler:
    - Her feature için manifest (metadata)
    - Feature versioning (v1, v2, ...)
    - Point-in-time sorgu (backtest'te gelecek veri sızıntısı yok)
    - Thread-safe (RLock)
    - DuckDB entegrasyonu
    """

    def __init__(self, store_path: str | None = None, duckdb_path: str | None = None):
        """Feature store başlat.

        Args:
            store_path: Kalıcı JSON depolama dosya yolu (opsiyonel).
            duckdb_path: DuckDB veritabanı dosya yolu (opsiyonel).
        """
        self._store_path = store_path
        self._duckdb_path = duckdb_path
        self._manifests: dict[str, FeatureManifest] = {}
        self._feature_values: dict[str, dict[str, dict[str, float]]] = {}  # date → ticker → features
        self._lock = threading.RLock()

    def __enter__(self) -> FeatureStore:
        """Context manager girişi."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager çıkışı: Otomatik kalıcı kayıt."""
        self.shutdown()

    def register_feature(self, manifest: FeatureManifest) -> None:
        """Feature manifest'ini kaydet."""
        with self._lock:
            self._manifests[manifest.feature_name] = manifest
        logger.debug("Feature registered", name=manifest.feature_name, version=manifest.version)

    def put(
        self,
        ticker: str,
        date: str,
        features: dict[str, float],
        source: str = "alternative",
    ) -> None:
        """Feature değerleri yaz.

        Args:
            ticker: Hisse kodu.
            date: Tarih (YYYY-MM-DD).
            features: Feature değerleri.
            source: Kaynak adı.
        """
        if not ticker or not date or not features:
            return

        ticker_clean = ticker.upper().strip()
        with self._lock:
            if date not in self._feature_values:
                self._feature_values[date] = {}
            if ticker_clean not in self._feature_values[date]:
                self._feature_values[date][ticker_clean] = {}

            self._feature_values[date][ticker_clean].update(features)

            # Manifest'leri otomatik oluştur
            for name in features:
                if name not in self._manifests:
                    self._manifests[name] = FeatureManifest(
                        feature_name=name,
                        version="v1",
                        source=source,
                        description=f"Auto-registered from {source}",
                        dtype="float",
                        range_min=-1000.0,
                        range_max=1000.0,
                    )

        # Opsiyonel DuckDB sync
        if self._duckdb_path:
            self.export_to_duckdb(self._duckdb_path)

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
        ticker_clean = ticker.upper().strip()
        with self._lock:
            if date not in self._feature_values or ticker_clean not in self._feature_values[date]:
                return {}

            features = self._feature_values[date][ticker_clean].copy()

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
        with self._lock:
            dates = sorted([d for d in self._feature_values if d <= before_date])

        if not dates:
            return {}

        latest_date = dates[-1]
        return self.get(ticker, latest_date, feature_names)

    def get_feature_manifest(self, feature_name: str) -> FeatureManifest | None:
        """Feature manifest getir."""
        with self._lock:
            return self._manifests.get(feature_name)

    def list_features(self, source: str | None = None) -> list[str]:
        """Feature'ları listele."""
        with self._lock:
            if source:
                return [name for name, m in self._manifests.items() if m.source == source]
            return list(self._manifests.keys())

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler."""
        with self._lock:
            total_values = sum(
                len(ticker_features)
                for date_data in self._feature_values.values()
                for ticker_features in date_data.values()
            )
            features_cnt = len(self._manifests)
            dates_cnt = len(self._feature_values)
            sources = list({m.source for m in self._manifests.values()})

        return {
            "total_features": features_cnt,
            "total_dates": dates_cnt,
            "total_values": total_values,
            "sources": sources,
        }

    def export_to_duckdb(self, db_path: str = "data/alternative_feature_store.duckdb") -> None:
        """Tüm kayıtlı feature verilerini yerel DuckDB tablosuna aktar."""
        with self._lock:
            rows: list[tuple[str, str, str, float]] = []
            for d, t_map in self._feature_values.items():
                for t, f_map in t_map.items():
                    for fname, fval in f_map.items():
                        rows.append((d, t, fname, float(fval)))

        if not rows:
            return

        try:
            import duckdb

            db_file = Path(db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)

            con = duckdb.connect(str(db_file))
            try:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pit_features (
                        date VARCHAR,
                        ticker VARCHAR,
                        feature_name VARCHAR,
                        feature_value DOUBLE,
                        PRIMARY KEY (date, ticker, feature_name)
                    )
                    """
                )
                con.executemany(
                    """
                    INSERT OR REPLACE INTO pit_features (date, ticker, feature_name, feature_value)
                    VALUES (?, ?, ?, ?)
                    """,
                    rows,
                )
                logger.info("FeatureStore exported to DuckDB", rows=len(rows), db_path=str(db_file))
            finally:
                con.close()
        except Exception as e:
            logger.error("DuckDB export failed for FeatureStore", error=str(e))

    def save(self, path: str | None = None) -> None:
        """Feature store'u dosyaya kaydet.

        Args:
            path: Kayıt dosya yolu (None ise store_path kullanılır).
        """
        save_path = path or self._store_path
        if not save_path:
            return

        with self._lock:
            data = {
                "manifests": {k: v.to_dict() for k, v in self._manifests.items()},
                "values": self._feature_values,
                "saved_at": datetime.now(UTC).isoformat(),
            }

        try:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))

            logger.info("Feature store saved", path=save_path)
        except Exception as e:
            logger.error("Feature store save failed", path=save_path, error=str(e))

    def load(self, path: str | None = None) -> None:
        """Feature store'u dosyadan yükle.

        Args:
            path: Yükleme dosya yolu (None ise store_path kullanılır).
        """
        load_path = path or self._store_path
        if not load_path or not Path(load_path).exists():
            return

        try:
            with open(load_path, "rb") as f:
                data = orjson.loads(f.read())

            with self._lock:
                # Manifest'leri yükle
                for name, m_dict in data.get("manifests", {}).items():
                    self._manifests[name] = FeatureManifest(**m_dict)

                # Değerleri yükle
                self._feature_values = data.get("values", {})

            logger.info("Feature store loaded", path=load_path)
        except Exception as e:
            logger.warning("Failed to load feature store", path=load_path, error=str(e))

    def shutdown(self) -> None:
        """Feature store'u güvenli şekilde kapat ve kaydet."""
        try:
            if self._store_path:
                self.save()
            if self._duckdb_path:
                self.export_to_duckdb(self._duckdb_path)
            logger.info("Feature store shutdown complete")
        except Exception as e:
            logger.warning("Feature store shutdown failed", error=str(e))

    def __repr__(self) -> str:
        with self._lock:
            feats = len(self._manifests)
            dates = len(self._feature_values)
        return f"FeatureStore(manifests={feats}, dates={dates}, store_path={self._store_path!r})"


# Singleton
feature_store = FeatureStore()
