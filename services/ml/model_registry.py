"""ALPHA BIST — Model Registry (Nihai).

Model version tracking, metrics storage, status management, lineage.
"""
import os
import json
import pickle
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()

# Model status lifecycle
MODEL_STATUSES = ["CANDIDATE", "CHAMPION", "SHADOW", "RETIRED", "FAILED"]


@dataclass
class ModelEntry:
    """Registry entry for a model."""
    model_id: str
    version: str
    model_type: str  # lightgbm, xgboost, catboost, stacking, etc.
    status: str = "CANDIDATE"
    metrics: Dict[str, Any] = field(default_factory=dict)
    hyperparams: Dict[str, Any] = field(default_factory=dict)
    features: List[str] = field(default_factory=list)
    training_data_hash: str = ""
    created_at: str = ""
    promoted_at: Optional[str] = None
    retired_at: Optional[str] = None
    description: str = ""
    tags: List[str] = field(default_factory=list)


class ModelRegistry:
    """Model kayıt defteri — version, metrics, status, lineage."""

    def __init__(self, registry_path: str = "data/model_registry"):
        self._registry_path = registry_path
        self._entries: Dict[str, ModelEntry] = {}
        self._models: Dict[str, Any] = {}  # actual model objects (in-memory)
        os.makedirs(registry_path, exist_ok=True)
        self._load_registry()

    def register(
        self,
        model_id: str,
        version: str,
        model: Any,
        model_type: str,
        metrics: Dict[str, Any],
        hyperparams: Optional[Dict[str, Any]] = None,
        features: Optional[List[str]] = None,
        training_data_hash: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> str:
        """Model kaydet.

        Returns:
            Registry key (model_id:version)
        """
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
            created_at=datetime.now(timezone.utc).isoformat(),
            description=description,
            tags=tags or [],
        )

        self._entries[key] = entry
        self._models[key] = model

        # Model'i diske kaydet
        self._save_model(key, model)
        self._save_registry()

        logger.info("model_registered", model_id=model_id, version=version, model_type=model_type)
        return key

    def promote(self, model_id: str, version: str) -> bool:
        """Model'i champion yap. Mevcut champion'ı retire eder."""
        key = f"{model_id}:{version}"

        if key not in self._entries:
            logger.warning("model_not_found", key=key)
            return False

        # Mevcut champion'ı retire et
        for k, v in self._entries.items():
            if v.model_id == model_id and v.status == "CHAMPION":
                v.status = "RETIRED"
                v.retired_at = datetime.now(timezone.utc).isoformat()
                logger.info("model_retired", key=k)

        # Yeni champion
        self._entries[key].status = "CHAMPION"
        self._entries[key].promoted_at = datetime.now(timezone.utc).isoformat()

        self._save_registry()
        logger.info("model_promoted", key=key)
        return True

    def reject(self, model_id: str, version: str) -> bool:
        """Model'i reddet (FAILED)."""
        key = f"{model_id}:{version}"
        if key not in self._entries:
            return False

        self._entries[key].status = "FAILED"
        self._save_registry()
        logger.info("model_rejected", key=key)
        return True

    def get_champion(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Champion model'i getir."""
        for key, entry in self._entries.items():
            if entry.model_id == model_id and entry.status == "CHAMPION":
                return {
                    "key": key,
                    "entry": entry,
                    "model": self._models.get(key),
                }
        return None

    def get_model(self, model_id: str, version: str) -> Optional[Any]:
        """Model objesini getir."""
        key = f"{model_id}:{version}"
        if key in self._models:
            return self._models[key]
        # Diskten yükle
        return self._load_model(key)

    def list_models(
        self,
        model_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Modelleri listele."""
        results = []
        for key, entry in self._entries.items():
            if model_id and entry.model_id != model_id:
                continue
            if status and entry.status != status:
                continue
            results.append({
                "key": key,
                "model_id": entry.model_id,
                "version": entry.version,
                "model_type": entry.model_type,
                "status": entry.status,
                "metrics": entry.metrics,
                "created_at": entry.created_at,
                "promoted_at": entry.promoted_at,
            })
        return sorted(results, key=lambda x: x["created_at"], reverse=True)

    def compare_versions(
        self, model_id: str, version_a: str, version_b: str
    ) -> Dict[str, Any]:
        """İki versiyonu karşılaştır."""
        key_a = f"{model_id}:{version_a}"
        key_b = f"{model_id}:{version_b}"

        entry_a = self._entries.get(key_a)
        entry_b = self._entries.get(key_b)

        if not entry_a or not entry_b:
            return {"error": "Version not found"}

        comparison = {"version_a": version_a, "version_b": version_b, "metrics_comparison": {}}

        all_metrics = set(list(entry_a.metrics.keys()) + list(entry_b.metrics.keys()))
        for metric in all_metrics:
            val_a = entry_a.metrics.get(metric, 0)
            val_b = entry_b.metrics.get(metric, 0)
            if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                diff = val_b - val_a
                pct = (diff / abs(val_a) * 100) if val_a != 0 else 0
                comparison["metrics_comparison"][metric] = {
                    "a": val_a, "b": val_b,
                    "diff": round(diff, 4),
                    "pct_change": round(pct, 2),
                    "b_better": diff > 0,
                }

        return comparison

    def _save_model(self, key: str, model: Any):
        """Model'i diske kaydet."""
        try:
            path = os.path.join(self._registry_path, f"{key.replace(':', '_')}.pkl")
            with open(path, "wb") as f:
                pickle.dump(model, f)
        except Exception as e:
            logger.error("model_save_failed", key=key, error=str(e))

    def _load_model(self, key: str) -> Optional[Any]:
        """Model'i diskten yükle."""
        try:
            path = os.path.join(self._registry_path, f"{key.replace(':', '_')}.pkl")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return pickle.load(f)
        except Exception as e:
            logger.error("model_load_failed", key=key, error=str(e))
        return None

    def _save_registry(self):
        """Registry metadata'sını diske kaydet."""
        try:
            data = {k: asdict(v) for k, v in self._entries.items()}
            path = os.path.join(self._registry_path, "registry.json")
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error("registry_save_failed", error=str(e))

    def _load_registry(self):
        """Registry metadata'sını diskten yükle."""
        try:
            path = os.path.join(self._registry_path, "registry.json")
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                for key, entry_dict in data.items():
                    self._entries[key] = ModelEntry(**entry_dict)
        except Exception as e:
            logger.warning("registry_load_failed", error=str(e))
