"""ALPHA BIST — Market State Monitoring v2.0

Prometheus metrics + Grafana dashboard data.

Metrikler:
- market_state_regime (gauge) — Mevcut rejim (encoded)
- market_state_confidence (gauge) — Rejim confidence'ı
- market_state_stability (gauge) — Kararlılık skoru
- market_state_breadth_pct (gauge) — Advancing %
- market_state_risk_appetite (gauge) — Risk appetite skoru
- market_state_transition_total (counter) — Toplam geçiş sayısı
- market_state_alert_total (counter) — Toplam alert sayısı
- market_state_duration_ms (histogram) — Hesaplama süresi
- market_state_breadth_mcclellan (gauge) — McClellan Oscillator
- market_state_breadth_trin (gauge) — TRIN
"""

import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()

# Rejim encoding (Prometheus gauge için)
REGIME_ENCODING = {
    "UNKNOWN": 0,
    "BULL": 1,
    "BEAR": 2,
    "SIDEWAYS": 3,
    "HIGH_VOLATILITY": 4,
    "LOW_VOLATILITY": 5,
    "RISK_ON": 6,
    "RISK_OFF": 7,
    "CRISIS": 8,
    "RECOVERY": 9,
    "MOMENTUM_EXPANSION": 10,
    "MOMENTUM_CONTRACTION": 11,
}


@dataclass
class MarketStateMetrics:
    """Prometheus metrikleri."""
    # Regime
    regime_value: int = 0           # Encoded regime
    regime_confidence: float = 0.0
    regime_consensus: bool = False

    # Stability
    stability_score: float = 1.0
    transition_count: int = 0

    # Breadth
    breadth_pct: float = 50.0
    breadth_mcclellan: float = 0.0
    breadth_trin: float = 1.0
    breadth_thrust: float = 0.5

    # Risk appetite
    risk_appetite: float = 0.5

    # Component states
    momentum_state: str = "NEUTRAL"
    volatility_state: str = "NORMAL"
    volume_state: str = "AVERAGE"

    # Alerts
    alert_count: int = 0
    critical_alerts: int = 0

    # Performance
    compute_duration_ms: float = 0.0
    last_update: str = ""

    def to_prometheus(self) -> str:
        """Prometheus text format'ında metrikler."""
        lines = []

        # Regime
        lines.append(f"# HELP market_state_regime Current market regime (encoded)")
        lines.append(f"# TYPE market_state_regime gauge")
        lines.append(f"market_state_regime {self.regime_value}")

        lines.append(f"# HELP market_state_confidence Regime confidence [0-1]")
        lines.append(f"# TYPE market_state_confidence gauge")
        lines.append(f"market_state_confidence {self.regime_confidence}")

        # Stability
        lines.append(f"# HELP market_state_stability Regime stability score [0-1]")
        lines.append(f"# TYPE market_state_stability gauge")
        lines.append(f"market_state_stability {self.stability_score}")

        lines.append(f"# HELP market_state_transitions Total regime transitions")
        lines.append(f"# TYPE market_state_transitions counter")
        lines.append(f"market_state_transitions {self.transition_count}")

        # Breadth
        lines.append(f"# HELP market_state_breadth_pct Percentage of advancing stocks")
        lines.append(f"# TYPE market_state_breadth_pct gauge")
        lines.append(f"market_state_breadth_pct {self.breadth_pct}")

        lines.append(f"# HELP market_state_breadth_mcclellan McClellan Oscillator")
        lines.append(f"# TYPE market_state_breadth_mcclellan gauge")
        lines.append(f"market_state_breadth_mcclellan {self.breadth_mcclellan}")

        lines.append(f"# HELP market_state_breadth_trin TRIN / Arms Index")
        lines.append(f"# TYPE market_state_breadth_trin gauge")
        lines.append(f"market_state_breadth_trin {self.breadth_trin}")

        lines.append(f"# HELP market_state_breadth_thrust Breadth Thrust")
        lines.append(f"# TYPE market_state_breadth_thrust gauge")
        lines.append(f"market_state_breadth_thrust {self.breadth_thrust}")

        # Risk appetite
        lines.append(f"# HELP market_state_risk_appetite Risk appetite [0-1]")
        lines.append(f"# TYPE market_state_risk_appetite gauge")
        lines.append(f"market_state_risk_appetite {self.risk_appetite}")

        # Alerts
        lines.append(f"# HELP market_state_alerts Total alerts")
        lines.append(f"# TYPE market_state_alerts counter")
        lines.append(f"market_state_alerts {self.alert_count}")

        # Performance
        lines.append(f"# HELP market_state_compute_ms Compute duration in ms")
        lines.append(f"# TYPE market_state_compute_ms histogram")
        lines.append(f"market_state_compute_ms {self.compute_duration_ms}")

        return "\\n".join(lines)


class MarketStateMonitor:
    """Market state monitoring — Prometheus + Grafana."""

    def __init__(self):
        self._metrics = MarketStateMetrics()
        self._history: List[MarketStateMetrics] = []
        self._max_history = 1000

    def update(
        self,
        regime: str = "UNKNOWN",
        confidence: float = 0.0,
        consensus: bool = False,
        stability: float = 1.0,
        transition_count: int = 0,
        breadth_pct: float = 50.0,
        mcclellan: float = 0.0,
        trin: float = 1.0,
        thrust: float = 0.5,
        risk_appetite: float = 0.5,
        alert_count: int = 0,
        critical_alerts: int = 0,
        compute_duration_ms: float = 0.0,
    ):
        """Metrikleri güncelle."""
        self._metrics = MarketStateMetrics(
            regime_value=REGIME_ENCODING.get(regime, 0),
            regime_confidence=confidence,
            regime_consensus=consensus,
            stability_score=stability,
            transition_count=transition_count,
            breadth_pct=breadth_pct,
            breadth_mcclellan=mcclellan,
            breadth_trin=trin,
            breadth_thrust=thrust,
            risk_appetite=risk_appetite,
            alert_count=alert_count,
            critical_alerts=critical_alerts,
            compute_duration_ms=compute_duration_ms,
            last_update=datetime.now(timezone.utc).isoformat(),
        )

        # History
        self._history.append(self._metrics)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_prometheus_metrics(self) -> str:
        """Prometheus text format."""
        return self._metrics.to_prometheus()

    def get_grafana_dashboard(self) -> Dict[str, Any]:
        """Grafana dashboard JSON."""
        return {
            "dashboard": {
                "title": "ALPHA BIST — Market State",
                "tags": ["alpha", "market_state", "regime"],
                "timezone": "utc",
                "panels": [
                    {
                        "title": "Current Regime",
                        "type": "stat",
                        "targets": [{"expr": "market_state_regime"}],
                        "fieldConfig": {
                            "defaults": {
                                "mappings": [
                                    {"type": "value", "options": {str(v): k for k, v in REGIME_ENCODING.items()}}
                                ]
                            }
                        },
                        "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
                    },
                    {
                        "title": "Regime Confidence",
                        "type": "gauge",
                        "targets": [{"expr": "market_state_confidence"}],
                        "fieldConfig": {"defaults": {"min": 0, "max": 1}},
                        "gridPos": {"h": 4, "w": 6, "x": 6, "y": 0},
                    },
                    {
                        "title": "Stability Score",
                        "type": "gauge",
                        "targets": [{"expr": "market_state_stability"}],
                        "fieldConfig": {"defaults": {"min": 0, "max": 1}},
                        "gridPos": {"h": 4, "w": 6, "x": 12, "y": 0},
                    },
                    {
                        "title": "Risk Appetite",
                        "type": "gauge",
                        "targets": [{"expr": "market_state_risk_appetite"}],
                        "fieldConfig": {"defaults": {"min": 0, "max": 1}},
                        "gridPos": {"h": 4, "w": 6, "x": 18, "y": 0},
                    },
                    {
                        "title": "Breadth % Advancing",
                        "type": "timeseries",
                        "targets": [{"expr": "market_state_breadth_pct"}],
                        "fieldConfig": {"defaults": {"min": 0, "max": 100, "thresholds": {
                            "steps": [
                                {"value": 0, "color": "red"},
                                {"value": 35, "color": "yellow"},
                                {"value": 65, "color": "green"},
                            ]
                        }}},
                        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
                    },
                    {
                        "title": "McClellan Oscillator",
                        "type": "timeseries",
                        "targets": [{"expr": "market_state_breadth_mcclellan"}],
                        "fieldConfig": {"defaults": {"thresholds": {
                            "steps": [
                                {"value": -100, "color": "red"},
                                {"value": -50, "color": "yellow"},
                                {"value": 50, "color": "green"},
                                {"value": 100, "color": "yellow"},
                            ]
                        }}},
                        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
                    },
                    {
                        "title": "TRIN (Arms Index)",
                        "type": "timeseries",
                        "targets": [{"expr": "market_state_breadth_trin"}],
                        "fieldConfig": {"defaults": {"thresholds": {
                            "steps": [
                                {"value": 0, "color": "green"},
                                {"value": 1.0, "color": "yellow"},
                                {"value": 1.5, "color": "red"},
                            ]
                        }}},
                        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12},
                    },
                    {
                        "title": "Breadth Thrust",
                        "type": "timeseries",
                        "targets": [{"expr": "market_state_breadth_thrust"}],
                        "fieldConfig": {"defaults": {"min": 0, "max": 1, "thresholds": {
                            "steps": [
                                {"value": 0, "color": "red"},
                                {"value": 0.5, "color": "yellow"},
                                {"value": 0.615, "color": "green"},
                            ]
                        }}},
                        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 12},
                    },
                    {
                        "title": "Transitions",
                        "type": "stat",
                        "targets": [{"expr": "market_state_transitions"}],
                        "gridPos": {"h": 4, "w": 6, "x": 0, "y": 20},
                    },
                    {
                        "title": "Alerts",
                        "type": "stat",
                        "targets": [{"expr": "market_state_alerts"}],
                        "fieldConfig": {"defaults": {"thresholds": {
                            "steps": [{"value": 0, "color": "green"}, {"value": 1, "color": "red"}]
                        }}},
                        "gridPos": {"h": 4, "w": 6, "x": 6, "y": 20},
                    },
                    {
                        "title": "Compute Duration (ms)",
                        "type": "timeseries",
                        "targets": [{"expr": "market_state_compute_ms"}],
                        "gridPos": {"h": 4, "w": 12, "x": 12, "y": 20},
                    },
                ],
            }
        }

    def get_summary(self) -> Dict[str, Any]:
        """Monitoring özeti."""
        return {
            "current_regime": {v: k for k, v in REGIME_ENCODING.items()}.get(self._metrics.regime_value, "UNKNOWN"),
            "confidence": self._metrics.regime_confidence,
            "stability": self._metrics.stability_score,
            "breadth_pct": self._metrics.breadth_pct,
            "risk_appetite": self._metrics.risk_appetite,
            "transition_count": self._metrics.transition_count,
            "alert_count": self._metrics.alert_count,
            "last_update": self._metrics.last_update,
            "history_size": len(self._history),
        }


# Singleton
market_state_monitor = MarketStateMonitor()
