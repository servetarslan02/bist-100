"""
ALPHA BIST — Self-Evaluator v1.0

Agent self-evaluation — periyodik performans kontrolü.

Kontroller:
1. Accuracy check
2. Confidence calibration
3. Drift detection
4. Overconfidence check
5. Agent-specific tuning önerileri

FAZ 5: Self-Evaluation
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from .agent_memory import AgentMemory

logger = structlog.get_logger()


@dataclass
class EvalReport:
    """Değerlendirme raporu."""
    agent_role: str
    accuracy: float
    recent_accuracy: float  # Son 50 görev
    calibration: dict[str, Any]
    drift_detected: bool
    overconfident: bool
    total_tasks: int
    total_outcomes: int
    recommendation: str  # OK, RETRAIN, INVESTIGATE_DRIFT, RECALIBRATE
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_role": self.agent_role,
            "accuracy": self.accuracy,
            "recent_accuracy": self.recent_accuracy,
            "calibration": self.calibration,
            "drift_detected": self.drift_detected,
            "overconfident": self.overconfident,
            "total_tasks": self.total_tasks,
            "total_outcomes": self.total_outcomes,
            "recommendation": self.recommendation,
            "details": self.details,
        }


class AgentSelfEvaluator:
    """Agent self-evaluation — periyodik performans kontrolü.

    Kontroller:
    1. Accuracy: Genel ve rejim bazlı doğruluk
    2. Calibration: Confidence vs gerçek doğruluk uyumu
    3. Drift: Son performans vs geçmiş performans
    4. Overconfidence: Yüksek güven ama düşük doğruluk
    5. Recommendation: RETRAIN, RECALIBRATE, INVESTIGATE_DRIFT, OK
    """

    def __init__(
        self,
        drift_threshold: float = 0.1,
        min_samples: int = 30,
        calibration_bins: int = 5,
        overconfidence_threshold: float = 0.15,
    ):
        self.drift_threshold = drift_threshold
        self.min_samples = min_samples
        self.calibration_bins = calibration_bins
        self.overconfidence_threshold = overconfidence_threshold

    def evaluate(
        self,
        memory: AgentMemory,
        regime: str | None = None,
    ) -> EvalReport:
        """Agent performansını değerlendir.

        Args:
            memory: Agent hafızası
            regime: Spesifik rejim (opsiyonel)

        Returns:
            EvalReport
        """
        # 1. Accuracy
        accuracy = memory.episodic.get_accuracy(regime=regime)
        recent_accuracy = memory.episodic.get_accuracy(last_n=50)

        # 2. Confidence calibration
        calibration = self._check_calibration(memory)

        # 3. Drift detection
        drift = self._detect_drift(memory)

        # 4. Overconfidence check
        overconfident = self._check_overconfidence(calibration)

        # 5. Recommendation
        recommendation = self._recommend(accuracy, drift, overconfident)

        # 6. Details
        details = self._create_details(memory, accuracy, recent_accuracy)

        report = EvalReport(
            agent_role=memory.agent_role,
            accuracy=accuracy,
            recent_accuracy=recent_accuracy,
            calibration=calibration,
            drift_detected=drift,
            overconfident=overconfident,
            total_tasks=len(memory.episodic.episodes),
            total_outcomes=len(memory.episodic.outcomes),
            recommendation=recommendation,
            details=details,
        )

        logger.info(
            "Agent evaluation completed",
            agent=memory.agent_role,
            accuracy=accuracy,
            recent_accuracy=recent_accuracy,
            drift=drift,
            recommendation=recommendation,
        )

        return report

    def _check_calibration(self, memory: AgentMemory) -> dict[str, Any]:
        """Confidence kalibrasyonu — beklenen vs gerçek doğruluk."""
        return memory.episodic.get_confidence_calibration()

    def _detect_drift(self, memory: AgentMemory) -> bool:
        """Performans drift'i tespit et.

        Son N outcome vs önceki N outcome karşılaştırması.
        Fark > threshold = drift.
        """
        outcomes = list(memory.episodic.outcomes.values())
        if len(outcomes) < self.min_samples * 2:
            return False

        # Son N outcome
        recent = outcomes[-self.min_samples:]
        recent_acc = sum(1 for o in recent if o["correct"]) / len(recent)

        # Önceki N outcome
        previous = outcomes[-self.min_samples * 2:-self.min_samples]
        previous_acc = sum(1 for o in previous if o["correct"]) / len(previous)

        drift = abs(recent_acc - previous_acc) > self.drift_threshold

        if drift:
            logger.warning(
                "Drift detected",
                agent=memory.agent_role,
                recent_accuracy=round(recent_acc, 4),
                previous_accuracy=round(previous_acc, 4),
                difference=round(abs(recent_acc - previous_acc), 4),
            )

        return drift

    def _check_overconfidence(self, calibration: dict) -> bool:
        """Overconfidence kontrolü.

        Yüksek confidence ama düşük gerçek doğruluk = overconfident.
        """
        if not calibration.get("calibrated"):
            return False

        for c in calibration.get("calibration", []):
            miscalibration = c.get("miscalibration", 0)
            if miscalibration > self.overconfidence_threshold:
                # Confidence > accuracy = overconfident
                if c.get("avg_confidence", 0) > c.get("actual_accuracy", 0):
                    return True

        return False

    def _recommend(
        self,
        accuracy: float,
        drift: bool,
        overconfident: bool,
    ) -> str:
        """Öneri oluştur."""
        if accuracy < 0.45:
            return "RETRAIN"
        elif drift:
            return "INVESTIGATE_DRIFT"
        elif overconfident:
            return "RECALIBRATE"
        return "OK"

    def _create_details(
        self,
        memory: AgentMemory,
        accuracy: float,
        recent_accuracy: float,
    ) -> dict[str, Any]:
        """Detaylı bilgi oluştur."""
        return {
            "accuracy_by_regime": memory.episodic.get_accuracy_by_regime(),
            "accuracy_by_ticker": memory.episodic.get_accuracy_by_ticker(),
            "confidence_stats": self._confidence_stats(memory),
            "outcome_distribution": self._outcome_distribution(memory),
        }

    def _confidence_stats(self, memory: AgentMemory) -> dict[str, float]:
        """Confidence istatistikleri."""
        confidences = [e.confidence for e in memory.episodic.episodes]
        if not confidences:
            return {"mean": 0, "std": 0, "min": 0, "max": 0}

        return {
            "mean": round(float(np.mean(confidences)), 4),
            "std": round(float(np.std(confidences)), 4),
            "min": round(float(np.min(confidences)), 4),
            "max": round(float(np.max(confidences)), 4),
        }

    def _outcome_distribution(self, memory: AgentMemory) -> dict[str, int]:
        """Sonuç dağılımı."""
        outcomes = memory.episodic.outcomes.values()
        return {
            "total": len(list(outcomes)),
            "correct": sum(1 for o in outcomes if o["correct"]),
            "wrong": sum(1 for o in outcomes if not o["correct"]),
            "long_correct": sum(
                1 for o in outcomes
                if o["predicted"] == "LONG" and o["correct"]
            ),
            "long_wrong": sum(
                1 for o in outcomes
                if o["predicted"] == "LONG" and not o["correct"]
            ),
            "short_correct": sum(
                1 for o in outcomes
                if o["predicted"] == "SHORT" and o["correct"]
            ),
            "short_wrong": sum(
                1 for o in outcomes
                if o["predicted"] == "SHORT" and not o["correct"]
            ),
        }


class MultiAgentEvaluator:
    """Tüm agent'ları değerlendir — toplu rapor."""

    def __init__(self):
        self.evaluator = AgentSelfEvaluator()

    def evaluate_all(
        self,
        memories: dict[str, AgentMemory],
    ) -> dict[str, Any]:
        """Tüm agent'ları değerlendir."""
        reports = {}
        alerts = []

        for role_name, memory in memories.items():
            report = self.evaluator.evaluate(memory)
            reports[role_name] = report.to_dict()

            # Alarm gerekli mi?
            if report.recommendation != "OK":
                alerts.append({
                    "agent": role_name,
                    "recommendation": report.recommendation,
                    "accuracy": report.accuracy,
                    "drift_detected": report.drift_detected,
                })

        # Genel sistem sağlığı (double-evaluation'ı önlemek için
        # zaten hesaplanmış report'ları kullan)
        accuracies = [r["accuracy"] for r in reports.values()]

        system_health = "HEALTHY"
        if any(a < 0.45 for a in accuracies):
            system_health = "CRITICAL"
        elif any(a < 0.55 for a in accuracies):
            system_health = "DEGRADED"

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "system_health": system_health,
            "agent_reports": reports,
            "alerts": alerts,
            "summary": {
                "total_agents": len(reports),
                "healthy": sum(1 for r in reports.values() if r["recommendation"] == "OK"),
                "needs_attention": sum(1 for r in reports.values() if r["recommendation"] != "OK"),
                "avg_accuracy": round(
                    sum(r["accuracy"] for r in reports.values()) / len(reports) if reports else 0,
                    4
                ),
            },
        }
