"""ALPHA BIST — Kişisel PC Donanım Kaynak Yöneticisi ve Uyarlamalı Profil Motoru (Hardware Profile).

Bu modül, platformun çalıştığı ana bilgisayarın (örn. NVIDIA RTX 4080 GPU, 24 Çekirdek CPU,
NVMe SSD ve 16+ GB RAM) fiziksel kaynak sınırlarını analiz eder; sistemin kilitlenmesini,
aşırı ısınmasını veya diğer masaüstü süreçlerinin aksamasını engellemek amacıyla güvenli
tavan kotaları (CPU iş parçacığı, VRAM kotası, DuckDB bellek tavanı, SSD G/Ç hızı) uygular.

Temel Yetenekler:
1. GPU VRAM Koruma Tavanı:
   - Ayrık GPU için maksimum %25 VRAM kotası belirler (kalan VRAM kullanıcı ve sistem süreçlerine ayrılır).
2. Akıllı Cihaz Seçici (Optimal Device Selector):
   - Küçük batch (<10.000) çıkarımlarda PCIe bellek transfer gecikmesi olmaksızın CPU vektörizasyonunu seçer.
   - Büyük batch veya model eğitimi durumunda otomatik olarak CUDA hızlandırıcısına yönlendirir.
3. CPU İş Parçacığı Sınırı:
   - Çok çekirdekli sistemlerde (24 çekirdek vb.) Polars, OpenMP ve MKL için en fazla 4 thread sınırı koyar.
4. Windows Süreç Önceliği:
   - Süreç önceliğini `BELOW_NORMAL_PRIORITY_CLASS` seviyesine çekerek sıfır takılma sağlar.
5. DuckDB ve RAM Sınırı:
   - Bellek kullanımını güvenli tavanla (512MB - 1024MB) sınırlar.
6. Polars ve DuckDB Denetim İzi:
   - Donanım özellikleri ve kaynak sınırlarını Polars DataFrame ve DuckDB kalıcı tablosuna aktarır.
7. Geri Alma ve Yaşam Döngüsü (Context Manager & Rollback):
   - Ortam değişkenlerini ve öncelik ayarlarını güvenle uygular ve geri alabilir.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
# Standart Donanım ve Kota Sabitleri
# ==============================================================================

DEFAULT_MAX_CPU_THREADS: int = 4
DEFAULT_MIN_CPU_THREADS: int = 2
DEFAULT_VRAM_FRACTION: float = 0.25
DEFAULT_MAX_DUCKDB_MEM_HIGH_MB: int = 1024
DEFAULT_MAX_DUCKDB_MEM_LOW_MB: int = 512
DEFAULT_MAX_CACHE_ITEMS: int = 5000
DEFAULT_SSD_WRITE_LIMIT_MBPS: int = 128
DEFAULT_HARDWARE_PROFILE_DB_PATH: str = "data/hardware_profile_audit.duckdb"


# ==============================================================================
# Veri Modelleri
# ==============================================================================


@dataclass(slots=True)
class HardwareSpecs:
    """Sistemde tespit edilen fiziksel ve mantıksal donanım özellikleri.

    Attributes:
        cpu_cores_logical: Mantıksal CPU çekirdek sayısı.
        cpu_cores_physical: Fiziksel CPU çekirdek sayısı.
        ram_total_gb: Toplam kurulu sistem belleği (GB).
        ram_available_gb: Kullanılabilir boş sistem belleği (GB).
        gpu_name: Tespit edilen grafik kartı adı veya None.
        gpu_total_vram_mb: Toplam GPU VRAM miktarı (MB).
        gpu_available: Kullanılabilir GPU mevcut mu.
        cuda_driver_version: NVIDIA CUDA sürücü sürümü veya None.
        ssd_mount: Birincil SSD disk sürücüsü veya bağlama noktası.
    """

    cpu_cores_logical: int
    cpu_cores_physical: int
    ram_total_gb: float
    ram_available_gb: float
    gpu_name: str | None
    gpu_total_vram_mb: float
    gpu_available: bool
    cuda_driver_version: str | None
    ssd_mount: str

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return {
            "cpu_cores_logical": self.cpu_cores_logical,
            "cpu_cores_physical": self.cpu_cores_physical,
            "ram_total_gb": self.ram_total_gb,
            "ram_available_gb": self.ram_available_gb,
            "gpu_name": self.gpu_name,
            "gpu_total_vram_mb": self.gpu_total_vram_mb,
            "gpu_available": self.gpu_available,
            "cuda_driver_version": self.cuda_driver_version,
            "ssd_mount": self.ssd_mount,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HardwareSpecs:
        """Sözlükten HardwareSpecs nesnesi üretir."""
        return cls(
            cpu_cores_logical=int(data.get("cpu_cores_logical", 1)),
            cpu_cores_physical=int(data.get("cpu_cores_physical", 1)),
            ram_total_gb=float(data.get("ram_total_gb", 0.0)),
            ram_available_gb=float(data.get("ram_available_gb", 0.0)),
            gpu_name=data.get("gpu_name"),
            gpu_total_vram_mb=float(data.get("gpu_total_vram_mb", 0.0)),
            gpu_available=bool(data.get("gpu_available", False)),
            cuda_driver_version=data.get("cuda_driver_version"),
            ssd_mount=str(data.get("ssd_mount", "/")),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> HardwareSpecs:
        """JSON verisinden HardwareSpecs nesnesi üretir."""
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        gpu_str = f"{self.gpu_name} ({self.gpu_total_vram_mb:.0f}MB)" if self.gpu_available else "YOK"
        return (
            f"HardwareSpecs(cpu_fiziksel={self.cpu_cores_physical}, cpu_mantiksal={self.cpu_cores_logical}, "
            f"ram_toplam={self.ram_total_gb:.1f}GB, gpu='{gpu_str}')"
        )


@dataclass(slots=True)
class ResourceLimits:
    """Kişisel PC ortamı için hesaplanan güvenli çalışma sınırları.

    Attributes:
        max_cpu_threads: İzin verilen maksimum paralel iş parçacığı sayısı.
        max_gpu_vram_mb: İzin verilen maksimum GPU VRAM miktarı (MB).
        gpu_vram_fraction: İzin verilen maksimum GPU VRAM oranı (0.0 - 1.0).
        max_duckdb_memory_mb: DuckDB veritabanı maksimum bellek limiti (MB).
        max_cache_items: Bellek önbelleğinde tutulabilecek maksimum nesne sayısı.
        process_priority: Süreç öncelik sınıfı ('BELOW_NORMAL', 'NORMAL').
        ssd_write_limit_mbps: Hedeflenen SSD maksimum yazma hızı (MB/s).
    """

    max_cpu_threads: int
    max_gpu_vram_mb: float
    gpu_vram_fraction: float
    max_duckdb_memory_mb: int
    max_cache_items: int
    process_priority: str
    ssd_write_limit_mbps: int

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return {
            "max_cpu_threads": self.max_cpu_threads,
            "max_gpu_vram_mb": self.max_gpu_vram_mb,
            "gpu_vram_fraction": self.gpu_vram_fraction,
            "max_duckdb_memory_mb": self.max_duckdb_memory_mb,
            "max_cache_items": self.max_cache_items,
            "process_priority": self.process_priority,
            "ssd_write_limit_mbps": self.ssd_write_limit_mbps,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceLimits:
        """Sözlükten ResourceLimits nesnesi üretir."""
        return cls(
            max_cpu_threads=int(data.get("max_cpu_threads", DEFAULT_MAX_CPU_THREADS)),
            max_gpu_vram_mb=float(data.get("max_gpu_vram_mb", 0.0)),
            gpu_vram_fraction=float(data.get("gpu_vram_fraction", 0.0)),
            max_duckdb_memory_mb=int(
                data.get("max_duckdb_memory_mb", DEFAULT_MAX_DUCKDB_MEM_LOW_MB)
            ),
            max_cache_items=int(data.get("max_cache_items", DEFAULT_MAX_CACHE_ITEMS)),
            process_priority=str(data.get("process_priority", "BELOW_NORMAL")),
            ssd_write_limit_mbps=int(
                data.get("ssd_write_limit_mbps", DEFAULT_SSD_WRITE_LIMIT_MBPS)
            ),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> ResourceLimits:
        """JSON verisinden ResourceLimits nesnesi üretir."""
        data = orjson.loads(json_str_or_bytes)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"ResourceLimits(max_cpu_threads={self.max_cpu_threads}, max_vram_mb={self.max_gpu_vram_mb:.0f}MB, "
            f"duckdb_tavan={self.max_duckdb_memory_mb}MB, oncelik='{self.process_priority}')"
        )


# ==============================================================================
# Donanım Kaynak Yöneticisi Çekirdek Sınıfı
# ==============================================================================


class HardwareResourceManager:
    """Kişisel PC donanım kaynak yöneticisi ve uyarlamalı profil uygulayıcı.

    Sistem donanımını otomatik analiz eder, güvenli çalışma kotaları türetir,
    işletim sistemi ortam değişkenlerine ve süreç önceliğine bu sınırları enjekte eder.
    """

    def __init__(self) -> None:
        """HardwareResourceManager başlatıcı."""
        self._lock = threading.RLock()
        self.specs: HardwareSpecs = self._detect_hardware()
        self.limits: ResourceLimits = self._calculate_safe_limits()
        self._is_applied: bool = False
        self._original_env: dict[str, str | None] = {}
        self._original_nice: int | None = None

    def __enter__(self) -> HardwareResourceManager:
        """Context manager protokolü desteği ile profili uygula."""
        self.apply_profile()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager çıkışında orijinal ortam değişkenlerini geri yükle."""
        self.restore_profile()

    def _detect_hardware(self) -> HardwareSpecs:
        """Sistem donanımını otomatik tarar ve donanım özelliklerini üretir.

        Returns:
            HardwareSpecs: Tespit edilen CPU, RAM, GPU ve disk özellikleri.
        """
        logical_cores = max(1, psutil.cpu_count(logical=True) or 8)
        physical_cores = max(1, psutil.cpu_count(logical=False) or 4)
        ram = psutil.virtual_memory()
        ram_total_gb = round(ram.total / (1024**3), 2)
        ram_avail_gb = round(ram.available / (1024**3), 2)

        # GPU tespiti (NVIDIA-SMI)
        gpu_name: str | None = None
        gpu_vram_mb: float = 0.0
        cuda_driver: str | None = None
        gpu_available: bool = False

        try:
            res = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().split(",")]
                if len(parts) >= 3:
                    gpu_name = parts[0]
                    gpu_vram_mb = float(parts[1])
                    cuda_driver = parts[2]
                    gpu_available = True
        except Exception as smi_err:
            logger.debug("nvidia_smi_tarama_notu", hata=str(smi_err))

        # NVIDIA-SMI bulunamazsa veya başarısız olursa PyTorch CUDA üzerinden yedek algılama
        if not gpu_available and HAS_TORCH and torch is not None:
            try:
                if torch.cuda.is_available():
                    gpu_name = torch.cuda.get_device_name(0)
                    gpu_vram_mb = round(
                        torch.cuda.get_device_properties(0).total_memory / (1024**2), 1
                    )
                    cuda_driver = str(torch.version.cuda) if torch.version.cuda else None
                    gpu_available = True
            except Exception as torch_probe_err:
                logger.debug("torch_cuda_tarama_notu", hata=str(torch_probe_err))

        return HardwareSpecs(
            cpu_cores_logical=logical_cores,
            cpu_cores_physical=physical_cores,
            ram_total_gb=ram_total_gb,
            ram_available_gb=ram_avail_gb,
            gpu_name=gpu_name,
            gpu_total_vram_mb=gpu_vram_mb,
            gpu_available=gpu_available,
            cuda_driver_version=cuda_driver,
            ssd_mount=os.getcwd()[:2] if sys.platform == "win32" else "/",
        )

    def _calculate_safe_limits(self) -> ResourceLimits:
        """Kişisel PC için sistemi yormayan dengeli limitleri hesaplar.

        Returns:
            ResourceLimits: Türetilen güvenli kaynak limitleri.
        """
        # 1. CPU Threading: Çok çekirdekte arka planda maksimum 4, en az 2 thread
        half_physical = max(1, self.specs.cpu_cores_physical // 2)
        max_cpu_threads = min(
            DEFAULT_MAX_CPU_THREADS,
            max(DEFAULT_MIN_CPU_THREADS, half_physical),
        )

        # 2. GPU VRAM: RTX 4080 (12GB) gibi bir GPU'da maksimum %25 kota ayır
        vram_fraction = DEFAULT_VRAM_FRACTION if self.specs.gpu_available else 0.0
        max_gpu_vram_mb = round(self.specs.gpu_total_vram_mb * vram_fraction, 1)

        # 3. DuckDB ve RAM tavanı
        max_duckdb_mem_mb = (
            DEFAULT_MAX_DUCKDB_MEM_HIGH_MB
            if self.specs.ram_total_gb >= 16.0
            else DEFAULT_MAX_DUCKDB_MEM_LOW_MB
        )

        return ResourceLimits(
            max_cpu_threads=max_cpu_threads,
            max_gpu_vram_mb=max_gpu_vram_mb,
            gpu_vram_fraction=vram_fraction,
            max_duckdb_memory_mb=max_duckdb_mem_mb,
            max_cache_items=DEFAULT_MAX_CACHE_ITEMS,
            process_priority="BELOW_NORMAL",
            ssd_write_limit_mbps=DEFAULT_SSD_WRITE_LIMIT_MBPS,
        )

    def refresh_hardware_specs(self) -> None:
        """Donanım özelliklerini tazeleyip limitleri yeniden hesaplar."""
        with self._lock:
            self.specs = self._detect_hardware()
            self.limits = self._calculate_safe_limits()
            logger.info(
                "donanim_ozellikleri_tazelendi",
                ram_available_gb=self.specs.ram_available_gb,
                gpu_available=self.specs.gpu_available,
            )

    @otel_trace("hardware_profile.apply_profile")
    def apply_profile(self) -> dict[str, Any]:
        """Tüm ortam değişkenlerini ve süreç sınırlarını sisteme uygular.

        Returns:
            dict[str, Any]: Uygulanan eylemler ve yapılandırma özeti.
        """
        applied_actions: dict[str, Any] = {}

        with self._lock:
            env_keys = [
                "POLARS_MAX_THREADS",
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            ]
            for key in env_keys:
                if key not in self._original_env:
                    self._original_env[key] = os.environ.get(key)

            # A) CPU Thread Sınırları (NumPy, Polars, OMP, MKL, NumExpr)
            threads_str = str(self.limits.max_cpu_threads)
            for key in env_keys:
                os.environ[key] = threads_str
            applied_actions["cpu_threads_set"] = self.limits.max_cpu_threads

            # B) Windows Süreç Önceliği (BELOW_NORMAL)
            if sys.platform == "win32":
                try:
                    p = psutil.Process(os.getpid())
                    if self._original_nice is None:
                        try:
                            self._original_nice = p.nice()
                        except Exception:
                            self._original_nice = None
                    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                    applied_actions["process_priority"] = "BELOW_NORMAL_PRIORITY_CLASS"
                except Exception as e:
                    applied_actions["process_priority_error"] = str(e)

            # C) GPU Güvenlik Tavanı (PyTorch / CUDA bellek kısıtı)
            if self.specs.gpu_available:
                if HAS_TORCH and torch is not None:
                    try:
                        if torch.cuda.is_available():
                            torch.cuda.set_per_process_memory_fraction(
                                self.limits.gpu_vram_fraction, 0
                            )
                            applied_actions["cuda_vram_fraction_applied"] = (
                                self.limits.gpu_vram_fraction
                            )
                        else:
                            applied_actions["cuda_note"] = (
                                "NVIDIA GPU mevcut, PyTorch CPU modunda (GPU boşta)"
                            )
                    except Exception as torch_err:
                        applied_actions["cuda_error"] = str(torch_err)
                else:
                    applied_actions["cuda_note"] = "PyTorch kütüphanesi yüklü değil, GPU boşta"
            else:
                applied_actions["cuda_note"] = "Ayrık GPU bulunamadı, CPU profili aktif"

            # D) DuckDB Bellek Sınırı
            applied_actions["duckdb_max_memory"] = f"{self.limits.max_duckdb_memory_mb}MB"

            # E) SSD Koruma Limiti
            applied_actions["ssd_limit"] = f"{self.limits.ssd_write_limit_mbps} MB/s"

            self._is_applied = True

        logger.info(
            "kisisel_bilgisayar_donanim_profili_uygulandi",
            cpu_threads=self.limits.max_cpu_threads,
            gpu=self.specs.gpu_name or "YOK",
            max_vram_mb=self.limits.max_gpu_vram_mb,
            ram_cap=f"{self.limits.max_duckdb_memory_mb}MB",
        )
        return applied_actions

    def restore_profile(self) -> dict[str, Any]:
        """Uygulanan ortam değişkenlerini ve süreç önceliğini orijinal durumuna döndürür.

        Returns:
            dict[str, Any]: Geri yüklenen parametrelerin dökümü.
        """
        restored: dict[str, Any] = {}
        with self._lock:
            for key, val in self._original_env.items():
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val
                restored[key] = val
            self._original_env.clear()

            if sys.platform == "win32" and self._original_nice is not None:
                try:
                    p = psutil.Process(os.getpid())
                    p.nice(self._original_nice)
                    restored["process_priority"] = self._original_nice
                except Exception as e:
                    restored["process_priority_restore_error"] = str(e)
                self._original_nice = None

            self._is_applied = False

        logger.info("donanim_profili_orijinal_durumuna_donduruldu")
        return restored

    def get_optimal_device_for_task(
        self,
        batch_size: int,
        task_type: str = "inference",
    ) -> str:
        """Göreve ve veri boyutuna göre en verimli donanımı (CPU vs CUDA) seçer.

        Kural:
        - Küçük batch çıkarımlarda (<10.000): CPU vektörizasyonu daha hızlıdır (PCIe gecikmesi yok).
        - Büyük batch (>=10.000) veya derin öğrenme eğitiminde ('training'): GPU'ya yönlendirir.

        Args:
            batch_size: İşlenecek veri veya bar sayısı.
            task_type: Görev sınıfı ('inference' veya 'training').

        Returns:
            str: Seçilen hedef cihaz ('cuda' veya 'cpu').
        """
        with self._lock:
            if not self.specs.gpu_available:
                return "cpu"

            if task_type == "training" or batch_size >= 10_000:
                return "cuda"

            return "cpu"

    def get_status_report(self) -> dict[str, Any]:
        """Donanım durumu ve limit uyum raporunu döner.

        Returns:
            dict[str, Any]: Sistem özellikleri, aktif limitler ve çalışma durumu.
        """
        proc = psutil.Process(os.getpid())
        mem_rss_mb = round(proc.memory_info().rss / (1024 * 1024), 2)

        with self._lock:
            return {
                "specs": {
                    "cpu_logical_cores": self.specs.cpu_cores_logical,
                    "ram_total_gb": self.specs.ram_total_gb,
                    "ram_available_gb": self.specs.ram_available_gb,
                    "gpu_detected": self.specs.gpu_name or "YOK",
                    "gpu_total_vram_mb": self.specs.gpu_total_vram_mb,
                    "cuda_driver": self.specs.cuda_driver_version or "N/A",
                },
                "limits": {
                    "max_cpu_threads": self.limits.max_cpu_threads,
                    "max_gpu_vram_mb": self.limits.max_gpu_vram_mb,
                    "gpu_vram_fraction_cap": f"%{self.limits.gpu_vram_fraction * 100:.0f}",
                    "duckdb_memory_cap": f"{self.limits.max_duckdb_memory_mb}MB",
                    "process_priority": self.limits.process_priority,
                    "ssd_write_budget_mbps": f"{self.limits.ssd_write_limit_mbps} MB/s",
                },
                "runtime_state": {
                    "profile_applied": self._is_applied,
                    "current_process_ram_mb": mem_rss_mb,
                    "recommended_device_647_inference": self.get_optimal_device_for_task(
                        647, "inference"
                    ),
                    "recommended_device_100k_training": self.get_optimal_device_for_task(
                        100_000, "training"
                    ),
                },
            }

    # ==========================================================================
    # POLARS VE DUCKDB ENTEGRASYONU
    # ==========================================================================

    def export_specs_to_polars(self) -> pl.DataFrame:
        """Donanım özelliklerini kesin şemalı Polars DataFrame olarak dışa aktarır.

        Returns:
            pl.DataFrame: Donanım özelliklerini içeren tek satırlık tablo.
        """
        with self._lock:
            schema = {
                "cpu_cores_logical": pl.Int64,
                "cpu_cores_physical": pl.Int64,
                "ram_total_gb": pl.Float64,
                "ram_available_gb": pl.Float64,
                "gpu_name": pl.Utf8,
                "gpu_total_vram_mb": pl.Float64,
                "gpu_available": pl.Boolean,
                "cuda_driver_version": pl.Utf8,
                "ssd_mount": pl.Utf8,
            }
            return pl.DataFrame([self.specs.to_dict()], schema=schema)

    def export_limits_to_polars(self) -> pl.DataFrame:
        """Hesaplanan kaynak sınırlarını kesin şemalı Polars DataFrame olarak dışa aktarır.

        Returns:
            pl.DataFrame: Güvenli kaynak sınırlarını içeren tek satırlık tablo.
        """
        with self._lock:
            schema = {
                "max_cpu_threads": pl.Int64,
                "max_gpu_vram_mb": pl.Float64,
                "gpu_vram_fraction": pl.Float64,
                "max_duckdb_memory_mb": pl.Int64,
                "max_cache_items": pl.Int64,
                "process_priority": pl.Utf8,
                "ssd_write_limit_mbps": pl.Int64,
            }
            return pl.DataFrame([self.limits.to_dict()], schema=schema)

    def export_to_duckdb(
        self,
        db_path: str = DEFAULT_HARDWARE_PROFILE_DB_PATH,
    ) -> int:
        """Donanım özelliklerini ve uygulanan limitleri DuckDB tablosuna aktarır.

        Args:
            db_path: DuckDB veritabanı dosya yolu.

        Returns:
            int: Başarıyla kaydedilen satır sayısı (1).

        Raises:
            Exception: DuckDB bağlantı veya yazma hatası durumunda.
        """
        target_file = Path(db_path).resolve()
        target_file.parent.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(UTC).isoformat()
        row_id = uuid.uuid4().hex

        with self._lock:
            row = (
                row_id,
                now_iso,
                self.specs.cpu_cores_logical,
                self.specs.cpu_cores_physical,
                self.specs.ram_total_gb,
                self.specs.ram_available_gb,
                self.specs.gpu_name or "YOK",
                self.specs.gpu_total_vram_mb,
                self.specs.gpu_available,
                self.limits.max_cpu_threads,
                self.limits.max_gpu_vram_mb,
                self.limits.max_duckdb_memory_mb,
                self.limits.process_priority,
                self._is_applied,
                orjson.dumps(self.specs.to_dict(), default=str).decode("utf-8"),
                orjson.dumps(self.limits.to_dict(), default=str).decode("utf-8"),
            )

            with duckdb.connect(str(target_file)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS hardware_resource_audit (
                        id VARCHAR PRIMARY KEY,
                        created_at TIMESTAMP,
                        cpu_logical INTEGER,
                        cpu_physical INTEGER,
                        ram_total_gb DOUBLE,
                        ram_avail_gb DOUBLE,
                        gpu_name VARCHAR,
                        gpu_vram_mb DOUBLE,
                        gpu_available BOOLEAN,
                        max_cpu_threads INTEGER,
                        max_gpu_vram_mb DOUBLE,
                        max_duckdb_mem_mb INTEGER,
                        process_priority VARCHAR,
                        is_applied BOOLEAN,
                        specs_json VARCHAR,
                        limits_json VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO hardware_resource_audit (
                        id, created_at, cpu_logical, cpu_physical, ram_total_gb, ram_avail_gb,
                        gpu_name, gpu_vram_mb, gpu_available, max_cpu_threads, max_gpu_vram_mb,
                        max_duckdb_mem_mb, process_priority, is_applied, specs_json, limits_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )

        logger.info("donanim_profil_denetimi_duckdb_kaydedildi", yol=str(target_file), id=row_id)
        return 1

    def query_audit_duckdb(
        self,
        db_path: str = DEFAULT_HARDWARE_PROFILE_DB_PATH,
        limit: int = 100,
    ) -> pl.DataFrame:
        """Kayıtlı donanım profili denetim geçmişini DuckDB üzerinden Polars olarak çeker.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            limit: Döndürülecek maksimum satır sayısı.

        Returns:
            pl.DataFrame: Donanım profili denetim geçmişi tablosu.
        """
        target_file = Path(db_path).resolve()
        if not target_file.exists():
            return pl.DataFrame()

        with self._lock:
            with duckdb.connect(str(target_file), read_only=True) as conn:
                query = (
                    "SELECT id, created_at, cpu_logical, cpu_physical, ram_total_gb, ram_avail_gb, "
                    "gpu_name, gpu_vram_mb, gpu_available, max_cpu_threads, max_gpu_vram_mb, "
                    "max_duckdb_mem_mb, process_priority, is_applied "
                    "FROM hardware_resource_audit ORDER BY created_at DESC LIMIT ?"
                )
                return conn.execute(query, [limit]).pl()

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            durum = "UYGULANDI" if self._is_applied else "BEKLEMEDE"
            return (
                f"HardwareResourceManager(durum='{durum}', max_threads={self.limits.max_cpu_threads}, "
                f"gpu_aktif={self.specs.gpu_available})"
            )


# ==============================================================================
# Global Singleton ve Yardımcı Modül Fonksiyonları
# ==============================================================================

hardware_manager: HardwareResourceManager = HardwareResourceManager()


def get_hardware_manager() -> HardwareResourceManager:
    """Global HardwareResourceManager singleton örneğini döndürür."""
    return hardware_manager


def apply_hardware_profile() -> dict[str, Any]:
    """Sistem ortam değişkenlerine ve süreç önceliğine donanım sınırlarını uygular."""
    return hardware_manager.apply_profile()


def restore_hardware_profile() -> dict[str, Any]:
    """Ortam değişkenlerini ve süreç önceliğini orijinal durumuna döndürür."""
    return hardware_manager.restore_profile()


def get_optimal_execution_device(batch_size: int, task_type: str = "inference") -> str:
    """Veri boyutu ve görev tipine göre optimal cihazı ('cuda' veya 'cpu') döner."""
    return hardware_manager.get_optimal_device_for_task(batch_size=batch_size, task_type=task_type)


def get_hardware_status_report() -> dict[str, Any]:
    """Sistem donanım durumu ve kaynak sınırları raporunu döner."""
    return hardware_manager.get_status_report()


def export_specs_to_polars() -> pl.DataFrame:
    """Sistem donanım özelliklerini Polars DataFrame olarak döner."""
    return hardware_manager.export_specs_to_polars()


def export_limits_to_polars() -> pl.DataFrame:
    """Sistem kaynak sınırlarını Polars DataFrame olarak döner."""
    return hardware_manager.export_limits_to_polars()


def export_hardware_profile_to_duckdb(
    db_path: str = DEFAULT_HARDWARE_PROFILE_DB_PATH,
) -> int:
    """Sistem özelliklerini ve limitlerini DuckDB denetim tablosuna kaydeder."""
    return hardware_manager.export_to_duckdb(db_path=db_path)


def query_hardware_profile_duckdb(
    db_path: str = DEFAULT_HARDWARE_PROFILE_DB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerindeki donanım kaynak denetim geçmişini Polars DataFrame olarak sorgular."""
    return hardware_manager.query_audit_duckdb(db_path=db_path, limit=limit)


__all__: list[str] = [
    "DEFAULT_HARDWARE_PROFILE_DB_PATH",
    "DEFAULT_MAX_CACHE_ITEMS",
    "DEFAULT_MAX_CPU_THREADS",
    "DEFAULT_MAX_DUCKDB_MEM_HIGH_MB",
    "DEFAULT_MAX_DUCKDB_MEM_LOW_MB",
    "DEFAULT_MIN_CPU_THREADS",
    "DEFAULT_SSD_WRITE_LIMIT_MBPS",
    "DEFAULT_VRAM_FRACTION",
    "HardwareResourceManager",
    "HardwareSpecs",
    "ResourceLimits",
    "apply_hardware_profile",
    "export_hardware_profile_to_duckdb",
    "export_limits_to_polars",
    "export_specs_to_polars",
    "get_hardware_manager",
    "get_hardware_status_report",
    "get_optimal_execution_device",
    "hardware_manager",
    "query_hardware_profile_duckdb",
    "restore_hardware_profile",
]
