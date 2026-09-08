"""ALPHA BIST — Modeller Arası Başarım Karşılaştırma Motoru (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; geliştirilen tüm makine öğrenimi modellerinin (Şampiyon LightGBM, Challenger
CatBoost ve XGBoost, Derin Öğrenme LSTM vb.) tahmin güçlerini; Bilgi Katsayısı (IC),
Precision@K, Yön Doğruluğu (Hit Rate), Sharpe Oranı, Maksimum Düşüş (Drawdown) ve
Olasılık Kalibrasyon Skoru (Brier Score) üzerinden çok boyutlu olarak karşılaştırır.

Temel Yetenekler:
- IC (Spearman Rank Correlation) ve Parametrik Olmayan Korelasyon Analizi
- Precision@K: En yüksek skora sahip K hissede pozitif getiri isabet oranı
- Risk-Ayarlı Getiri: Sinyal bazlı yıllıklandırılmış Sharpe Oranı ve Max Drawdown
- Kalibrasyon Kalitesi: Brier Score tabanlı olasılık güvenilirlik ölçümü
- Ağırlıklı Bileşik Skor (Composite Score) ile nesnel şampiyon belirleme
- Polars DataFrame üzerinden sonuç ve liderlik tablosu çıktısı (`compare_polars`)
- DuckDB üzerinde SSD korumalı WAL ile karşılaştırma denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve fail-closed mimari
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
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
DEFAULT_TOP_K: Final[int] = 10
DEFAULT_ANNUALIZATION_FACTOR: Final[int] = 252
DEFAULT_DECISION_THRESHOLD: Final[float] = 0.50
DEFAULT_DUCKDB_PATH: Final[str] = "data/model_comparator.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8

# Bileşik skor ağırlıkları
WEIGHT_IC: Final[float] = 0.25
WEIGHT_PRECISION_K: Final[float] = 0.20
WEIGHT_HIT_RATE: Final[float] = 0.15
WEIGHT_SHARPE: Final[float] = 0.15
WEIGHT_CALIBRATION: Final[float] = 0.10
WEIGHT_F1: Final[float] = 0.10
WEIGHT_ACCURACY: Final[float] = 0.05


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
class ModelResult:
    """Tekil model karşılaştırma metrikleri sonuç veri modeli."""

    name: str
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    ic: float = 0.0
    precision_at_k: float = 0.0
    hit_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    calibration_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Metrik sonuçlarını sözlük formatına dönüştürür."""
        return {
            "name": self.name,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "ic": round(self.ic, 4),
            "precision_at_k": round(self.precision_at_k, 4),
            "hit_rate": round(self.hit_rate, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "calibration_score": round(self.calibration_score, 4),
            "composite_score": round(self.composite_score, 4),
        }

    def to_orjson_bytes(self) -> bytes:
        """Metrik sonuçlarını orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelResult:
        """Sözlükten ModelResult nesnesi oluşturur."""
        return cls(
            name=str(data.get("name", "")),
            accuracy=float(data.get("accuracy", 0.0)),
            precision=float(data.get("precision", 0.0)),
            recall=float(data.get("recall", 0.0)),
            f1=float(data.get("f1", 0.0)),
            ic=float(data.get("ic", 0.0)),
            precision_at_k=float(data.get("precision_at_k", 0.0)),
            hit_rate=float(data.get("hit_rate", 0.0)),
            sharpe_ratio=float(data.get("sharpe_ratio", 0.0)),
            max_drawdown=float(data.get("max_drawdown", 0.0)),
            calibration_score=float(data.get("calibration_score", 0.0)),
        )

    @property
    def composite_score(self) -> float:
        """Ağırlıklı bileşik performansı hesaplar [Yüksek = Daha İyi]."""
        # Brier score düşükken iyi olduğu için (1.0 - Brier) kullanılır
        cal_component = max(0.0, 1.0 - self.calibration_score)
        comp = (
            self.ic * WEIGHT_IC
            + self.precision_at_k * WEIGHT_PRECISION_K
            + self.hit_rate * WEIGHT_HIT_RATE
            + self.sharpe_ratio * WEIGHT_SHARPE
            + cal_component * WEIGHT_CALIBRATION
            + self.f1 * WEIGHT_F1
            + self.accuracy * WEIGHT_ACCURACY
        )
        return float(comp)

    def __repr__(self) -> str:
        return (
            f"ModelResult(model='{self.name}', comp_score={self.composite_score:.4f}, "
            f"ic={self.ic:.4f}, p@k={self.precision_at_k:.2f}, sharpe={self.sharpe_ratio:.2f})"
        )


class ModelComparator:
    """Modelleri risk, getiri, yön doğruluğu ve kalibrasyona göre karşılaştıran motor."""

    def __init__(
        self,
        k: int = DEFAULT_TOP_K,
        annualization_factor: int = DEFAULT_ANNUALIZATION_FACTOR,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """ModelComparator nesnesini başlatır.

        Args:
            k: Precision@K için dikkate alınacak en iyi K hisse adedi.
            annualization_factor: Yıllık işlem günü sayısı.
            duckdb_path: Denetim izi DuckDB veritabanı yolu.
        """
        self._lock = threading.RLock()
        self.k = int(k)
        self.annualization_factor = int(annualization_factor)
        self.duckdb_path = duckdb_path

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS model_comparator_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        model_name VARCHAR,
                        composite_score DOUBLE,
                        ic DOUBLE,
                        precision_at_k DOUBLE,
                        hit_rate DOUBLE,
                        sharpe_ratio DOUBLE,
                        max_drawdown DOUBLE,
                        calibration_score DOUBLE
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB comparator denetim tablosu hazirlanamadi", hata=str(exc))

    def compare(
        self,
        models: dict[str, Callable[[np.ndarray], Any]],
        X_test: np.ndarray,
        y_test: np.ndarray,
        returns: np.ndarray | None = None,
        y_prob: dict[str, np.ndarray] | None = None,
    ) -> list[ModelResult]:
        """Tüm modelleri test verisi üzerinde çalıştırıp bileşik skora göre sıralar.

        Args:
            models: `{model_adi: tahmin_fonksiyonu}` sözlüğü.
            X_test: Test öznitelik matrisi.
            y_test: Gerçek hedef değerleri serisi.
            returns: Gerçek yüzde getiriler (Sharpe ve Drawdown için opsiyonel).
            y_prob: `{model_adi: olasilik_dizisi}` kalibrasyon analizi için (opsiyonel).

        Returns:
            Bileşik skora göre azalan sıralı `ModelResult` listesi.
        """
        with self._lock:
            results: list[ModelResult] = []

            for name, predict_fn in models.items():
                try:
                    preds_raw = predict_fn(X_test)
                    preds = np.asarray(preds_raw, dtype=np.float64).reshape(-1)

                    res = self._evaluate_model(
                        name=name,
                        preds=preds,
                        y_test=y_test,
                        returns=returns,
                        probabilities=y_prob.get(name) if y_prob else None,
                    )
                    results.append(res)
                    self._record_audit(res)
                except Exception as ex:
                    logger.warning("Model degerlendirme basarisiz oldu", model=name, hata=str(ex))
                    empty_res = ModelResult(name=name)
                    results.append(empty_res)
                    self._record_audit(empty_res)

            # Bileşik skora göre azalan sırala
            results.sort(key=lambda r: r.composite_score, reverse=True)

            logger.info("Modeller arasi karsilastirma tamamlandi", model_sayisi=len(results))
            return results

    def compare_polars(
        self,
        models: dict[str, Callable[[np.ndarray], Any]],
        X_test: np.ndarray,
        y_test: np.ndarray,
        returns: np.ndarray | None = None,
        y_prob: dict[str, np.ndarray] | None = None,
    ) -> pl.DataFrame:
        """Karşılaştırma sonuçlarını sıralanmış Polars DataFrame liderlik tablosu olarak döndürür.

        Args:
            models: Modeller sözlüğü.
            X_test: Test öznitelik matrisi.
            y_test: Gerçek değerler.
            returns: Getiriler.
            y_prob: Olasılık tahminleri.

        Returns:
            Liderlik tablosu Polars DataFrame'i.
        """
        import polars as pl

        results = self.compare(models, X_test, y_test, returns=returns, y_prob=y_prob)
        if not results:
            return pl.DataFrame()

        records = [r.to_dict() for r in results]
        return pl.DataFrame(records)

    def _evaluate_model(
        self,
        name: str,
        preds: np.ndarray,
        y_test: np.ndarray,
        returns: np.ndarray | None = None,
        probabilities: np.ndarray | None = None,
    ) -> ModelResult:
        """Tek bir modelin tüm metriklerini güvenli biçimde hesaplar."""
        y_arr = np.asarray(y_test, dtype=np.float64).reshape(-1)
        p_arr = np.asarray(preds, dtype=np.float64).reshape(-1)

        # İkili sınıflandırma eşlemesi
        binary_preds = (p_arr > DEFAULT_DECISION_THRESHOLD).astype(int)
        binary_true = (
            (y_arr > DEFAULT_DECISION_THRESHOLD).astype(int)
            if np.max(y_arr) <= 1.0
            else (y_arr > 0.0).astype(int)
        )

        # 1. Doğruluk (Accuracy)
        accuracy = float(np.mean(binary_preds == binary_true)) if len(binary_true) > 0 else 0.0

        # 2. Precision, Recall, F1
        tp = int(np.sum((binary_preds == 1) & (binary_true == 1)))
        fp = int(np.sum((binary_preds == 1) & (binary_true == 0)))
        fn = int(np.sum((binary_preds == 0) & (binary_true == 1)))

        precision = tp / float(tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / float(tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2.0 * precision * recall) / float(precision + recall) if (precision + recall) > 0.0 else 0.0

        # 3. IC (Information Coefficient — Spearman Rank)
        ic = 0.0
        if len(np.unique(p_arr)) > 1 and len(np.unique(y_arr)) > 1:
            try:
                from scipy.stats import spearmanr

                ic_val, _ = spearmanr(p_arr, y_arr)
                ic = float(ic_val) if np.isfinite(ic_val) else 0.0
            except Exception:
                corr = np.corrcoef(p_arr, y_arr)[0, 1]
                ic = float(corr) if np.isfinite(corr) else 0.0

        # 4. Precision@K
        precision_at_k = self._precision_at_k(p_arr, y_arr, self.k)

        # 5. Hit Rate (Yön Doğruluğu)
        hit_rate = self._hit_rate(p_arr, y_arr)

        # 6. Sharpe Ratio
        sharpe_ratio = 0.0
        if returns is not None and len(returns) == len(p_arr):
            sharpe_ratio = self._sharpe_ratio(p_arr, np.asarray(returns, dtype=np.float64).reshape(-1))

        # 7. Max Drawdown
        max_drawdown = 0.0
        if returns is not None and len(returns) == len(p_arr):
            max_drawdown = self._max_drawdown(p_arr, np.asarray(returns, dtype=np.float64).reshape(-1))

        # 8. Calibration Score (Brier Score)
        calibration_score = 0.0
        if probabilities is not None and len(probabilities) == len(y_arr):
            calibration_score = self._calibration_score(
                binary_true, np.asarray(probabilities, dtype=np.float64).reshape(-1)
            )

        return ModelResult(
            name=name,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1=f1,
            ic=ic,
            precision_at_k=precision_at_k,
            hit_rate=hit_rate,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            calibration_score=calibration_score,
        )

    def _precision_at_k(self, preds: np.ndarray, y_test: np.ndarray, k: int) -> float:
        """En yüksek K tahmindeki pozitif getiri isabet oranını hesaplar."""
        n = len(preds)
        if n == 0:
            return 0.0
        eff_k = min(max(1, k), n)

        top_k_indices = np.argsort(preds)[-eff_k:]
        top_k_true = y_test[top_k_indices]
        return float(np.mean(top_k_true > 0.0)) if len(top_k_true) > 0 else 0.0

    def _hit_rate(self, preds: np.ndarray, y_test: np.ndarray) -> float:
        """Tahmin yönü ile gerçekleşen getiri yönünün uyuşma oranını hesaplar."""
        if len(preds) == 0 or len(y_test) == 0:
            return 0.0

        pred_dir = (preds > DEFAULT_DECISION_THRESHOLD).astype(int)
        true_dir = (
            (y_test > DEFAULT_DECISION_THRESHOLD).astype(int)
            if np.max(y_test) <= 1.0
            else (y_test > 0.0).astype(int)
        )
        return float(np.mean(pred_dir == true_dir))

    def _sharpe_ratio(self, preds: np.ndarray, returns: np.ndarray) -> float:
        """Alış (BUY) sinyali verilen örneklemin yıllıklandırılmış Sharpe oranını hesaplar."""
        buy_mask = preds > DEFAULT_DECISION_THRESHOLD
        if not np.any(buy_mask):
            return 0.0

        buy_returns = returns[buy_mask]
        mean_ret = float(np.mean(buy_returns))
        std_ret = float(np.std(buy_returns))

        if std_ret < DEFAULT_EPSILON:
            return 0.0

        sharpe = (mean_ret / std_ret) * np.sqrt(self.annualization_factor)
        return round(float(sharpe), 4)

    def _max_drawdown(self, preds: np.ndarray, returns: np.ndarray) -> float:
        """Alış (BUY) sinyali verilen portföyün kümülatif getirisinden maksimum düşüşü hesaplar."""
        buy_mask = preds > DEFAULT_DECISION_THRESHOLD
        if not np.any(buy_mask):
            return 0.0

        portfolio_returns = returns[buy_mask]
        cumulative = np.cumsum(portfolio_returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max

        max_dd = float(np.min(drawdown)) if len(drawdown) > 0 else 0.0
        return round(abs(max_dd), 4)

    def _calibration_score(self, y_true_binary: np.ndarray, y_prob: np.ndarray) -> float:
        """Olasılık kalibrasyon hatasını (Brier Score) hesaplar [0 = Kusursuz, 1 = Kötü]."""
        mask = np.isfinite(y_true_binary) & np.isfinite(y_prob)
        yt = y_true_binary[mask]
        yp = np.clip(y_prob[mask], 0.0, 1.0)
        if len(yt) == 0:
            return 0.50

        brier = float(np.mean((yp - yt) ** 2))
        return round(brier, 4)

    def _record_audit(self, res: ModelResult) -> None:
        """Karşılaştırma denetim izini DuckDB'ye yazar."""
        try:
            with duckdb.connect(self.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO model_comparator_audit (
                        model_name, composite_score, ic, precision_at_k,
                        hit_rate, sharpe_ratio, max_drawdown, calibration_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        str(res.name),
                        float(res.composite_score),
                        float(res.ic),
                        float(res.precision_at_k),
                        float(res.hit_rate),
                        float(res.sharpe_ratio),
                        float(res.max_drawdown),
                        float(res.calibration_score),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB comparator denetim kaydi atlandi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki model karşılaştırma denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM model_comparator_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        return f"ModelComparator(top_k={self.k}, ann_factor={self.annualization_factor})"


# Singleton
model_comparator = ModelComparator()

__all__: Final[list[str]] = [
    "DEFAULT_ANNUALIZATION_FACTOR",
    "DEFAULT_DECISION_THRESHOLD",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_TOP_K",
    "WEIGHT_ACCURACY",
    "WEIGHT_CALIBRATION",
    "WEIGHT_F1",
    "WEIGHT_HIT_RATE",
    "WEIGHT_IC",
    "WEIGHT_PRECISION_K",
    "WEIGHT_SHARPE",
    "ModelComparator",
    "ModelResult",
    "configure_duckdb_wal",
    "model_comparator",
]
