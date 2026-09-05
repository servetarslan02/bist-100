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
from typing import Any

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
        return orjson.dumps(self.to_dict())

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

    @property
    def is_running(self) -> bool:
        """Yazıcının aktif çalışıp çalışmadığını döner.

        Returns:
            bool: Çalışıyorsa True.
        """
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

            if is_bytes:
                with open(target_file, mode) as f:
                    f.write(data)
            else:
                with open(target_file, mode, encoding="utf-8") as f:
                    f.write(data)

            with self._lock:
                self._total_bytes_written += len(data)
                self._total_flushes += 1
        except Exception as e:
            logger.error("ssd_dogrudan_yazma_hatasi", yol=target_path, hata=str(e))

    def _flusher_loop(self) -> None:
        """Arka planda periyodik olarak tamponu diske boşaltan döngü."""
        while self._running:
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

                if is_bytes:
                    combined_bytes = b"".join(
                        d if isinstance(d, bytes) else str(d).encode("utf-8") for d, _ in operations
                    )
                    with open(target_file, "ab") as f:
                        f.write(combined_bytes)
                    with self._lock:
                        self._total_bytes_written += len(combined_bytes)
                else:
                    combined_str = "".join(d if isinstance(d, str) else str(d) for d, _ in operations)
                    with open(target_file, "a", encoding="utf-8") as f:
                        f.write(combined_str)
                    with self._lock:
                        self._total_bytes_written += len(combined_str.encode("utf-8"))

                with self._lock:
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

    def __init__(self, enable_ssd_writer: bool = True) -> None:
        """HardwareOrchestrator başlatıcı.

        Args:
            enable_ssd_writer: SSD tamponlu yazıcısının başlatılıp başlatılmayacağı.
        """
        self._lock = threading.RLock()
        self._device: str = "cpu"
        self._gpu_name: str = "N/A"
        self._vram_gb: float = 0.0
        self._cuda_version: str | None = None
        self._ssd_writer: SSDThrottledWriter | None = (
            SSDThrottledWriter() if enable_ssd_writer else None
        )

        self._detect_and_configure_hardware()

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

                        # RTX 4080 Donanım Hızlandırma Ayarları
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
            logger.info("donanim_cpu_ram_modunda", cekirdek=psutil.cpu_count(logical=True))

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
            cpu_cores = psutil.cpu_count(logical=True) or 4
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
            cpu_cores = psutil.cpu_count(logical=True) or 4
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
        cpu_cores = psutil.cpu_count(logical=True) or 4
        params["n_jobs"] = max(1, cpu_cores - 2)
        return params

    @otel_trace("hardware_orchestrator.get_hardware_profile")
    def get_hardware_profile(self) -> HardwareProfile:
        """Tüm donanım bileşenlerinin anlık durum raporunu döndürür.

        Returns:
            HardwareProfile: Donanım ve bellek kaynakları profili.
        """
        mem = psutil.virtual_memory()
        _, _, free_d = shutil.disk_usage(".")
        cores = psutil.cpu_count(logical=True) or 1

        with self._lock:
            buffer_enabled = self._ssd_writer is not None and self._ssd_writer.is_running
            return HardwareProfile(
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

    def export_profile_to_polars(self) -> pl.DataFrame:
        """Mevcut donanım profilini Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Donanım profil verisini içeren tek satırlık tablo.
        """
        profile = self.get_hardware_profile()
        return pl.DataFrame([profile.to_dict()])

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
        target_file = Path(db_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        row = (
            uuid.uuid4().hex,
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
            orjson.dumps(profile.to_dict()).decode("utf-8"),
        )

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
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

        logger.info("donanim_profili_duckdb_aktarildi", yol=db_path)
        return 1

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"HardwareOrchestrator(cihaz='{self._device}', gpu='{self._gpu_name}', "
                f"vram={self._vram_gb:.1f}GB)"
            )


# ==============================================================================
# Global Singleton ve Dışa Aktarımlar
# ==============================================================================

hardware_orchestrator: HardwareOrchestrator = HardwareOrchestrator()

__all__: list[str] = [
    "DEFAULT_FLUSH_INTERVAL_SEC",
    "DEFAULT_HARDWARE_AUDIT_DB_PATH",
    "DEFAULT_MAX_BUFFER_SIZE",
    "HardwareOrchestrator",
    "HardwareProfile",
    "SSDThrottledWriter",
    "hardware_orchestrator",
]
