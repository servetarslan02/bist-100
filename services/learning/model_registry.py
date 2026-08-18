"""
ALPHA BIST — Model Registry v1.0

Model versiyon kayıt defteri:
- Version tracking (metadata, metrics, features)
- Performance history
- Rollback desteği
- Auto-cleanup

KURAL: Her model versiyonu izlenebilir olmalı.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from services.learning.config.learning_config import learning_settings

logger = structlog.get_logger()


@dataclass
class ModelRecord:
    """Model kayıt kaydı."""
    model_id: str
    version: str
    created_at: str
    status: str  # CANDIDATE, SHADOW, CHAMPION, RETIRED
    metrics: Dict
    features: List[str]
    hyperparameters: Dict
    training_data_info: Dict
    regime: str
    performance_history: List[Dict] = field(default_factory=list)
    retired_at: Optional[str] = None
    retired_reason: Optional[str] = None


class ModelRegistry:
    """Model versiyon kayıt defteri."""

    def __init__(self):
        self._records: List[ModelRecord] = []
        self._active_versions: Dict[str, str] = {}  # regime → version

    def register(
        self,
        model_id: str,
        version: str,
        metrics: Dict,
        features: List[str],
        hyperparameters: Dict,
        training_data_info: Dict,
        regime: str = "UNKNOWN",
        status: str = "CANDIDATE",
    ) -> ModelRecord:
        """Yeni model versiyonu kaydet."""
        record = ModelRecord(
            model_id=model_id,
            version=version,
            created_at=datetime.now(timezone.utc).isoformat(),
            status=status,
            metrics=metrics,
            features=features,
            hyperparameters=hyperparameters,
            training_data_info=training_data_info,
            regime=regime,
        )

        self._records.append(record)
        self._cleanup_old_versions()

        logger.info("Model registered", model_id=model_id, version=version, status=status)
        return record

    def promote_to_champion(self, version: str, regime: str = "UNKNOWN"):
        """Versiyonu champion yap."""
        for r in self._records:
            if r.status == "CHAMPION" and r.regime == regime:
                r.status = "RETIRED"
                r.retired_at = datetime.now(timezone.utc).isoformat()
                r.retired_reason = "Superseded by new champion"

        record = self._get_version(version)
        if record:
            record.status = "CHAMPION"
            self._active_versions[regime] = version
            logger.info("Model promoted to champion", version=version, regime=regime)

    def promote_to_shadow(self, version: str):
        """Versiyonu shadow mode'a al."""
        record = self._get_version(version)
        if record:
            record.status = "SHADOW"
            logger.info("Model promoted to shadow", version=version)

    def rollback(self, to_version: str) -> bool:
        """Önceki versiyona geri dön."""
        record = self._get_version(to_version)
        if record and record.status == "RETIRED":
            record.status = "CHAMPION"
            record.retired_at = None
            record.retired_reason = None
            logger.info("Rollback successful", version=to_version)
            return True
        return False

    def get_champion(self, regime: str = "UNKNOWN") -> Optional[ModelRecord]:
        """Mevcut champion model."""
        version = self._active_versions.get(regime)
        if version:
            return self._get_version(version)

        for r in self._records:
            if r.status == "CHAMPION" and r.regime == regime:
                return r
        return None

    def get_version(self, version: str) -> Optional[ModelRecord]:
        """Versiyon detayı."""
        return self._get_version(version)

    def get_all_versions(self) -> List[Dict]:
        """Tüm versiyonlar."""
        return [
            {
                "model_id": r.model_id,
                "version": r.version,
                "status": r.status,
                "created_at": r.created_at,
                "regime": r.regime,
                "metrics": r.metrics,
            }
            for r in self._records
        ]

    def add_performance_record(self, version: str, metrics: Dict):
        """Performans kaydı ekle."""
        record = self._get_version(version)
        if record:
            record.performance_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **metrics,
            })

    def get_report(self) -> Dict[str, Any]:
        """Rapor."""
        champions = [r for r in self._records if r.status == "CHAMPION"]
        shadows = [r for r in self._records if r.status == "SHADOW"]
        retired = [r for r in self._records if r.status == "RETIRED"]

        return {
            "total_versions": len(self._records),
            "champions": len(champions),
            "shadows": len(shadows),
            "retired": len(retired),
            "active_versions": self._active_versions,
        }

    def _get_version(self, version: str) -> Optional[ModelRecord]:
        """Versiyon bul."""
        for r in self._records:
            if r.version == version:
                return r
        return None

    def _cleanup_old_versions(self):
        """Eski versiyonları temizle."""
        cfg = learning_settings.model_registry
        if not cfg.auto_cleanup:
            return

        # Champion ve shadow'ları koru
        protected = {r.version for r in self._records if r.status in ["CHAMPION", "SHADOW"]}
        retired = [r for r in self._records if r.status == "RETIRED"]

        # Eski retired'ları sil
        if len(retired) > cfg.max_versions:
            to_remove = sorted(retired, key=lambda r: r.created_at)[:len(retired) - cfg.max_versions]
            for r in to_remove:
                self._records.remove(r)
                logger.debug("Cleaned up old version", version=r.version)


# Singleton
model_registry = ModelRegistry()
