"""
ALPHA BIST — Donanım & Kaynak Orkestrasyon Motoru (Hardware Orchestrator v2.0)
================================================================================
Sistemdeki tüm donanım katmanlarının rollerini optimal şekilde dağıtır:

1. 🎮 GPU (NVIDIA GeForce RTX 4080 - 12 GB VRAM):
   - Derin Öğrenme (Transformer, LSTM, MLP) Tensör Eğitimi ve Geri Yayılımı
   - Hızlı Model Çıkarımları (Batch & Real-time Inference)
   - CatBoost / XGBoost GPU Ağaç Hızlandırması (Histogram GPU)
   - PyTorch TF32 & cuDNN Benchmark Optimizasyonu

2. ⚡ RAM (16 GB Yüksek Hızlı Bellek):
   - Gerçek Zamanlı Veri Tamponu (In-Memory Circular Buffer)
   - Feature Mühendisliği Matrisleri ve Online Öğrenme Tabloları
   - DuckDB In-Memory (:memory:) Geçici Hesaplama Katmanı

3. ⚙️ CPU (24 Mantıksal Çekirdek):
   - Asenkron Olay Yolu (Event Bus) ve Webhook Yönetimi
   - Emir ve Risk Kuralları (BIST Devre Kesici, T+2 Takas, Slippage)
   - Veri Toplama, Temizleme ve Çoklu İşlem Dağıtımı

4. 💾 SSD (NVMe Depolama & I/O Hız/Ömür Koruyucu):
   - SSD Yazma Hızı Sınırı & Rate-Limited Batch Flusher
   - Her tick'te diske yazmak yerine RAM'de toplayıp blok halinde flush etme
   - Model ağırlıkları, DuckDB/SQLite kalıcı logları için tamponlu I/O
"""

import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any

import psutil
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class HardwareProfile:
    """Sistem donanım profili."""
    device_type: str            # 'cuda' veya 'cpu'
    gpu_name: str
    gpu_vram_gb: float
    cuda_version: str | None
    total_ram_gb: float
    available_ram_gb: float
    cpu_cores: int
    ssd_free_gb: float
    ssd_write_buffer_enabled: bool


class SSDThrottledWriter:
    """
    SSD I/O Hız Sınırı & Tamponlu Yazıcı (Buffered Batch Flusher).
    Diske sürekli ufak yazmalar yaparak SSD'yi yormak ve G/Ç darboğazı yaratmak yerine,
    kayıtları RAM kuyruğunda biriktirir ve belirlenen aralıklarla (flush_interval_sec)
    ya da kuyruk dolduğunda tek seferde blok halinde diske yazar.
    """

    def __init__(self, flush_interval_sec: float = 5.0, max_buffer_size: int = 5000):
        self.flush_interval_sec = flush_interval_sec
        self.max_buffer_size = max_buffer_size
        self._write_queue: queue.Queue = queue.Queue(maxsize=max_buffer_size * 2)
        self._running = True
        self._total_bytes_written = 0
        self._total_flushes = 0
        self._lock = threading.Lock()

        # Arka plan flush thread'i
        self._worker_thread = threading.Thread(target=self._flusher_loop, daemon=True, name="SSDThrottledWriter")
        self._worker_thread.start()

    def enqueue_write(self, target_path: str, data: str | bytes, append: bool = True) -> None:
        """Diske yazılacak veriyi RAM kuyruğuna ekler (Gecikmesiz / Non-blocking)."""
        try:
            self._write_queue.put_nowait((target_path, data, append))
        except queue.Full:
            # Kuyruk aşırı dolarsa hemen doğrudan senkron yaz
            self._direct_write(target_path, data, append)

    def _direct_write(self, target_path: str, data: str | bytes, append: bool) -> None:
        try:
            mode = "a" if append else "w"
            if isinstance(data, bytes):
                mode += "b"
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            with open(target_path, mode, encoding=None if isinstance(data, bytes) else "utf-8") as f:
                f.write(data)
            with self._lock:
                self._total_bytes_written += len(data)
                self._total_flushes += 1
        except Exception as e:
            logger.error("Direct SSD write error", path=target_path, error=str(e))

    def _flusher_loop(self) -> None:
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
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                is_bytes = any(isinstance(d, bytes) for d, _ in operations)
                mode = "a" if is_bytes else "w"
                if is_bytes:
                    mode = "ab"
                    combined_bytes = b"".join(d if isinstance(d, bytes) else str(d).encode("utf-8") for d, _ in operations)
                    with open(path, mode) as f:
                        f.write(combined_bytes)
                    with self._lock:
                        self._total_bytes_written += len(combined_bytes)
                else:
                    combined_str = "".join(d if isinstance(d, str) else str(d) for d, _ in operations)
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(combined_str)
                    with self._lock:
                        self._total_bytes_written += len(combined_str.encode("utf-8"))
                with self._lock:
                    self._total_flushes += 1
            except Exception as e:
                logger.error("SSD Batch Flush Error", path=path, error=str(e))

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pending_queue_size": self._write_queue.qsize(),
                "total_flushes": self._total_flushes,
                "total_mb_written": round(self._total_bytes_written / (1024 * 1024), 3),
            }

    def shutdown(self) -> None:
        self._running = False
        self.flush()


class HardwareOrchestrator:
    """
    Alpha BIST Donanım ve Rol Yönetim Merkezi.
    GPU, RAM, CPU ve SSD iş yüklerini optimum mimariye göre otomatik yapılandırır.
    """

    def __init__(self):
        self._device = "cpu"
        self._gpu_name = "N/A"
        self._vram_gb = 0.0
        self._cuda_version = None
        self.ssd_writer = SSDThrottledWriter(flush_interval_sec=3.0, max_buffer_size=10000)

        self._detect_and_configure_hardware()

    def _detect_and_configure_hardware(self) -> None:
        """Donanımı algılar ve GPU/CUDA optimizasyonlarını devreye sokar."""
        try:
            import torch
            if torch.cuda.is_available():
                self._device = "cuda"
                self._gpu_name = torch.cuda.get_device_name(0)
                self._vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
                self._cuda_version = torch.version.cuda

                # RTX 4080 Donanım Hızlandırma Ayarları
                torch.backends.cuda.matmul.allow_tf32 = True  # Ampere/Ada Lovelace TF32 Matmul Hızlandırması
                torch.backends.cudnn.allow_tf32 = True
                torch.backends.cudnn.benchmark = True         # Otomatik en hızlı convolution kernel seçici

                logger.info(
                    "GPU Accelerated Hardware Initialized",
                    gpu=self._gpu_name,
                    vram_gb=self._vram_gb,
                    cuda=self._cuda_version,
                    tf32=True,
                )
            else:
                self._device = "cpu"
                logger.info("Hardware running in CPU/RAM mode", cores=psutil.cpu_count(logical=True))
        except ImportError:
            self._device = "cpu"

    @property
    def device(self) -> str:
        """PyTorch modelleri için optimal cihaz ('cuda' veya 'cpu')."""
        return self._device

    def is_gpu_available(self) -> bool:
        return self._device == "cuda"

    def get_catboost_params(self, custom_params: dict[str, Any] | None = None) -> dict[str, Any]:
        """CatBoost modelleri için GPU/CPU parametrelerini otomatik hazırlar."""
        params = custom_params.copy() if custom_params else {}
        if self.is_gpu_available():
            params["task_type"] = "GPU"
            params["devices"] = "0"
        else:
            params["task_type"] = "CPU"
            params["thread_count"] = max(1, psutil.cpu_count(logical=True) - 2)
        return params

    def get_xgboost_params(self, custom_params: dict[str, Any] | None = None) -> dict[str, Any]:
        """XGBoost modelleri için GPU/CPU parametrelerini otomatik hazırlar."""
        params = custom_params.copy() if custom_params else {}
        if self.is_gpu_available():
            params["tree_method"] = "hist"
            params["device"] = "cuda"
        else:
            params["tree_method"] = "hist"
            params["device"] = "cpu"
            params["n_jobs"] = max(1, psutil.cpu_count(logical=True) - 2)
        return params

    def get_lightgbm_params(self, custom_params: dict[str, Any] | None = None) -> dict[str, Any]:
        """LightGBM modelleri için optimal paralel CPU iş parçacığı parametresi."""
        params = custom_params.copy() if custom_params else {}
        params["n_jobs"] = max(1, psutil.cpu_count(logical=True) - 2)
        return params

    def get_hardware_profile(self) -> HardwareProfile:
        """Tüm donanım bileşenlerinin anlık durum raporunu döndürür."""
        mem = psutil.virtual_memory()
        _, _, free_d = shutil.disk_usage(".")
        return HardwareProfile(
            device_type=self._device,
            gpu_name=self._gpu_name,
            gpu_vram_gb=self._vram_gb,
            cuda_version=self._cuda_version,
            total_ram_gb=round(mem.total / (1024**3), 2),
            available_ram_gb=round(mem.available / (1024**3), 2),
            cpu_cores=psutil.cpu_count(logical=True),
            ssd_free_gb=round(free_d / (1024**3), 2),
            ssd_write_buffer_enabled=True,
        )


# Global singleton donanım orkestratörü
hardware_orchestrator = HardwareOrchestrator()
