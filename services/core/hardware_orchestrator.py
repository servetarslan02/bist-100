"""ALPHA BIST — Donanım ve Kaynak Orkestrasyon Motoru (Hardware Orchestrator).

Bu modül, platformun GPU, RAM, CPU ve SSD donanım kaynaklarını dinamik olarak denetler,
makine öğrenmesi (LightGBM, CatBoost, XGBoost, PyTorch) modelleri için optimal işlemci
ve bellek parametrelerini belirler; SSD aşınmasını ve G/Ç darboğazını önlemek için
tamponlu toplu yazıcı (SSDThrottledWriter) sağlar.

Donanım Rol Dağılım Mimarisi:
1. GPU (NVIDIA CUDA / Tensor Core / TF32):
   - Derin Öğrenme modelleri (Transformer, LSTM, MLP) çıkarım ve eğitimi.
   - CatBoost ve XGBoost GPU ağaç hızlandırması (Histogram GPU).
   - PyTorch TF32 matmul ve cuDNN benchmark kernel optimizasyonu.
2. RAM (In-Memory Veri İşleme):
   - Gerçek zamanlı dairesel veri tamponları (In-Memory Circular Buffer).
   - DuckDB in-process analitik hesaplama katmanı.
3. CPU (Çoklu Çekirdek & Asenkron Yürütme):
   - Event Bus, emir ve risk kuralları, BIST devre kesici kontrolleri.
   - LightGBM şampiyon model çoklu iş parçacığı (n_jobs) paralelleştirmesi.
4. SSD (NVMe Depolama ve I/O Ömür Koruyucu):
   - Hız sınırlı ve tamponlu blok yazıcı (Rate-Limited Batch Flusher).
   - Her tick'te doğrudan diske gitmek yerine RAM'de toplayıp blok halinde flush etme.
"""

from __future__ import annotations

import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from types import TracebackType

import duckdb
import orjson
import polars as pl
import psutil
import structlog

from services.core.otel import otel_trace

try:
    import torch

    HAS_TORCH = True
except ImportError:
    torch = None
    HAS_TORCH = False

logger = structlog.get_logger(__name__)

# ==============================================================================
# Standart Donanım ve Tamponlama Sabitleri
# ==============================================================================

DEFAULT_FLUSH_INTERVAL_SEC: float = 5.0
DEFAULT_MAX_BUFFER_SIZE: int = 5000
DEFAULT_HARDWARE_AUDIT_DB_PATH: str = "data/hardware_audit.duckdb"
DEFAULT_PROFILE_CACHE_TTL_SEC: float = 1.0
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


# ==============================================================================
# Veri Modelleri
# ==============================================================================


@dataclass(slots=True)
class HardwareProfile:
    """Sistem donanım profili ve anlık kaynak durum modeli.

    Attributes:
        device_type: Aktif işlem cihazı ('cuda' veya 'cpu').
        gpu_name: Grafik işlemci adı veya 'N/A'.
        gpu_vram_gb: Toplam GPU VRAM miktarı (GB).
        cuda_version: CUDA sürüm numarası veya None.
        total_ram_gb: Toplam sistem belleği (GB).
        available_ram_gb: Kullanılabilir boş sistem belleği (GB).
        cpu_cores: Mantıksal CPU çekirdek sayısı.
        ssd_free_gb: Boş SSD depolama alanı (GB).
        ssd_write_buffer_enabled: SSD yazma tamponu aktif mi.
        timestamp: Profil alma zaman damgası (ISO 8601 UTC).
    """

    device_type: str
    gpu_name: str
    gpu_vram_gb: float
    cuda_version: str | None
    total_ram_gb: float
    available_ram_gb: float
    cpu_cores: int
    ssd_free_gb: float
    ssd_write_buffer_enabled: bool
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return {
            "device_type": self.device_type,
            "gpu_name": self.gpu_name,
            "gpu_vram_gb": self.gpu_vram_gb,
            "cuda_version": self.cuda_version,
            "total_ram_gb": self.total_ram_gb,
            "available_ram_gb": self.available_ram_gb,
            "cpu_cores": self.cpu_cores,
            "ssd_free_gb": self.ssd_free_gb,
            "ssd_write_buffer_enabled": self.ssd_write_buffer_enabled,
            "timestamp": self.timestamp,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HardwareProfile:
        """Sözlükten HardwareProfile nesnesi üretir.

        Args:
            data: Anahtar-değer donanım profili sözlüğü.

        Returns:
            HardwareProfile: Örnek nesnesi.
        """
        return cls(
            device_type=str(data.get("device_type", "cpu")),
            gpu_name=str(data.get("gpu_name", "N/A")),
            gpu_vram_gb=float(data.get("gpu_vram_gb", 0.0)),
            cuda_version=data.get("cuda_version"),
            total_ram_gb=float(data.get("total_ram_gb", 0.0)),
            available_ram_gb=float(data.get("available_ram_gb", 0.0)),
            cpu_cores=int(data.get("cpu_cores", 1)),
            ssd_free_gb=float(data.get("ssd_free_gb", 0.0)),
            ssd_write_buffer_enabled=bool(data.get("ssd_write_buffer_enabled", False)),
            timestamp=str(data.get("timestamp", datetime.now(UTC).isoformat())),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> HardwareProfile:
        """JSON dizesi veya baytından HardwareProfile nesnesi üretir."""
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"HardwareProfile(cihaz='{self.device_type}', gpu='{self.gpu_name}', "
            f"vram={self.gpu_vram_gb:.1f}GB, ram_bosta={self.available_ram_gb:.1f}GB, "
            f"cpu_cekirdek={self.cpu_cores}, ssd_bosta={self.ssd_free_gb:.1f}GB)"
        )


# ==============================================================================
# SSD Hız Sınırı ve Tamponlu Yazıcı
# ==============================================================================


class SSDThrottledWriter:
    """SSD I/O Hız Sınırı ve Tamponlu Blok Yazıcı (Rate-Limited Batch Flusher).

    Diske sürekli ufak yazmalar yaparak SSD'yi yıpratmak ve G/Ç darboğazı yaratmak yerine,
    kayıtları RAM kuyruğunda biriktirir ve belirlenen aralıklarla (flush_interval_sec)
    veya kuyruk dolduğunda tek seferde blok halinde diske yazar.
    """

    def __init__(
        self,
        flush_interval_sec: float = DEFAULT_FLUSH_INTERVAL_SEC,
        max_buffer_size: int = DEFAULT_MAX_BUFFER_SIZE,
    ) -> None:
        """SSDThrottledWriter başlatıcı.

        Args:
            flush_interval_sec: Otomatik periyodik flush aralığı (saniye).
            max_buffer_size: Maksimum RAM tamponu kuyruk kapasitesi.
        """
        self.flush_interval_sec = flush_interval_sec
        self.max_buffer_size = max_buffer_size
        self._write_queue: queue.Queue[tuple[str, str | bytes, bool]] = queue.Queue(
            maxsize=max_buffer_size * 2
        )
        self._running = True
        self._total_bytes_written = 0
        self._total_flushes = 0
        self._lock = threading.RLock()

        # Arka plan flush iş parçacığı
        self._worker_thread = threading.Thread(
            target=self._flusher_loop,
            daemon=True,
            name="SSDThrottledWriter",
        )
        self._worker_thread.start()

    def __enter__(self) -> SSDThrottledWriter:
        """Context manager desteği."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager çıkışında güvenli flush ve kapatma."""
        self.shutdown()

    @property
    def is_running(self) -> bool:
        """Yazıcının aktif çalışıp çalışmadığını döner.

        Returns:
            bool: Çalışıyorsa True.
        """
        with self._lock:
            return self._running

    def enqueue_write(
        self,
        target_path: str | Path,
        data: str | bytes,
        append: bool = True,
    ) -> None:
        """Diske yazılacak veriyi RAM kuyruğuna ekler (Non-blocking).

        Kuyruk kapasitesi dolarsa doğrudan senkron diske yazarak veri kaybını engeller.

        Args:
            target_path: Hedef dosya yolu.
            data: Yazılacak metin veya bayt verisi.
            append: Dosya sonuna eklensin mi (True: append, False: overwrite).
        """
        path_str = str(target_path)
        try:
            self._write_queue.put_nowait((path_str, data, append))
        except queue.Full:
            logger.warning("ssd_yazma_kuyrugu_dolu_dogrudan_yaziliyor", yol=path_str)
            self._direct_write(path_str, data, append)

    def _direct_write(self, target_path: str, data: str | bytes, append: bool) -> None:
        """Kuyruk dolduğunda veya acil durumlarda doğrudan senkron yaz."""
        try:
            mode = "a" if append else "w"
            is_bytes = isinstance(data, bytes)
            if is_bytes:
                mode += "b"

            target_file = Path(target_path).resolve()
            target_file.parent.mkdir(parents=True, exist_ok=True)

            with self._lock:
                if is_bytes:
                    with open(target_file, mode) as f:
                        f.write(data)  # type: ignore[arg-type]
                else:
                    with open(target_file, mode, encoding="utf-8") as f:
                        f.write(data)  # type: ignore[arg-type]

                self._total_bytes_written += len(data)
                self._total_flushes += 1
        except Exception as e:
            logger.error("ssd_dogrudan_yazma_hatasi", yol=target_path, hata=str(e))

    def _flusher_loop(self) -> None:
        """Arka planda periyodik olarak tamponu diske boşaltan döngü."""
        while True:
            with self._lock:
                running = self._running
            if not running:
                break
            time.sleep(self.flush_interval_sec)
            self.flush()

    def flush(self) -> None:
        """RAM tamponundaki tüm birikmiş yazma işlemlerini tek blokta SSD'ye yazar."""
        if self._write_queue.empty():
            return

        batch_by_file: dict[str, list[tuple[str | bytes, bool]]] = {}
        while not self._write_queue.empty():
            try:
                target_path, data, append = self._write_queue.get_nowait()
                if target_path not in batch_by_file:
                    batch_by_file[target_path] = []
                batch_by_file[target_path].append((data, append))
            except queue.Empty:
                break

        for path, operations in batch_by_file.items():
            try:
                target_file = Path(path).resolve()
                target_file.parent.mkdir(parents=True, exist_ok=True)
                is_bytes = any(isinstance(d, bytes) for d, _ in operations)

                with self._lock:
                    if is_bytes:
                        combined_bytes = b"".join(
                            d if isinstance(d, bytes) else str(d).encode("utf-8") for d, _ in operations
                        )
                        with open(target_file, "ab") as f:
                            f.write(combined_bytes)
                        self._total_bytes_written += len(combined_bytes)
                    else:
                        combined_str = "".join(d if isinstance(d, str) else str(d) for d, _ in operations)
                        with open(target_file, "a", encoding="utf-8") as f:
                            f.write(combined_str)
                        self._total_bytes_written += len(combined_str.encode("utf-8"))

                    self._total_flushes += 1
            except Exception as e:
                logger.error("ssd_toplu_yazma_hatasi", yol=path, hata=str(e))

    def get_stats(self) -> dict[str, Any]:
        """Yazma ve tampon istatistiklerini döner.

        Returns:
            dict[str, Any]: Kuyruk boyutu, toplam flush sayısı ve yazılan MB.
        """
        with self._lock:
            return {
                "pending_queue_size": self._write_queue.qsize(),
                "total_flushes": self._total_flushes,
                "total_mb_written": round(self._total_bytes_written / (1024 * 1024), 3),
                "is_running": self._running,
            }

    def shutdown(self) -> None:
        """Yazma kuyruğunu son kez diske yaz ve arka plan iş parçacığını sonlandır."""
        with self._lock:
            self._running = False
        self.flush()

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        stats = self.get_stats()
        return (
            f"SSDThrottledWriter(bekleyen={stats['pending_queue_size']}, "
            f"toplam_flush={stats['total_flushes']}, yazilan_mb={stats['total_mb_written']}MB)"
        )


# ==============================================================================
# Donanım Orkestratörü Ana Sınıfı
# ==============================================================================


class HardwareOrchestrator:
    """Alpha BIST Donanım ve Kaynak Yönetim Merkezi.

    GPU, RAM, CPU ve SSD iş yüklerini optimum mimariye göre otomatik yapılandırır;
    CatBoost, XGBoost, LightGBM ve PyTorch için en uygun parametreleri üretir.
    """

    def __init__(
        self,
        enable_ssd_writer: bool = True,
        cache_ttl_sec: float = DEFAULT_PROFILE_CACHE_TTL_SEC,
    ) -> None:
        """HardwareOrchestrator başlatıcı.

        Args:
            enable_ssd_writer: SSD tamponlu yazıcısının başlatılıp başlatılmayacağı.
            cache_ttl_sec: Donanım profili sorgusu önbellek geçerlilik süresi (saniye).
        """
        self._lock = threading.RLock()
        self._device: str = "cpu"
        self._gpu_name: str = "N/A"
        self._vram_gb: float = 0.0
        self._cuda_version: str | None = None
        self._cache_ttl_sec: float = cache_ttl_sec
        self._cached_profile: HardwareProfile | None = None
        self._last_profile_time: float = 0.0
        self._ssd_writer: SSDThrottledWriter | None = (
            SSDThrottledWriter() if enable_ssd_writer else None
        )

        self._detect_and_configure_hardware()

    def __enter__(self) -> HardwareOrchestrator:
        """Context manager protokolü desteği."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager çıkışında temizleme ve SSD tamponunu son kez boşaltma."""
        self.shutdown()

    @property
    def ssd_writer(self) -> SSDThrottledWriter:
        """SSD I/O tamponlu yazıcı örneği (ihtiyaç anında tembel başlatılır).

        Returns:
            SSDThrottledWriter: Aktif tamponlu yazıcı örneği.
        """
        if self._ssd_writer is None:
            with self._lock:
                if self._ssd_writer is None:
                    self._ssd_writer = SSDThrottledWriter()
        return self._ssd_writer

    def _detect_and_configure_hardware(self) -> None:
        """Donanımı algılar ve GPU/CUDA optimizasyonlarını devreye sokar."""
        with self._lock:
            if HAS_TORCH and torch is not None:
                try:
                    if torch.cuda.is_available():
                        self._device = "cuda"
                        self._gpu_name = torch.cuda.get_device_name(0)
                        self._vram_gb = round(
                            torch.cuda.get_device_properties(0).total_memory / (1024**3), 2
                        )
                        self._cuda_version = torch.version.cuda

                        # Tensor Core ve TF32 Donanım Hızlandırma Ayarları
                        torch.backends.cuda.matmul.allow_tf32 = True
                        torch.backends.cudnn.allow_tf32 = True
                        torch.backends.cudnn.benchmark = True

                        logger.info(
                            "gpu_donanim_hizlandirma_aktif",
                            gpu=self._gpu_name,
                            vram_gb=self._vram_gb,
                            cuda=self._cuda_version,
                            tf32=True,
                        )
                        return
                except Exception as e:
                    logger.warning("cuda_yapilandirma_hatasi", hata=str(e))

            self._device = "cpu"
            self._gpu_name = "N/A"
            self._vram_gb = 0.0
            self._cuda_version = None
            cpu_cores = max(1, psutil.cpu_count(logical=True) or 1)
            logger.info("donanim_cpu_ram_modunda", cekirdek=cpu_cores)

    @property
    def device(self) -> str:
        """PyTorch modelleri için optimal cihaz ('cuda' veya 'cpu').

        Returns:
            str: Cihaz tanımlayıcısı.
        """
        with self._lock:
            return self._device

    def is_gpu_available(self) -> bool:
        """GPU donanımının kullanılabilir olup olmadığını kontrol eder.

        Returns:
            bool: CUDA aktif ise True, aksi halde False.
        """
        with self._lock:
            return self._device == "cuda"

    @otel_trace("hardware_orchestrator.get_catboost_params")
    def get_catboost_params(
        self,
        custom_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """CatBoost modelleri için GPU/CPU parametrelerini otomatik hazırlar.

        Args:
            custom_params: Opsiyonel kullanıcı parametreleri.

        Returns:
            dict[str, Any]: Donanıma uyarlanmış parametre sözlüğü.
        """
        params = custom_params.copy() if custom_params else {}
        if self.is_gpu_available():
            params["task_type"] = "GPU"
            params["devices"] = "0"
        else:
            params["task_type"] = "CPU"
            cpu_cores = max(1, psutil.cpu_count(logical=True) or 1)
            params["thread_count"] = max(1, cpu_cores - 2)
        return params

    @otel_trace("hardware_orchestrator.get_xgboost_params")
    def get_xgboost_params(
        self,
        custom_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """XGBoost modelleri için GPU/CPU parametrelerini otomatik hazırlar.

        Args:
            custom_params: Opsiyonel kullanıcı parametreleri.

        Returns:
            dict[str, Any]: Donanıma uyarlanmış parametre sözlüğü.
        """
        params = custom_params.copy() if custom_params else {}
        if self.is_gpu_available():
            params["tree_method"] = "hist"
            params["device"] = "cuda"
        else:
            params["tree_method"] = "hist"
            params["device"] = "cpu"
            cpu_cores = max(1, psutil.cpu_count(logical=True) or 1)
            params["n_jobs"] = max(1, cpu_cores - 2)
        return params

    @otel_trace("hardware_orchestrator.get_lightgbm_params")
    def get_lightgbm_params(
        self,
        custom_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """LightGBM modelleri için optimal paralel CPU iş parçacığı parametresi.

        Args:
            custom_params: Opsiyonel kullanıcı parametreleri.

        Returns:
            dict[str, Any]: Donanıma uyarlanmış parametre sözlüğü.
        """
        params = custom_params.copy() if custom_params else {}
        cpu_cores = max(1, psutil.cpu_count(logical=True) or 1)
        params["n_jobs"] = max(1, cpu_cores - 2)
        return params

    def get_optimal_ml_params(
        self,
        framework: str,
        custom_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """İlgili makine öğrenmesi kütüphanesi için optimal parametreleri döner.

        Args:
            framework: Kütüphane adı ('catboost', 'xgboost', 'lightgbm').
            custom_params: Eklemek veya ezmek istenen parametreler.

        Returns:
            dict[str, Any]: Yapılandırılmış parametre sözlüğü.
        """
        fw = framework.lower().strip()
        if fw == "catboost":
            return self.get_catboost_params(custom_params)
        elif fw == "xgboost":
            return self.get_xgboost_params(custom_params)
        elif fw == "lightgbm":
            return self.get_lightgbm_params(custom_params)
        else:
            logger.warning("bilinmeyen_ml_framework_varsayilan_cpu", framework=framework)
            params = custom_params.copy() if custom_params else {}
            cpu_cores = max(1, psutil.cpu_count(logical=True) or 1)
            params.setdefault("n_jobs", max(1, cpu_cores - 2))
            return params

    @otel_trace("hardware_orchestrator.get_hardware_profile")
    def get_hardware_profile(self, force_refresh: bool = False) -> HardwareProfile:
        """Tüm donanım bileşenlerinin anlık durum raporunu döndürür (TTL önbellekli).

        Args:
            force_refresh: Önbelleği atlayarak taze veri topla.

        Returns:
            HardwareProfile: Donanım ve bellek kaynakları profili.
        """
        now = time.monotonic()
        with self._lock:
            if not force_refresh and self._cached_profile is not None:
                if (now - self._last_profile_time) < self._cache_ttl_sec:
                    return self._cached_profile

        mem = psutil.virtual_memory()
        _, _, free_d = shutil.disk_usage(".")
        cores = max(1, psutil.cpu_count(logical=True) or 1)

        with self._lock:
            buffer_enabled = self._ssd_writer is not None and self._ssd_writer.is_running
            profile = HardwareProfile(
                device_type=self._device,
                gpu_name=self._gpu_name,
                gpu_vram_gb=self._vram_gb,
                cuda_version=self._cuda_version,
                total_ram_gb=round(mem.total / (1024**3), 2),
                available_ram_gb=round(mem.available / (1024**3), 2),
                cpu_cores=cores,
                ssd_free_gb=round(free_d / (1024**3), 2),
                ssd_write_buffer_enabled=buffer_enabled,
            )
            self._cached_profile = profile
            self._last_profile_time = now
            return profile

    def export_profile_to_polars(self) -> pl.DataFrame:
        """Mevcut donanım profilini kesin şemalı Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Donanım profil verisini içeren tek satırlık tablo.
        """
        profile = self.get_hardware_profile()
        schema = {
            "device_type": pl.Utf8,
            "gpu_name": pl.Utf8,
            "gpu_vram_gb": pl.Float64,
            "cuda_version": pl.Utf8,
            "total_ram_gb": pl.Float64,
            "available_ram_gb": pl.Float64,
            "cpu_cores": pl.Int64,
            "ssd_free_gb": pl.Float64,
            "ssd_write_buffer_enabled": pl.Boolean,
            "timestamp": pl.Utf8,
        }
        return pl.DataFrame([profile.to_dict()], schema=schema)

    def export_profile_to_duckdb(
        self,
        db_path: str = DEFAULT_HARDWARE_AUDIT_DB_PATH,
    ) -> int:
        """Donanım profilini kalıcı denetim için DuckDB tablosuna aktarır.

        Args:
            db_path: DuckDB veritabanı dosya yolu.

        Returns:
            int: Başarıyla kaydedilen satır sayısı (1).

        Raises:
            Exception: DuckDB bağlantı veya kayıt hatası durumunda.
        """
        profile = self.get_hardware_profile()
        target_file = Path(db_path).resolve()
        target_file.parent.mkdir(parents=True, exist_ok=True)

        row_id = uuid.uuid4().hex
        row = (
            row_id,
            profile.device_type,
            profile.gpu_name,
            profile.gpu_vram_gb,
            profile.cuda_version,
            profile.total_ram_gb,
            profile.available_ram_gb,
            profile.cpu_cores,
            profile.ssd_free_gb,
            profile.ssd_write_buffer_enabled,
            profile.timestamp,
            orjson.dumps(profile.to_dict(), default=str).decode("utf-8"),
        )

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS hardware_profile_audit (
                        id VARCHAR PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        device_type VARCHAR,
                        gpu_name VARCHAR,
                        gpu_vram_gb DOUBLE,
                        cuda_version VARCHAR,
                        total_ram_gb DOUBLE,
                        available_ram_gb DOUBLE,
                        cpu_cores INTEGER,
                        ssd_free_gb DOUBLE,
                        ssd_write_buffer_enabled BOOLEAN,
                        timestamp VARCHAR,
                        profile_json VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO hardware_profile_audit (
                        id, device_type, gpu_name, gpu_vram_gb, cuda_version,
                        total_ram_gb, available_ram_gb, cpu_cores, ssd_free_gb,
                        ssd_write_buffer_enabled, timestamp, profile_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )

        logger.info("donanim_profili_duckdb_aktarildi", yol=str(target_file), id=row_id)
        return 1

    def query_audit_duckdb(
        self,
        db_path: str = DEFAULT_HARDWARE_AUDIT_DB_PATH,
        limit: int = 100,
    ) -> pl.DataFrame:
        """Kayıtlı donanım profillerini DuckDB üzerinden Polars DataFrame olarak çeker.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            limit: Döndürülecek maksimum satır sayısı.

        Returns:
            pl.DataFrame: Donanım denetim geçmişi tablosu.
        """
        target_file = Path(db_path).resolve()
        schema: dict[str, pl.DataType] = {
            "id": pl.Utf8,
            "created_at": pl.Datetime,
            "device_type": pl.Utf8,
            "gpu_name": pl.Utf8,
            "gpu_vram_gb": pl.Float64,
            "cuda_version": pl.Utf8,
            "total_ram_gb": pl.Float64,
            "available_ram_gb": pl.Float64,
            "cpu_cores": pl.Int64,
            "ssd_free_gb": pl.Float64,
            "ssd_write_buffer_enabled": pl.Boolean,
            "timestamp": pl.Utf8,
        }
        if not target_file.exists():
            return pl.DataFrame(schema=schema)

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
                table_check = conn.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_name = 'hardware_profile_audit'"
                ).fetchone()
                if not table_check or table_check[0] == 0:
                    return pl.DataFrame(schema=schema)

                query = (
                    "SELECT id, created_at, device_type, gpu_name, gpu_vram_gb, "
                    "cuda_version, total_ram_gb, available_ram_gb, cpu_cores, "
                    "ssd_free_gb, ssd_write_buffer_enabled, timestamp "
                    "FROM hardware_profile_audit ORDER BY created_at DESC LIMIT ?"
                )
                return conn.execute(query, [max(1, int(limit))]).pl()

    def flush(self) -> None:
        """SSD tamponlu yazıcısının bekleyen tüm verilerini diske yazar."""
        if self._ssd_writer is not None:
            self._ssd_writer.flush()

    def shutdown(self) -> None:
        """Tüm arka plan servislerini ve tamponları güvenli sonlandırır."""
        with self._lock:
            if self._ssd_writer is not None:
                self._ssd_writer.shutdown()

    def to_dict(self) -> dict[str, Any]:
        """Orkestratör durumunu sözlük olarak döner."""
        with self._lock:
            return {
                "device": self._device,
                "gpu_name": self._gpu_name,
                "vram_gb": self._vram_gb,
                "cuda_version": self._cuda_version,
                "has_ssd_writer": self._ssd_writer is not None,
            }

    def to_orjson_bytes(self) -> bytes:
        """Orkestratör durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def clear_audit_duckdb(self, db_path: str = DEFAULT_HARDWARE_AUDIT_DB_PATH) -> None:
        """DuckDB donanım denetim tablosunu sıfırlar."""
        clear_hardware_audit_duckdb(db_path=db_path)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"HardwareOrchestrator(cihaz='{self._device}', gpu='{self._gpu_name}', "
                f"vram={self._vram_gb:.1f}GB)"
            )


# ==============================================================================
# Global Singleton ve Yardımcı Fonksiyonlar
# ==============================================================================

hardware_orchestrator: HardwareOrchestrator = HardwareOrchestrator()


def get_hardware_orchestrator() -> HardwareOrchestrator:
    """Global HardwareOrchestrator singleton örneğini döndürür."""
    return hardware_orchestrator


def get_current_hardware_profile(force_refresh: bool = False) -> HardwareProfile:
    """Sistemin güncel donanım profilini döner."""
    return hardware_orchestrator.get_hardware_profile(force_refresh=force_refresh)


def is_gpu_accelerated() -> bool:
    """Sistemde aktif GPU hızlandırma bulunup bulunmadığını döner."""
    return hardware_orchestrator.is_gpu_available()


def get_optimal_ml_params(
    framework: str,
    custom_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """CatBoost, XGBoost veya LightGBM için optimize edilmiş parametreleri döner."""
    return hardware_orchestrator.get_optimal_ml_params(framework, custom_params)


def enqueue_ssd_write(
    target_path: str | Path,
    data: str | bytes,
    append: bool = True,
) -> None:
    """Global SSDThrottledWriter üzerinden RAM tamponlu yazma kuyruğuna ekler."""
    hardware_orchestrator.ssd_writer.enqueue_write(target_path, data, append)


def flush_ssd_writer() -> None:
    """SSD tamponundaki bekleyen tüm yazma işlemlerini hemen diske boşaltır."""
    hardware_orchestrator.flush()


def export_hardware_profile_to_polars() -> pl.DataFrame:
    """Mevcut donanım profilini Polars DataFrame olarak döner."""
    return hardware_orchestrator.export_profile_to_polars()


def export_hardware_audit_to_duckdb(
    db_path: str = DEFAULT_HARDWARE_AUDIT_DB_PATH,
) -> int:
    """Mevcut donanım profilini DuckDB denetim tablosuna kaydeder."""
    return hardware_orchestrator.export_profile_to_duckdb(db_path)


def query_hardware_audit_duckdb(
    db_path: str = DEFAULT_HARDWARE_AUDIT_DB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerindeki donanım denetim geçmişini Polars DataFrame olarak sorgular."""
    return hardware_orchestrator.query_audit_duckdb(db_path=db_path, limit=limit)


def read_hardware_audit_from_duckdb(
    db_path: str = DEFAULT_HARDWARE_AUDIT_DB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Okunan donanım profili denetim kayıtları.
    """
    path_obj = Path(db_path).resolve()
    schema: dict[str, pl.DataType] = {
        "id": pl.Utf8,
        "created_at": pl.Datetime,
        "device_type": pl.Utf8,
        "gpu_name": pl.Utf8,
        "gpu_vram_gb": pl.Float64,
        "cuda_version": pl.Utf8,
        "total_ram_gb": pl.Float64,
        "available_ram_gb": pl.Float64,
        "cpu_cores": pl.Int64,
        "ssd_free_gb": pl.Float64,
        "ssd_write_buffer_enabled": pl.Boolean,
        "timestamp": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'hardware_profile_audit'"
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = (
                "SELECT id, created_at, device_type, gpu_name, gpu_vram_gb, "
                "cuda_version, total_ram_gb, available_ram_gb, cpu_cores, "
                "ssd_free_gb, ssd_write_buffer_enabled, timestamp "
                "FROM hardware_profile_audit ORDER BY created_at DESC LIMIT ?"
            )
            return conn.execute(query, [max(1, int(limit))]).pl()
    except Exception as exc:
        logger.warning("duckdb_hardware_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_hardware_audit_duckdb(db_path: str = DEFAULT_HARDWARE_AUDIT_DB_PATH) -> None:
    """DuckDB'deki donanım profili denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path).resolve()
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS hardware_profile_audit;")
    except Exception as exc:
        logger.error("duckdb_hardware_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: list[str] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_FLUSH_INTERVAL_SEC",
    "DEFAULT_HARDWARE_AUDIT_DB_PATH",
    "DEFAULT_MAX_BUFFER_SIZE",
    "DEFAULT_PROFILE_CACHE_TTL_SEC",
    "DEFAULT_WAL_SIZE",
    "HardwareOrchestrator",
    "HardwareProfile",
    "SSDThrottledWriter",
    "clear_hardware_audit_duckdb",
    "configure_duckdb_wal",
    "enqueue_ssd_write",
    "export_hardware_audit_to_duckdb",
    "export_hardware_profile_to_polars",
    "flush_ssd_writer",
    "get_current_hardware_profile",
    "get_hardware_orchestrator",
    "get_optimal_ml_params",
    "hardware_orchestrator",
    "is_gpu_accelerated",
    "query_hardware_audit_duckdb",
    "read_hardware_audit_from_duckdb",
    "to_orjson_bytes",
]
