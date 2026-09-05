"""
ALPHA BIST — Deterministik Kurtarma Modülü

Restart sonrası aynı sonuç garantisi. Sistem durumunu persist eder
ve geri yükleyebilir.

Özellikler:
1. State serialization/deserialization
2. Deterministik random seed yönetimi
3. Config versioning ve snapshot
4. Recovery validation
5. Idempotent operation garantisi

Referanslar:
- BACKTEST-NIHAI-SPEC.md - Deterministic recovery
- 02-SISTEM-MIMARISI.md - 2.4 Idempotency
"""

import copy
import hashlib
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog

logger = structlog.get_logger(__name__)

# =====================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ)
# =====================================================================
DEFAULT_RANDOM_SEED: int = 42
DEFAULT_TOLERANCE: float = 1e-10
DEFAULT_MAX_CHECKPOINTS: int = 500
DEFAULT_KEEP_LAST_CHECKPOINTS: int = 10


@dataclass
class SystemCheckpoint:
    """Sistem checkpoint'i.

    Sistem durumunun tamamını tek bir veri yapısında tutar.
    Deterministik kurtarma için hash ile bütünlük doğrulaması sağlar.
    """

    checkpoint_id: str
    timestamp: datetime
    config_snapshot: dict[str, Any]
    portfolio_state: dict[str, Any]
    model_state: dict[str, Any] | None
    feature_cache_state: dict[str, Any]
    random_seed: int
    execution_counter: int
    hash_state: str  # Deterministik hash

    def __repr__(self) -> str:
        """SystemCheckpoint okunabilir temsili."""
        return (
            f"SystemCheckpoint("
            f"id={self.checkpoint_id!r}, "
            f"seed={self.random_seed}, "
            f"counter={self.execution_counter}, "
            f"hash={self.hash_state!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint'i sözlük formatına dönüştürür.

        Returns:
            Tüm alanları içeren sözlük (JSON serileştirme için)
        """
        return {
            "checkpoint_id": self.checkpoint_id,
            "timestamp": self.timestamp.isoformat(),
            "config_snapshot": self.config_snapshot,
            "portfolio_state": self.portfolio_state,
            "model_state": self.model_state,
            "feature_cache_state": self.feature_cache_state,
            "random_seed": self.random_seed,
            "execution_counter": self.execution_counter,
            "hash_state": self.hash_state,
        }

    def compute_state_hash(self) -> str:
        """Durum hash'i hesapla (deterministik kontrol için).

        Returns:
            SHA-256 tabanlı 16 karakterlik hash
        """
        content = orjson.dumps(
            {
                "config": self.config_snapshot,
                "portfolio": self.portfolio_state,
                "seed": self.random_seed,
                "counter": self.execution_counter,
            },
            option=orjson.OPT_SORT_KEYS,
            default=str,
        )
        raw_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()[:16]


class DeterministicRecovery:
    """
    Deterministik recovery yöneticisi.

    Sistem durumunu checkpoint'ler ve restart sonrası
    aynı sonuçları garanti eder.
    """

    def __init__(self, storage_path: str | None = None) -> None:
        """Deterministik recovery yöneticisini başlatır.

        Args:
            storage_path: Checkpoint depolama yolu (varsayılan: .alpha_checkpoints)
        """
        self._storage_path = Path(storage_path) if storage_path else Path(".alpha_checkpoints")
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._checkpoints: list[SystemCheckpoint] = []
        self._current_seed: int = DEFAULT_RANDOM_SEED
        self._execution_counter: int = 0
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        """DeterministicRecovery okunabilir temsili."""
        with self._lock:
            cp_count = len(self._checkpoints)
            seed = self._current_seed
            counter = self._execution_counter
        return (
            f"DeterministicRecovery("
            f"checkpoints={cp_count}, "
            f"seed={seed}, "
            f"counter={counter})"
        )

    def set_seed(self, seed: int = DEFAULT_RANDOM_SEED) -> None:
        """Random seed ayarla (deterministik sonuçlar için).

        Args:
            seed: Ayarlanacak seed değeri
        """
        with self._lock:
            self._current_seed = seed
            np.random.seed(seed)
        logger.info("random_seed_ayarlandi: seed=%s", seed)

    def create_checkpoint(
        self,
        config: dict[str, Any],
        portfolio_state: dict[str, Any],
        model_state: dict[str, Any] | None = None,
        feature_cache: dict[str, Any] | None = None,
    ) -> SystemCheckpoint:
        """
        Sistem checkpoint'i oluştur.

        Args:
            config: Sistem konfigürasyonu
            portfolio_state: Portföy durumu
            model_state: Model durumu (opsiyonel)
            feature_cache: Feature cache durumu

        Returns:
            SystemCheckpoint nesnesi
        """
        checkpoint_id = (
            f"cp_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
            f"_{self._execution_counter:06d}"
        )

        # Deep copy ile nested yapıların sonradan değiştirilmesini önle
        checkpoint = SystemCheckpoint(
            checkpoint_id=checkpoint_id,
            timestamp=datetime.now(UTC),
            config_snapshot=copy.deepcopy(config),
            portfolio_state=copy.deepcopy(portfolio_state),
            model_state=copy.deepcopy(model_state) if model_state else None,
            feature_cache_state=copy.deepcopy(feature_cache or {}),
            random_seed=self._current_seed,
            execution_counter=self._execution_counter,
            hash_state="",
        )
        checkpoint.hash_state = checkpoint.compute_state_hash()

        self._checkpoints.append(checkpoint)
        if len(self._checkpoints) > 500:
            self._checkpoints = self._checkpoints[-500:]
        self._persist_checkpoint(checkpoint)

        logger.info(
            "checkpoint_olusturuldu: id=%s, hash=%s",
            checkpoint_id,
            checkpoint.hash_state,
        )

        return checkpoint

    def restore_checkpoint(
        self,
        checkpoint_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], int]:
        """
        Checkpoint'ten durum geri yükle.

        Args:
            checkpoint_id: Geri yüklenecek checkpoint ID (None = son checkpoint)

        Returns:
            (config, portfolio_state, random_seed) üçlüsü

        Raises:
            ValueError: Checkpoint bulunamazsa veya bütünlük kontrolü başarısızsa
        """
        if checkpoint_id:
            checkpoint = None
            for cp in self._checkpoints:
                if cp.checkpoint_id == checkpoint_id:
                    checkpoint = cp
                    break
            if checkpoint is None:
                # Disk'ten yüklemeyi dene
                checkpoint = self._load_checkpoint(checkpoint_id)
        else:
            checkpoint = self._checkpoints[-1] if self._checkpoints else None

        if checkpoint is None:
            raise ValueError(f"Checkpoint bulunamadı: {checkpoint_id}")

        # Bütünlük kontrolü
        expected_hash = checkpoint.compute_state_hash()
        if checkpoint.hash_state != expected_hash:
            logger.error(
                "checkpoint_hash_uyusmazligi: id=%s, beklenen=%s, mevcut=%s",
                checkpoint.checkpoint_id,
                expected_hash,
                checkpoint.hash_state,
            )
            raise ValueError("Checkpoint bütünlük kontrolü başarısız")

        # Durumu geri yükle
        self._current_seed = checkpoint.random_seed
        self._execution_counter = checkpoint.execution_counter
        np.random.seed(self._current_seed)

        logger.info(
            "checkpoint_yuklendi: id=%s, seed=%s",
            checkpoint.checkpoint_id,
            self._current_seed,
        )

        return (
            checkpoint.config_snapshot,
            checkpoint.portfolio_state,
            checkpoint.random_seed,
        )

    def validate_determinism(
        self,
        func: Any,
        args: tuple,
        expected_result: Any,
        tolerance: float = 1e-10,
    ) -> tuple[bool, Any]:
        """
        Fonksiyonun deterministik olduğunu doğrula.

        Aynı seed ve argümanlarla aynı sonucu üretmeli.

        Args:
            func: Test edilecek fonksiyon
            args: Fonksiyon argümanları
            expected_result: Beklenen sonuç
            tolerance: Float toleransı

        Returns:
            (is_deterministic, actual_result) çifti
        """
        np.random.seed(self._current_seed)

        actual = func(*args)

        if isinstance(expected_result, (int, float)):
            is_det = abs(actual - expected_result) < tolerance
        elif isinstance(expected_result, np.ndarray):
            is_det = np.allclose(actual, expected_result, atol=tolerance)
        elif isinstance(expected_result, list):
            is_det = all(
                abs(a - e) < tolerance
                for a, e in zip(actual, expected_result, strict=False)
                if isinstance(a, (int, float)) and isinstance(e, (int, float))
            )
        else:
            is_det = actual == expected_result

        if not is_det:
            logger.warning(
                "determinizm_kontrolu_basarisiz: beklenen=%s, gercek=%s",
                str(expected_result)[:100],
                str(actual)[:100],
            )

        return is_det, actual

    def generate_reproduction_report(
        self,
        original_run_id: str,
        reproduction_run_id: str,
        original_metrics: dict[str, float],
        reproduction_metrics: dict[str, float],
        tolerance: float = 0.001,
    ) -> dict[str, Any]:
        """
        Reproducibility raporu oluştur.

        Args:
            original_run_id: Orijinal çalıştırma ID'si
            reproduction_run_id: Reprodüksiyon ID'si
            original_metrics: Orijinal metrikler
            reproduction_metrics: Reprodüksiyon metrikleri
            tolerance: Tolerans

        Returns:
            Reproducibility raporu sözlüğü
        """
        discrepancies = []

        for key in original_metrics:
            if key in reproduction_metrics:
                orig = original_metrics[key]
                repro = reproduction_metrics[key]

                if isinstance(orig, (int, float)) and isinstance(repro, (int, float)):
                    diff = abs(orig - repro)
                    if diff > tolerance:
                        discrepancies.append(
                            {
                                "metric": key,
                                "original": round(orig, 6),
                                "reproduction": round(repro, 6),
                                "difference": round(diff, 6),
                                "relative_diff_pct": (
                                    round(diff / abs(orig) * 100, 4)
                                    if orig != 0
                                    else float("inf")
                                ),
                            }
                        )

        is_reproducible = len(discrepancies) == 0

        report = {
            "original_run_id": original_run_id,
            "reproduction_run_id": reproduction_run_id,
            "is_reproducible": is_reproducible,
            "tolerance": tolerance,
            "total_metrics_compared": len(original_metrics),
            "discrepancies": discrepancies,
            "verdict": "PASS" if is_reproducible else "FAIL",
        }

        logger.info(
            "reproduction_raporu: sonuc=%s, uyumsuzluk=%s",
            report["verdict"],
            len(discrepancies),
        )

        return report

    def _persist_checkpoint(self, checkpoint: SystemCheckpoint) -> None:
        """Checkpoint'i diske yaz.

        Args:
            checkpoint: Yazılacak checkpoint nesnesi
        """
        filepath = self._storage_path / f"{checkpoint.checkpoint_id}.json"
        try:
            with open(filepath, "w") as f:
                f.write(
                    orjson.dumps(
                        checkpoint.to_dict(),
                        option=orjson.OPT_INDENT_2,
                        default=str,
                    ).decode()
                )
        except Exception as e:
            logger.warning(
                "checkpoint_kayit_basarisiz: id=%s, hata=%s",
                checkpoint.checkpoint_id,
                str(e),
            )

    def _load_checkpoint(self, checkpoint_id: str) -> SystemCheckpoint | None:
        """Checkpoint'i diskten yükle.

        Args:
            checkpoint_id: Yüklenecek checkpoint ID'si

        Returns:
            SystemCheckpoint veya None (bulunamazsa/hatalıysa)
        """
        filepath = self._storage_path / f"{checkpoint_id}.json"
        if not filepath.exists():
            return None

        try:
            with open(filepath) as f:
                data = orjson.loads(f.read())
            return SystemCheckpoint(
                checkpoint_id=data["checkpoint_id"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                config_snapshot=data["config_snapshot"],
                portfolio_state=data["portfolio_state"],
                model_state=data.get("model_state"),
                feature_cache_state=data.get("feature_cache_state", {}),
                random_seed=data["random_seed"],
                execution_counter=data["execution_counter"],
                hash_state=data["hash_state"],
            )
        except Exception as e:
            logger.error(
                "checkpoint_yukleme_basarisiz: id=%s, hata=%s",
                checkpoint_id,
                str(e),
            )
            return None

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """Mevcut checkpoint'leri listele.

        Returns:
            Her checkpoint için id, timestamp ve hash içeren sözlük listesi
        """
        checkpoints = []
        for filepath in sorted(self._storage_path.glob("cp_*.json")):
            try:
                with open(filepath) as f:
                    data = orjson.loads(f.read())
                checkpoints.append(
                    {
                        "checkpoint_id": data["checkpoint_id"],
                        "timestamp": data["timestamp"],
                        "hash": data["hash_state"],
                    }
                )
            except Exception as e:
                logger.debug(
                    "checkpoint_okuma_hatasi: dosya=%s, hata=%s",
                    filepath.name,
                    str(e),
                )
        return checkpoints

    def cleanup_old_checkpoints(self, keep_last: int = 10) -> None:
        """Eski checkpoint'leri temizle.

        Args:
            keep_last: Son kaç checkpoint'in tutulacağı
        """
        files = sorted(self._storage_path.glob("cp_*.json"))
        if len(files) > keep_last:
            for filepath in files[:-keep_last]:
                try:
                    filepath.unlink()
                    logger.info("eski_checkpoint_silindi: dosya=%s", filepath.name)
                except Exception as e:
                    logger.warning(
                        "checkpoint_silme_basarisiz: dosya=%s, hata=%s",
                        filepath.name,
                        str(e),
                    )


class IdempotencyGuard:
    """
    İdempotent işlem garantisi.

    Aynı işlemin birden fazla kez çalıştırılması aynı sonucu üretmeli.
    """

    def __init__(self) -> None:
        """İdempotency guard'ı başlatır."""
        self._executed_operations: dict[str, Any] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        """IdempotencyGuard okunabilir temsili."""
        with self._lock:
            count = len(self._executed_operations)
        return f"IdempotencyGuard(cached={count})"

    def compute_operation_hash(self, operation: str, params: dict[str, Any]) -> str:
        """İşlem hash'i hesapla.

        Args:
            operation: İşlem adı
            params: İşlem parametreleri

        Returns:
            SHA-256 tabanlı 16 karakterlik hash
        """
        content = (
            f"{operation}:"
            f"{orjson.dumps(params, option=orjson.OPT_SORT_KEYS, default=str).decode()}"
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def is_already_executed(self, operation: str, params: dict[str, Any]) -> bool:
        """İşlem daha önce yapılmış mı?

        Args:
            operation: İşlem adı
            params: İşlem parametreleri

        Returns:
            True ise işlem daha önce yapılmış
        """
        op_hash = self.compute_operation_hash(operation, params)
        with self._lock:
            return op_hash in self._executed_operations

    def record_execution(self, operation: str, params: dict[str, Any], result: Any) -> None:
        """İşlem kaydı yap.

        Args:
            operation: İşlem adı
            params: İşlem parametreleri
            result: İşlem sonucu
        """
        op_hash = self.compute_operation_hash(operation, params)
        with self._lock:
            self._executed_operations[op_hash] = {
                "operation": operation,
                "params": params,
                "result": result,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def get_or_execute(
        self,
        operation: str,
        params: dict[str, Any],
        func: Any,
        *args,
        **kwargs,
    ) -> Any:
        """
        İdempotent işlem çalıştır.

        Daha önce yapılmışsa kayıtlı sonucu döndürür,
        yoksa çalıştırıp kaydeder.

        Args:
            operation: İşlem adı
            params: İşlem parametreleri
            func: Çalıştırılacak fonksiyon
            *args: Fonksiyon pozisyonel argümanları
            **kwargs: Fonksiyon anahtar kelime argümanları

        Returns:
            İşlem sonucu
        """
        op_hash = self.compute_operation_hash(operation, params)
        with self._lock:
            if op_hash in self._executed_operations:
                logger.debug("onbellekten_getiriliyor: islem=%s", operation)
                return self._executed_operations[op_hash]["result"]

        result = func(*args, **kwargs)
        self.record_execution(operation, params, result)
        return result

    def clear_cache(self) -> None:
        """Önbelleği temizle."""
        with self._lock:
            self._executed_operations.clear()


# Singleton
deterministic_recovery = DeterministicRecovery()
idempotency_guard = IdempotencyGuard()

__all__ = [
    "SystemCheckpoint",
    "DeterministicRecovery",
    "IdempotencyGuard",
    "deterministic_recovery",
    "idempotency_guard",
    "DEFAULT_RANDOM_SEED",
    "DEFAULT_TOLERANCE",
    "DEFAULT_MAX_CHECKPOINTS",
    "DEFAULT_KEEP_LAST_CHECKPOINTS",
]
