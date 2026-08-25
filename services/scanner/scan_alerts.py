"""
ALPHA BIST — Scan Alert Manager v1.0

Kritik tarama sonuçlarını bildirim sistemine bağlar.
Özelleştirilebilir alert kuralları.

Kaynaklar: Mometic (2026), Endüstri standardı
"""

import time
from typing import Dict, List, Any, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class ScanAlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


class ScanAlertType(str, Enum):
    HIGH_SCORE = "HIGH_SCORE"
    NEW_SIGNAL = "NEW_SIGNAL"
    TIER_CHANGE = "TIER_CHANGE"
    ANOMALY = "ANOMALY"
    REGIME_SHIFT = "REGIME_SHIFT"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    BREAKOUT = "BREAKOUT"


@dataclass
class ScanAlert:
    """Tarama alert'i."""
    alert_id: str
    alert_type: ScanAlertType
    severity: ScanAlertSeverity
    ticker: str
    title: str
    message: str
    score: float
    signal: str
    direction: str
    confidence: float
    price: float
    timestamp: str
    acknowledged: bool = False


@dataclass
class ScanAlertRule:
    """Alert kuralı."""
    rule_id: str
    name: str
    alert_type: ScanAlertType
    severity: ScanAlertSeverity
    condition: str       # "score_gt", "new_signal", "tier_change", "anomaly"
    threshold: float
    enabled: bool = True
    cooldown_seconds: int = 300  # 5 dakika
    last_fired: float = 0.0
    description: str = ""


class ScanAlertManager:
    """Tarama alert yöneticisi.

    Alert Kuralları:
    - Score > 80 → INFO
    - Score > 90 → WARNING
    - Tier değişimi (event escalation) → WARNING
    - Anomaly (volume_zscore > 4) → CRITICAL
    - Yeni sinyal (önceki taramada yoktu) → INFO
    """

    def __init__(self):
        self._alerts: List[ScanAlert] = []
        self._rules: List[ScanAlertRule] = []
        self._callbacks: List[Callable] = []
        self._previous_signals: Dict[str, str] = {}  # ticker → signal
        self._setup_default_rules()

    def _setup_default_rules(self):
        """Varsayılan alert kuralları."""
        self._rules = [
            ScanAlertRule(
                rule_id="high_score_80",
                name="Yüksek Skor (80+)",
                alert_type=ScanAlertType.HIGH_SCORE,
                severity=ScanAlertSeverity.INFO,
                condition="score_gt",
                threshold=80.0,
                description="Fırsat skoru 80'in üzerinde",
            ),
            ScanAlertRule(
                rule_id="high_score_90",
                name="Çok Yüksek Skor (90+)",
                alert_type=ScanAlertType.HIGH_SCORE,
                severity=ScanAlertSeverity.WARNING,
                condition="score_gt",
                threshold=90.0,
                description="Fırsat skoru 90'ın üzerinde",
            ),
            ScanAlertRule(
                rule_id="new_signal",
                name="Yeni Sinyal",
                alert_type=ScanAlertType.NEW_SIGNAL,
                severity=ScanAlertSeverity.INFO,
                condition="new_signal",
                threshold=0,
                cooldown_seconds=600,  # 10 dakika
                description="Önceki taramada olmayan yeni sinyal",
            ),
            ScanAlertRule(
                rule_id="tier_escalation",
                name="Tier Yükseltme",
                alert_type=ScanAlertType.TIER_CHANGE,
                severity=ScanAlertSeverity.WARNING,
                condition="tier_change",
                threshold=0,
                description="Event-driven tier atlama",
            ),
            ScanAlertRule(
                rule_id="volume_anomaly",
                name="Hacim Anomalisi",
                alert_type=ScanAlertType.ANOMALY,
                severity=ScanAlertSeverity.CRITICAL,
                condition="anomaly",
                threshold=4.0,  # volume_zscore > 4
                cooldown_seconds=600,
                description="Olağandışı hacim artışı (4σ+)",
            ),
            ScanAlertRule(
                rule_id="breakout_signal",
                name="Kırılım Sinyali",
                alert_type=ScanAlertType.BREAKOUT,
                severity=ScanAlertSeverity.WARNING,
                condition="breakout",
                threshold=80.0,  # breakout_score > 80
                description="Güçlü kırılım sinyali",
            ),
        ]

    def check_scan_results(
        self,
        results: List[Dict[str, Any]],
        regime: str = "RANGE",
    ) -> List[ScanAlert]:
        """Tarama sonuçlarını kontrol et ve alert üret.

        Args:
            results: Tarama sonuçları
            regime: Piyasa rejimi

        Returns:
            Üretilen alert'ler
        """
        now = time.time()
        new_alerts = []

        for result in results:
            ticker = result.get("ticker", "")
            score = result.get("score", 0)
            signal = result.get("signal", "")
            direction = result.get("direction", "NEUTRAL")
            confidence = result.get("confidence", 0)
            price = result.get("price", 0)
            volume_zscore = result.get("volume_zscore", 0)
            breakout_score = result.get("breakout_score", 0)
            tier = result.get("tier", 0)

            # Her kuralı kontrol et
            for rule in self._rules:
                if not rule.enabled:
                    continue

                # Cooldown kontrolü
                if now - rule.last_fired < rule.cooldown_seconds:
                    continue

                triggered = False
                message = ""

                if rule.condition == "score_gt" and score >= rule.threshold:
                    triggered = True
                    message = f"{ticker}: Fırsat skoru {score:.1f} (eşik: {rule.threshold})"

                elif rule.condition == "new_signal":
                    prev_signal = self._previous_signals.get(ticker, "")
                    if signal and signal != prev_signal:
                        triggered = True
                        message = f"{ticker}: Yeni sinyal: {signal} (önceki: {prev_signal or 'yok'})"

                elif rule.condition == "tier_change" and result.get("escalated"):
                    triggered = True
                    message = f"{ticker}: Tier {tier}'a yükseltildi (event: {result.get('escalation_reason', '')})"

                elif rule.condition == "anomaly" and volume_zscore >= rule.threshold:
                    triggered = True
                    message = f"{ticker}: Hacim anomalisi {volume_zscore:.1f}σ (eşik: {rule.threshold}σ)"

                elif rule.condition == "breakout" and breakout_score >= rule.threshold:
                    triggered = True
                    message = f"{ticker}: Kırılım skoru {breakout_score:.0f} (eşik: {rule.threshold})"

                if triggered:
                    alert = ScanAlert(
                        alert_id=f"{rule.rule_id}_{ticker}_{int(now)}",
                        alert_type=rule.alert_type,
                        severity=rule.severity,
                        ticker=ticker,
                        title=rule.name,
                        message=message,
                        score=score,
                        signal=signal,
                        direction=direction,
                        confidence=confidence,
                        price=price,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )

                    new_alerts.append(alert)
                    rule.last_fired = now

                    logger.warning("Scan alert fired",
                                 rule=rule.rule_id,
                                 ticker=ticker,
                                 severity=rule.severity.value)

            # Sinyal geçmişini güncelle
            if signal:
                self._previous_signals[ticker] = signal

        self._alerts.extend(new_alerts)

        # Callback'leri çağır
        for alert in new_alerts:
            for callback in self._callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    logger.error("Alert callback error", error=str(e))

        return new_alerts

    def register_callback(self, callback: Callable):
        """Alert callback kaydet.

        Args:
            callback: Alert callback fonksiyonu
        """
        self._callbacks.append(callback)
        if len(self._callbacks) > 100:
            self._callbacks = self._callbacks[-100:]

    def add_rule(self, rule: ScanAlertRule):
        """Yeni alert kuralı ekle.

        Args:
            rule: Alert kuralı
        """
        self._rules.append(rule)
        if len(self._rules) > 100:
            self._rules = self._rules[-100:]
        logger.info("Scan alert rule added", rule_id=rule.rule_id)

    def get_alerts(
        self,
        severity: ScanAlertSeverity = None,
        alert_type: ScanAlertType = None,
        limit: int = 50,
    ) -> List[ScanAlert]:
        """Alert'leri filtrele.

        Args:
            severity: Severity filtresi
            alert_type: Tür filtresi
            limit: Maksimum sonuç

        Returns:
            Filtrelenmiş alert'ler
        """
        filtered = self._alerts

        if severity:
            filtered = [a for a in filtered if a.severity == severity]
        if alert_type:
            filtered = [a for a in filtered if a.alert_type == alert_type]

        return filtered[-limit:]

    def get_alert_summary(self) -> Dict[str, Any]:
        """Alert özeti.

        Returns:
            Alert istatistikleri
        """
        total = len(self._alerts)
        unacknowledged = sum(1 for a in self._alerts if not a.acknowledged)

        by_severity = {}
        for severity in ScanAlertSeverity:
            count = sum(1 for a in self._alerts if a.severity == severity)
            by_severity[severity.value] = count

        by_type = {}
        for alert_type in ScanAlertType:
            count = sum(1 for a in self._alerts if a.alert_type == alert_type)
            if count > 0:
                by_type[alert_type.value] = count

        return {
            "total_alerts": total,
            "unacknowledged": unacknowledged,
            "by_severity": by_severity,
            "by_type": by_type,
            "rules_count": len(self._rules),
            "active_rules": sum(1 for r in self._rules if r.enabled),
        }

    def acknowledge_alert(self, alert_id: str):
        """Alert'i onayla.

        Args:
            alert_id: Alert kimliği
        """
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                break

    def clear_old_alerts(self, max_age_hours: int = 24):
        """Eski alert'leri temizle.

        Args:
            max_age_hours: Maksimum yaş (saat)
        """
        cutoff = time.time() - (max_age_hours * 3600)
        self._alerts = [
            a for a in self._alerts
            if datetime.fromisoformat(a.timestamp).timestamp() > cutoff
        ]


# Singleton
scan_alert_manager = ScanAlertManager()
