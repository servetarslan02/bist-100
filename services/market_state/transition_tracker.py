"""ALPHA BIST — Regime Transition Tracker v2.0

Rejim değişimlerini takip eder:
- Transition history (ne zaman, hangi rejimden hangisine)
- Average duration (ortalama süre)
- Stability score (kararlılık skoru)
- Transition probability matrix
- Regime confidence trend

Kaynaklar:
- MDPI (2026): Regime duration tracking
- arXiv RMATS (2026): Hierarchical HMM regime boundary detection
"""

import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
from collections import Counter
import structlog

logger = structlog.get_logger()


@dataclass
class TransitionRecord:
    """Tek bir rejim geçiş kaydı."""
    from_regime: str
    to_regime: str
    timestamp: datetime
    duration_days: float
    from_confidence: float = 0.0
    to_confidence: float = 0.0


@dataclass
class TransitionStats:
    """Rejim geçiş istatistikleri."""
    total_observations: int = 0
    total_transitions: int = 0
    regime_distribution: Dict[str, int] = field(default_factory=dict)
    avg_duration_days: float = 0.0
    stability_score: float = 1.0
    current_regime: str = "UNKNOWN"
    current_duration_days: float = 0.0
    transition_matrix: Dict[str, Dict[str, float]] = field(default_factory=dict)
    confidence_trend: str = "STABLE"  # INCREASING / DECREASING / STABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_observations": self.total_observations,
            "total_transitions": self.total_transitions,
            "regime_distribution": self.regime_distribution,
            "avg_duration_days": round(self.avg_duration_days, 1),
            "stability_score": round(self.stability_score, 4),
            "current_regime": self.current_regime,
            "current_duration_days": round(self.current_duration_days, 2),
            "transition_matrix": self.transition_matrix,
            "confidence_trend": self.confidence_trend,
        }


class RegimeTransitionTracker:
    """Rejim geçiş takibi ve istatistikleri.

    Kullanım:
        tracker = RegimeTransitionTracker(max_history=1000)
        tracker.record("BULL", 0.78)
        stats = tracker.get_stats()
    """

    def __init__(self, max_history: int = 1000, stability_window: int = 20):
        self._max_history = max_history
        self._stability_window = stability_window

        # History
        self._history: List[Dict[str, Any]] = []
        self._transitions: List[TransitionRecord] = []

        # Transition counts (for probability matrix)
        self._transition_counts: Dict[str, Dict[str, int]] = {}

        # Current state
        self._current_regime: Optional[str] = None
        self._current_start: Optional[datetime] = None
        self._current_confidence: float = 0.0

    def record(
        self,
        regime: str,
        confidence: float,
        timestamp: Optional[datetime] = None,
    ):
        """Rejim kaydet, geçiş tespit et.

        Args:
            regime: Tespit edilen rejim
            confidence: Rejim confidence'ı [0, 1]
            timestamp: Zaman damgası (opsiyonel, varsayılan: now)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # History'ye ekle
        self._history.append({
            "regime": regime,
            "confidence": confidence,
            "timestamp": timestamp.isoformat(),
        })

        # History boyut kontrolü
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Geçiş tespit
        if self._current_regime is not None and self._current_regime != regime:
            # Rejim değişti!
            duration = self._calculate_duration(self._current_start, timestamp)

            transition = TransitionRecord(
                from_regime=self._current_regime,
                to_regime=regime,
                timestamp=timestamp,
                duration_days=duration,
                from_confidence=self._current_confidence,
                to_confidence=confidence,
            )
            self._transitions.append(transition)

            # Transition counts güncelle
            if self._current_regime not in self._transition_counts:
                self._transition_counts[self._current_regime] = {}
            self._transition_counts[self._current_regime][regime] = (
                self._transition_counts[self._current_regime].get(regime, 0) + 1
            )

            # Transition history boyut kontrolü
            if len(self._transitions) > self._max_history:
                self._transitions = self._transitions[-self._max_history:]

            logger.info(
                "Regime transition",
                from_regime=self._current_regime,
                to_regime=regime,
                duration_days=round(duration, 1),
                from_confidence=round(self._current_confidence, 3),
                to_confidence=round(confidence, 3),
            )

            # Yeni rejimi current yap
            self._current_start = timestamp

        elif self._current_regime is None:
            # İlk rejim kaydı
            self._current_start = timestamp

        self._current_regime = regime
        self._current_confidence = confidence

    def get_stats(self) -> TransitionStats:
        """Rejim istatistiklerini döndür."""
        if not self._history:
            return TransitionStats()

        # Rejim dağılımı
        regime_counts = Counter(h["regime"] for h in self._history)

        # Ortalama süre
        durations = [t.duration_days for t in self._transitions if t.duration_days > 0]
        avg_duration = float(np.mean(durations)) if durations else 0.0

        # Kararlılık skoru
        stability = self._compute_stability()

        # Mevcut rejim süresi
        now = datetime.now(timezone.utc)
        current_duration = self._calculate_duration(self._current_start, now)

        # Geçiş matrisi
        transition_matrix = self._compute_transition_matrix()

        # Confidence trend
        confidence_trend = self._compute_confidence_trend()

        return TransitionStats(
            total_observations=len(self._history),
            total_transitions=len(self._transitions),
            regime_distribution=dict(regime_counts),
            avg_duration_days=round(avg_duration, 1),
            stability_score=round(stability, 4),
            current_regime=self._current_regime or "UNKNOWN",
            current_duration_days=round(current_duration, 2),
            transition_matrix=transition_matrix,
            confidence_trend=confidence_trend,
        )

    def get_stability_score(self) -> float:
        """Kararlılık skoru [0, 1].

        1 = çok kararlı (az geçiş)
        0 = çok kararsız (sık geçiş)
        """
        return self._compute_stability()

    def get_transition_probability(self, from_regime: str, to_regime: str) -> float:
        """Belirli bir geçişin olasılığı [0, 1]."""
        matrix = self._compute_transition_matrix()
        return matrix.get(from_regime, {}).get(to_regime, 0.0)

    def get_current_regime_duration(self) -> float:
        """Mevcut rejimin süresi (gün)."""
        if self._current_start is None:
            return 0.0
        now = datetime.now(timezone.utc)
        return self._calculate_duration(self._current_start, now)

    def get_recent_transitions(self, limit: int = 10) -> List[Dict]:
        """Son N geçiş."""
        recent = self._transitions[-limit:]
        return [
            {
                "from": t.from_regime,
                "to": t.to_regime,
                "timestamp": t.timestamp.isoformat(),
                "duration_days": round(t.duration_days, 1),
                "from_confidence": round(t.from_confidence, 3),
                "to_confidence": round(t.to_confidence, 3),
            }
            for t in recent
        ]

    def _compute_stability(self) -> float:
        """Kararlılık skoru hesapla.

        Son N gözlemde kaç geçiş oldu?
        Geçiş oranı düşük = kararlı.
        """
        if len(self._history) < 2:
            return 1.0

        # Son window gözlemdeki geçiş sayısı
        window = min(self._stability_window, len(self._history))
        recent_history = self._history[-window:]

        transitions_in_window = 0
        for i in range(1, len(recent_history)):
            if recent_history[i]["regime"] != recent_history[i - 1]["regime"]:
                transitions_in_window += 1

        # Geçiş oranı (gözlem başına)
        transition_rate = transitions_in_window / max(window - 1, 1)

        # Kararlılık = 1 - geçiş oranı (maks 1)
        stability = max(0.0, 1.0 - transition_rate * 2)  # *2 çünkü her geçiş 2 gözlem etkiler

        return stability

    def _compute_transition_matrix(self) -> Dict[str, Dict[str, float]]:
        """Geçiş olasılıkları matrisi."""
        matrix = {}

        for from_regime, to_counts in self._transition_counts.items():
            total = sum(to_counts.values())
            if total > 0:
                matrix[from_regime] = {
                    to_regime: round(count / total, 4)
                    for to_regime, count in to_counts.items()
                }

        return matrix

    def _compute_confidence_trend(self) -> str:
        """Son gözlemlerde confidence trend'i.

        INCREASING: Confidence artıyor (rejim kararlaşıyor)
        DECREASING: Confidence azalıyor (rejim sarsılıyor)
        STABLE: Sabit
        """
        if len(self._history) < 10:
            return "STABLE"

        recent = self._history[-10:]
        confidences = [h["confidence"] for h in recent]

        # Basit trend: ilk yarı vs ikinci yarı ortalaması
        mid = len(confidences) // 2
        first_half = np.mean(confidences[:mid])
        second_half = np.mean(confidences[mid:])

        diff = second_half - first_half

        if diff > 0.05:
            return "INCREASING"
        elif diff < -0.05:
            return "DECREASING"
        return "STABLE"

    def _calculate_duration(self, start: Optional[datetime], end: datetime) -> float:
        """Süre hesapla (gün)."""
        if start is None:
            return 0.0

        try:
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            return (end - start).total_seconds() / 86400
        except Exception:
            return 0.0

    def reset(self):
        """Tüm state sıfırla (backtest için)."""
        self._history = []
        self._transitions = []
        self._transition_counts = {}
        self._current_regime = None
        self._current_start = None
        self._current_confidence = 0.0
