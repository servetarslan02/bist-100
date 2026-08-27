"""
ALPHA BIST — Deterministic Recovery Module

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

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog

logger = structlog.get_logger()


@dataclass
class SystemCheckpoint:
    """Sistem checkpoint'i."""

    checkpoint_id: str
    timestamp: datetime
    config_snapshot: dict[str, Any]
    portfolio_state: dict[str, Any]
    model_state: dict[str, Any] | None
    feature_cache_state: dict[str, Any]
    random_seed: int
    execution_counter: int
    hash_state: str  # Deterministik hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "timestamp": self.timestamp.isoformat(),
            "config_snapshot": self.config_snapshot,
            "portfolio_state": self.portfolio_state,
            "random_seed": self.random_seed,
            "execution_counter": self.execution_counter,
            "hash_state": self.hash_state,
        }

    def compute_state_hash(self) -> str:
        """Durum hash'i hesapla (deterministik kontrol için)."""
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
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class DeterministicRecovery:
    """
    Deterministik recovery yöneticisi.

    Sistem durumunu checkpoint'ler ve restart sonrası
    aynı sonuçları garanti eder.
    """

    def __init__(self, storage_path: str | None = None):
        self._storage_path = Path(storage_path) if storage_path else Path(".alpha_checkpoints")
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._checkpoints: list[SystemCheckpoint] = []
        self._current_seed: int = 42
        self._execution_counter: int = 0

    def set_seed(self, seed: int = 42):
        """Random seed ayarla (deterministik sonuçlar için)."""
        self._current_seed = seed
        np.random.seed(seed)
        logger.info("Random seed set", seed=seed)

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
            SystemCheckpoint
        """
        checkpoint_id = f"cp_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{self._execution_counter:06d}"

        checkpoint = SystemCheckpoint(
            checkpoint_id=checkpoint_id,
            timestamp=datetime.now(UTC),
            config_snapshot=config.copy(),
            portfolio_state=portfolio_state.copy(),
            model_state=model_state.copy() if model_state else None,
            feature_cache_state=(feature_cache or {}).copy(),
            random_seed=self._current_seed,
            execution_counter=self._execution_counter,
            hash_state="",
        )
        checkpoint.hash_state = checkpoint.compute_state_hash()

        self._checkpoints.append(checkpoint)
        if len(self._checkpoints) > 500:
            self._checkpoints = self._checkpoints[-500:]
        self._persist_checkpoint(checkpoint)

        logger.info("Checkpoint created", checkpoint_id=checkpoint_id, hash=checkpoint.hash_state)

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
            (config, portfolio_state, random_seed)
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
            raise ValueError(f"Checkpoint not found: {checkpoint_id}")

        # Validate hash
        expected_hash = checkpoint.compute_state_hash()
        if checkpoint.hash_state != expected_hash:
            logger.error(
                "Checkpoint hash mismatch",
                checkpoint_id=checkpoint.checkpoint_id,
                expected=expected_hash,
                actual=checkpoint.hash_state,
            )
            raise ValueError("Checkpoint integrity check failed")

        # Restore state
        self._current_seed = checkpoint.random_seed
        self._execution_counter = checkpoint.execution_counter
        np.random.seed(self._current_seed)

        logger.info("Checkpoint restored", checkpoint_id=checkpoint.checkpoint_id, seed=self._current_seed)

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
            (is_deterministic, actual_result)
        """
        # Set seed
        np.random.seed(self._current_seed)

        # Run function
        actual = func(*args)

        # Compare
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
            logger.warning("Determinism check failed", expected=str(expected_result)[:100], actual=str(actual)[:100])

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
            Reproducibility raporu
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
                                "relative_diff_pct": round(diff / abs(orig) * 100, 4) if orig != 0 else float("inf"),
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

        logger.info("Reproduction report", verdict=report["verdict"], discrepancies=len(discrepancies))

        return report

    def _persist_checkpoint(self, checkpoint: SystemCheckpoint):
        """Checkpoint'i diske yaz."""
        filepath = self._storage_path / f"{checkpoint.checkpoint_id}.json"
        try:
            with open(filepath, "w") as f:
                f.write(orjson.dumps(checkpoint.to_dict(), option=orjson.OPT_INDENT_2, default=str).decode())
        except Exception as e:
            logger.warning("Failed to persist checkpoint", checkpoint_id=checkpoint.checkpoint_id, error=str(e))

    def _load_checkpoint(self, checkpoint_id: str) -> SystemCheckpoint | None:
        """Checkpoint'i diskten yükle."""
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
            logger.error("Failed to load checkpoint", checkpoint_id=checkpoint_id, error=str(e))
            return None

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """Mevcut checkpoint'leri listele."""
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
                logger.debug("Handled exception", error=str(e), context="deterministic.py:338")
        return checkpoints

    def cleanup_old_checkpoints(self, keep_last: int = 10):
        """Eski checkpoint'leri temizle."""
        files = sorted(self._storage_path.glob("cp_*.json"))
        if len(files) > keep_last:
            for filepath in files[:-keep_last]:
                filepath.unlink()
                logger.info("Removed old checkpoint", file=filepath.name)


class IdempotencyGuard:
    """
    İdempotent işlem garantisi.

    Aynı işlemin birden fazla kez çalıştırılması aynı sonucu üretmeli.
    """

    def __init__(self):
        self._executed_operations: dict[str, Any] = {}

    def compute_operation_hash(self, operation: str, params: dict[str, Any]) -> str:
        """İşlem hash'i hesapla."""
        content = f"{operation}:{orjson.dumps(params, option=orjson.OPT_SORT_KEYS, default=str).decode()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def is_already_executed(self, operation: str, params: dict[str, Any]) -> bool:
        """İşlem daha önce yapılmış mı?"""
        op_hash = self.compute_operation_hash(operation, params)
        return op_hash in self._executed_operations

    def record_execution(self, operation: str, params: dict[str, Any], result: Any):
        """İşlem kaydı yap."""
        op_hash = self.compute_operation_hash(operation, params)
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
        """
        if self.is_already_executed(operation, params):
            logger.debug("Returning cached result", operation=operation)
            return self._executed_operations[self.compute_operation_hash(operation, params)]["result"]

        result = func(*args, **kwargs)
        self.record_execution(operation, params, result)
        return result

    def clear_cache(self):
        """Cache'i temizle."""
        self._executed_operations.clear()


# Singleton
deterministic_recovery = DeterministicRecovery()
idempotency_guard = IdempotencyGuard()
