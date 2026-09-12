"""ALPHA BIST — Self-Evaluator (Öz-Değerlendirme) Modülü v3.0.

Bu modül, Alpha BIST multi-agent mimarisindeki uzman ajanların geçmiş tahminlerini
ve gerçekleşen piyasa sonuçlarını (outcomes) periyodik olarak denetler.
Doğruluk oranı (accuracy), güven kalibrasyonu (confidence calibration), konsept kayması
(drift detection) ve aşırı güven (overconfidence) analizleri yürüterek ajanların yeniden
eğitilmesi veya parametrelerinin kalibre edilmesi yönünde sistemik öneriler üretir.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import orjson
import structlog

if TYPE_CHECKING:
    from .agent_memory import AgentMemory

logger = structlog.get_logger(__name__)

__all__: Final[list[str]] = [
    "EvalReport",
    "AgentSelfEvaluator",
    "MultiAgentEvaluator",
]


@dataclass
class EvalReport:
    """Ajan öz-değerlendirme metrikleri ve tuning önerileri raporu."""

    agent_role: str
    accuracy: float
    recent_accuracy: float  # Son 50 görev doğruluğu
    calibration: dict[str, Any]
    drift_detected: bool
    overconfident: bool
    total_tasks: int
    total_outcomes: int
    recommendation: str  # 'OK', 'RETRAIN', 'INVESTIGATE_DRIFT', 'RECALIBRATE'
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Rapor verilerini serileştirilebilir sözlüğe çevirir.

        Returns:
            dict[str, Any]: Yapılandırılmış değerlendirme verisi.
        """
        return {
            "agent_role": self.agent_role,
            "accuracy": round(self.accuracy, 4),
            "recent_accuracy": round(self.recent_accuracy, 4),
            "calibration": self.calibration,
            "drift_detected": self.drift_detected,
            "overconfident": self.overconfident,
            "total_tasks": self.total_tasks,
            "total_outcomes": self.total_outcomes,
            "recommendation": self.recommendation,
            "details": self.details,
        }

    def to_json(self) -> str:
        """Raporu orjson kullanarak JSON metnine dönüştürür.

        Returns:
            str: JSON biçimli rapor.
        """
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        return (
            f"EvalReport(role={self.agent_role!r}, acc={self.accuracy:.2f}, "
            f"recent={self.recent_accuracy:.2f}, drift={self.drift_detected}, "
            f"rec={self.recommendation!r})"
        )


class AgentSelfEvaluator:
    """Tekil bir ajanın bellek kayıtlarını analiz eden öz-değerlendirme motoru."""

    def __init__(
        self,
        drift_threshold: float = 0.10,
        min_samples: int = 30,
        calibration_bins: int = 5,
        overconfidence_threshold: float = 0.15,
    ) -> None:
        """AgentSelfEvaluator başlatıcı.

        Args:
            drift_threshold: Performans kayması tespit eşiği (doğruluk farkı).
            min_samples: Drift tespiti için gereken minimum örnekleme sayısı.
            calibration_bins: Güven kalibrasyonu aralık dilim sayısı.
            overconfidence_threshold: Aşırı güven tespit eşiği.
        """
        self.drift_threshold: float = drift_threshold
        self.min_samples: int = max(5, min_samples)
        self.calibration_bins: int = max(2, calibration_bins)
        self.overconfidence_threshold: float = overconfidence_threshold

    def evaluate(
        self,
        memory: AgentMemory,
        regime: str | None = None,
    ) -> EvalReport:
        """Ajanın epizodik hafıza ve sonuç kayıtlarını değerlendirir.

        Args:
            memory: Ajan hafıza nesnesi (AgentMemory).
            regime: İsteğe bağlı spesifik makro piyasa rejimi filtresi.

        Returns:
            EvalReport: Kapsamlı değerlendirme ve öneri raporu.
        """
        # 1. Doğruluk (Genel ve Son 50 görev)
        accuracy = float(memory.episodic.get_accuracy(regime=regime))
        recent_accuracy = float(memory.episodic.get_accuracy(last_n=50))

        # 2. Güven Kalibrasyonu
        calibration = self._check_calibration(memory)

        # 3. Performans Kayması (Drift)
        drift = self._detect_drift(memory)

        # 4. Aşırı Güven Kontrolü
        overconfident = self._check_overconfidence(calibration)

        # 5. Öneri Üretimi
        recommendation = self._recommend(accuracy, drift, overconfident)

        # 6. Detaylı Metrikler
        details = self._create_details(memory, accuracy, recent_accuracy)

        report = EvalReport(
            agent_role=str(memory.agent_role),
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
            "Ajan öz-değerlendirmesi tamamlandı",
            ajan=report.agent_role,
            dogruluk=report.accuracy,
            son_dogruluk=report.recent_accuracy,
            drift=report.drift_detected,
            oneri=report.recommendation,
        )

        return report

    def _check_calibration(self, memory: AgentMemory) -> dict[str, Any]:
        """Ajanın güven skoru kalibrasyonunu ölçer."""
        raw_calib = memory.episodic.get_confidence_calibration()
        if not isinstance(raw_calib, dict):
            return {"calibrated": False, "calibration": []}
        return raw_calib

    def _detect_drift(self, memory: AgentMemory) -> bool:
        """Zaman serisi boyunca doğrulukta anlamlı bir bozulma/kayma var mı denetler."""
        outcomes = sorted(
            memory.episodic.outcomes.values(),
            key=lambda o: str(o.get("timestamp", "")),
        )

        if len(outcomes) < self.min_samples * 2:
            return False

        # Son N sonuç
        recent = outcomes[-self.min_samples:]
        recent_acc = sum(1 for o in recent if o.get("correct", False)) / len(recent)

        # Önceki N sonuç
        previous = outcomes[-self.min_samples * 2 : -self.min_samples]
        previous_acc = sum(1 for o in previous if o.get("correct", False)) / len(previous)

        diff = abs(recent_acc - previous_acc)
        drift = diff > self.drift_threshold

        if drift:
            logger.warning(
                "Ajan performansında kayma (drift) tespit edildi",
                ajan=str(memory.agent_role),
                guncel_dogruluk=round(recent_acc, 4),
                onceki_dogruluk=round(previous_acc, 4),
                fark=round(diff, 4),
            )

        return drift

    def _check_overconfidence(self, calibration: dict[str, Any]) -> bool:
        """Ajanın yüksek güven beyan edip düşük başarı gösterip göstermediğini denetler."""
        if not calibration.get("calibrated", False):
            return False

        bins = calibration.get("calibration", [])
        for c in bins:
            miscalibration = float(c.get("miscalibration", 0.0))
            if miscalibration > self.overconfidence_threshold:
                avg_conf = float(c.get("avg_confidence", 0.0))
                act_acc = float(c.get("actual_accuracy", 0.0))
                if avg_conf > act_acc:
                    return True

        return False

    @staticmethod
    def _recommend(
        accuracy: float,
        drift: bool,
        overconfident: bool,
    ) -> str:
        """Performans metriklerine göre aksiyon önerisi üretir."""
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
        """Ayrıntılı rejim ve dağılım istatistiklerini derler."""
        return {
            "accuracy_by_regime": memory.episodic.get_accuracy_by_regime(),
            "accuracy_by_ticker": memory.episodic.get_accuracy_by_ticker(),
            "confidence_stats": self._confidence_stats(memory),
            "outcome_distribution": self._outcome_distribution(memory),
        }

    @staticmethod
    def _confidence_stats(memory: AgentMemory) -> dict[str, float]:
        """Güven skorlarının temel istatistiklerini hesaplar."""
        confidences = [
            float(e.confidence)
            for e in memory.episodic.episodes
            if hasattr(e, "confidence") and not math.isnan(float(e.confidence))
        ]
        if not confidences:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}

        return {
            "mean": round(statistics.mean(confidences), 4),
            "std": round(statistics.stdev(confidences) if len(confidences) > 1 else 0.0, 4),
            "min": round(min(confidences), 4),
            "max": round(max(confidences), 4),
        }

    @staticmethod
    def _outcome_distribution(memory: AgentMemory) -> dict[str, int]:
        """Sonuç dağılımını yön bazında kategorize eder."""
        outcomes = list(memory.episodic.outcomes.values())
        return {
            "total": len(outcomes),
            "correct": sum(1 for o in outcomes if o.get("correct", False)),
            "wrong": sum(1 for o in outcomes if not o.get("correct", False)),
            "long_correct": sum(1 for o in outcomes if o.get("predicted") == "LONG" and o.get("correct", False)),
            "long_wrong": sum(1 for o in outcomes if o.get("predicted") == "LONG" and not o.get("correct", False)),
            "short_correct": sum(1 for o in outcomes if o.get("predicted") == "SHORT" and o.get("correct", False)),
            "short_wrong": sum(1 for o in outcomes if o.get("predicted") == "SHORT" and not o.get("correct", False)),
            "no_trade": sum(1 for o in outcomes if o.get("predicted") == "NO_TRADE"),
        }

    def __repr__(self) -> str:
        return (
            f"AgentSelfEvaluator(drift_thresh={self.drift_threshold}, "
            f"min_samples={self.min_samples}, overconf_thresh={self.overconfidence_threshold})"
        )


class MultiAgentEvaluator:
    """Sistemdeki tüm ajanların performansını toplu denetleyen orkestratör."""

    def __init__(self, evaluator: AgentSelfEvaluator | None = None) -> None:
        """MultiAgentEvaluator başlatıcı.

        Args:
            evaluator: İsteğe bağlı özel AgentSelfEvaluator örneği.
        """
        self.evaluator: AgentSelfEvaluator = evaluator or AgentSelfEvaluator()

    def evaluate_all(
        self,
        memories: dict[str, AgentMemory],
    ) -> dict[str, Any]:
        """Tüm ajanları değerlendirip sistem genel sağlık durumunu üretir.

        Args:
            memories: {rol_adı: AgentMemory} sözlüğü.

        Returns:
            dict[str, Any]: Sistem sağlığı, uyarılar ve ajan raporları.
        """
        reports: dict[str, Any] = {}
        alerts: list[dict[str, Any]] = []

        for role_name, memory in memories.items():
            report = self.evaluator.evaluate(memory)
            reports[role_name] = report.to_dict()

            if report.recommendation != "OK":
                alerts.append(
                    {
                        "agent": role_name,
                        "recommendation": report.recommendation,
                        "accuracy": report.accuracy,
                        "drift_detected": report.drift_detected,
                    }
                )

        # Genel sistem sıhhati
        accuracies = [float(r["accuracy"]) for r in reports.values() if not math.isnan(float(r["accuracy"]))]

        system_health = "HEALTHY"
        if any(a < 0.45 for a in accuracies):
            system_health = "CRITICAL"
        elif any(a < 0.55 for a in accuracies):
            system_health = "DEGRADED"

        avg_acc = (sum(accuracies) / len(accuracies)) if accuracies else 0.0

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "system_health": system_health,
            "agent_reports": reports,
            "alerts": alerts,
            "summary": {
                "total_agents": len(reports),
                "healthy": sum(1 for r in reports.values() if r["recommendation"] == "OK"),
                "needs_attention": sum(1 for r in reports.values() if r["recommendation"] != "OK"),
                "avg_accuracy": round(avg_acc, 4),
            },
        }

    def __repr__(self) -> str:
        return f"MultiAgentEvaluator(evaluator={self.evaluator!r})"
