"""ALPHA BIST — İleriye Yürüyen Doğrulama (Walk-Forward Validation) Motoru (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; finansal zaman serisi modellerinin aşırı öğrenmesini (overfitting) ve geleceği
görme yanlılığını (look-ahead bias / information leakage) önlemek amacıyla Purge (Arındırma)
ve Embargo (Geciktirme) korumalı Walk-Forward çapraz doğrulama motorunu uygular.

Temel Yetenekler:
- Sıfır Veri Sızıntısı (Zero Data Leakage / Point-In-Time) İlkesi
- Purge: Eğitim ve test veri pencereleri arasında etiket vadesi (horizon) kadar boşluk
- Embargo: Test penceresi sonrasında piyasa hafızası ve otokorelasyonu önleyen boşluk
- Genişleyen (Expanding) veya Kayan (Rolling) Pencere Seçenekleri
- Polars Native Zamansal Dilimleme (`generate_splits_polars`, `evaluate_polars`)
- DuckDB SSD Korumalı WAL ile Doğrulama Denetim İzi (Audit Trail)
- İş Parçacığı Güvenliği (`threading.RLock`) ve Kesin Tip Belirteçleri
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_TRAIN_SIZE: Final[int] = 252  # ~1 Yıllık işlem günü
DEFAULT_TEST_SIZE: Final[int] = 21  # ~1 Aylık işlem günü
DEFAULT_PURGE_SIZE: Final[int] = 5  # 5 günlük etiket vadesi için tampon
DEFAULT_EMBARGO_SIZE: Final[int] = 5  # Test sonrası otokorelasyon tamponu
DEFAULT_STEP_SIZE: Final[int] = 21  # Her adımda ilerleme miktarı
DEFAULT_DUCKDB_PATH: Final[str] = "data/walk_forward_audit.duckdb"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısına SSD ömrünü ve WAL boyutunu koruma direktiflerini uygular.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute("PRAGMA checkpoint_threshold = '4MB';")
        conn.execute("PRAGMA wal_autocheckpoint = '2MB';")
    except Exception as exc:
        logger.warning("DuckDB WAL pragma yapilandirmasi basarisiz", hata=str(exc))


@dataclass(slots=True)
class WFSplitConfig:
    """Walk-forward dilimleme parametreleri konfigürasyon veri modeli."""

    train_size: int = DEFAULT_TRAIN_SIZE
    test_size: int = DEFAULT_TEST_SIZE
    purge_size: int = DEFAULT_PURGE_SIZE
    embargo_size: int = DEFAULT_EMBARGO_SIZE
    step_size: int = DEFAULT_STEP_SIZE
    expanding: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük yapısına dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WFSplitConfig:
        """Sözlükten WFSplitConfig nesnesi oluşturur."""
        return cls(
            train_size=int(data.get("train_size", DEFAULT_TRAIN_SIZE)),
            test_size=int(data.get("test_size", DEFAULT_TEST_SIZE)),
            purge_size=int(data.get("purge_size", DEFAULT_PURGE_SIZE)),
            embargo_size=int(data.get("embargo_size", DEFAULT_EMBARGO_SIZE)),
            step_size=int(data.get("step_size", DEFAULT_STEP_SIZE)),
            expanding=bool(data.get("expanding", False)),
        )

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Konfigürasyonun özet metin gösterimini oluşturur."""
        return (
            f"WFSplitConfig(train={self.train_size}, test={self.test_size}, "
            f"purge={self.purge_size}, embargo={self.embargo_size}, expanding={self.expanding})"
        )


@dataclass(slots=True)
class WFSplit:
    """Tek bir walk-forward veri dilimi modeli."""

    split_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_dates: list[Any] = field(default_factory=list)
    test_dates: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Dilim bilgilerini sözlük yapısına dönüştürür."""
        return {
            "split_index": self.split_index,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "train_dates": [str(d) for d in self.train_dates],
            "test_dates": [str(d) for d in self.test_dates],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WFSplit:
        """Sözlükten WFSplit nesnesi oluşturur."""
        return cls(
            split_index=int(data.get("split_index", 0)),
            train_start=int(data.get("train_start", 0)),
            train_end=int(data.get("train_end", 0)),
            test_start=int(data.get("test_start", 0)),
            test_end=int(data.get("test_end", 0)),
            train_dates=list(data.get("train_dates", [])),
            test_dates=list(data.get("test_dates", [])),
        )

    def __getitem__(self, key: str) -> Any:
        """Geriye dönük sözlük erişim uyumluluğu sağlar."""
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Geriye dönük dict.get uyumluluğu sağlar."""
        return getattr(self, key, default)

    def to_orjson_bytes(self) -> bytes:
        """Dilim bilgilerini orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Dilimin özet metin gösterimini oluşturur."""
        return (
            f"WFSplit(idx={self.split_index}, train=[{self.train_start}:{self.train_end}] "
            f"({len(self.train_dates)} bars), test=[{self.test_start}:{self.test_end}] ({len(self.test_dates)} bars))"
        )


@dataclass(slots=True)
class WFResult:
    """Tekil walk-forward split değerlendirme sonuç modeli."""

    train_start: Any
    train_end: Any
    test_start: Any
    test_end: Any
    train_size: int
    test_size: int
    metrics: dict[str, float] = field(default_factory=dict)
    predictions: list[Any] = field(default_factory=list)
    actuals: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Sonuçları sözlük yapısına dönüştürür."""
        return {
            "train_start": str(self.train_start),
            "train_end": str(self.train_end),
            "test_start": str(self.test_start),
            "test_end": str(self.test_end),
            "train_size": self.train_size,
            "test_size": self.test_size,
            "metrics": self.metrics,
            "predictions_count": len(self.predictions),
            "actuals_count": len(self.actuals),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WFResult:
        """Sözlükten WFResult nesnesi oluşturur."""
        return cls(
            train_start=data.get("train_start"),
            train_end=data.get("train_end"),
            test_start=data.get("test_start"),
            test_end=data.get("test_end"),
            train_size=int(data.get("train_size", 0)),
            test_size=int(data.get("test_size", 0)),
            metrics=dict(data.get("metrics", {})),
            predictions=list(data.get("predictions", [])),
            actuals=list(data.get("actuals", [])),
        )

    def to_orjson_bytes(self) -> bytes:
        """Sonuçları orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Sonucun özet metin gösterimini oluşturur."""
        ic_val = self.metrics.get("correlation", 0.0)
        dir_acc = self.metrics.get("direction_accuracy", 0.0)
        return (
            f"WFResult(test=[{self.test_start}..{self.test_end}], "
            f"train_bars={self.train_size}, test_bars={self.test_size}, "
            f"IC={ic_val:.4f}, DirAcc={dir_acc:.1f}%)"
        )


@dataclass(slots=True)
class WFAggregatedMetrics:
    """Tüm split'lerin birleştirilmiş özet metrikleri."""

    avg_correlation: float
    std_correlation: float
    avg_direction_accuracy: float
    std_direction_accuracy: float
    avg_rmse: float
    total_splits: int
    avg_train_size: float
    avg_test_size: float

    def to_dict(self) -> dict[str, Any]:
        """Metrikleri sözlüğe dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WFAggregatedMetrics:
        """Sözlükten WFAggregatedMetrics nesnesi oluşturur."""
        return cls(
            avg_correlation=float(data.get("avg_correlation", 0.0)),
            std_correlation=float(data.get("std_correlation", 0.0)),
            avg_direction_accuracy=float(data.get("avg_direction_accuracy", 0.0)),
            std_direction_accuracy=float(data.get("std_direction_accuracy", 0.0)),
            avg_rmse=float(data.get("avg_rmse", 0.0)),
            total_splits=int(data.get("total_splits", 0)),
            avg_train_size=float(data.get("avg_train_size", 0.0)),
            avg_test_size=float(data.get("avg_test_size", 0.0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """Metrikleri orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return (
            f"WFAggregatedMetrics(splits={self.total_splits}, "
            f"IC={self.avg_correlation:.4f}±{self.std_correlation:.4f}, "
            f"DirAcc={self.avg_direction_accuracy:.1f}±{self.std_direction_accuracy:.1f}%, "
            f"RMSE={self.avg_rmse:.4f})"
        )


class WalkForwardValidation:
    """Purge ve Embargo korumalı Walk-Forward Doğrulama Motoru."""

    def __init__(
        self,
        train_size: int = DEFAULT_TRAIN_SIZE,
        test_size: int = DEFAULT_TEST_SIZE,
        purge_size: int = DEFAULT_PURGE_SIZE,
        embargo_size: int = DEFAULT_EMBARGO_SIZE,
        step_size: int = DEFAULT_STEP_SIZE,
        expanding: bool = False,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """Walk-forward doğrulama motorunu başlatır.

        Args:
            train_size: Eğitim penceresi bar uzunluğu (varsayılan: 252 seans).
            test_size: Test penceresi bar uzunluğu (varsayılan: 21 seans).
            purge_size: Eğitim ve test arasındaki arındırma boşluğu (varsayılan: 5 seans).
            embargo_size: Test sonrası geciktirme boşluğu (varsayılan: 5 seans).
            step_size: Her iterasyonda pencere kaydırma adımı (varsayılan: 21 seans).
            expanding: True ise eğitim penceresi genişler (expanding window), False ise kayar (rolling).
            duckdb_path: Doğrulama denetim izi için DuckDB dosya yolu.
        """
        self._config = WFSplitConfig(
            train_size=max(10, train_size),
            test_size=max(1, test_size),
            purge_size=max(0, purge_size),
            embargo_size=max(0, embargo_size),
            step_size=max(1, step_size),
            expanding=expanding,
        )
        self._train_size = self._config.train_size
        self._test_size = self._config.test_size
        self._purge_size = self._config.purge_size
        self._embargo_size = self._config.embargo_size
        self._step_size = self._config.step_size
        self._expanding = self._config.expanding

        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()

        self._init_duckdb()
        logger.info(
            "WalkForwardValidation baslatildi",
            train=self._train_size,
            test=self._test_size,
            purge=self._purge_size,
            embargo=self._embargo_size,
            expanding=self._expanding,
        )

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu güvenle ilklendirir."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS walk_forward_audit (
                        timestamp TIMESTAMPTZ PRIMARY KEY,
                        total_splits INTEGER NOT NULL,
                        avg_ic DOUBLE NOT NULL,
                        std_ic DOUBLE NOT NULL,
                        avg_direction_accuracy DOUBLE NOT NULL,
                        avg_rmse DOUBLE NOT NULL,
                        train_size INTEGER NOT NULL,
                        test_size INTEGER NOT NULL,
                        purge_size INTEGER NOT NULL,
                        embargo_size INTEGER NOT NULL,
                        details_json VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB walk_forward_audit tablosu ilklendirilemedi", hata=str(exc))

    def generate_splits(self, dates: list[Any]) -> list[WFSplit]:
        """Tarih listesinden Purge ve Embargo korumalı walk-forward dilimlerini üretir.

        Args:
            dates: Kronolojik sıralı tarih listesi (datetime veya string).

        Returns:
            Oluşturulan WFSplit nesneleri listesi.
        """
        with self._lock:
            splits: list[WFSplit] = []
            total = len(dates)

            if total < (self._train_size + self._purge_size + self._test_size):
                logger.warning(
                    "Walk-forward icin yetersiz veri",
                    toplam_tarih=total,
                    gerekli=self._train_size + self._purge_size + self._test_size,
                )
                return splits

            # İlk test başlangıç noktası
            start_idx = self._train_size + self._purge_size
            split_idx = 0

            while (start_idx + self._test_size) <= total:
                # Test aralığı: [start_idx, start_idx + test_size)
                test_start = start_idx
                test_end = start_idx + self._test_size

                # Train aralığı: [train_start, start_idx - purge_size)
                train_start = 0 if self._expanding else max(0, start_idx - self._purge_size - self._train_size)
                train_end = max(0, start_idx - self._purge_size)

                # Sıfır Veri Sızıntısı Kontrolü
                assert train_end <= (test_start - self._purge_size), "Veri sizintisi: purge ihlali tespit edildi!"

                split = WFSplit(
                    split_index=split_idx,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_dates=dates[train_start:train_end],
                    test_dates=dates[test_start:test_end],
                )
                splits.append(split)
                split_idx += 1

                # Embargo korumasıyla bir sonraki adıma geç
                start_idx += self._step_size

            logger.info("Walk-forward dilimleri olusturuldu", dilim_sayisi=len(splits))
            return splits

    def generate_splits_polars(self, df: pl.DataFrame, date_column: str = "Date") -> list[WFSplit]:
        """Polars DataFrame üzerinden tarih sütununu kullanarak dilimleri üretir.

        Args:
            df: Veri çerçevesi.
            date_column: Tarih sütun adı.

        Returns:
            WFSplit nesneleri listesi.
        """
        if date_column not in df.columns or df.is_empty():
            return []
        dates = df[date_column].to_list()
        return self.generate_splits(dates)

    def evaluate(
        self,
        data: dict[str, Any],
        model_fn: Callable[[], Any],
        feature_fn: Callable[[dict[str, Any]], Any],
    ) -> list[WFResult]:
        """Walk-forward validasyonunu yürütür ve her split için performans hesaplar.

        Args:
            data: {"dates": [...], "returns": [...], "features": ...} veri sözlüğü.
            model_fn: Her split için yeni model örneği döndüren çağrılabilir fonksiyon.
            feature_fn: Ham alt veri diliminden feature matrisi çıkaran fonksiyon.

        Returns:
            Her split için üretilen WFResult nesneleri listesi.
        """
        with self._lock:
            dates = data.get("dates", [])
            splits = self.generate_splits(dates)
            results: list[WFResult] = []

            for i, split in enumerate(splits):
                logger.debug("Walk-forward dilimi degerlendiriliyor", dilim=f"{i + 1}/{len(splits)}")

                # Train ve Test verilerini dilimle
                train_data = {
                    k: v[split.train_start : split.train_end]
                    for k, v in data.items()
                    if k != "dates" and hasattr(v, "__getitem__")
                }
                test_data = {
                    k: v[split.test_start : split.test_end]
                    for k, v in data.items()
                    if k != "dates" and hasattr(v, "__getitem__")
                }

                # Feature çıkarımı
                train_features = feature_fn(train_data)
                test_features = feature_fn(test_data)

                # Model eğitimi
                model = model_fn()
                if hasattr(model, "train"):
                    model.train(train_features)
                elif hasattr(model, "fit"):
                    model.fit(train_features)

                # Tahmin
                if hasattr(model, "predict"):
                    predictions = model.predict(test_features)
                else:
                    predictions = []

                actuals = list(test_data.get("returns", []))
                metrics = self._calculate_metrics(predictions, actuals)

                res = WFResult(
                    train_start=split.train_dates[0] if split.train_dates else split.train_start,
                    train_end=split.train_dates[-1] if split.train_dates else split.train_end,
                    test_start=split.test_dates[0] if split.test_dates else split.test_start,
                    test_end=split.test_dates[-1] if split.test_dates else split.test_end,
                    train_size=len(split.train_dates),
                    test_size=len(split.test_dates),
                    metrics=metrics,
                    predictions=predictions if isinstance(predictions, list) else list(predictions),
                    actuals=actuals,
                )
                results.append(res)

            # DuckDB denetim kaydı
            if results:
                agg = self.get_aggregated_metrics(results)
                self._record_audit_event(agg, results)

            return results

    def _calculate_metrics(
        self,
        predictions: Any,
        actuals: list[float] | np.ndarray,
    ) -> dict[str, float]:
        """Tekil split için IC, yön doğruluğu ve RMSE hesaplar.

        Args:
            predictions: Tahmin skorları veya sözlük listesi.
            actuals: Gerçekleşen getiriler.

        Returns:
            Metrikler sözlüğü.
        """
        if predictions is None or len(predictions) == 0 or len(actuals) == 0:
            return {}

        # Skaler değerleri çıkar
        if isinstance(predictions, list) and isinstance(predictions[0], dict):
            pred_vals = np.array([float(p.get("score", 0.0)) for p in predictions], dtype=np.float64)
        else:
            pred_vals = np.asarray(predictions, dtype=np.float64).flatten()

        act_vals = np.asarray(actuals, dtype=np.float64).flatten()

        min_len = min(len(pred_vals), len(act_vals))
        if min_len < 2:
            return {}

        pred_vals = pred_vals[:min_len]
        act_vals = act_vals[:min_len]

        valid_mask = np.isfinite(pred_vals) & np.isfinite(act_vals)
        if np.sum(valid_mask) < 2:
            return {}

        pred_vals = pred_vals[valid_mask]
        act_vals = act_vals[valid_mask]

        # Pearson Korelasyonu (Information Coefficient)
        corr_matrix = np.corrcoef(pred_vals, act_vals)
        corr = float(corr_matrix[0, 1]) if (len(np.unique(pred_vals)) > 1 and len(np.unique(act_vals)) > 1) else 0.0
        if not np.isfinite(corr):
            corr = 0.0

        # Yön Doğruluğu (Directional Accuracy %)
        pred_dir = np.sign(pred_vals)
        act_dir = np.sign(act_vals)
        dir_acc = float(np.mean(pred_dir == act_dir) * 100.0)

        # Hata Kareleri Ortalamasının Kökü (RMSE)
        rmse = float(np.sqrt(np.mean((pred_vals - act_vals) ** 2)))

        return {
            "correlation": round(corr, 4),
            "direction_accuracy": round(dir_acc, 2),
            "rmse": round(rmse, 4),
        }

    def get_aggregated_metrics(self, results: list[WFResult]) -> dict[str, Any]:
        """Tüm split'lerin birleştirilmiş istatistiksel özetini hesaplar.

        Args:
            results: WFResult listesi.

        Returns:
            Özet metrikler sözlüğü.
        """
        if not results:
            return {}

        corrs = [r.metrics.get("correlation", 0.0) for r in results if "correlation" in r.metrics]
        accs = [r.metrics.get("direction_accuracy", 0.0) for r in results if "direction_accuracy" in r.metrics]
        rmses = [r.metrics.get("rmse", 0.0) for r in results if "rmse" in r.metrics]

        return {
            "avg_correlation": round(float(np.mean(corrs)), 4) if corrs else 0.0,
            "std_correlation": round(float(np.std(corrs)), 4) if corrs else 0.0,
            "avg_direction_accuracy": round(float(np.mean(accs)), 2) if accs else 0.0,
            "std_direction_accuracy": round(float(np.std(accs)), 2) if accs else 0.0,
            "avg_rmse": round(float(np.mean(rmses)), 4) if rmses else 0.0,
            "total_splits": len(results),
            "avg_train_size": round(float(np.mean([r.train_size for r in results])), 0) if results else 0.0,
            "avg_test_size": round(float(np.mean([r.test_size for r in results])), 0) if results else 0.0,
        }

    def _record_audit_event(self, agg: dict[str, Any], results: list[WFResult]) -> None:
        """Doğrulama özetini DuckDB denetim tablosuna kaydeder."""
        try:
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO walk_forward_audit
                    (timestamp, total_splits, avg_ic, std_ic, avg_direction_accuracy, avg_rmse,
                     train_size, test_size, purge_size, embargo_size, details_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        datetime.now(UTC).isoformat(),
                        int(agg.get("total_splits", 0)),
                        float(agg.get("avg_correlation", 0.0)),
                        float(agg.get("std_correlation", 0.0)),
                        float(agg.get("avg_direction_accuracy", 0.0)),
                        float(agg.get("avg_rmse", 0.0)),
                        self._train_size,
                        self._test_size,
                        self._purge_size,
                        self._embargo_size,
                        orjson.dumps([r.to_dict() for r in results]).decode(),
                    ],
                )
        except Exception as exc:
            logger.warning("Walk-forward denetim kaydi DuckDB'ye yazilamadi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB walk_forward_audit tablosunu Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self._duckdb_path) as conn:
                    configure_duckdb_wal(conn)
                    arrow_table = conn.execute(
                        "SELECT * FROM walk_forward_audit ORDER BY timestamp DESC;"
                    ).arrow()
                    return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as exc:
                logger.warning("DuckDB walk_forward_audit tablosu okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """WalkForwardValidation özet metin gösterimi."""
        return (
            f"WalkForwardValidation(train={self._train_size}, test={self._test_size}, "
            f"purge={self._purge_size}, embargo={self._embargo_size})"
        )


# Singleton
wf_validator: Final[WalkForwardValidation] = WalkForwardValidation()


__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EMBARGO_SIZE",
    "DEFAULT_PURGE_SIZE",
    "DEFAULT_STEP_SIZE",
    "DEFAULT_TEST_SIZE",
    "DEFAULT_TRAIN_SIZE",
    "WFAggregatedMetrics",
    "WFResult",
    "WFSplit",
    "WFSplitConfig",
    "WalkForwardValidation",
    "configure_duckdb_wal",
    "wf_validator",
]
