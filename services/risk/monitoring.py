"""
ALPHA BIST — Risk Monitoring & Alerting v1.0

Gerçek zamanlı risk izleme ve uyarı sistemi.
Özelleştirilebilir alert kuralları.

Kaynaklar:
- arXiv 2605.19337 — Agentic Trading Meta-Analiz (2026)
- ScienceDirect — Integrated Risk Management Framework (2026)
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


class AlertType(str, Enum):
    VAR_BREACH = "VAR_BREACH"
    DRAWDOWN = "DRAWDOWN"
    CONCENTRATION = "CONCENTRATION"
    VOLATILITY = "VOLATILITY"
    DAILY_LOSS = "DAILY_LOSS"
    CORRELATION = "CORRELATION"
    LIQUIDITY = "LIQUIDITY"
    CUSTOM = "CUSTOM"


@dataclass
class Alert:
    """Risk alert."""
    alert_id: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    metric_name: str
    metric_value: float
    threshold: float
    ticker: Optional[str] = None
    timestamp: str = ""
    acknowledged: bool = False

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class AlertRule:
    """Alert kuralı."""
    rule_id: str
    name: str
    alert_type: AlertType
    severity: AlertSeverity
    condition: str  # "gt", "lt", "eq", "gte", "lte"
    threshold: float
    metric_name: str
    enabled: bool = True
    cooldown_seconds: int = 300  # 5 dakika
    last_fired: Optional[str] = None
    description: str = ""


@dataclass
class RiskMetricsSnapshot:
    """Anlık risk metrikleri."""
    timestamp: str
    portfolio_value: float
    var_95: float
    cvar_95: float
    portfolio_volatility: float
    current_drawdown_pct: float
    max_drawdown_pct: float
    daily_pnl: float
    daily_pnl_pct: float
    position_count: int
    max_position_pct: float
    sector_concentration: Dict[str, float]
    correlation_risk: float
    regime: str
    risk_score: float  # 0-100


class RiskMonitor:
    """Risk izleme ve alerting sistemi."""

    def __init__(self):
        self._alerts: List[Alert] = []
        self._rules: List[AlertRule] = []
        self._metrics_history: List[RiskMetricsSnapshot] = []
        self._alert_callbacks: List[Callable] = []
        self._setup_default_rules()

    def _setup_default_rules(self):
        """Varsayılan alert kuralları."""
        self._rules = [
            AlertRule(
                rule_id="var_95_breach",
                name="VaR 95% Aşıldı",
                alert_type=AlertType.VAR_BREACH,
                severity=AlertSeverity.WARNING,
                condition="gt",
                threshold=5.0,  # Portföyün %5'i
                metric_name="var_95_pct",
                description="VaR 95% eşiği aşıldı",
            ),
            AlertRule(
                rule_id="cvar_95_breach",
                name="CVaR 95% Aşıldı",
                alert_type=AlertType.VAR_BREACH,
                severity=AlertSeverity.BLOCK,
                condition="gt",
                threshold=8.0,
                metric_name="cvar_95_pct",
                description="CVaR 95% eşiği aşıldı — tail risk yüksek",
            ),
            AlertRule(
                rule_id="drawdown_warning",
                name="Drawdown Uyarı",
                alert_type=AlertType.DRAWDOWN,
                severity=AlertSeverity.WARNING,
                condition="gt",
                threshold=5.0,
                metric_name="current_drawdown_pct",
                description="Drawdown %5'i aştı",
            ),
            AlertRule(
                rule_id="drawdown_critical",
                name="Drawdown Kritik",
                alert_type=AlertType.DRAWDOWN,
                severity=AlertSeverity.CRITICAL,
                condition="gt",
                threshold=15.0,
                metric_name="current_drawdown_pct",
                description="Drawdown %15'i aştı — acil müdahale",
            ),
            AlertRule(
                rule_id="daily_loss_limit",
                name="Günlük Zarar Limiti",
                alert_type=AlertType.DAILY_LOSS,
                severity=AlertSeverity.BLOCK,
                condition="gt",
                threshold=5.0,
                metric_name="daily_loss_pct",
                description="Günlük zarar limiti aşıldı",
            ),
            AlertRule(
                rule_id="concentration_warning",
                name="Konsantrasyon Uyarısı",
                alert_type=AlertType.CONCENTRATION,
                severity=AlertSeverity.WARNING,
                condition="gt",
                threshold=25.0,
                metric_name="max_position_pct",
                description="Tek pozisyon portföyün %25'inden fazlası",
            ),
            AlertRule(
                rule_id="high_volatility",
                name="Yüksek Volatilite",
                alert_type=AlertType.VOLATILITY,
                severity=AlertSeverity.WARNING,
                condition="gt",
                threshold=30.0,
                metric_name="annualized_volatility_pct",
                description="Yıllık volatilite %30'un üzerinde",
            ),
            AlertRule(
                rule_id="risk_score_high",
                name="Risk Skoru Yüksek",
                alert_type=AlertType.CUSTOM,
                severity=AlertSeverity.WARNING,
                condition="gt",
                threshold=70.0,
                metric_name="risk_score",
                description="Risk skoru 70'in üzerinde",
            ),
        ]

    def check_metrics(self, metrics: RiskMetricsSnapshot) -> List[Alert]:
        """Risk metriklerini kontrol et ve alert üret.

        Args:
            metrics: Anlık risk metrikleri

        Returns:
            Üretilen alert'ler
        """
        now = datetime.now(timezone.utc).isoformat()
        new_alerts = []

        # Metrikleri sözlüğe çevir
        metric_values = {
            "var_95_pct": (metrics.var_95 / metrics.portfolio_value * 100) if metrics.portfolio_value > 0 else 0,
            "cvar_95_pct": (metrics.cvar_95 / metrics.portfolio_value * 100) if metrics.portfolio_value > 0 else 0,
            "current_drawdown_pct": metrics.current_drawdown_pct,
            "daily_loss_pct": abs(metrics.daily_pnl_pct) if metrics.daily_pnl < 0 else 0,
            "max_position_pct": metrics.max_position_pct,
            "annualized_volatility_pct": metrics.portfolio_volatility * 100,  # Assuming daily vol
            "risk_score": metrics.risk_score,
            "position_count": metrics.position_count,
            "correlation_risk": metrics.correlation_risk,
        }

        for rule in self._rules:
            if not rule.enabled:
                continue

            value = metric_values.get(rule.metric_name)
            if value is None:
                continue

            # Koşul kontrolü
            triggered = False
            if rule.condition == "gt" and value > rule.threshold:
                triggered = True
            elif rule.condition == "lt" and value < rule.threshold:
                triggered = True
            elif rule.condition == "gte" and value >= rule.threshold:
                triggered = True
            elif rule.condition == "lte" and value <= rule.threshold:
                triggered = True
            elif rule.condition == "eq" and abs(value - rule.threshold) < 0.001:
                triggered = True

            if triggered:
                # Cooldown kontrolü
                if rule.last_fired:
                    try:
                        last = datetime.fromisoformat(rule.last_fired)
                        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                        if elapsed < rule.cooldown_seconds:
                            continue
                    except Exception:
                        pass

                alert = Alert(
                    alert_id=f"{rule.rule_id}_{now}",
                    alert_type=rule.alert_type,
                    severity=rule.severity,
                    title=rule.name,
                    message=f"{rule.description}: {rule.metric_name}={value:.2f} (eşik: {rule.threshold:.2f})",
                    metric_name=rule.metric_name,
                    metric_value=value,
                    threshold=rule.threshold,
                    timestamp=now,
                )

                new_alerts.append(alert)
                rule.last_fired = now

                logger.warning("Risk alert fired",
                             rule=rule.rule_id,
                             severity=rule.severity.value,
                             value=round(value, 2),
                             threshold=rule.threshold)

        self._alerts.extend(new_alerts)

        # Callback'leri çağır
        for alert in new_alerts:
            for callback in self._alert_callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    logger.error("Alert callback error", error=str(e))

        return new_alerts

    def add_rule(self, rule: AlertRule):
        """Yeni alert kuralı ekle."""
        self._rules.append(rule)
        logger.info("Alert rule added", rule_id=rule.rule_id, name=rule.name)

    def remove_rule(self, rule_id: str):
        """Alert kuralı kaldır."""
        self._rules = [r for r in self._rules if r.rule_id != rule_id]

    def enable_rule(self, rule_id: str, enabled: bool = True):
        """Alert kuralını aktif/pasif yap."""
        for rule in self._rules:
            if rule.rule_id == rule_id:
                rule.enabled = enabled
                break

    def register_callback(self, callback: Callable):
        """Alert callback kaydet."""
        self._alert_callbacks.append(callback)

    def get_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        alert_type: Optional[AlertType] = None,
        limit: int = 50,
        unacknowledged_only: bool = False,
    ) -> List[Alert]:
        """Alert'leri filtrele."""
        filtered = self._alerts

        if severity:
            filtered = [a for a in filtered if a.severity == severity]
        if alert_type:
            filtered = [a for a in filtered if a.alert_type == alert_type]
        if unacknowledged_only:
            filtered = [a for a in filtered if not a.acknowledged]

        return filtered[-limit:]

    def acknowledge_alert(self, alert_id: str):
        """Alert'i onayla."""
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                break

    def get_rules(self) -> List[AlertRule]:
        """Tüm alert kurallarını al."""
        return self._rules

    def get_alert_summary(self) -> Dict[str, Any]:
        """Alert özeti."""
        total = len(self._alerts)
        unacknowledged = sum(1 for a in self._alerts if not a.acknowledged)

        by_severity = {}
        for severity in AlertSeverity:
            count = sum(1 for a in self._alerts if a.severity == severity)
            by_severity[severity.value] = count

        by_type = {}
        for alert_type in AlertType:
            count = sum(1 for a in self._alerts if a.alert_type == alert_type)
            if count > 0:
                by_type[alert_type.value] = count

        return {
            "total_alerts": total,
            "unacknowledged": unacknowledged,
            "by_severity": by_severity,
            "by_type": by_type,
            "last_alert": self._alerts[-1].timestamp if self._alerts else None,
        }


# Singleton
risk_monitor = RiskMonitor()
