"""ALPHA BIST — Market State Output Formatter v2.0

Tüm bileşenleri tek bir MarketStateOutput'ta birleştirir.
API ve event bus için standart format.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

from .breadth_engine import BreadthResult
from .component_states import ComponentStates
from .ensemble_regime import EnsembleResult
from .transition_tracker import TransitionStats
from .multi_timeframe import MultiTimeframeResult

logger = structlog.get_logger()


@dataclass
class MarketStateOutput:
    """Market state'in nihai çıktı formatı — tüm bileşenler birleşik."""

    # Meta
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "2.0"

    # Regime (ensemble)
    regime: str = "UNKNOWN"
    regime_confidence: float = 0.0
    regime_method: str = "ensemble_voting"
    regime_consensus: bool = False
    regime_stability: float = 1.0
    regime_duration_days: float = 0.0
    confidence_trend: str = "STABLE"

    # Breadth
    breadth: Dict[str, Any] = field(default_factory=dict)

    # Component States
    momentum_state: str = "NEUTRAL"
    volatility_state: str = "NORMAL"
    volume_state: str = "AVERAGE"
    rsi_state: str = "NEUTRAL"
    liquidity_state: str = "NORMAL"
    sentiment_state: str = "NEUTRAL"
    macro_state: str = "NEUTRAL"

    # Anomaly
    anomaly_count: int = 0
    anomaly_severity: str = "NONE"

    # Risk appetite
    risk_appetite: float = 0.5
    risk_appetite_state: str = "NEUTRAL"

    # Multi-timeframe
    daily_state: Dict[str, Any] = field(default_factory=dict)
    weekly_state: Dict[str, Any] = field(default_factory=dict)
    multi_tf_alignment: float = 1.0
    multi_tf_divergences: List[str] = field(default_factory=list)

    # Ensemble details
    ensemble_methods: Dict[str, Any] = field(default_factory=dict)
    hmm_probabilities: Dict[str, float] = field(default_factory=dict)

    # Transition stats
    total_transitions: int = 0
    transition_matrix: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Tam output dict."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
            "regime": self.regime,
            "regime_confidence": round(self.regime_confidence, 4),
            "regime_method": self.regime_method,
            "regime_consensus": self.regime_consensus,
            "regime_stability": round(self.regime_stability, 4),
            "regime_duration_days": round(self.regime_duration_days, 2),
            "confidence_trend": self.confidence_trend,
            "breadth": self.breadth,
            "momentum_state": self.momentum_state,
            "volatility_state": self.volatility_state,
            "volume_state": self.volume_state,
            "rsi_state": self.rsi_state,
            "liquidity_state": self.liquidity_state,
            "sentiment_state": self.sentiment_state,
            "macro_state": self.macro_state,
            "anomaly_count": self.anomaly_count,
            "anomaly_severity": self.anomaly_severity,
            "risk_appetite": round(self.risk_appetite, 4),
            "risk_appetite_state": self.risk_appetite_state,
            "daily_state": self.daily_state,
            "weekly_state": self.weekly_state,
            "multi_tf_alignment": round(self.multi_tf_alignment, 4),
            "multi_tf_divergences": self.multi_tf_divergences,
            "ensemble_methods": self.ensemble_methods,
            "hmm_probabilities": self.hmm_probabilities,
            "total_transitions": self.total_transitions,
            "transition_matrix": self.transition_matrix,
        }


class MarketStateFormatter:
    """Tüm bileşen sonuçlarını tek MarketStateOutput'ta birleştirir.

    Kullanım:
        formatter = MarketStateFormatter()
        output = formatter.format(
            breadth_result,
            component_states,
            ensemble_result,
            transition_stats,
            risk_appetite_score,
            multi_tf_result,
        )
    """

    def format(
        self,
        breadth: Optional[BreadthResult] = None,
        components: Optional[ComponentStates] = None,
        ensemble: Optional[EnsembleResult] = None,
        transition: Optional[TransitionStats] = None,
        risk_appetite: float = 0.5,
        risk_appetite_state: str = "NEUTRAL",
        multi_tf: Optional[MultiTimeframeResult] = None,
    ) -> MarketStateOutput:
        """Tüm bileşenleri birleştir.

        Returns:
            MarketStateOutput
        """
        output = MarketStateOutput()

        # Regime (ensemble)
        if ensemble:
            output.regime = ensemble.regime
            output.regime_confidence = ensemble.confidence
            output.regime_consensus = ensemble.consensus
            output.ensemble_methods = ensemble.method_details
            output.hmm_probabilities = ensemble.hmm_probabilities

        # Breadth
        if breadth:
            output.breadth = breadth.to_dict()

        # Component States
        if components:
            output.momentum_state = components.momentum_state
            output.volatility_state = components.volatility_state
            output.volume_state = components.volume_state
            output.rsi_state = components.rsi_state
            output.liquidity_state = components.liquidity_state
            output.sentiment_state = components.sentiment_state
            output.macro_state = components.macro_state
            output.anomaly_count = components.anomaly_count
            output.anomaly_severity = components.anomaly_severity

        # Transition
        if transition:
            output.regime_stability = transition.stability_score
            output.regime_duration_days = transition.current_duration_days
            output.confidence_trend = transition.confidence_trend
            output.total_transitions = transition.total_transitions
            output.transition_matrix = transition.transition_matrix

        # Risk appetite
        output.risk_appetite = risk_appetite
        output.risk_appetite_state = risk_appetite_state

        # Multi-timeframe
        if multi_tf:
            if "daily" in multi_tf.states:
                output.daily_state = multi_tf.states["daily"].to_dict()
            if "weekly" in multi_tf.states:
                output.weekly_state = multi_tf.states["weekly"].to_dict()
            output.multi_tf_alignment = multi_tf.alignment_score
            output.multi_tf_divergences = multi_tf.divergences

        return output

    def format_json(
        self,
        breadth: Optional[BreadthResult] = None,
        components: Optional[ComponentStates] = None,
        ensemble: Optional[EnsembleResult] = None,
        transition: Optional[TransitionStats] = None,
        risk_appetite: float = 0.5,
        risk_appetite_state: str = "NEUTRAL",
        multi_tf: Optional[MultiTimeframeResult] = None,
    ) -> str:
        """JSON string olarak formatla."""
        import orjson
        output = self.format(
            breadth, components, ensemble, transition,
            risk_appetite, risk_appetite_state, multi_tf,
        )
        return orjson.dumps(output.to_dict(), default=str).decode()
