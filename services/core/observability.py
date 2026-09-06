"""
ALPHA BIST — Observability & Monitoring v2.0
============================================
Sistem Gözlemlenebilirlik, İzleme ve Teşhis Mimarisi:
- Prometheus Metrikleri (resmi prometheus_client entegrasyonu)
- Dağıtık İzleme (OpenTelemetry API ve yerel güvenli halka arabellek)
- Performans ve Gecikme İzleme (Histogram ve zamanlayıcı context manager)
- Maliyet İzleme (LLM token ve USD harcama takibi)
- Kaynak Yönetimi (psutil tabanlı CPU, RAM ve Disk izleme)
- Yapılandırma Yönetimi (versiyonlu, denetlenebilir ConfigManager)
- Bileşen Sağlık Denetimi (HealthChecker)
- Polars Analitik Dışa Aktarımı (GEMINI.md Kural 2)
"""

from __future__ import annotations

import functools
import os
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Final

import duckdb
import orjson
import polars as pl
import psutil
import structlog
from opentelemetry import trace
from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.observability")


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için SSD koruyucu ve optimize WAL parametrelerini ayarlar."""
    try:
        conn.execute("PRAGMA checkpoint_threshold='4MB'")
        conn.execute("PRAGMA wal_autocheckpoint='2MB'")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def otel_trace(span_name: str) -> Any:
    """Metot veya fonksiyonu OpenTelemetry span içine alan genel dekoratör.

    Args:
        span_name: Span adı.

    Returns:
        Sarmalayıcı fonksiyon.
    """

    def decorator(func: Any) -> Any:
        """Hedef fonksiyonu OTel span ile sarmalar."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Fonksiyon çağrısını span içinde icra eder."""
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# Standart histogram bucket'ları (saniye cinsinden)
DEFAULT_BUCKETS: Final[tuple[float, ...]] = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
DEFAULT_MAX_TRACE_HISTORY: Final[int] = 1000
DEFAULT_MAX_CONFIG_VERSIONS: Final[int] = 500


class PrometheusMetrics:
    """Prometheus uyumlu metrik sistemi — resmi prometheus_client entegrasyonu ile."""

    def __init__(self) -> None:
        """Prometheus metrik koleksiyonunu ve iş parçacığı kilidini ilklendirir."""
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = threading.RLock()

    def _get_or_create_counter(self, name: str, labels: list[str] | None = None) -> Counter:
        """Mevcut Counter'ı döner veya yoksa thread-safe olarak oluşturur."""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name, f"{name} counter", labels or [])
            return self._counters[name]

    def _get_or_create_gauge(self, name: str, labels: list[str] | None = None) -> Gauge:
        """Mevcut Gauge'ı döner veya yoksa thread-safe olarak oluşturur."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name, f"{name} gauge", labels or [])
            return self._gauges[name]

    def _get_or_create_histogram(
        self,
        name: str,
        labels: list[str] | None = None,
        buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> Histogram:
        """Mevcut Histogram'ı döner veya yoksa thread-safe olarak oluşturur."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, f"{name} histogram", labels or [], buckets=buckets)
            return self._histograms[name]

    def inc(self, name: str, value: int = 1, labels: dict[str, str] | None = None) -> None:
        """Belirtilen Counter metriğini artırır.

        Args:
            name: Metrik adı.
            value: Artış miktarı.
            labels: Opsiyonel etiket sözlüğü.
        """
        label_names = list(labels.keys()) if labels else []
        counter = self._get_or_create_counter(name, label_names)
        if labels:
            counter.labels(**labels).inc(value)
        else:
            counter.inc(value)

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Belirtilen Gauge değerini günceller.

        Args:
            name: Metrik adı.
            value: Atanacak sayısal değer.
            labels: Opsiyonel etiket sözlüğü.
        """
        label_names = list(labels.keys()) if labels else []
        gauge = self._get_or_create_gauge(name, label_names)
        val = float(value or 0.0)
        if labels:
            gauge.labels(**labels).set(val)
        else:
            gauge.set(val)

    def observe(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        buckets: tuple[float, ...] | None = None,
    ) -> None:
        """Histogram gözlem kaydı yapar.

        Args:
            name: Metrik adı.
            value: Gözlemlenen değer.
            labels: Opsiyonel etiket sözlüğü.
            buckets: Özel bucket sınırları tuple'ı.
        """
        label_names = list(labels.keys()) if labels else []
        hist = self._get_or_create_histogram(name, label_names, buckets or DEFAULT_BUCKETS)
        val = float(value or 0.0)
        if labels:
            hist.labels(**labels).observe(val)
        else:
            hist.observe(val)

    def timed(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        buckets: tuple[float, ...] | None = None,
    ) -> Any:
        """İşlem süresini ölçen context manager döndürür."""
        label_names = list(labels.keys()) if labels else []
        hist = self._get_or_create_histogram(name, label_names, buckets or DEFAULT_BUCKETS)
        if labels:
            return hist.labels(**labels).time()
        return hist.time()

    def record_api_call(self, endpoint: str, duration_seconds: float, success: bool = True) -> None:
        """API istek süresi ve durumunu kaydeder."""
        status = "success" if success else "failure"
        self.observe("api_latency_seconds", duration_seconds, labels={"endpoint": endpoint, "status": status})
        self.inc("api_requests_total", 1, labels={"endpoint": endpoint, "status": status})

    def record_db_query(self, db_type: str, operation: str, duration_seconds: float) -> None:
        """Veritabanı sorgu süresini kaydeder."""
        self.observe("db_query_duration_seconds", duration_seconds, labels={"db_type": db_type, "operation": operation})

    def record_feature_computation(self, feature_set: str, duration_seconds: float, num_tickers: int = 1) -> None:
        """Özellik (feature) hesaplama süresini ve işlenen hisse adedini kaydeder."""
        self.observe("feature_computation_duration_seconds", duration_seconds, labels={"feature_set": feature_set})
        self.inc("feature_ticks_processed_total", num_tickers, labels={"feature_set": feature_set})

    def record_ml_inference(self, model_name: str, duration_seconds: float, num_samples: int = 1) -> None:
        """ML model tahmin süresini ve örnek adedini kaydeder."""
        self.observe("ml_inference_duration_seconds", duration_seconds, labels={"model_name": model_name})
        self.inc("ml_predictions_total", num_samples, labels={"model_name": model_name})

    def record_cache_access(self, cache_name: str, hit: bool) -> None:
        """Önbellek isabet ve ıskalama durumunu kaydeder."""
        res = "hit" if hit else "miss"
        self.inc("cache_access_total", 1, labels={"cache_name": cache_name, "result": res})

    def record_error(self, component: str, error_type: str) -> None:
        """Hata sayacını artırır."""
        self.inc("system_errors_total", 1, labels={"component": component, "error_type": error_type})

    def get_metrics(self) -> dict[str, Any]:
        """Geriye dönük uyumluluk için dict formatında özet metrikleri döner."""
        with self._lock:
            histograms_dict = {}
            for name, hist in self._histograms.items():
                try:
                    collected = hist.collect()
                    samples = collected[0].samples if collected else []
                    buckets: dict[str, int] = {}
                    count = 0
                    sum_val = 0.0
                    for s in samples:
                        if s.name.endswith("_bucket"):
                            le = s.labels.get("le", "")
                            buckets[le] = int(s.value)
                        elif s.name.endswith("_count"):
                            count = int(s.value)
                        elif s.name.endswith("_sum"):
                            sum_val = float(s.value)
                    histograms_dict[name] = {
                        "count": count,
                        "sum": sum_val,
                        "buckets": buckets,
                    }
                except Exception:
                    histograms_dict[name] = {"count": 0, "sum": 0.0, "buckets": {}}
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": histograms_dict,
            }

    def get_prometheus_text(self) -> str:
        """Prometheus text exposition formatında metrikleri üretir."""
        return generate_latest(REGISTRY).decode("utf-8")

    def __repr__(self) -> str:
        """Metrik koleksiyonunun okunabilir temsili."""
        with self._lock:
            return (
                f"<PrometheusMetrics counters={len(self._counters)} "
                f"gauges={len(self._gauges)} histograms={len(self._histograms)}>"
            )


class DistributedTracing:
    """Dağıtık izleme — OpenTelemetry entegrasyonu ve yerel halka tamponu."""

    def __init__(self, max_history: int = DEFAULT_MAX_TRACE_HISTORY) -> None:
        """Dağıtık izleme yöneticisini ilklendirir."""
        self._tracer = trace.get_tracer(__name__)
        self._history: deque[dict[str, Any]] = deque(maxlen=max_history)
        self._lock = threading.RLock()

    def start_trace(self, operation: str) -> str:
        """Yeni bir izleme span'ı başlatır ve trace kimliğini döndürür.

        Args:
            operation: İşlem adı.

        Returns:
            Hex formatında 32 karakterlik trace_id.
        """
        span = self._tracer.start_span(operation)
        ctx = span.get_span_context()
        trace_id = format(ctx.trace_id, "032x")
        span.set_attribute("status", "started")

        with self._lock:
            self._history.append(
                {
                    "trace_id": trace_id,
                    "operation": operation,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "status": "started",
                }
            )
        return trace_id

    def add_span(
        self,
        trace_id: str,
        operation: str,
        duration_ms: float = 0.0,
        status: str = "completed",
    ) -> None:
        """İzleme geçmişine alt span kaydeder."""
        with self._lock:
            self._history.append(
                {
                    "trace_id": trace_id,
                    "operation": operation,
                    "duration_ms": duration_ms,
                    "status": status,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    def get_trace(self, trace_id: str) -> list[dict[str, Any]]:
        """Belirtilen trace_id'ye ait yerel tampon kayıtlarını döndürür."""
        with self._lock:
            return [t for t in self._history if t["trace_id"] == trace_id]

    def get_spans(self, trace_id: str) -> list[dict[str, Any]]:
        """get_trace için takma ad."""
        return self.get_trace(trace_id)

    def get_recent_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        """En son izleme kayıtlarını döndürür."""
        with self._lock:
            return list(self._history)[-limit:]

    def __repr__(self) -> str:
        """İzleme yöneticisinin metinsel temsili."""
        with self._lock:
            return f"<DistributedTracing local_buffered_traces={len(self._history)}>"


class PerformanceMonitor:
    """Performans ve gecikme izleme yöneticisi."""

    def __init__(self) -> None:
        """Performans izleyicisini ilklendirir."""
        self._latencies: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=1000))
        self._lock = threading.RLock()

    @otel_trace("observability.PerformanceMonitor.record_latency")
    def record_latency(self, operation: str, latency_ms: float) -> None:
        """İşlem gecikmesini yerel tampona ve Prometheus'a kaydeder."""
        val = max(0.0, float(latency_ms or 0.0))
        with self._lock:
            self._latencies[operation].append(val)
        prometheus_metrics.observe("operation_latency_seconds", val / 1000.0, labels={"operation": operation})

    @otel_trace("observability.PerformanceMonitor.get_stats")
    def get_stats(self, operation: str) -> dict[str, float]:
        """Belirtilen operasyon için yerel gecikme istatistiklerini hesaplar."""
        with self._lock:
            vals = list(self._latencies.get(operation, []))
        if not vals:
            return {"count": 0.0, "avg_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}

        import numpy as np

        arr = np.array(vals)
        return {
            "count": float(len(arr)),
            "avg_ms": float(np.mean(arr)),
            "p95_ms": float(np.percentile(arr, 95)),
            "p99_ms": float(np.percentile(arr, 99)),
        }

    @otel_trace("observability.PerformanceMonitor.get_all_stats")
    def get_all_stats(self) -> dict[str, dict[str, float]]:
        """Tüm kayıtlı operasyonların gecikme özetlerini döndürür."""
        with self._lock:
            ops = list(self._latencies.keys())
        return {op: self.get_stats(op) for op in ops}

    def __repr__(self) -> str:
        """Performans izleyicisinin metinsel temsili."""
        with self._lock:
            return f"<PerformanceMonitor tracked_operations={len(self._latencies)}>"


class CostMonitor:
    """LLM ve harici API maliyet izleyicisi."""

    def __init__(self) -> None:
        """Maliyet izleme yöneticisini ilklendirir."""
        self._total_cost: float = 0.0
        self._by_model: dict[str, float] = defaultdict(float)
        self._lock = threading.RLock()

    @otel_trace("observability.CostMonitor.record")
    def record(self, provider: str, model: str, tokens: int, cost_usd: float) -> None:
        """Model kullanım maliyetini ve token adedini kaydeder."""
        c = max(0.0, float(cost_usd or 0.0))
        t = max(0, int(tokens or 0))
        with self._lock:
            self._total_cost += c
            self._by_model[model] += c

        prometheus_metrics.inc("llm_tokens_total", t, labels={"provider": provider, "model": model})
        prometheus_metrics.inc("llm_cost_usd_total", c, labels={"provider": provider, "model": model})
        prometheus_metrics.set_gauge("llm_cost_usd_cumulative", self._total_cost)

    @otel_trace("observability.CostMonitor.get_summary")
    def get_summary(self) -> dict[str, Any]:
        """Kümülatif maliyet ve model bazlı harcama özetini döndürür."""
        with self._lock:
            return {
                "total_cost_usd": self._total_cost,
                "by_model": dict(self._by_model),
            }

    def __repr__(self) -> str:
        """Maliyet yöneticisinin metinsel temsili."""
        with self._lock:
            return f"<CostMonitor total_cost_usd=${self._total_cost:.4f}>"


class ResourceMonitor:
    """Sistem ve süreç kaynak kullanımı izleyicisi (psutil tabanlı)."""

    def __init__(self) -> None:
        """Kaynak izleyicisini ilklendirir."""
        self._process = psutil.Process(os.getpid())
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    @otel_trace("observability.ResourceMonitor.start_background_monitoring")
    def start_background_monitoring(self, interval_seconds: int = 60) -> None:
        """Arka plan periyodik donanım izleme iş parçacığını başlatır."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._monitor_loop,
                args=(interval_seconds,),
                daemon=True,
                name="ResourceMonitorThread",
            )
            self._thread.start()
            logger.info("kaynak_izleme_arkaplan_baslatildi", aralik_sn=interval_seconds)

    @otel_trace("observability.ResourceMonitor.stop_background_monitoring")
    def stop_background_monitoring(self) -> None:
        """Arka plan kaynak izleme iş parçacığını durdurur."""
        with self._lock:
            self._running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._thread = None
            logger.info("kaynak_izleme_arkaplan_durduruldu")

    def _monitor_loop(self, interval: int) -> None:
        """Periyodik izleme döngüsü."""
        while self._running:
            try:
                self.snapshot()
            except Exception as e:
                logger.error("kaynak_izleme_dongu_hatasi", hata=str(e))
            time.sleep(interval)

    @otel_trace("observability.ResourceMonitor.snapshot")
    def snapshot(
        self,
        cpu_pct: float = 0.0,
        memory_mb: float = 0.0,
        gpu_pct: float = 0.0,
        disk_mb: float = 0.0,
    ) -> None:
        """Gerçek donanım kullanım verilerini okur ve Prometheus metriklerine yazar."""
        try:
            actual_cpu = self._process.cpu_percent(interval=None)
            actual_mem = self._process.memory_info().rss / (1024 * 1024)

            prometheus_metrics.set_gauge("process_cpu_percent", actual_cpu)
            prometheus_metrics.set_gauge("process_memory_mb", actual_mem)

            # Windows ve Linux uyumlu kök dizin kontrolü
            root_path = Path.cwd().anchor or "/"
            disk = psutil.disk_usage(root_path)
            prometheus_metrics.set_gauge("system_disk_used_percent", disk.percent)
        except Exception as exc:
            logger.warning("kaynak_metrik_kayit_hatasi", hata=str(exc))

    @otel_trace("observability.ResourceMonitor.get_current")
    def get_current(self) -> dict[str, Any]:
        """Anlık CPU, bellek ve disk kullanım değerlerini döndürür."""
        try:
            cpu = self._process.cpu_percent(interval=None)
            mem = self._process.memory_info().rss / (1024 * 1024)
            root_path = Path.cwd().anchor or "/"
            disk = psutil.disk_usage(root_path)
            return {
                "cpu_pct": cpu,
                "memory_mb": mem,
                "disk_used_percent": disk.percent,
                "gpu_pct": 0.0,
            }
        except Exception as exc:
            logger.warning("kaynak_anlik_durum_okuma_hatasi", hata=str(exc))
            return {"cpu_pct": 0.0, "memory_mb": 0.0, "disk_used_percent": 0.0, "gpu_pct": 0.0}

    def __repr__(self) -> str:
        """Kaynak izleyicisinin metinsel temsili."""
        return f"<ResourceMonitor running={self._running} pid={self._process.pid}>"


class ConfigManager:
    """Denetlenebilir ve versiyonlu dinamik konfigürasyon yöneticisi."""

    def __init__(self) -> None:
        """Konfigürasyon yöneticisini ve varsayılan parametrelerini ilklendirir."""
        self._config: dict[str, Any] = {}
        self._versions: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._defaults: dict[str, Any] = {
            "risk.max_position_pct": 10.0,
            "risk.max_sector_pct": 30.0,
            "risk.max_drawdown_pct": 15.0,
            "risk.daily_loss_limit_pct": 5.0,
            "ml.retrain_interval_hours": 168,
            "llm.context_size": 8192,
            "market.open_hour": "10:00",
            "market.close_hour": "18:00",
        }

    @otel_trace("observability.ConfigManager.get")
    def get(self, key: str, default: Any = None) -> Any:
        """Belirtilen anahtara ait değeri döner."""
        with self._lock:
            return self._config.get(key, self._defaults.get(key, default))

    @otel_trace("observability.ConfigManager.set")
    def set(self, key: str, value: Any, actor: str = "system", reason: str = "") -> None:
        """Konfigürasyon parametresini günceller ve değişiklik geçmişine kaydeder."""
        with self._lock:
            old_value = self._config.get(key)
            self._config[key] = value

            self._versions.append(
                {
                    "key": key,
                    "old": str(old_value),
                    "new": str(value),
                    "raw_value": value,
                    "actor": actor,
                    "reason": reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            if len(self._versions) > DEFAULT_MAX_CONFIG_VERSIONS:
                self._versions = self._versions[-DEFAULT_MAX_CONFIG_VERSIONS:]

        logger.info("konfigurasyon_guncellendi", key=key, old=old_value, new=value, actor=actor)

    @otel_trace("observability.ConfigManager.get_history")
    def get_history(self, key: str) -> list[dict[str, Any]]:
        """Belirtilen anahtara ait tüm değişiklik tarihçesini döndürür."""
        with self._lock:
            return [v for v in self._versions if v["key"] == key]

    @otel_trace("observability.ConfigManager.get_all")
    def get_all(self) -> dict[str, Any]:
        """Tüm varsayılan ve üzerine yazılmış parametreleri birleştirerek döndürür."""
        with self._lock:
            result = dict(self._defaults)
            result.update(self._config)
            return result

    @otel_trace("observability.ConfigManager.rollback")
    def rollback(self, key: str, actor: str = "self_healing") -> bool:
        """Belirtilen anahtara ait değeri bir önceki geçerli sürüme otomatik geri alır.

        Self-healing ve hata onarımı için kullanılır.

        Args:
            key: Geri alınacak konfigürasyon anahtarı.
            actor: İşlemi gerçekleştiren aktör.

        Returns:
            Geri alma başarılı ise True, önceki sürüm yoksa False.
        """
        with self._lock:
            key_history = [v for v in self._versions if v["key"] == key]
            if len(key_history) < 2:
                # Önceki sürüm yoksa ve varsayılanlarda varsa varsayılana dön
                if key in self._config:
                    del self._config[key]
                    logger.info("konfigurasyon_varsayilana_donduruldu", key=key, actor=actor)
                    return True
                return False

            prev_entry = key_history[-2]
            prev_value = prev_entry.get("raw_value", prev_entry["new"])
            self._config[key] = prev_value
            self._versions.append(
                {
                    "key": key,
                    "old": str(key_history[-1]["new"]),
                    "new": str(prev_value),
                    "raw_value": prev_value,
                    "actor": actor,
                    "reason": "self_healing_rollback",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            logger.info("konfigurasyon_geri_alindi", key=key, new_value=prev_value, actor=actor)
            return True

    def to_orjson_bytes(self) -> bytes:
        """Tüm konfigürasyonu C seviyesinde yüksek hızlı orjson bayt dizisine serileştirir."""
        with self._lock:
            return orjson.dumps(self.get_all(), option=orjson.OPT_SORT_KEYS)

    def export_history_to_polars(self) -> pl.DataFrame:
        """Konfigürasyon değişiklik tarihçesini Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            items = list(self._versions)

        schema = {
            "key": pl.String,
            "old": pl.String,
            "new": pl.String,
            "actor": pl.String,
            "reason": pl.String,
            "timestamp": pl.String,
        }
        if not items:
            return pl.DataFrame(schema=schema)

        return pl.DataFrame(items, schema=schema)

    def __repr__(self) -> str:
        """Konfigürasyon yöneticisinin metinsel temsili."""
        with self._lock:
            return f"<ConfigManager active_overrides={len(self._config)} history_records={len(self._versions)}>"


class HealthChecker:
    """Sistem bileşenlerinin sağlık kontrolü ve teyit yöneticisi."""

    def __init__(self) -> None:
        """Sağlık kontrol yöneticisini ilklendirir."""
        self._components: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    @otel_trace("observability.HealthChecker.register")
    def register(self, component: str, check_fn: Any = None) -> None:
        """İzlenecek yeni bir sistem bileşeni kaydeder."""
        with self._lock:
            self._components[component] = {
                "status": "UNKNOWN",
                "last_check": None,
                "check_fn": check_fn,
                "recovery_fn": None,
                "details": "",
            }

    def register_recovery_action(self, component: str, recovery_fn: Callable[[], bool]) -> None:
        """Bileşen arızalandığında otomatik onarımı tetikleyecek self-healing fonksiyonunu kaydeder.

        Args:
            component: Bileşen adı.
            recovery_fn: Başarı durumunda True dönen onarım fonksiyonu.
        """
        with self._lock:
            if component not in self._components:
                self.register(component)
            self._components[component]["recovery_fn"] = recovery_fn
        logger.info("self_healing_onarim_eylemi_kaydedildi", bilesen=component)

    @otel_trace("observability.HealthChecker.trigger_self_healing")
    def trigger_self_healing(self, component: str) -> bool:
        """Arızalı bileşen için self-healing kurtarma sürecini tetikler.

        Args:
            component: Kurtarılacak bileşen adı.

        Returns:
            Kurtarma başarılıysa True, kurtarma fonksiyonu yoksa veya başarısızsa False.
        """
        with self._lock:
            comp = self._components.get(component)
            if not comp or not comp.get("recovery_fn"):
                logger.warning("self_healing_eylemi_bulunamadi", bilesen=component)
                return False
            recovery_fn = comp["recovery_fn"]

        try:
            logger.info("self_healing_onarim_baslatiliyor", bilesen=component)
            success = bool(recovery_fn())
            if success:
                self.update_status(component, "HEALTHY", details="Self-healing onarımı başarıyla tamamlandı")
                logger.info("self_healing_onarimi_basarili", bilesen=component)
                return True
            else:
                self.update_status(component, "FAILED", details="Self-healing onarımı başarısız oldu")
                logger.error("self_healing_onarimi_basarisiz", bilesen=component)
                return False
        except Exception as exc:
            self.update_status(component, "FAILED", details=f"Self-healing istisnası: {exc}")
            logger.error("self_healing_istisnasi", bilesen=component, hata=str(exc))
            return False

    @otel_trace("observability.HealthChecker.update_status")
    def update_status(self, component: str, status: str, details: str = "") -> None:
        """Bileşenin sağlık durumunu günceller ve Prometheus gauge'ını ayarlar."""
        with self._lock:
            if component not in self._components:
                self.register(component)

            self._components[component]["status"] = status
            self._components[component]["details"] = details
            self._components[component]["last_check"] = datetime.now(UTC).isoformat()

        status_val = 1 if status == "HEALTHY" else 0
        prometheus_metrics.set_gauge("component_health_status", status_val, labels={"component": component})

    @otel_trace("observability.HealthChecker.check_all")
    def check_all(self) -> dict[str, Any]:
        """Kayıtlı tüm bileşenlerin güncel durumunu denetler ve genel sistem durumunu üretir."""
        results = {}
        overall = "HEALTHY"

        with self._lock:
            for name, comp in self._components.items():
                results[name] = {
                    "status": comp["status"],
                    "details": comp.get("details", ""),
                    "last_check": comp.get("last_check"),
                }
                if comp["status"] in ("FAILED", "UNHEALTHY"):
                    overall = "UNHEALTHY"
                elif comp["status"] == "DEGRADED" and overall != "UNHEALTHY":
                    overall = "DEGRADED"

        return {
            "overall": overall,
            "components": results,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def to_orjson_bytes(self) -> bytes:
        """Tüm bileşen sağlık durumlarını C seviyesinde orjson bayt dizisine serileştirir."""
        with self._lock:
            return orjson.dumps(self.check_all(), option=orjson.OPT_SORT_KEYS)

    def export_health_to_polars(self) -> pl.DataFrame:
        """Bileşen sağlık durumlarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            items = [
                {
                    "component": name,
                    "status": info["status"],
                    "details": info.get("details", ""),
                    "last_check": info.get("last_check") or "",
                    "checked_at": datetime.now(UTC).isoformat(),
                }
                for name, info in self._components.items()
            ]

        schema = {
            "component": pl.String,
            "status": pl.String,
            "details": pl.String,
            "last_check": pl.String,
            "checked_at": pl.String,
        }
        if not items:
            return pl.DataFrame(schema=schema)

        return pl.DataFrame(items, schema=schema)

    def __repr__(self) -> str:
        """Sağlık yöneticisinin metinsel temsili."""
        with self._lock:
            return f"<HealthChecker registered_components={len(self._components)}>"


# Singletons
prometheus_metrics: Final[PrometheusMetrics] = PrometheusMetrics()
distributed_tracing: Final[DistributedTracing] = DistributedTracing()
performance_monitor: Final[PerformanceMonitor] = PerformanceMonitor()
cost_monitor: Final[CostMonitor] = CostMonitor()
resource_monitor: Final[ResourceMonitor] = ResourceMonitor()
config_manager: Final[ConfigManager] = ConfigManager()
health_checker: Final[HealthChecker] = HealthChecker()


def export_observability_metrics_to_polars() -> pl.DataFrame:
    """Tüm metrik özetlerini Polars DataFrame olarak dışa aktarır."""
    data = prometheus_metrics.get_metrics()
    records = []
    ts = datetime.now(UTC).isoformat()

    for name in data.get("counters", {}):
        records.append({"type": "counter", "name": name, "value": 1.0, "timestamp": ts})
    for name in data.get("gauges", {}):
        records.append({"type": "gauge", "name": name, "value": 1.0, "timestamp": ts})
    for name, info in data.get("histograms", {}).items():
        records.append({"type": "histogram_count", "name": name, "value": float(info.get("count", 0)), "timestamp": ts})

    schema = {
        "type": pl.String,
        "name": pl.String,
        "value": pl.Float64,
        "timestamp": pl.String,
    }
    if not records:
        return pl.DataFrame(schema=schema)

    return pl.DataFrame(records, schema=schema)


DEFAULT_OBSERVABILITY_DB_PATH: Final[str] = "data/observability.duckdb"


def save_observability_snapshot_to_duckdb(
    db_path: str = DEFAULT_OBSERVABILITY_DB_PATH,
) -> None:
    """Anlık metrik ve bileşen sağlık durumunu DuckDB tablosuna atomik olarak kaydeder.

    SSD koruması ve optimize WAL parametreleri ile çalışır.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    try:
        configure_duckdb_wal(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observability_metrics_snapshot (
                metric_type VARCHAR,
                metric_name VARCHAR,
                metric_value DOUBLE,
                recorded_at VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS component_health_snapshot (
                component VARCHAR,
                status VARCHAR,
                details VARCHAR,
                last_check VARCHAR,
                recorded_at VARCHAR
            )
            """
        )

        df_metrics = export_observability_metrics_to_polars()
        if df_metrics.height > 0:
            conn.register("tmp_metrics", df_metrics.to_arrow())
            conn.execute(
                """
                INSERT INTO observability_metrics_snapshot
                SELECT type, name, value, timestamp FROM tmp_metrics
                """
            )
            conn.unregister("tmp_metrics")

        df_health = health_checker.export_health_to_polars()
        if df_health.height > 0:
            conn.register("tmp_health", df_health.to_arrow())
            conn.execute(
                """
                INSERT INTO component_health_snapshot
                SELECT component, status, details, last_check, checked_at FROM tmp_health
                """
            )
            conn.unregister("tmp_health")
        conn.commit()
        logger.info("observability_snapshot_duckdb_kaydedildi", db_path=str(path))
    finally:
        conn.close()


__all__: Final[list[str]] = [
    "DEFAULT_BUCKETS",
    "DEFAULT_MAX_CONFIG_VERSIONS",
    "DEFAULT_MAX_TRACE_HISTORY",
    "DEFAULT_OBSERVABILITY_DB_PATH",
    "ConfigManager",
    "CostMonitor",
    "DistributedTracing",
    "HealthChecker",
    "PerformanceMonitor",
    "PrometheusMetrics",
    "ResourceMonitor",
    "config_manager",
    "configure_duckdb_wal",
    "cost_monitor",
    "distributed_tracing",
    "export_observability_metrics_to_polars",
    "health_checker",
    "otel_trace",
    "performance_monitor",
    "prometheus_metrics",
    "resource_monitor",
    "save_observability_snapshot_to_duckdb",
]
