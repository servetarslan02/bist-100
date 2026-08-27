"""
ALPHA BIST — Champion-Challenger Engine v1.0

Otomatik champion-challenger yönetimi:
- Promote: Challenger yeni champion
- Reject: Challenger reddet
- Canary deployment: Küçük pozisyonlarla test
- Rollback: Önceki versiyona geri dön

KURAL: Champion değişikliği statistical significance gerektirir.
"""

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class ChampionRecord:
    """Champion model kaydı."""

    model_id: str
    version: str
    promoted_at: str
    promoted_from: str | None
    metrics_at_promotion: dict
    regime: str


class ChampionChallengerEngine:
    """Champion-challenger yönetim motoru."""

    def __init__(self):
        self._current_champion: ChampionRecord | None = None
        self._champion_history: deque = deque(maxlen=500)
        self._rejected_challengers: deque = deque(maxlen=500)
        # Canary deployment attribute'ları
        self._canary_active: bool = False
        self._canary_model: str | None = None
        self._canary_version: str | None = None
        self._canary_allocation: float = 0.0
        self._canary_start: datetime | None = None
        self._canary_metrics: dict = {}
        self._canary_regime: str = "UNKNOWN"

    def promote(self, challenger_id: str, version: str, metrics: dict, regime: str = "UNKNOWN"):
        """Challenger'ı yeni champion yap."""
        old_champion = self._current_champion

        self._current_champion = ChampionRecord(
            model_id=challenger_id,
            version=version,
            promoted_at=datetime.now(UTC).isoformat(),
            promoted_from=old_champion.model_id if old_champion else None,
            metrics_at_promotion=metrics,
            regime=regime,
        )

        self._champion_history.append(self._current_champion)
        if len(self._champion_history) > 1000:
            self._champion_history = self._champion_history[-1000:]

        logger.info(
            "Challenger promoted to champion",
            challenger=challenger_id,
            old=old_champion.model_id if old_champion else "none",
            improvement=metrics.get("improvement_pct", 0),
        )

    def reject(self, challenger_id: str, reason: str, metrics: dict):
        """Challenger'ı reddet."""
        self._rejected_challengers.append(
            {
                "model_id": challenger_id,
                "rejected_at": datetime.now(UTC).isoformat(),
                "reason": reason,
                "metrics": metrics,
            }
        )
        if len(self._rejected_challengers) > 500:
            self._rejected_challengers = self._rejected_challengers[-500:]

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

    def get_champion(self) -> ChampionRecord | None:
        """Mevcut champion."""
        return self._current_champion

    def get_history(self) -> list[dict]:
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

    def canary_deploy(
        self,
        challenger_id: str,
        version: str,
        allocation_pct: float = 0.1,
        metrics: dict = None,
        regime: str = "UNKNOWN",
    ):
        """Canary deployment — küçük pozisyonlarla test.

        Yeni modeli production'da %10 pozisyonla test eder.
        Başarılıysa kademeli artır, başarısızsa geri çek.

        Args:
            challenger_id: Yeni model ID
            version: Model versiyonu
            allocation_pct: Başlangıç pozisyon oranı (%10 varsayılan)
            metrics: Mevcut metrikler
            regime: Piyasa rejimi
        """
        logger.info("Canary deployment started", challenger=challenger_id, allocation=f"{allocation_pct * 100:.0f}%")

        self._canary_active = True
        self._canary_model = challenger_id
        self._canary_version = version
        self._canary_allocation = allocation_pct
        self._canary_start = datetime.now(UTC)
        self._canary_metrics = metrics or {}
        self._canary_regime = regime

    def evaluate_canary(self, actual_returns: dict[str, float]) -> dict[str, Any]:
        """Canary deployment sonucunu değerlendir."""
        if not self._canary_active:
            return {"active": False}

        days_elapsed = (datetime.now(UTC) - self._canary_start).days

        # Canary model performansını değerlendir
        canary_metrics = self._calculate_canary_metrics(actual_returns)

        # Karar
        if days_elapsed < 7:
            recommendation = "CONTINUE"
        elif canary_metrics.get("sharpe", 0) > 0.3 and canary_metrics.get("win_rate", 0) > 0.5:
            recommendation = "PROMOTE"
            # Allocation artır
            self._canary_allocation = min(self._canary_allocation * 2, 1.0)
        elif canary_metrics.get("sharpe", 0) < 0:
            recommendation = "REJECT"
            self._canary_active = False
        else:
            recommendation = "CONTINUE"

        return {
            "active": self._canary_active,
            "model_id": self._canary_model,
            "allocation_pct": self._canary_allocation,
            "days_elapsed": days_elapsed,
            "metrics": canary_metrics,
            "recommendation": recommendation,
        }

    def _calculate_canary_metrics(self, actual_returns: dict[str, float]) -> dict[str, float]:
        """Canary model metrikleri."""
        # Basit metrik hesaplama
        returns_list = list(actual_returns.values())
        if not returns_list:
            return {"sharpe": 0, "win_rate": 0}

        avg_return = float(np.mean(returns_list))
        std_return = float(np.std(returns_list))
        sharpe = (avg_return / max(std_return, 1e-8)) * np.sqrt(252)
        win_rate = float(np.mean([r > 0 for r in returns_list]))

        return {
            "sharpe": round(sharpe, 4),
            "win_rate": round(win_rate, 4),
            "avg_return": round(avg_return, 6),
        }

    def get_report(self) -> dict[str, Any]:
        """Rapor."""
        report = {
            "current_champion": {
                "model_id": self._current_champion.model_id,
                "version": self._current_champion.version,
                "promoted_at": self._current_champion.promoted_at,
            }
            if self._current_champion
            else None,
            "total_promotions": len(self._champion_history),
            "total_rejections": len(self._rejected_challengers),
        }
        if self._canary_active:
            report["canary"] = {
                "model_id": self._canary_model,
                "allocation_pct": self._canary_allocation,
                "days_elapsed": (datetime.now(UTC) - self._canary_start).days,
            }
        return report


# Singleton
champion_challenger = ChampionChallengerEngine()

# Singleton
champion_challenger = ChampionChallengerEngine()
