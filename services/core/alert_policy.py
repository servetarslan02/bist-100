"""
ALPHA BIST — Alert Policy Configuration

Dosya tabanlı alert policy yönetimi.
Runtime reload, validation, safe fallback.

Özellikler:
- JSON/YAML config dosyasından policy okuma
- Runtime config reload (dosya değişikliği algılama)
- Policy validation (geçersiz config → fallback)
- Escalation kuralları, severity, timeout, notification routing
- Maintenance window (silence) desteği

Kullanım:
    policy = AlertPolicy.load("config/alert_policy.json")
    policy.reload_if_changed()
    timeout = policy.get_escalation_timeout("cash_negative")
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()

DEFAULT_POLICY_PATH = Path(__file__).parent.parent.parent / "config" / "alert_policy.json"

# Safe fallback values
FALLBACK_ESCALATION_TIMEOUT_S = {
    "health_change": 300,
    "invariant_failure": 60,
    "lock_deadlock": 120,
    "lock_timeout_spike": 300,
    "cash_negative": 30,
    "drawdown_breach": 180,
}

FALLBACK_NOTIFICATION_ROUTING = {
    "INFO": ["log"],
    "WARNING": ["log", "webhook"],
    "CRITICAL": ["log", "webhook", "slack", "discord", "pagerduty", "email"],
}

FALLBACK_SEVERITY_THRESHOLDS = {
    "drawdown_warning_pct": 10.0,
    "drawdown_critical_pct": 15.0,
    "lock_timeout_spike_count": 3,
}


@dataclass
class SilenceRule:
    """Alert susturma kuralı."""
    alert_type: Optional[str] = None       # None = tüm tipler
    fingerprint: Optional[str] = None      # None = tüm fingerprint'ler
    start_time: float = 0.0
    end_time: float = 0.0
    reason: str = ""
    created_by: str = "system"

    @property
    def is_active(self) -> bool:
        now = time.time()
        return self.start_time <= now <= self.end_time

    @property
    def is_expired(self) -> bool:
        return time.time() > self.end_time

    def matches(self, alert_type: str, fingerprint: str) -> bool:
        """Bu silence kuralı bu alert'e uygulanır mı?"""
        if not self.is_active:
            return False
        if self.alert_type and self.alert_type != alert_type:
            return False
        if self.fingerprint and self.fingerprint != fingerprint:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "fingerprint": self.fingerprint,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "start_iso": self._ts_to_iso(self.start_time),
            "end_iso": self._ts_to_iso(self.end_time),
            "reason": self.reason,
            "created_by": self.created_by,
            "is_active": self.is_active,
            "is_expired": self.is_expired,
        }

    @staticmethod
    def _ts_to_iso(ts: float) -> str:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""


@dataclass
class AlertPolicy:
    """Alert policy yapılandırması."""
    escalation_timeouts: Dict[str, int] = field(default_factory=lambda: dict(FALLBACK_ESCALATION_TIMEOUT_S))
    notification_routing: Dict[str, List[str]] = field(default_factory=lambda: dict(FALLBACK_NOTIFICATION_ROUTING))
    severity_thresholds: Dict[str, float] = field(default_factory=lambda: dict(FALLBACK_SEVERITY_THRESHOLDS))
    silence_rules: List[SilenceRule] = field(default_factory=list)
    _config_path: Optional[str] = None
    _last_modified: float = 0.0
    _version: int = 0

    # =====================================================
    # LOAD / RELOAD
    # =====================================================

    @classmethod
    def load(cls, path: str = None) -> "AlertPolicy":
        """Config dosyasından policy yükle."""
        config_path = path or str(DEFAULT_POLICY_PATH)
        policy = cls(_config_path=config_path)

        if not os.path.exists(config_path):
            logger.info("Alert policy file not found, using defaults", path=config_path)
            return policy

        try:
            with open(config_path) as f:
                data = json.load(f)

            policy = cls._from_dict(data, config_path)
            logger.info("Alert policy loaded", path=config_path, version=policy._version)
            return policy

        except Exception as e:
            logger.error("Alert policy load failed, using fallback", path=config_path, error=str(e))
            return cls(_config_path=config_path)

    def reload_if_changed(self) -> bool:
        """Dosya değiştiyse yeniden yükle."""
        if not self._config_path or not os.path.exists(self._config_path):
            return False

        try:
            mtime = os.path.getmtime(self._config_path)
            if mtime <= self._last_modified:
                return False

            with open(self._config_path) as f:
                data = json.load(f)

            new_policy = AlertPolicy._from_dict(data, self._config_path)

            # Validation
            errors = new_policy.validate()
            if errors:
                logger.error("Alert policy validation failed, keeping current",
                           errors=errors)
                return False

            # Apply
            self.escalation_timeouts = new_policy.escalation_timeouts
            self.notification_routing = new_policy.notification_routing
            self.severity_thresholds = new_policy.severity_thresholds
            self.silence_rules = new_policy.silence_rules
            self._last_modified = mtime
            self._version += 1

            logger.info("Alert policy reloaded", version=self._version)
            return True

        except Exception as e:
            logger.error("Alert policy reload failed", error=str(e))
            return False

    # =====================================================
    # VALIDATION
    # =====================================================

    def validate(self) -> List[str]:
        """Policy doğrulama. Hata listesi döndürür."""
        errors = []

        # Escalation timeouts
        for alert_type, timeout in self.escalation_timeouts.items():
            if not isinstance(timeout, (int, float)) or timeout < 0:
                errors.append(f"Invalid escalation timeout for {alert_type}: {timeout}")
            if timeout > 86400:  # 24 saat
                errors.append(f"Escalation timeout too long for {alert_type}: {timeout}s")

        # Notification routing
        valid_channels = {"log", "webhook", "slack", "discord", "pagerduty", "email"}
        for severity, channels in self.notification_routing.items():
            if severity not in ("INFO", "WARNING", "CRITICAL"):
                errors.append(f"Invalid severity in routing: {severity}")
            for ch in channels:
                if ch not in valid_channels:
                    errors.append(f"Invalid notification channel: {ch}")

        # Severity thresholds
        for key, val in self.severity_thresholds.items():
            if not isinstance(val, (int, float)):
                errors.append(f"Invalid threshold {key}: {val}")

        return errors

    # =====================================================
    # QUERIES
    # =====================================================

    def get_escalation_timeout(self, alert_type: str) -> int:
        """Alert tipi için escalation timeout (saniye)."""
        return self.escalation_timeouts.get(alert_type, 300)

    def get_notification_channels(self, severity: str) -> List[str]:
        """Severity için bildirim kanalları."""
        return self.notification_routing.get(severity, ["log"])

    def get_threshold(self, key: str, default: float = 0.0) -> float:
        """Eşik değeri."""
        return self.severity_thresholds.get(key, default)

    # =====================================================
    # SILENCE MANAGEMENT
    # =====================================================

    def add_silence(self, alert_type: str = None, fingerprint: str = None,
                    duration_s: float = 3600, reason: str = "",
                    created_by: str = "system") -> SilenceRule:
        """Yeni silence kuralı ekle."""
        rule = SilenceRule(
            alert_type=alert_type,
            fingerprint=fingerprint,
            start_time=time.time(),
            end_time=time.time() + duration_s,
            reason=reason,
            created_by=created_by,
        )
        self.silence_rules.append(rule)
        self._cleanup_expired_silences()
        logger.info("Silence added", alert_type=alert_type, fingerprint=fingerprint,
                   duration_s=duration_s, reason=reason)
        return rule

    def remove_silence(self, fingerprint: str = None, alert_type: str = None) -> int:
        """Silence kuralı kaldır."""
        before = len(self.silence_rules)
        self.silence_rules = [
            r for r in self.silence_rules
            if not (r.fingerprint == fingerprint or r.alert_type == alert_type)
        ]
        removed = before - len(self.silence_rules)
        if removed:
            logger.info("Silence removed", count=removed)
        return removed

    def is_silenced(self, alert_type: str, fingerprint: str) -> bool:
        """Bu alert susturulmuş mu?"""
        self._cleanup_expired_silences()
        return any(r.matches(alert_type, fingerprint) for r in self.silence_rules)

    def get_active_silences(self) -> List[Dict[str, Any]]:
        """Aktif silence kuralları."""
        self._cleanup_expired_silences()
        return [r.to_dict() for r in self.silence_rules if r.is_active]

    def _cleanup_expired_silences(self):
        """Süresi biten silence'ları temizle."""
        self.silence_rules = [r for r in self.silence_rules if not r.is_expired]

    # =====================================================
    # PERSISTENCE (restart recovery)
    # =====================================================

    def save_silences(self, path: str = None):
        """Silence kurallarını dosyaya kaydet."""
        save_path = path or (str(Path(self._config_path).parent / "silence_state.json") if self._config_path else None)
        if not save_path:
            return

        try:
            data = [r.to_dict() for r in self.silence_rules if not r.is_expired]
            with open(save_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.info("Silence state saved", path=save_path, count=len(data))
        except Exception as e:
            logger.warning("Silence save failed", error=str(e))

    def load_silences(self, path: str = None):
        """Silence kurallarını dosyadan yükle."""
        load_path = path or (str(Path(self._config_path).parent / "silence_state.json") if self._config_path else None)
        if not load_path or not os.path.exists(load_path):
            return

        try:
            with open(load_path) as f:
                data = json.load(f)

            for item in data:
                rule = SilenceRule(
                    alert_type=item.get("alert_type"),
                    fingerprint=item.get("fingerprint"),
                    start_time=item.get("start_time", 0),
                    end_time=item.get("end_time", 0),
                    reason=item.get("reason", ""),
                    created_by=item.get("created_by", "system"),
                )
                if not rule.is_expired:
                    self.silence_rules.append(rule)

            logger.info("Silence state loaded", path=load_path,
                       active=len([r for r in self.silence_rules if r.is_active]))
        except Exception as e:
            logger.warning("Silence load failed", error=str(e))

    # =====================================================
    # SERIALIZATION
    # =====================================================

    def to_dict(self) -> Dict[str, Any]:
        return {
            "escalation_timeouts": self.escalation_timeouts,
            "notification_routing": self.notification_routing,
            "severity_thresholds": self.severity_thresholds,
            "active_silences": len([r for r in self.silence_rules if r.is_active]),
            "version": self._version,
        }

    @classmethod
    def _from_dict(cls, data: Dict[str, Any], config_path: str = "") -> "AlertPolicy":
        policy = cls(_config_path=config_path)
        policy._last_modified = os.path.getmtime(config_path) if config_path and os.path.exists(config_path) else 0
        policy._version = data.get("version", 0)

        if "escalation_timeouts" in data:
            policy.escalation_timeouts = data["escalation_timeouts"]
        if "notification_routing" in data:
            policy.notification_routing = data["notification_routing"]
        if "severity_thresholds" in data:
            policy.severity_thresholds = data["severity_thresholds"]

        return policy


# Default config dosyası oluştur
def ensure_default_config(path: str = None):
    """Varsayılan config dosyası yoksa oluştur."""
    config_path = path or str(DEFAULT_POLICY_PATH)
    if os.path.exists(config_path):
        return

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    default = {
        "version": 1,
        "escalation_timeouts": FALLBACK_ESCALATION_TIMEOUT_S,
        "notification_routing": FALLBACK_NOTIFICATION_ROUTING,
        "severity_thresholds": FALLBACK_SEVERITY_THRESHOLDS,
    }
    with open(config_path, "w") as f:
        json.dump(default, f, indent=2)
    logger.info("Default alert policy created", path=config_path)
