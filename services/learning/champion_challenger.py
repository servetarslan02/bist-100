"""
ALPHA BIST — Champion-Challenger Engine v1.0

Otomatik champion-challenger yönetimi:
- Promote: Challenger yeni champion
- Reject: Challenger reddet
- Canary deployment: Küçük pozisyonlarla test
- Rollback: Önceki versiyona geri dön

KURAL: Champion değişikliği statistical significance gerektirir.
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from services.learning.config.learning_config import learning_settings

logger = structlog.get_logger()


@dataclass
class ChampionRecord:
    """Champion model kaydı."""
    model_id: str
    version: str
    promoted_at: str
    promoted_from: Optional[str]
    metrics_at_promotion: Dict
    regime: str


class ChampionChallengerEngine:
    """Champion-challenger yönetim motoru."""

    def __init__(self):
        self._current_champion: Optional[ChampionRecord] = None
        self._champion_history: List[ChampionRecord] = []
        self._rejected_challengers: List[Dict] = []

    def promote(self, challenger_id: str, version: str, metrics: Dict, regime: str = "UNKNOWN"):
        """Challenger'ı yeni champion yap."""
        old_champion = self._current_champion

        self._current_champion = ChampionRecord(
            model_id=challenger_id,
            version=version,
            promoted_at=datetime.now(timezone.utc).isoformat(),
            promoted_from=old_champion.model_id if old_champion else None,
            metrics_at_promotion=metrics,
            regime=regime,
        )

        self._champion_history.append(self._current_champion)

        logger.info("Challenger promoted to champion",
                   challenger=challenger_id,
                   old=old_champion.model_id if old_champion else "none",
                   improvement=metrics.get("improvement_pct", 0))

    def reject(self, challenger_id: str, reason: str, metrics: Dict):
        """Challenger'ı reddet."""
        self._rejected_challengers.append({
            "model_id": challenger_id,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "metrics": metrics,
        })

        logger.info("Challenger rejected", challenger=challenger_id, reason=reason)

    def rollback(self, to_version: str) -> bool:
        """Önceki versiyona geri dön."""
        for record in reversed(self._champion_history):
            if record.version == to_version:
                self._current_champion = record
                logger.info("Rollback successful", version=to_version)
                return True

        logger.warning("Rollback target not found", version=to_version)
        return False

    def get_champion(self) -> Optional[ChampionRecord]:
        """Mevcut champion."""
        return self._current_champion

    def get_history(self) -> List[Dict]:
        """Champion geçmişi."""
        return [
            {
                "model_id": r.model_id,
                "version": r.version,
                "promoted_at": r.promoted_at,
                "promoted_from": r.promoted_from,
                "regime": r.regime,
            }
            for r in self._champion_history
        ]

    def get_report(self) -> Dict[str, Any]:
        """Rapor."""
        return {
            "current_champion": {
                "model_id": self._current_champion.model_id,
                "version": self._current_champion.version,
                "promoted_at": self._current_champion.promoted_at,
            } if self._current_champion else None,
            "total_promotions": len(self._champion_history),
            "total_rejections": len(self._rejected_challengers),
        }


# Singleton
champion_challenger = ChampionChallengerEngine()
