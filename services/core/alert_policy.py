"""
ALPHA BIST — Alert Policy Configuration v2.0

Merkezi policy yönetimi: API, versioning, rollback, audit, DB silence.

Özellikler:
- API üzerinden policy CRUD
- Policy versiyonlama + geçmiş
- Rollback desteği
- Audit log (kim, ne zaman, ne yaptı)
- DB tabanlı silence yönetimi
- Runtime config reload
- Validation + safe fallback
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()

DEFAULT_POLICY_PATH = Path(__file__).parent.parent.parent / "config" / "alert_policy.json"

# Safe fallback values
FALLBACK_ESCALATION_TIMEOUT_S = {
    "health_change": 300, "invariant_failure": 60, "lock_deadlock": 120,
    "lock_timeout_spike": 300, "cash_negative": 30, "drawdown_breach": 180,
}

FALLBACK_NOTIFICATION_ROUTING = {
    "INFO": ["log"], "WARNING": ["log", "webhook"],
    "CRITICAL": ["log", "webhook", "slack", "discord", "pagerduty", "email"],
}

FALLBACK_SEVERITY_THRESHOLDS = {
    "drawdown_warning_pct": 10.0, "drawdown_critical_pct": 15.0,
    "lock_timeout_spike_count": 3,
}


# =====================================================
# AUDIT LOG
# =====================================================

@dataclass
class PolicyAuditEntry:
    timestamp: float
    action: str  # create, update, rollback, silence_add, silence_remove
    version: int
    actor: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "action": self.action,
            "version": self.version,
            "actor": self.actor,
            "details": self.details,
        }


# =====================================================
# SILENCE RULE
# =====================================================

@dataclass
class SilenceRule:
    """Alert susturma kuralı."""
    alert_type: Optional[str] = None
    fingerprint: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0
    reason: str = ""
    created_by: str = "system"
    created_at: float = field(default_factory=time.time)

    @property
    def is_active(self) -> bool:
        now = time.time()
        return self.start_time <= now <= self.end_time

    @property
    def is_expired(self) -> bool:
        return time.time() > self.end_time

    def matches(self, alert_type: str, fingerprint: str) -> bool:
        if not self.is_active:
            return False
        if self.alert_type and self.alert_type != alert_type:
            return False
        if self.fingerprint and self.fingerprint != fingerprint:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_type": self.alert_type, "fingerprint": self.fingerprint,
            "start_time": self.start_time, "end_time": self.end_time,
            "start_iso": self._ts_iso(self.start_time), "end_iso": self._ts_iso(self.end_time),
            "reason": self.reason, "created_by": self.created_by,
            "created_at": self.created_at, "is_active": self.is_active, "is_expired": self.is_expired,
        }

    @staticmethod
    def _ts_iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""


# =====================================================
# ALERT POLICY
# =====================================================

@dataclass
class AlertPolicy:
    """Alert policy yapılandırması — API yönetilebilir."""
    escalation_timeouts: Dict[str, int] = field(default_factory=lambda: dict(FALLBACK_ESCALATION_TIMEOUT_S))
    notification_routing: Dict[str, List[str]] = field(default_factory=lambda: dict(FALLBACK_NOTIFICATION_ROUTING))
    severity_thresholds: Dict[str, float] = field(default_factory=lambda: dict(FALLBACK_SEVERITY_THRESHOLDS))
    silence_rules: List[SilenceRule] = field(default_factory=list)
    _config_path: Optional[str] = None
    _last_modified: float = 0.0
    _version: int = 0
    _history: List[Dict[str, Any]] = field(default_factory=list)
    _audit_log: List[PolicyAuditEntry] = field(default_factory=list)

    # =====================================================
    # LOAD / RELOAD
    # =====================================================

    @classmethod
    def load(cls, path: str = None) -> "AlertPolicy":
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
        if not self._config_path or not os.path.exists(self._config_path):
            return False
        try:
            mtime = os.path.getmtime(self._config_path)
            if mtime <= self._last_modified:
                return False
            with open(self._config_path) as f:
                data = json.load(f)
            new_policy = AlertPolicy._from_dict(data, self._config_path)
            errors = new_policy.validate()
            if errors:
                logger.error("Alert policy validation failed, keeping current", errors=errors)
                return False
            self._save_history()
            self.escalation_timeouts = new_policy.escalation_timeouts
            self.notification_routing = new_policy.notification_routing
            self.severity_thresholds = new_policy.severity_thresholds
            self._last_modified = mtime
            self._version += 1
            self._add_audit("reload", {"source": "file"})
            logger.info("Alert policy reloaded", version=self._version)
            return True
        except Exception as e:
            logger.error("Alert policy reload failed", error=str(e))
            return False

    # =====================================================
    # API-BASED POLICY MANAGEMENT
    # =====================================================

    def update(self, new_config: Dict[str, Any], actor: str = "api") -> Dict[str, Any]:
        """Policy güncelle (API üzerinden)."""
        # Validate
        test_policy = AlertPolicy._from_dict(new_config, "")
        errors = test_policy.validate()
        if errors:
            return {"success": False, "errors": errors}

        # Save history for rollback
        self._save_history()

        # Apply
        if "escalation_timeouts" in new_config:
            self.escalation_timeouts = new_config["escalation_timeouts"]
        if "notification_routing" in new_config:
            self.notification_routing = new_config["notification_routing"]
        if "severity_thresholds" in new_config:
            self.severity_thresholds = new_config["severity_thresholds"]

        self._version += 1
        self._add_audit("update", {"actor": actor, "changes": list(new_config.keys())})

        # Persist to file
        self._save_to_file()

        return {"success": True, "version": self._version}

    def rollback(self, target_version: int = 0, actor: str = "api") -> Dict[str, Any]:
        """Önceki versiyona geri dön."""
        if not self._history:
            return {"success": False, "error": "No history available"}

        if target_version == 0:
            # Bir önceki versiyona dön
            target = self._history[-1]
        else:
            # Belirli versiyonu bul
            target = None
            for h in self._history:
                if h.get("version") == target_version:
                    target = h
                    break
            if not target:
                return {"success": False, "error": f"Version {target_version} not found"}

        self._save_history()
        self.escalation_timeouts = target.get("escalation_timeouts", dict(FALLBACK_ESCALATION_TIMEOUT_S))
        self.notification_routing = target.get("notification_routing", dict(FALLBACK_NOTIFICATION_ROUTING))
        self.severity_thresholds = target.get("severity_thresholds", dict(FALLBACK_SEVERITY_THRESHOLDS))
        self._version += 1
        self._add_audit("rollback", {"actor": actor, "target_version": target_version})
        self._save_to_file()

        return {"success": True, "version": self._version, "rolled_back_to": target.get("version", "?")}

    def get_history(self) -> List[Dict[str, Any]]:
        """Policy versiyon geçmişi."""
        return self._history[-20:]

    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Audit log."""
        return [e.to_dict() for e in self._audit_log[-limit:]]

    # =====================================================
    # SILENCE MANAGEMENT (DB-backed)
    # =====================================================

    def add_silence(self, alert_type: str = None, fingerprint: str = None,
                    duration_s: float = 3600, reason: str = "",
                    created_by: str = "system", db=None) -> SilenceRule:
        """Susturma ekle + DB persist + audit."""
        rule = SilenceRule(
            alert_type=alert_type, fingerprint=fingerprint,
            start_time=time.time(), end_time=time.time() + duration_s,
            reason=reason, created_by=created_by,
        )
        self.silence_rules.append(rule)
        self._cleanup_expired_silences()
        self._add_audit("silence_add", {
            "alert_type": alert_type, "fingerprint": fingerprint,
            "duration_s": duration_s, "reason": reason, "created_by": created_by,
        })

        # DB persist
        if db:
            self._persist_silence_to_db(rule, db)

        return rule

    def remove_silence(self, fingerprint: str = None, alert_type: str = None,
                       actor: str = "api", db=None) -> int:
        """Susturma kaldır."""
        before = len(self.silence_rules)
        removed_rules = [r for r in self.silence_rules
                        if (fingerprint and r.fingerprint == fingerprint) or
                           (alert_type and r.alert_type == alert_type)]
        self.silence_rules = [
            r for r in self.silence_rules
            if not ((fingerprint and r.fingerprint == fingerprint) or
                    (alert_type and r.alert_type == alert_type))
        ]
        removed = before - len(self.silence_rules)
        if removed:
            self._add_audit("silence_remove", {
                "fingerprint": fingerprint, "alert_type": alert_type,
                "actor": actor, "removed_count": removed,
            })
            if db:
                for rule in removed_rules:
                    self._remove_silence_from_db(rule, db)
        return removed

    def is_silenced(self, alert_type: str, fingerprint: str) -> bool:
        self._cleanup_expired_silences()
        return any(r.matches(alert_type, fingerprint) for r in self.silence_rules)

    def get_active_silences(self) -> List[Dict[str, Any]]:
        self._cleanup_expired_silences()
        return [r.to_dict() for r in self.silence_rules if r.is_active]

    def load_silences_from_db(self, db):
        """DB'den silence'ları yükle."""
        try:
            rows = db.execute(
                "SELECT * FROM alert_silences WHERE end_time > ?",
                (time.time(),)
            ).fetchall()
            self.silence_rules = []
            for row in rows:
                rule = SilenceRule(
                    alert_type=row["alert_type"], fingerprint=row["fingerprint"],
                    start_time=row["start_time"], end_time=row["end_time"],
                    reason=row["reason"] or "", created_by=row["created_by"] or "system",
                    created_at=row["created_at"] or time.time(),
                )
                self.silence_rules.append(rule)
            logger.info("Silences loaded from DB", count=len(self.silence_rules))
        except Exception as e:
            logger.warning("Silence DB load failed", error=str(e))

    def _persist_silence_to_db(self, rule: SilenceRule, db):
        """Silence'ı DB'ye kaydet."""
        try:
            db.execute(
                "INSERT INTO alert_silences "
                "(alert_type, fingerprint, start_time, end_time, reason, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rule.alert_type, rule.fingerprint, rule.start_time, rule.end_time,
                 rule.reason, rule.created_by, rule.created_at)
            )
            db.commit()
        except Exception as e:
            logger.warning("Silence DB persist failed", error=str(e))

    def _remove_silence_from_db(self, rule: SilenceRule, db):
        """Silence'ı DB'den sil."""
        try:
            if rule.fingerprint:
                db.execute("DELETE FROM alert_silences WHERE fingerprint = ?", (rule.fingerprint,))
            elif rule.alert_type:
                db.execute("DELETE FROM alert_silences WHERE alert_type = ?", (rule.alert_type,))
            db.commit()
        except Exception as e:
            logger.warning("Silence DB remove failed", error=str(e))

    # =====================================================
    # VALIDATION
    # =====================================================

    def validate(self) -> List[str]:
        errors = []
        for alert_type, timeout in self.escalation_timeouts.items():
            if not isinstance(timeout, (int, float)) or timeout < 0:
                errors.append(f"Invalid escalation timeout for {alert_type}: {timeout}")
            if timeout > 86400:
                errors.append(f"Escalation timeout too long for {alert_type}: {timeout}s")
        valid_channels = {"log", "webhook", "slack", "discord", "pagerduty", "email"}
        for severity, channels in self.notification_routing.items():
            if severity not in ("INFO", "WARNING", "CRITICAL"):
                errors.append(f"Invalid severity in routing: {severity}")
            for ch in channels:
                if ch not in valid_channels:
                    errors.append(f"Invalid notification channel: {ch}")
        return errors

    # =====================================================
    # QUERIES
    # =====================================================

    def get_escalation_timeout(self, alert_type: str) -> Optional[int]:
        return self.escalation_timeouts.get(str(alert_type) if not isinstance(alert_type, str) else alert_type)

    def get_notification_channels(self, severity: str) -> List[str]:
        return self.notification_routing.get(severity, ["log"])

    def get_threshold(self, key: str, default: float = 0.0) -> float:
        return self.severity_thresholds.get(key, default)

    # =====================================================
    # INTERNAL
    # =====================================================

    def _save_history(self):
        self._history.append({
            "version": self._version,
            "timestamp": time.time(),
            "escalation_timeouts": dict(self.escalation_timeouts),
            "notification_routing": dict(self.notification_routing),
            "severity_thresholds": dict(self.severity_thresholds),
        })
        if len(self._history) > 50:
            self._history = self._history[-50:]

    def _add_audit(self, action: str, details: Dict[str, Any]):
        entry = PolicyAuditEntry(
            timestamp=time.time(), action=action,
            version=self._version, actor=details.get("actor", "system"),
            details=details,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]

    def _save_to_file(self):
        if not self._config_path:
            return
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "w") as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning("Policy save to file failed", error=str(e))

    def _cleanup_expired_silences(self):
        self.silence_rules = [r for r in self.silence_rules if not r.is_expired]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self._version,
            "escalation_timeouts": self.escalation_timeouts,
            "notification_routing": self.notification_routing,
            "severity_thresholds": self.severity_thresholds,
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


def ensure_default_config(path: str = None):
    config_path = path or str(DEFAULT_POLICY_PATH)
    if os.path.exists(config_path):
        return
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump({"version": 1, **AlertPolicy().to_dict()}, f, indent=2)
    logger.info("Default alert policy created", path=config_path)
