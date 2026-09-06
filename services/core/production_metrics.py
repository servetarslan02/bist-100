"""ALPHA BIST — Production Metrics v1.0

Yapılandırılmış, yüksek performanslı ve hafif üretim metrikleri toplayıcısı.
Harici Prometheus bağımlılığı olmadan bellek içi (in-memory) sayaç, gösterge ve histogram yönetimi sağlar.
Thread-safe (RLock), DuckDB kalıcı snapshot kaydı ve Polars analitik dışa aktarımı destekler.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Modül Sabitleri
DEFAULT_HISTOGRAM_MAXLEN: Final[int] = 1000
DEFAULT_METRICS_DUCKDB_PATH: Final[str] = "data/production_metrics.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(
    conn: duckdb.DuckDBPyConnection,
    checkpoint_threshold: str = DEFAULT_CHECKPOINT_SIZE,
    wal_autocheckpoint: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB WAL boyutunu optimize eder."""
    try:
        conn.execute(f"SET checkpoint_threshold = '{checkpoint_threshold}';")
        conn.execute(f"SET wal_autocheckpoint = '{wal_autocheckpoint}';")
    except Exception as e:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(e))


class ProductionMetrics:
    """Üretim ortamı metrik toplayıcısı.

    Sayaçlar (counters), göstergeler (gauges) ve histogramlar (histograms)
    reentrant kilit (RLock) ile iş parçacığı güvenli biçimde yönetilir.
    """

    def __init__(self, duckdb_path: str = DEFAULT_METRICS_DUCKDB_PATH) -> None:
        self._lock = threading.RLock()
        self._duckdb_path = duckdb_path
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=DEFAULT_HISTOGRAM_MAXLEN))
        self._last_reset: float = time.time()

    @otel_trace("production_metrics.inc")
    def inc(self, name: str, value: float = 1.0, labels: dict[str, Any] | None = None) -> None:
        """Belirtilen sayaç değerini artırır.

        Args:
            name: Metrik adı.
            value: Artış miktarı (varsayılan: 1.0).
            labels: İsteğe bağlı etiket sözlüğü.
        """
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    @otel_trace("production_metrics.set_gauge")
    def set_gauge(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        """Belirtilen gösterge (gauge) değerini günceller.

        Args:
            name: Metrik adı.
            value: Yeni anlık sayısal değer.
            labels: İsteğe bağlı etiket sözlüğü.
        """
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value

    @otel_trace("production_metrics.observe")
    def observe(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        """Histogram için yeni bir gözlem değeri ekler.

        Args:
            name: Metrik adı.
            value: Gözlenen sayısal değer (süre, gecikme vb.).
            labels: İsteğe bağlı etiket sözlüğü.
        """
        key = self._key(name, labels)
        with self._lock:
            self._histograms[key].append(value)

    def timer(self, name: str, labels: dict[str, Any] | None = None) -> _Timer:
        """Kod bloklarının çalışma süresini otomatik ölçen context manager döndürür.

        Args:
            name: Histogram metrik adı.
            labels: İsteğe bağlı etiket sözlüğü.

        Returns:
            _Timer bağlam yöneticisi.
        """
        return _Timer(self, name, labels)

    @otel_trace("production_metrics.get_all")
    def get_all(self) -> dict[str, Any]:
        """Tüm metriklerin özet anlık görüntüsünü döndürür."""
        with self._lock:
            result: dict[str, Any] = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {},
                "uptime_seconds": round(time.time() - self._last_reset, 1),
            }
            for key, values in self._histograms.items():
                if values:
                    val_list = sorted(values)
                    n = len(val_list)
                    result["histograms"][key] = {
                        "count": n,
                        "mean": round(sum(val_list) / n, 4),
                        "min": round(val_list[0], 4),
                        "max": round(val_list[-1], 4),
                        "p50": round(val_list[n // 2], 4),
                        "p95": round(val_list[int(n * 0.95)], 4) if n >= 20 else round(val_list[-1], 4),
                    }
            return result

    def to_orjson_bytes(self) -> bytes:
        """Tüm metrikleri yüksek hızlı orjson bayt dizisine dönüştürür."""
        return orjson.dumps(self.get_all())

    @otel_trace("production_metrics.reset")
    def reset(self) -> None:
        """Tüm metrikleri sıfırlar."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._last_reset = time.time()
            logger.info("uretim_metrikleri_sifirlandi")

    @staticmethod
    def _key(name: str, labels: dict[str, Any] | None) -> str:
        """Metrik adı ve etiketlerden standart anahtar oluşturur."""
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            return f"{name}{{{label_str}}}"
        return name

    # =====================================================
    # POLARS & DUCKDB ENTEGRASYONU
    # =====================================================

    def export_to_polars(self) -> pl.DataFrame:
        """Metrik verilerini Polars DataFrame olarak dışa aktarır."""
        rows: list[dict[str, Any]] = []
        metrics_data = self.get_all()

        for k, v in metrics_data["counters"].items():
            rows.append({"type": "counter", "name": k, "value": float(v), "extra": ""})

        for k, v in metrics_data["gauges"].items():
            rows.append({"type": "gauge", "name": k, "value": float(v), "extra": ""})

        for k, stats in metrics_data["histograms"].items():
            rows.append(
                {
                    "type": "histogram",
                    "name": k,
                    "value": float(stats["mean"]),
                    "extra": f"p50={stats['p50']},p95={stats['p95']},cnt={stats['count']}",
                }
            )

        if not rows:
            return pl.DataFrame(
                schema={
                    "type": pl.String,
                    "name": pl.String,
                    "value": pl.Float64,
                    "extra": pl.String,
                }
            )
        return pl.from_dicts(rows)

    def save_snapshot_to_duckdb(self, db_path: str | None = None) -> int:
        """Metrik anlık görüntüsünü DuckDB kalıcı tablosuna kaydeder.

        Args:
            db_path: İsteğe bağlı DuckDB veritabanı dosya yolu.

        Returns:
            Kaydedilen metrik satırı sayısı.
        """
        df = self.export_to_polars()
        if df.is_empty():
            return 0

        target_path = db_path or self._duckdb_path
        path_obj = Path(target_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(str(path_obj))
        try:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS production_metrics_snapshots (
                    type VARCHAR,
                    name VARCHAR,
                    value DOUBLE,
                    extra VARCHAR,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.register("tmp_metrics_df", df.to_arrow())
            conn.execute(
                """
                INSERT INTO production_metrics_snapshots (type, name, value, extra)
                SELECT type, name, value, extra
                FROM tmp_metrics_df
                """
            )
            logger.info("uretim_metrikleri_duckdb_kaydedildi", kayit_sayisi=df.height, db_path=str(path_obj))
            return df.height
        finally:
            conn.close()

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        with self._lock:
            return (
                f"ProductionMetrics(counters={len(self._counters)}, "
                f"gauges={len(self._gauges)}, histograms={len(self._histograms)})"
            )


@dataclass(slots=True)
class _Timer:
    """Metrik zamanlama bağlam yöneticisi."""

    metrics: ProductionMetrics
    name: str
    labels: dict[str, Any] | None
    start_time: float = 0.0

    def __enter__(self) -> _Timer:
        """Zaman sayacını başlatır."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Geçen süreyi histogram metriği olarak kaydeder."""
        elapsed = time.time() - self.start_time
        self.metrics.observe(self.name, elapsed, self.labels)


# Pre-defined metric names
class Metrics:
    """Sabit kurumsal metrik isimleri."""

    # Data
    DATA_FETCH_TOTAL = "data_fetch_total"
    DATA_FETCH_ERRORS = "data_fetch_errors"
    DATA_FETCH_LATENCY = "data_fetch_latency_seconds"
    DATA_STALE_COUNT = "data_stale_count"

    # Feature
    FEATURE_CALC_TOTAL = "feature_calc_total"
    FEATURE_CALC_LATENCY = "feature_calc_latency_seconds"
    FEATURE_NAN_COUNT = "feature_nan_count"

    # Model
    MODEL_INFERENCE_TOTAL = "model_inference_total"
    MODEL_INFERENCE_LATENCY = "model_inference_latency_seconds"
    MODEL_CONFIDENCE = "model_confidence"
    MODEL_PREDICTION_STD = "model_prediction_std"

    # Signal
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_DIRECTION_UP = "signal_direction_up"
    SIGNAL_DIRECTION_DOWN = "signal_direction_down"
    SIGNAL_DIRECTION_NEUTRAL = "signal_direction_neutral"

    # Risk
    RISK_CHECK_TOTAL = "risk_check_total"
    RISK_REJECTED = "risk_rejected"
    RISK_REJECTED_REASON = "risk_rejected_reason"

    # Circuit Breaker
    CIRCUIT_STATE = "circuit_breaker_state"
    CIRCUIT_TRIPS = "circuit_breaker_trips"

    # Paper Trading
    PAPER_ORDER_TOTAL = "paper_order_total"
    PAPER_ORDER_FILLED = "paper_order_filled"
    PAPER_ORDER_REJECTED = "paper_order_rejected"
    PAPER_PNL = "paper_pnl"

    # Worker
    WORKER_JOB_TOTAL = "worker_job_total"
    WORKER_JOB_FAILED = "worker_job_failed"
    WORKER_JOB_LATENCY = "worker_job_latency_seconds"

    # DB
    DB_QUERY_TOTAL = "db_query_total"
    DB_QUERY_ERRORS = "db_query_errors"
    DB_POOL_SIZE = "db_pool_size"


# Singleton
production_metrics = ProductionMetrics()


def export_production_metrics_to_polars(metrics: ProductionMetrics = production_metrics) -> pl.DataFrame:
    """ProductionMetrics verisini Polars DataFrame olarak dışa aktarır."""
    return metrics.export_to_polars()


def save_production_metrics_to_duckdb(
    metrics: ProductionMetrics = production_metrics,
    db_path: str = DEFAULT_METRICS_DUCKDB_PATH,
) -> int:
    """ProductionMetrics anlık görüntüsünü DuckDB'ye kalıcı yazar."""
    return metrics.save_snapshot_to_duckdb(db_path=db_path)


__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_HISTOGRAM_MAXLEN",
    "DEFAULT_METRICS_DUCKDB_PATH",
    "DEFAULT_WAL_SIZE",
    "Metrics",
    "ProductionMetrics",
    "configure_duckdb_wal",
    "export_production_metrics_to_polars",
    "production_metrics",
    "save_production_metrics_to_duckdb",
]

