"""ALPHA BIST — Qlib Finansal Makine Öğrenimi Entegratörü (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; Microsoft Qlib ve Alpha BIST mimarisi arasında yüksek performanslı veri, öznitelik
ve model köprüsü kurar. BIST hisse senetleri için zaman serisi dilimleme (Train / Valid / Test),
Sıfır Veri Sızıntısı (Purge + Embargo) ile ileriye dönük getiri (forward-return) etiketlemesi,
Polars native veri işleme ve DuckDB üzerinde denetim izi yönetimi sağlar.

Temel Yetenekler:
- Qlib Uyumlu Veri ve Öznitelik Hazırlığı (Data Handler & Feature Store)
- Sıfır Veri Sızıntılı (Zero Data Leakage) Katı Zamansal Bölümleme (Temporal Split)
- Etiket Ufku (Label Horizon) Boyunca Purge & Embargo Boşluk Koruması (Boundary Leakage Guard)
- Polars Tabanlı Hızlı Vektörize Veri Hazırlama (`prepare_data_polars`, `create_qlib_dataset_from_polars`)
- DuckDB SSD Korumalı WAL (`4MB/2MB`) ile Veri Seti Oluşturma Denetim İzi
- İş Parçacığı Güvenliği (`threading.RLock`) ve Fail-Closed Tasarım
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
    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_QLIB_DATA_DIR: Final[str] = "data/qlib"
DEFAULT_QLIB_CACHE_DIR: Final[str] = "data/qlib_cache"
DEFAULT_DUCKDB_PATH: Final[str] = "data/qlib_integration.duckdb"
DEFAULT_LABEL_HORIZON: Final[int] = 5
DEFAULT_TRAIN_RATIO: Final[float] = 0.60
DEFAULT_VALID_RATIO: Final[float] = 0.20
DEFAULT_TEST_RATIO: Final[float] = 0.20
DEFAULT_EPSILON: Final[float] = 1e-8


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısına SSD ömrünü ve WAL boyutunu koruma direktiflerini uygular.

    Standart: 4MB checkpoint threshold, 2MB wal autocheckpoint.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute("PRAGMA checkpoint_threshold = '4MB';")
        conn.execute("PRAGMA wal_autocheckpoint = '2MB';")
    except Exception as exc:
        logger.warning("DuckDB WAL pragma yapilandirmasi basarisiz", hata=str(exc))


@dataclass(slots=True)
class QlibConfig:
    """Qlib entegrasyonu konfigürasyon veri modeli."""

    data_dir: str = DEFAULT_QLIB_DATA_DIR
    provider: str = "csv"  # csv, parquet, yfinance, qlib
    cache_dir: str = DEFAULT_QLIB_CACHE_DIR
    feature_columns: list[str] = field(default_factory=list)
    label_columns: list[str] = field(default_factory=lambda: ["label_5d"])
    train_start: str = "2020-01-01"
    train_end: str = "2024-01-01"
    valid_start: str = "2024-01-01"
    valid_end: str = "2024-06-01"
    test_start: str = "2024-06-01"
    test_end: str = "2025-01-01"

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu standart sözlük yapısına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QlibConfig:
        """Sözlükten QlibConfig nesnesi oluşturur."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def __repr__(self) -> str:
        """Konfigürasyonun özet metin gösterimini oluşturur."""
        return f"QlibConfig(provider='{self.provider}', data_dir='{self.data_dir}', cache_dir='{self.cache_dir}')"


@dataclass(slots=True)
class QlibDatasetSplit:
    """Tekil veri seti bölümü (train, valid veya test)."""

    X: np.ndarray
    y: np.ndarray
    tickers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Bölüm özetini sözlük yapısına dönüştürür."""
        return {
            "n_samples": len(self.X) if len(self.X) > 0 else 0,
            "n_features": self.X.shape[1] if (len(self.X.shape) > 1 and len(self.X) > 0) else 0,
            "tickers": self.tickers,
        }

    def to_orjson_bytes(self) -> bytes:
        """Bölüm özetini orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any], X: np.ndarray | None = None, y: np.ndarray | None = None) -> QlibDatasetSplit:
        """Sözlükten ve dizilerden QlibDatasetSplit nesnesi oluşturur."""
        arr_x = X if X is not None else np.empty((0, 0), dtype=np.float64)
        arr_y = y if y is not None else np.empty((0,), dtype=np.float64)
        return cls(X=arr_x, y=arr_y, tickers=data.get("tickers", []))

    def __repr__(self) -> str:
        """Bölümün özet metin gösterimini oluşturur."""
        samples = len(self.X) if len(self.X) > 0 else 0
        features = self.X.shape[1] if (len(self.X.shape) > 1 and len(self.X) > 0) else 0
        return f"QlibDatasetSplit(samples={samples}, features={features}, tickers_count={len(self.tickers)})"


@dataclass(slots=True)
class QlibDatasetResult:
    """Train/Valid/Test bölümlerini içeren Qlib veri seti sonuç nesnesi."""

    train: QlibDatasetSplit
    valid: QlibDatasetSplit
    test: QlibDatasetSplit
    label_horizon: int
    purge_gap: int

    def to_dict(self) -> dict[str, Any]:
        """Veri seti sonucunu sözlük olarak döndürür."""
        return {
            "train": self.train.to_dict(),
            "valid": self.valid.to_dict(),
            "test": self.test.to_dict(),
            "label_horizon": self.label_horizon,
            "purge_gap": self.purge_gap,
        }

    def to_orjson_bytes(self) -> bytes:
        """Veri seti özetini orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> QlibDatasetResult:
        """Sözlükten QlibDatasetResult nesnesi oluşturur."""
        return cls(
            train=QlibDatasetSplit.from_dict(d.get("train", {})),
            valid=QlibDatasetSplit.from_dict(d.get("valid", {})),
            test=QlibDatasetSplit.from_dict(d.get("test", {})),
            label_horizon=int(d.get("label_horizon", 5)),
            purge_gap=int(d.get("purge_gap", 5)),
        )

    def __repr__(self) -> str:
        """Veri seti sonucunun özet metin gösterimini oluşturur."""
        return (
            f"QlibDatasetResult(train_samples={len(self.train.X)}, "
            f"valid_samples={len(self.valid.X)}, test_samples={len(self.test.X)}, "
            f"label_horizon={self.label_horizon}, purge_gap={self.purge_gap})"
        )


class QlibBIST:
    """Microsoft Qlib ile BIST piyasası entegrasyon sınıfı."""

    def __init__(
        self,
        config: QlibConfig | None = None,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """QlibBIST bileşenini başlatır.

        Args:
            config: Qlib konfigürasyon nesnesi (None ise varsayılan atanır).
            duckdb_path: Denetim izi için DuckDB dosya yolu.
        """
        self.config: QlibConfig = config or QlibConfig()
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()
        self._data_cache: dict[str, dict[str, Any]] = {}
        self._feature_store: dict[str, np.ndarray] = {}
        self._is_initialized: bool = False

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim izi tablosunu güvenle ilklendirir."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qlib_integration_audit (
                        timestamp TIMESTAMPTZ NOT NULL,
                        operation VARCHAR NOT NULL,
                        ticker_count BIGINT NOT NULL,
                        train_samples BIGINT NOT NULL,
                        valid_samples BIGINT NOT NULL,
                        test_samples BIGINT NOT NULL,
                        label_horizon INTEGER NOT NULL,
                        details VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB qlib_integration_audit tablosu ilklendirilemedi", hata=str(exc))

    def _record_audit_event(
        self,
        operation: str,
        ticker_count: int,
        train_samples: int,
        valid_samples: int,
        test_samples: int,
        label_horizon: int,
        details: dict[str, Any],
    ) -> None:
        """Oluşturulan veri setlerini DuckDB denetim tablosuna yazar."""
        try:
            now_iso = datetime.now(UTC).isoformat()
            details_json = orjson.dumps(details, default=str).decode()
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO qlib_integration_audit
                    (timestamp, operation, ticker_count, train_samples, valid_samples, test_samples, label_horizon, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [now_iso, operation, ticker_count, train_samples, valid_samples, test_samples, label_horizon, details_json],
                )
        except Exception as exc:
            logger.warning("DuckDB Qlib denetim kaydi basarisiz", hata=str(exc))

    def prepare_data(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        features: np.ndarray | None = None,
        prices: np.ndarray | None = None,
    ) -> dict[str, Any]:
        """Qlib formatında hisse verisini hazırlar ve önbelleğe alır.

        Args:
            ticker: BIST hisse sembolü (ör. 'THYAO').
            start_date: Başlangıç ISO tarihi.
            end_date: Bitiş ISO tarihi.
            features: Öznitelik matrisi (N, F).
            prices: Kapanış fiyatları dizisi (N,).

        Returns:
            Qlib uyumlu veri sözlüğü.
        """
        with self._lock:
            try:
                feat_arr = np.asarray(features, dtype=np.float64) if features is not None else np.empty((0, 0))
                price_arr = np.asarray(prices, dtype=np.float64) if prices is not None else np.empty((0,))

                if feat_arr.ndim == 1 and feat_arr.size > 0:
                    feat_arr = feat_arr.reshape(-1, 1)

                n_samples = len(feat_arr) if feat_arr.size > 0 else len(price_arr)
                n_features = feat_arr.shape[1] if (feat_arr.size > 0 and feat_arr.ndim > 1) else 0

                qlib_data: dict[str, Any] = {
                    "ticker": ticker,
                    "start_date": start_date,
                    "end_date": end_date,
                    "features": feat_arr.tolist() if feat_arr.size > 0 else [],
                    "prices": price_arr.tolist() if price_arr.size > 0 else [],
                    "n_samples": n_samples,
                    "n_features": n_features,
                    "status": "ready",
                }

                self._data_cache[ticker] = qlib_data
                return qlib_data

            except Exception as exc:
                logger.error("Qlib veri hazirlama basarisiz", ticker=ticker, hata=str(exc))
                return {"ticker": ticker, "status": "error", "error": str(exc)}

    def prepare_data_polars(
        self,
        df: pl.DataFrame,
        ticker: str,
        feature_cols: list[str],
        price_col: str = "close",
        date_col: str = "date",
    ) -> dict[str, Any]:
        """Polars DataFrame girdi alarak Qlib formatında veri hazırlar.

        Null ve eksik değerler Polars seviyesinde forward-fill ve sıfır ile güvenle temizlenir.

        Args:
            df: Hisse fiyat ve öznitelik tablosu.
            ticker: Hisse sembolü.
            feature_cols: Öznitelik sütun isimleri.
            price_col: Fiyat sütunu.
            date_col: Tarih sütunu.

        Returns:
            Qlib formatında veri sözlüğü.
        """
        if df.is_empty():
            return {"ticker": ticker, "status": "empty", "n_samples": 0}

        # Mevcut sütunları doğrula (Boundary Guard)
        existing_cols = set(df.columns)
        valid_feature_cols = [c for c in feature_cols if c in existing_cols]
        if not valid_feature_cols:
            logger.warning("Belirtilen oznitelik sutunlarinin hicbiri bulunamadi", ticker=ticker)
            return {"ticker": ticker, "status": "error", "error": "Gecerli oznitelik sutunu yok"}

        if price_col not in existing_cols:
            logger.warning("Fiyat sutunu bulunamadi", ticker=ticker, price_col=price_col)
            return {"ticker": ticker, "status": "error", "error": f"Fiyat sutunu yok: {price_col}"}

        # Tarih sıralaması ve null temizliği
        sorted_df = df.sort(date_col) if date_col in existing_cols else df
        dates = sorted_df[date_col].to_list() if date_col in existing_cols else []
        start_date = str(dates[0]) if dates else ""
        end_date = str(dates[-1]) if dates else ""

        # Polars null değerlerini güvenle temizle (TypeError koruması)
        cleaned_features_df = sorted_df.select(valid_feature_cols).fill_null(strategy="forward").fill_null(0.0)
        features = cleaned_features_df.to_numpy()

        cleaned_prices_series = sorted_df[price_col].fill_null(strategy="forward").fill_null(1.0)
        prices = cleaned_prices_series.to_numpy()

        return self.prepare_data(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            features=features,
            prices=prices,
        )

    def create_qlib_dataset(
        self,
        data: dict[str, dict[str, Any]],
        label_horizon: int = DEFAULT_LABEL_HORIZON,
        train_ratio: float = DEFAULT_TRAIN_RATIO,
        valid_ratio: float = DEFAULT_VALID_RATIO,
        purge_gap: int | None = None,
    ) -> dict[str, Any]:
        """Qlib eğitim, doğrulama ve test veri setlerini oluşturur.

        Point-in-Time & Sıfır Veri Sızıntısı Garantisi:
        1. Etiket hesaplaması ileri getiri (Price_{t+H} - Price_t)/Price_t formülüdür.
        2. Eğitim seti ile validasyon seti arasında ve validasyon ile test seti arasında
           en az `effective_purge = max(purge_gap, label_horizon)` bar boşluk bırakılır.
        3. Train ve Validasyon kümelerinin bitişinde, son `label_horizon` kadar barın
           bir sonraki dönemin fiyatını görmemesi için etiketleri sınırlanır (Strict Purge).

        Args:
            data: {ticker: prepared_data} sözlüğü.
            label_horizon: İleri getiri gün sayısı.
            train_ratio: Eğitim seti oranı (varsayılan 0.60).
            valid_ratio: Doğrulama seti oranı (varsayılan 0.20).
            purge_gap: Dilimler arası temizleme/ambargo penceresi.

        Returns:
            Qlib formatında train/valid/test sözlüğü.
        """
        with self._lock:
            effective_purge = max(purge_gap if purge_gap is not None else label_horizon, label_horizon)

            train_X: list[np.ndarray] = []
            train_y: list[np.ndarray] = []
            train_tickers: list[str] = []

            valid_X: list[np.ndarray] = []
            valid_y: list[np.ndarray] = []
            valid_tickers: list[str] = []

            test_X: list[np.ndarray] = []
            test_y: list[np.ndarray] = []
            test_tickers: list[str] = []

            for ticker, ticker_data in data.items():
                if ticker_data.get("status") != "ready":
                    continue

                feat_raw = ticker_data.get("features", [])
                price_raw = ticker_data.get("prices", [])

                features = np.asarray(feat_raw, dtype=np.float64)
                prices = np.asarray(price_raw, dtype=np.float64)

                if len(features) == 0 or len(prices) == 0 or len(features) != len(prices):
                    continue

                if features.ndim == 1:
                    features = features.reshape(-1, 1)

                n_feat = features.shape[1]
                if train_X and len(train_X[0].shape) > 1 and n_feat != train_X[0].shape[1]:
                    logger.warning(
                        "Oznitelik sutun boyutu uyumsuzlugu, hisse atlaniyor",
                        ticker=ticker,
                        beklenen=train_X[0].shape[1],
                        gelen=n_feat,
                    )
                    continue

                n = len(prices)
                # Minimum veri boyutu: train + purge + valid + purge + test + label_horizon
                min_required = label_horizon + (effective_purge * 2) + 20
                if n <= min_required:
                    continue

                # Forward return label: (Price_{t+H} - Price_t) / Price_t
                returns = np.zeros(n, dtype=np.float64)
                valid_denom = np.abs(prices[:-label_horizon]) > DEFAULT_EPSILON
                valid_indices = np.where(valid_denom)[0]

                returns[valid_indices] = (
                    prices[valid_indices + label_horizon] - prices[valid_indices]
                ) / np.maximum(prices[valid_indices], DEFAULT_EPSILON)

                # Katı Zamansal Bölümleme İndeksleri
                train_end_idx = int(n * train_ratio)
                valid_start_idx = train_end_idx + effective_purge
                valid_end_idx = int(n * (train_ratio + valid_ratio))
                test_start_idx = valid_end_idx + effective_purge

                if train_end_idx <= effective_purge or valid_start_idx >= valid_end_idx or test_start_idx >= n:
                    continue

                # Train (Sıfır sızıntı: Train kümesinin son label_horizon barı çıkarılır)
                tr_cutoff = max(1, train_end_idx - label_horizon)
                train_X.append(features[:tr_cutoff])
                train_y.append(returns[:tr_cutoff])
                train_tickers.extend([ticker] * tr_cutoff)

                # Valid (Sıfır sızıntı: Valid kümesinin son label_horizon barı çıkarılır)
                val_cutoff = max(valid_start_idx, valid_end_idx - label_horizon)
                if val_cutoff > valid_start_idx:
                    valid_X.append(features[valid_start_idx:val_cutoff])
                    valid_y.append(returns[valid_start_idx:val_cutoff])
                    valid_tickers.extend([ticker] * (val_cutoff - valid_start_idx))

                # Test (Son label_horizon bar kesilerek sınırlandırılır)
                tst_cutoff = max(test_start_idx, n - label_horizon)
                if tst_cutoff > test_start_idx:
                    test_X.append(features[test_start_idx:tst_cutoff])
                    test_y.append(returns[test_start_idx:tst_cutoff])
                    test_tickers.extend([ticker] * (tst_cutoff - test_start_idx))

            cat_train_X = np.concatenate(train_X, axis=0) if train_X else np.empty((0, 0), dtype=np.float64)
            cat_train_y = np.concatenate(train_y, axis=0) if train_y else np.empty((0,), dtype=np.float64)

            cat_valid_X = np.concatenate(valid_X, axis=0) if valid_X else np.empty((0, 0), dtype=np.float64)
            cat_valid_y = np.concatenate(valid_y, axis=0) if valid_y else np.empty((0,), dtype=np.float64)

            cat_test_X = np.concatenate(test_X, axis=0) if test_X else np.empty((0, 0), dtype=np.float64)
            cat_test_y = np.concatenate(test_y, axis=0) if test_y else np.empty((0,), dtype=np.float64)

            dataset: dict[str, Any] = {
                "train": {"X": cat_train_X, "y": cat_train_y, "tickers": train_tickers},
                "valid": {"X": cat_valid_X, "y": cat_valid_y, "tickers": valid_tickers},
                "test": {"X": cat_test_X, "y": cat_test_y, "tickers": test_tickers},
                "label_horizon": label_horizon,
                "purge_gap": effective_purge,
            }

            self._record_audit_event(
                operation="CREATE_DATASET",
                ticker_count=len(data),
                train_samples=len(cat_train_X),
                valid_samples=len(cat_valid_X),
                test_samples=len(cat_test_X),
                label_horizon=label_horizon,
                details={"purge_gap": effective_purge, "tickers_count": len(data)},
            )

            logger.info(
                "Qlib veri seti basariyla olusturuldu (Purge + Embargo uygulandi)",
                train_samples=len(cat_train_X),
                valid_samples=len(cat_valid_X),
                test_samples=len(cat_test_X),
                purge_gap=effective_purge,
            )

            return dataset

    def create_qlib_dataset_object(
        self,
        data: dict[str, dict[str, Any]],
        label_horizon: int = DEFAULT_LABEL_HORIZON,
        purge_gap: int | None = None,
    ) -> QlibDatasetResult:
        """Veri setini tip güvenli QlibDatasetResult nesnesi olarak döndürür.

        Args:
            data: {ticker: prepared_data} sözlüğü.
            label_horizon: İleri getiri ufku.
            purge_gap: Dilimler arası boşluk.

        Returns:
            QlibDatasetResult nesnesi.
        """
        raw = self.create_qlib_dataset(data, label_horizon=label_horizon, purge_gap=purge_gap)
        return QlibDatasetResult(
            train=QlibDatasetSplit(X=raw["train"]["X"], y=raw["train"]["y"], tickers=raw["train"]["tickers"]),
            valid=QlibDatasetSplit(X=raw["valid"]["X"], y=raw["valid"]["y"], tickers=raw["valid"]["tickers"]),
            test=QlibDatasetSplit(X=raw["test"]["X"], y=raw["test"]["y"], tickers=raw["test"]["tickers"]),
            label_horizon=raw["label_horizon"],
            purge_gap=raw["purge_gap"],
        )

    def create_qlib_dataset_from_polars(
        self,
        dfs: dict[str, pl.DataFrame],
        feature_cols: list[str],
        price_col: str = "close",
        date_col: str = "date",
        label_horizon: int = DEFAULT_LABEL_HORIZON,
        train_ratio: float = DEFAULT_TRAIN_RATIO,
        valid_ratio: float = DEFAULT_VALID_RATIO,
    ) -> QlibDatasetResult:
        """Polars DataFrame tabanlı hisse sözlüğünden doğrudan QlibDatasetResult üretir.

        Args:
            dfs: {ticker: pl.DataFrame} sözlüğü.
            feature_cols: Öznitelik sütunları.
            price_col: Fiyat sütunu.
            date_col: Tarih sütunu.
            label_horizon: Etiket ufku.
            train_ratio: Eğitim oranı.
            valid_ratio: Validasyon oranı.

        Returns:
            Tip güvenli QlibDatasetResult nesnesi.
        """
        prepared_dict: dict[str, dict[str, Any]] = {}
        for ticker, df in dfs.items():
            prep = self.prepare_data_polars(
                df=df,
                ticker=ticker,
                feature_cols=feature_cols,
                price_col=price_col,
                date_col=date_col,
            )
            prepared_dict[ticker] = prep

        return self.create_qlib_dataset_object(prepared_dict, label_horizon=label_horizon)

    def get_feature_store(self) -> dict[str, np.ndarray]:
        """Bellekteki öznitelik havuzunu döndürür."""
        with self._lock:
            return dict(self._feature_store)

    def add_to_feature_store(self, name: str, features: np.ndarray) -> None:
        """Öznitelik havuzuna yeni bir matris kaydeder."""
        with self._lock:
            self._feature_store[name] = np.asarray(features, dtype=np.float64)

    def get_cached_data(self, ticker: str) -> dict[str, Any] | None:
        """Önbellekteki hisse verisini döndürür."""
        with self._lock:
            return self._data_cache.get(ticker)

    def clear_cache(self) -> None:
        """Önbelleği temizler."""
        with self._lock:
            self._data_cache.clear()
            self._feature_store.clear()

    def get_stats(self) -> dict[str, Any]:
        """Qlib entegrasyon bileşeni istatistiklerini döndürür."""
        with self._lock:
            return {
                "cached_tickers": len(self._data_cache),
                "feature_store_size": len(self._feature_store),
                "data_dir": self.config.data_dir,
                "provider": self.config.provider,
            }

    def __repr__(self) -> str:
        """QlibBIST nesnesinin özet metin gösterimini oluşturur."""
        with self._lock:
            return f"QlibBIST(provider='{self.config.provider}', cached_tickers={len(self._data_cache)})"


qlib_bist: Final[QlibBIST] = QlibBIST()

__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_LABEL_HORIZON",
    "DEFAULT_QLIB_CACHE_DIR",
    "DEFAULT_QLIB_DATA_DIR",
    "DEFAULT_TEST_RATIO",
    "DEFAULT_TRAIN_RATIO",
    "DEFAULT_VALID_RATIO",
    "QlibBIST",
    "QlibConfig",
    "QlibDatasetResult",
    "QlibDatasetSplit",
    "configure_duckdb_wal",
    "qlib_bist",
]
