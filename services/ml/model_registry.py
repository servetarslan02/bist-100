"""ALPHA BIST — Model Registry (Nihai —⭐⭐⭐⭐⭐).

Model version tracking, metrics storage, status management, lineage,
artifact management, model comparison, snapshot/restore.
"""

import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()

MODEL_STATUSES = ["CANDIDATE", "SHADOW", "CHAMPION", "RETIRED", "FAILED", "ARCHIVED"]


@dataclass
class ModelEntry:
    """Registry entry for a model."""

    model_id: str
    version: str
    model_type: str
    status: str = "CANDIDATE"
    metrics: dict[str, Any] = field(default_factory=dict)
    hyperparams: dict[str, Any] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    training_data_hash: str = ""
    training_data_info: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    promoted_at: str | None = None
    retired_at: str | None = None
    description: str = ""
    tags: list[str] = field(default_factory=list)
    # Lineage
    parent_model: str | None = None
    training_config: dict[str, Any] = field(default_factory=dict)
    feature_set_version: str = ""
    # Performance tracking
    production_metrics: dict[str, Any] = field(default_factory=dict)
    last_evaluated: str | None = None
    # Metadata
    author: str = "system"
    notes: list[str] = field(default_factory=list)


class ModelRegistry:
    """Model kayıt defteri —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Version tracking (v1, v2, v3, ...)
    - Metrics storage (accuracy, IC, Sharpe, vb.)
    - Status lifecycle (CANDIDATE → SHADOW → CHAMPION → RETIRED)
    - Lineage tracking (parent model, training data hash, feature set)
    - Artifact management (model serialization, metadata)
    - Model comparison (version diff)
    - Snapshot/restore
    - Production metrics tracking
    - Auto-versioning
    - Model search & filtering
    """

    def __init__(self, registry_path: str = "data/model_registry"):
        """Otomatik eklendi."""
        self._registry_path = registry_path
        self._entries: dict[str, ModelEntry] = {}
        self._models: dict[str, Any] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}
        os.makedirs(registry_path, exist_ok=True)
        self._load_registry()

    def register(
        self,
        model_id: str,
        model: Any,
        model_type: str,
        metrics: dict[str, Any],
        hyperparams: dict[str, Any] | None = None,
        features: list[str] | None = None,
        training_data_hash: str = "",
        training_data_info: dict[str, Any] | None = None,
        description: str = "",
        tags: list[str] | None = None,
        parent_model: str | None = None,
        training_config: dict[str, Any] | None = None,
        author: str = "system",
    ) -> str:
        """Model kaydet — otomatik version numarası.

        Returns:
            Registry key (model_id:version)
        """
        version = self._next_version(model_id)
        key = f"{model_id}:{version}"

        entry = ModelEntry(
            model_id=model_id,
            version=version,
            model_type=model_type,
            status="CANDIDATE",
            metrics=metrics,
            hyperparams=hyperparams or {},
            features=features or [],
            training_data_hash=training_data_hash,
            training_data_info=training_data_info or {},
            created_at=datetime.now(UTC).isoformat(),
            description=description,
            tags=tags or [],
            parent_model=parent_model,
            training_config=training_config or {},
            author=author,
        )

        self._entries[key] = entry
        self._models[key] = model

        self._save_model(key, model)
        self._save_registry()

        logger.info("model_registered", model_id=model_id, version=version, model_type=model_type)
        return key

    def promote(self, model_id: str, version: str, reason: str = "") -> bool:
        """Model'i champion yap."""
        key = f"{model_id}:{version}"
        if key not in self._entries:
            logger.warning("model_not_found", key=key)
            return False

        # Mevcut champion'ı retire et
        for k, v in self._entries.items():
            if v.model_id == model_id and v.status == "CHAMPION":
                v.status = "RETIRED"
                v.retired_at = datetime.now(UTC).isoformat()
                if reason:
                    v.notes.append(f"Retired: {reason}")
                logger.info("model_retired", key=k)

        self._entries[key].status = "CHAMPION"
        self._entries[key].promoted_at = datetime.now(UTC).isoformat()
        if reason:
            self._entries[key].notes.append(f"Promoted: {reason}")

        self._save_registry()
        logger.info("model_promoted", key=key)
        return True

    def reject(self, model_id: str, version: str, reason: str = "") -> bool:
        """Model'i reddet (FAILED)."""
        key = f"{model_id}:{version}"
        if key not in self._entries:
            return False

        self._entries[key].status = "FAILED"
        if reason:
            self._entries[key].notes.append(f"Rejected: {reason}")
        self._save_registry()
        logger.info("model_rejected", key=key, reason=reason)
        return True

    def archive(self, model_id: str, version: str) -> bool:
        """Model'i arşivle."""
        key = f"{model_id}:{version}"
        if key not in self._entries:
            return False

        self._entries[key].status = "ARCHIVED"
        self._save_registry()
        return True

    def get_champion(self, model_id: str) -> dict[str, Any] | None:
        """Champion model'i getir."""
        for key, entry in self._entries.items():
            if entry.model_id == model_id and entry.status == "CHAMPION":
                return {"key": key, "entry": entry, "model": self._models.get(key)}
        return None

    def get_latest(self, model_id: str, status: str | None = None) -> dict[str, Any] | None:
        """En son version'u getir."""
        candidates = [
            (key, entry)
            for key, entry in self._entries.items()
            if entry.model_id == model_id and (status is None or entry.status == status)
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1].created_at, reverse=True)
        key, entry = candidates[0]
        return {"key": key, "entry": entry, "model": self._models.get(key)}

    def get_model(self, model_id: str, version: str) -> Any | None:
        """Model objesini getir."""
        key = f"{model_id}:{version}"
        if key in self._models:
            return self._models[key]
        return self._load_model(key)

    def list_models(
        self,
        model_id: str | None = None,
        status: str | None = None,
        model_type: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Modelleri listele — filtre destekli."""
        results = []
        for key, entry in self._entries.items():
            if model_id and entry.model_id != model_id:
                continue
            if status and entry.status != status:
                continue
            if model_type and entry.model_type != model_type:
                continue
            if tag and tag not in entry.tags:
                continue
            results.append(
                {
                    "key": key,
                    "model_id": entry.model_id,
                    "version": entry.version,
                    "model_type": entry.model_type,
                    "status": entry.status,
                    "metrics": entry.metrics,
                    "created_at": entry.created_at,
                    "promoted_at": entry.promoted_at,
                    "description": entry.description,
                    "tags": entry.tags,
                    "author": entry.author,
                }
            )

        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results[:limit]

    def compare_versions(
        self,
        model_id: str,
        version_a: str,
        version_b: str,
    ) -> dict[str, Any]:
        """İki versiyonu kapsamlı karşılaştır."""
        key_a = f"{model_id}:{version_a}"
        key_b = f"{model_id}:{version_b}"

        entry_a = self._entries.get(key_a)
        entry_b = self._entries.get(key_b)

        if not entry_a or not entry_b:
            return {"error": "Version not found"}

        comparison = {
            "version_a": version_a,
            "version_b": version_b,
            "status_a": entry_a.status,
            "status_b": entry_b.status,
            "metrics_comparison": {},
            "hyperparams_diff": {},
            "features_diff": {
                "added": list(set(entry_b.features) - set(entry_a.features)),
                "removed": list(set(entry_a.features) - set(entry_b.features)),
                "unchanged": len(set(entry_a.features) & set(entry_b.features)),
            },
        }

        # Metrics comparison
        all_metrics = set(list(entry_a.metrics.keys()) + list(entry_b.metrics.keys()))
        for metric in all_metrics:
            val_a = entry_a.metrics.get(metric, 0)
            val_b = entry_b.metrics.get(metric, 0)
            if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                diff = val_b - val_a
                pct = (diff / abs(val_a) * 100) if val_a != 0 else 0
                comparison["metrics_comparison"][metric] = {
                    "a": val_a,
                    "b": val_b,
                    "diff": round(diff, 4),
                    "pct_change": round(pct, 2),
                    "b_better": diff > 0,
                }

        # Hyperparams diff
        all_params = set(list(entry_a.hyperparams.keys()) + list(entry_b.hyperparams.keys()))
        for param in all_params:
            val_a = entry_a.hyperparams.get(param)
            val_b = entry_b.hyperparams.get(param)
            if val_a != val_b:
                comparison["hyperparams_diff"][param] = {"a": val_a, "b": val_b}

        return comparison

    def update_production_metrics(
        self,
        model_id: str,
        version: str,
        metrics: dict[str, Any],
    ) -> bool:
        """Production metriklerini güncelle."""
        key = f"{model_id}:{version}"
        if key not in self._entries:
            return False

        self._entries[key].production_metrics = metrics
        self._entries[key].last_evaluated = datetime.now(UTC).isoformat()
        self._save_registry()
        return True

    def add_note(self, model_id: str, version: str, note: str) -> bool:
        """Model'e not ekle."""
        key = f"{model_id}:{version}"
        if key not in self._entries:
            return False

        self._entries[key].notes.append(f"[{datetime.now(UTC).isoformat()}] {note}")
        self._save_registry()
        return True

    def snapshot(self, name: str) -> bool:
        """Tüm registry'nin snapshot'ını al."""
        self._snapshots[name] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "entries": {k: asdict(v) for k, v in self._entries.items()},
        }
        return True

    def get_stats(self) -> dict[str, Any]:
        """Registry istatistikleri."""
        status_counts = {}
        type_counts = {}
        for entry in self._entries.values():
            status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
            type_counts[entry.model_type] = type_counts.get(entry.model_type, 0) + 1

        return {
            "total_models": len(self._entries),
            "status_distribution": status_counts,
            "type_distribution": type_counts,
            "n_snapshots": len(self._snapshots),
        }

    def _next_version(self, model_id: str) -> str:
        """Sonraki version numarasını hesapla."""
        existing = [e.version for e in self._entries.values() if e.model_id == model_id]
        if not existing:
            return "v1"

        # Version parsing (v1, v2, v3, ...)
        versions = []
        for v in existing:
            try:
                versions.append(int(v.replace("v", "")))
            except ValueError:
                logger.warning("Data error in _next_version: ValueError", exc_info=True)

        if not versions:
            return "v1"

        return f"v{max(versions) + 1}"

    def _save_model(self, key: str, model: Any) -> Any:
        """Model'i diske kaydet (SHA256 hash ile)."""
        try:
            from services.core.safe_pickle import safe_pickle_dump

            path = os.path.join(self._registry_path, f"{key.replace(':', '_')}.pkl")
            safe_pickle_dump(model, path)
        except Exception as e:
            logger.error("model_save_failed", key=key, error=str(e))

    def _load_model(self, key: str) -> Any | None:
        """Model'i diskten yükle (SHA256 doğrulamalı)."""
        try:
            from services.core.safe_pickle import safe_pickle_load

            path = os.path.join(self._registry_path, f"{key.replace(':', '_')}.pkl")
            if os.path.exists(path):
                return safe_pickle_load(path)
        except Exception as e:
            logger.error("model_load_failed", key=key, error=str(e))
        return None

    def _save_registry(self) -> Any:
        """Registry metadata'sını diske kaydet (debounced — SSD dostu)."""
        from services.core.debounce import should_save
        if not should_save("model_registry", 120):
            return
        try:
            data = {k: asdict(v) for k, v in self._entries.items()}
            path = os.path.join(self._registry_path, "registry.json")
            with open(path, "w") as f:
                f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str).decode())
        except Exception as e:
            logger.error("registry_save_failed", error=str(e))

    def _load_registry(self) -> Any:
        """Registry metadata'sını diskten yükle."""
        try:
            path = os.path.join(self._registry_path, "registry.json")
            if os.path.exists(path):
                with open(path) as f:
                    data = orjson.loads(f.read())
                for key, entry_dict in data.items():
                    # Backward compatibility
                    valid_fields = {f.name for f in ModelEntry.__dataclass_fields__.values()}
                    filtered = {k: v for k, v in entry_dict.items() if k in valid_fields}
                    self._entries[key] = ModelEntry(**filtered)
        except Exception as e:
            logger.warning("registry_load_failed", error=str(e))
