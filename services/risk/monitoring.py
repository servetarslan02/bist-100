"""
ALPHA BIST — Risk Monitoring & Alerting v1.0

Gerçek zamanlı risk izleme ve uyarı sistemi.
Özelleştirilebilir alert kuralları.

Kaynaklar:
- arXiv 2605.19337 — Agentic Trading Meta-Analiz (2026)
- ScienceDirect — Integrated Risk Management Framework (2026)
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


class AlertType(StrEnum):
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
    ticker: str | None = None
    timestamp: str = ""
    acknowledged: bool = False

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


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
    last_fired: str | None = None
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
    sector_concentration: dict[str, float]
    correlation_risk: float
    regime: str
    risk_score: float  # 0-100


class RiskMonitor:
    """Risk izleme ve alerting sistemi."""

    def __init__(self):
        self._alerts: list[Alert] = []
        self._rules: list[AlertRule] = []
        self._metrics_history: list[RiskMetricsSnapshot] = []
        self._alert_callbacks: list[Callable] = []
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

    def check_metrics(self, metrics: RiskMetricsSnapshot) -> list[Alert]:
        """Risk metriklerini kontrol et ve alert üret.

        Args:
            metrics: Anlık risk metrikleri

        Returns:
            Üretilen alert'ler
        """
        now = datetime.now(UTC).isoformat()
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
            if (
                rule.condition == "gt"
                and value > rule.threshold
                or rule.condition == "lt"
                and value < rule.threshold
                or rule.condition == "gte"
                and value >= rule.threshold
                or rule.condition == "lte"
                and value <= rule.threshold
                or rule.condition == "eq"
                and abs(value - rule.threshold) < 0.001
            ):
                triggered = True

            if triggered:
                # Cooldown kontrolü
                if rule.last_fired:
                    try:
                        last = datetime.fromisoformat(rule.last_fired)
                        elapsed = (datetime.now(UTC) - last).total_seconds()
                        if elapsed < rule.cooldown_seconds:
                            continue
                    except Exception as e:
                        logger.debug("Handled exception", error=str(e), context="monitoring.py:244")

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

                logger.warning(
                    "Risk alert fired",
                    rule=rule.rule_id,
                    severity=rule.severity.value,
                    value=round(value, 2),
                    threshold=rule.threshold,
                )

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
        if len(self._rules) > 100:
            self._rules = self._rules[-100:]
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
        if len(self._alert_callbacks) > 100:
            self._alert_callbacks = self._alert_callbacks[-100:]

    def get_alerts(
        self,
        severity: AlertSeverity | None = None,
        alert_type: AlertType | None = None,
        limit: int = 50,
        unacknowledged_only: bool = False,
    ) -> list[Alert]:
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

    def get_rules(self) -> list[AlertRule]:
        """Tüm alert kurallarını al."""
        return self._rules

    # =====================================================
    # STREAMING REAL-TIME MONITORING (CANLI FİYAT / ORDER BOOK)
    # =====================================================
    def ingest_price_tick(
        self,
        ticker: str,
        price: float,
        volume: float = 0.0,
        best_bid: float | None = None,
        best_ask: float | None = None,
        reference_price: float | None = None,
        price_margin_pct: float = 10.0,
    ) -> list[Alert]:
        """Gerçek zamanlı WebSocket/Market Data fiyat tick'ini işler ve ani risk anomalilerini yakalar."""
        now = datetime.now(UTC).isoformat()
        generated_alerts = []

        if price <= 0:
            return generated_alerts

        # 1. Tavan / Taban Yakınlık Kontrolü (Limit Proximity Alert)
        if reference_price and reference_price > 0:
            upper_limit = reference_price * (1.0 + price_margin_pct / 100.0)
            lower_limit = reference_price * (1.0 - price_margin_pct / 100.0)

            # Tavana %1.5 kala uyarı
            if price >= upper_limit * 0.985:
                dist_pct = ((upper_limit - price) / upper_limit) * 100.0
                alert = Alert(
                    alert_id=f"limit_up_near_{ticker}_{now}",
                    alert_type=AlertType.CUSTOM,
                    severity=AlertSeverity.WARNING,
                    title="Tavan Fiyat Yakınlığı Uyarısı",
                    message=f"{ticker} tavana çok yakın! (Fiyat: {price:.2f}, Tavan: {upper_limit:.2f}, Kalan: %{dist_pct:.1f})",
                    metric_name="limit_up_proximity",
                    metric_value=float(dist_pct),
                    threshold=1.5,
                    ticker=ticker,
                    timestamp=now,
                )
                generated_alerts.append(alert)

            # Tabana %1.5 kala uyarı
            elif price <= lower_limit * 1.015:
                dist_pct = ((price - lower_limit) / lower_limit) * 100.0
                alert = Alert(
                    alert_id=f"limit_down_near_{ticker}_{now}",
                    alert_type=AlertType.CUSTOM,
                    severity=AlertSeverity.WARNING,
                    title="Taban Fiyat Yakınlığı Uyarısı",
                    message=f"{ticker} tabana çok yakın! (Fiyat: {price:.2f}, Taban: {lower_limit:.2f}, Kalan: %{dist_pct:.1f})",
                    metric_name="limit_down_proximity",
                    metric_value=float(dist_pct),
                    threshold=1.5,
                    ticker=ticker,
                    timestamp=now,
                )
                generated_alerts.append(alert)

        # 2. Alış-Satış Makası Açılması (Spread Blowout)
        if best_bid and best_ask and best_bid > 0 and best_ask >= best_bid:
            spread_bps = ((best_ask - best_bid) / best_bid) * 10000.0
            if spread_bps > 150.0:  # %1.50 üzeri aşırı spread
                alert = Alert(
                    alert_id=f"spread_blowout_{ticker}_{now}",
                    alert_type=AlertType.LIQUIDITY,
                    severity=AlertSeverity.WARNING,
                    title="Likidite Kuruması / Spread Açılması",
                    message=f"{ticker} makası aşırı açıldı: {spread_bps:.0f} bps (Bid: {best_bid:.2f}, Ask: {best_ask:.2f})",
                    metric_name="bid_ask_spread_bps",
                    metric_value=float(spread_bps),
                    threshold=150.0,
                    ticker=ticker,
                    timestamp=now,
                )
                generated_alerts.append(alert)

        if generated_alerts:
            self._alerts.extend(generated_alerts)
            if len(self._alerts) > 500:
                self._alerts = self._alerts[-500:]
            for alert in generated_alerts:
                for cb in self._alert_callbacks:
                    try:
                        cb(alert)
                    except Exception as err:
                        logger.error("Callback error", error=str(err))

        return generated_alerts

    def ingest_pipeline_metrics(self, ticker: str, metrics: dict[str, Any]):
        """Pipeline'dan gelen risk metriklerini monitoring'e besle."""
        try:
            if not hasattr(self, "_latest_metrics"):
                self._latest_metrics: dict[str, dict] = {}
            self._latest_metrics[ticker] = {
                "var_95": metrics.get("var_95"),
                "cvar_95": metrics.get("cvar_95"),
                "drawdown": metrics.get("drawdown"),
                "position_size": metrics.get("position_size"),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            # Alert kontrolü
            self._check_alerts(ticker, metrics)
        except Exception as e:
            logger.warning("Failed to ingest pipeline metrics", ticker=ticker, error=str(e))

    def _check_alerts(self, ticker: str, metrics: dict[str, Any]):
        """Basit alert kontrolü."""
        var_95 = abs(metrics.get("var_95", 0))
        if var_95 > 15:
            logger.warning("HIGH VaR ALERT", ticker=ticker, var_95=var_95)

    def get_alert_summary(self) -> dict[str, Any]:
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
