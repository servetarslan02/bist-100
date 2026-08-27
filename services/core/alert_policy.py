"""
ALPHA BIST — Alert Policy Configuration v3.0

Kurumsal operasyon: diff, optimistic locking, webhook, batch silence.

Özellikler:
- Policy diff (eski/yeni/değişen alanlar)
- Optimistic locking (çakışan güncellemeleri engelle)
- Policy change webhook notification
- Batch silence işlemleri (transaction)
- Audit log (her değişiklik)
"""

import asyncio
import copy
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()

DEFAULT_POLICY_PATH = Path(__file__).parent.parent.parent / "config" / "alert_policy.json"

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

MAX_BATCH_SILENCE_SIZE = 100
WEBHOOK_RETRY_COUNT = 3
WEBHOOK_RETRY_DELAY_S = 1.0


# =====================================================
# POLICY DIFF
# =====================================================


@dataclass
class PolicyDiff:
    """Policy değişiklik farkı."""

    changed_fields: list[str] = field(default_factory=list)
    added_keys: list[str] = field(default_factory=list)
    removed_keys: list[str] = field(default_factory=list)
    old_values: dict[str, Any] = field(default_factory=dict)
    new_values: dict[str, Any] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_fields or self.added_keys or self.removed_keys)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_changes": self.has_changes,
            "changed_fields": self.changed_fields,
            "added_keys": self.added_keys,
            "removed_keys": self.removed_keys,
            "old_values": self.old_values,
            "new_values": self.new_values,
        }

    def summary(self) -> str:
        parts = []
        if self.changed_fields:
            parts.append(f"changed: {', '.join(self.changed_fields)}")
        if self.added_keys:
            parts.append(f"added: {', '.join(self.added_keys)}")
        if self.removed_keys:
            parts.append(f"removed: {', '.join(self.removed_keys)}")
        return "; ".join(parts) if parts else "no changes"


@dataclass
class PolicyAuditEntry:
    timestamp: float
    action: str
    version: int
    actor: str
    details: dict[str, Any]
    diff: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "action": self.action,
            "version": self.version,
            "actor": self.actor,
            "details": self.details,
        }
        if self.diff:
            result["diff"] = self.diff
        return result


# =====================================================
# SILENCE RULE
# =====================================================


@dataclass
class SilenceRule:
    alert_type: str | None = None
    fingerprint: str | None = None
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
        return not (self.fingerprint and self.fingerprint != fingerprint)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "fingerprint": self.fingerprint,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "start_iso": self._ts_iso(self.start_time),
            "end_iso": self._ts_iso(self.end_time),
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "is_active": self.is_active,
            "is_expired": self.is_expired,
        }

    @staticmethod
    def _ts_iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=UTC).isoformat() if ts else ""


# =====================================================
# ALERT POLICY
# =====================================================


class VersionConflictError(Exception):
    """Optimistic locking conflict."""


@dataclass
class AlertPolicy:
    escalation_timeouts: dict[str, int] = field(default_factory=lambda: dict(FALLBACK_ESCALATION_TIMEOUT_S))
    notification_routing: dict[str, list[str]] = field(default_factory=lambda: dict(FALLBACK_NOTIFICATION_ROUTING))
    severity_thresholds: dict[str, float] = field(default_factory=lambda: dict(FALLBACK_SEVERITY_THRESHOLDS))
    silence_rules: list[SilenceRule] = field(default_factory=list)
    _config_path: str | None = None
    _last_modified: float = 0.0
    _version: int = 0
    _history: list[dict[str, Any]] = field(default_factory=list)
    _audit_log: list[PolicyAuditEntry] = field(default_factory=list)
    _webhook_urls: list[str] = field(default_factory=list)
    _lock_owner: str | None = None
    _lock_expires: float = 0.0

    # =====================================================
    # LOAD / RELOAD
    # =====================================================

    @classmethod
    def load(cls, path: str = None) -> "AlertPolicy":
        config_path = path or str(DEFAULT_POLICY_PATH)
        policy = cls(_config_path=config_path)
        if not os.path.exists(config_path):
            return policy
        try:
            with open(config_path) as f:
                data = orjson.loads(f.read())
            policy = cls._from_dict(data, config_path)
            return policy
        except Exception as e:
            logger.error("Policy load failed, using fallback", error=str(e))
            return cls(_config_path=config_path)

    def reload_if_changed(self) -> bool:
        if not self._config_path or not os.path.exists(self._config_path):
            return False
        try:
            mtime = os.path.getmtime(self._config_path)
            if mtime <= self._last_modified:
                return False
            with open(self._config_path) as f:
                data = orjson.loads(f.read())
            new_policy = AlertPolicy._from_dict(data, self._config_path)
            errors = new_policy.validate()
            if errors:
                logger.error("Policy validation failed", errors=errors)
                return False
            old_dict = self.to_dict()
            self._save_history()
            self.escalation_timeouts = new_policy.escalation_timeouts
            self.notification_routing = new_policy.notification_routing
            self.severity_thresholds = new_policy.severity_thresholds
            self._last_modified = mtime
            self._version += 1
            diff = self._compute_diff(old_dict, self.to_dict())
            self._add_audit("reload", {"source": "file"}, diff)
            self._notify_change("reload", diff)
            return True
        except Exception as e:
            logger.error("Policy reload failed", error=str(e))
            return False

    # =====================================================
    # POLICY UPDATE (with optimistic locking)
    # =====================================================

    def update(self, new_config: dict[str, Any], actor: str = "api", expected_version: int = 0) -> dict[str, Any]:
        """Policy güncelle (optimistic locking ile).

        Args:
            new_config: Yeni config
            actor: Kim güncelledi
            expected_version: Beklenen versiyon (0 = kontrol yok)
        """
        # Optimistic locking check
        if expected_version > 0 and expected_version != self._version:
            raise VersionConflictError(
                f"Version conflict: expected {expected_version}, current {self._version}. "
                f"Başka bir kullanıcı tarafından güncellenmiş olabilir."
            )

        # Validate
        test_policy = AlertPolicy._from_dict(new_config, "")
        errors = test_policy.validate()
        if errors:
            return {"success": False, "errors": errors}

        # Compute diff
        old_dict = copy.deepcopy(self.to_dict())

        # Save history
        self._save_history()

        # Apply changes
        if "escalation_timeouts" in new_config:
            self.escalation_timeouts = new_config["escalation_timeouts"]
        if "notification_routing" in new_config:
            self.notification_routing = new_config["notification_routing"]
        if "severity_thresholds" in new_config:
            self.severity_thresholds = new_config["severity_thresholds"]

        self._version += 1
        diff = self._compute_diff(old_dict, self.to_dict())

        # Audit
        self._add_audit(
            "update",
            {
                "actor": actor,
                "changes": list(new_config.keys()),
                "expected_version": expected_version,
            },
            diff,
        )

        # Persist
        self._save_to_file()

        # Webhook notification
        self._notify_change("update", diff)

        return {"success": True, "version": self._version, "diff": diff.to_dict()}

    # =====================================================
    # POLICY DIFF
    # =====================================================

    def compute_diff(self, new_config: dict[str, Any]) -> PolicyDiff:
        """İki config arasındaki farkı hesapla (uygulamadan)."""
        old_dict = self.to_dict()
        return self._compute_diff(old_dict, new_config)

    @staticmethod
    def _compute_diff(old: dict[str, Any], new: dict[str, Any]) -> PolicyDiff:
        """Diff hesaplama."""
        diff = PolicyDiff()

        all_keys = set(list(old.keys()) + list(new.keys()))
        for key in all_keys:
            if key.startswith("_"):
                continue
            old_val = old.get(key)
            new_val = new.get(key)

            if key not in old:
                diff.added_keys.append(key)
                diff.new_values[key] = new_val
            elif key not in new:
                diff.removed_keys.append(key)
                diff.old_values[key] = old_val
            elif old_val != new_val:
                diff.changed_fields.append(key)
                diff.old_values[key] = old_val
                diff.new_values[key] = new_val

        return diff

    def three_way_diff(self, base_version: int, version_a: int, version_b: int) -> dict[str, Any]:
        """Üçlü karşılaştırma: base ile iki versiyon arasındaki farkları bul.

        Returns:
            {
                "base_version": int,
                "version_a": int,
                "version_b": int,
                "a_only": {field: value},    # Sadece A'da değişen
                "b_only": {field: value},    # Sadece B'de değişen
                "both_changed": {field: {"a": val, "b": val}},  # Her ikisinde değişen (conflict)
                "identical": [field],         # Her ikisinde aynı değişen
                "has_conflicts": bool,
            }
        """
        base = self._get_history_version(base_version)
        ver_a = self._get_history_version(version_a)
        ver_b = self._get_history_version(version_b)

        if not base or not ver_a or not ver_b:
            return {
                "error": "One or more versions not found",
                "found": {"base": base is not None, "a": ver_a is not None, "b": ver_b is not None},
            }

        diff_a = self._compute_diff(base, ver_a)
        diff_b = self._compute_diff(base, ver_b)

        # Metadata alanlarını hariç tut
        skip_keys = {"version", "timestamp"}
        a_changed = set(diff_a.changed_fields + diff_a.added_keys + diff_a.removed_keys) - skip_keys
        b_changed = set(diff_b.changed_fields + diff_b.added_keys + diff_b.removed_keys) - skip_keys

        a_only = {}
        for f in a_changed - b_changed:
            base_val = base.get(f)
            a_val = ver_a.get(f)
            a_only[f] = {"base": base_val, "a": a_val}

        b_only = {}
        for f in b_changed - a_changed:
            base_val = base.get(f)
            b_val = ver_b.get(f)
            b_only[f] = {"base": base_val, "b": b_val}

        both_changed = {}
        identical = []
        for f in a_changed & b_changed:
            val_a = ver_a.get(f)
            val_b = ver_b.get(f)
            if val_a == val_b:
                identical.append(f)
            else:
                both_changed[f] = {"base": base.get(f), "a": val_a, "b": val_b}

        return {
            "base_version": base_version,
            "version_a": version_a,
            "version_b": version_b,
            "a_only": a_only,
            "b_only": b_only,
            "both_changed": both_changed,
            "identical": identical,
            "has_conflicts": len(both_changed) > 0,
            "conflict_fields": list(both_changed.keys()),
        }

    def _get_history_version(self, version: int) -> dict[str, Any] | None:
        """History'den belirli versiyonu getir."""
        if version == self._version:
            return self.to_dict()
        for h in self._history:
            if h.get("version") == version:
                return h
        return None

    # =====================================================
    # OPTIMISTIC LOCKING
    # =====================================================

    def acquire_edit_lock(self, owner: str, timeout_s: float = 30.0) -> bool:
        """Policy düzenleme kilidi al (auto-release expired locks)."""
        now = time.time()
        if self._lock_owner and self._lock_owner != owner:
            if self._lock_expires > now:
                return False  # Başkası kilitli ve süresi dolmamış
            # Süresi dolmuş kilit — otomatik temizle + audit
            old_owner = self._lock_owner
            self._lock_owner = None
            self._lock_expires = 0.0
            self._add_audit(
                "lock_expired_recovery",
                {
                    "old_owner": old_owner,
                    "new_owner": owner,
                    "expired_at": self._lock_expires,
                },
            )
        self._lock_owner = owner
        self._lock_expires = now + timeout_s
        self._add_audit("lock_acquired", {"owner": owner, "timeout_s": timeout_s})
        return True

    def release_edit_lock(self, owner: str) -> bool:
        """Policy düzenleme kilidi bırak."""
        if self._lock_owner != owner:
            return False
        self._lock_owner = None
        self._lock_expires = 0.0
        self._add_audit("lock_released", {"owner": owner})
        return True

    def is_locked(self) -> bool:
        """Kilitli mi?"""
        return self._lock_owner is not None and self._lock_expires > time.time()

    def get_lock_info(self) -> dict[str, Any]:
        """Kilit bilgisi."""
        return {
            "locked": self.is_locked(),
            "owner": self._lock_owner,
            "expires_at": self._lock_expires,
            "expires_iso": datetime.fromtimestamp(self._lock_expires, tz=UTC).isoformat()
            if self._lock_expires
            else None,
        }

    # =====================================================
    # ROLLBACK
    # =====================================================

    def rollback(self, target_version: int = 0, actor: str = "api") -> dict[str, Any]:
        if not self._history:
            return {"success": False, "error": "No history"}

        if target_version == 0:
            target = self._history[-1]
        else:
            target = None
            for h in self._history:
                if h.get("version") == target_version:
                    target = h
                    break
            if not target:
                return {"success": False, "error": f"Version {target_version} not found"}

        old_dict = copy.deepcopy(self.to_dict())
        self._save_history()
        self.escalation_timeouts = target.get("escalation_timeouts", dict(FALLBACK_ESCALATION_TIMEOUT_S))
        self.notification_routing = target.get("notification_routing", dict(FALLBACK_NOTIFICATION_ROUTING))
        self.severity_thresholds = target.get("severity_thresholds", dict(FALLBACK_SEVERITY_THRESHOLDS))
        self._version += 1
        diff = self._compute_diff(old_dict, self.to_dict())
        self._add_audit("rollback", {"actor": actor, "target_version": target_version}, diff)
        self._save_to_file()
        self._notify_change("rollback", diff)

        return {"success": True, "version": self._version, "diff": diff.to_dict()}

    # =====================================================
    # WEBHOOK NOTIFICATION
    # =====================================================

    def set_webhook_urls(self, urls: list[str]):
        """Policy değişiklik webhook URL'leri."""
        self._webhook_urls = urls

    def _notify_change(self, action: str, diff: PolicyDiff):
        """Policy değişikliği bildirimi."""
        if not self._webhook_urls or not diff.has_changes:
            return

        payload = {
            "event": "policy_change",
            "action": action,
            "version": self._version,
            "timestamp": datetime.now(UTC).isoformat(),
            "diff": diff.to_dict(),
        }

        for url in self._webhook_urls:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._send_webhook(url, payload))
                else:
                    # Event loop yoksa sync çalıştır
                    loop.run_until_complete(self._send_webhook(url, payload))
            except RuntimeError:
                # Yeni event loop oluştur
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self._send_webhook(url, payload))
                    loop.close()
                except Exception:
                    logger.warning("Webhook notification failed (no event loop)")

    async def _send_webhook(self, url: str, payload: dict[str, Any]):
        """Webhook gönder (retry ile)."""
        import aiohttp

        last_error = None
        for attempt in range(WEBHOOK_RETRY_COUNT):
            try:
                async with (
                    aiohttp.ClientSession() as session,
                    session.post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp,
                ):
                    if resp.status < 400:
                        logger.info("Policy webhook sent", url=url, status=resp.status, attempt=attempt + 1)
                        return True
                    else:
                        last_error = f"HTTP {resp.status}"
                        logger.warning("Policy webhook failed", url=url, status=resp.status, attempt=attempt + 1)
            except Exception as e:
                last_error = str(e)
                logger.warning("Policy webhook error", url=url, error=str(e), attempt=attempt + 1)

            if attempt < WEBHOOK_RETRY_COUNT - 1:
                await asyncio.sleep(WEBHOOK_RETRY_DELAY_S * (attempt + 1))

        self._add_audit("webhook_failed", {"url": url, "error": last_error, "attempts": WEBHOOK_RETRY_COUNT})
        return False

    # =====================================================
    # SILENCE MANAGEMENT (DB-backed + batch)
    # =====================================================

    def add_silence(
        self,
        alert_type: str = None,
        fingerprint: str = None,
        duration_s: float = 3600,
        reason: str = "",
        created_by: str = "system",
        db=None,
    ) -> SilenceRule:
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
        self._add_audit(
            "silence_add",
            {
                "alert_type": alert_type,
                "fingerprint": fingerprint,
                "duration_s": duration_s,
                "reason": reason,
                "created_by": created_by,
            },
        )
        if db:
            self._persist_silence_to_db(rule, db)
        return rule

    def batch_add_silences(
        self, rules_config: list[dict[str, Any]], created_by: str = "system", db=None
    ) -> list[dict[str, Any]]:
        """Toplu susturma ekleme (transaction, batch limit ile)."""
        # Batch size limit
        if len(rules_config) > MAX_BATCH_SILENCE_SIZE:
            return [
                {"success": False, "error": f"Batch size {len(rules_config)} exceeds limit {MAX_BATCH_SILENCE_SIZE}"}
            ]

        results = []
        created_rules = []

        for config in rules_config:
            rule = SilenceRule(
                alert_type=config.get("alert_type"),
                fingerprint=config.get("fingerprint"),
                start_time=time.time(),
                end_time=time.time() + config.get("duration_s", 3600),
                reason=config.get("reason", ""),
                created_by=created_by,
            )
            created_rules.append(rule)
            self.silence_rules.append(rule)
            results.append({"success": True, "rule": rule.to_dict()})

        # DB transaction
        if db and created_rules:
            try:
                for rule in created_rules:
                    self._persist_silence_to_db(rule, db)
                db.commit()
            except Exception as e:
                db.rollback()
                # Rollback in-memory
                for rule in created_rules:
                    if rule in self.silence_rules:
                        self.silence_rules.remove(rule)
                results = [{"success": False, "error": str(e)} for _ in rules_config]

        self._add_audit(
            "batch_silence_add",
            {
                "count": len(rules_config),
                "created_by": created_by,
                "success_count": sum(1 for r in results if r.get("success")),
            },
        )
        return results

    def batch_remove_silences(self, filters: list[dict[str, str]], actor: str = "api", db=None) -> dict[str, int]:
        """Toplu susturma kaldırma (transaction)."""
        removed_count = 0
        removed_rules = []

        for f in filters:
            fp = f.get("fingerprint")
            at = f.get("alert_type")
            to_remove = [r for r in self.silence_rules if (fp and r.fingerprint == fp) or (at and r.alert_type == at)]
            for rule in to_remove:
                self.silence_rules.remove(rule)
                removed_rules.append(rule)
                removed_count += 1

        # DB transaction
        if db and removed_rules:
            try:
                for rule in removed_rules:
                    self._remove_silence_from_db(rule, db)
                db.commit()
            except Exception:
                db.rollback()
                # Restore in-memory
                self.silence_rules.extend(removed_rules)
                removed_count = 0

        self._add_audit(
            "batch_silence_remove",
            {
                "filters": filters,
                "actor": actor,
                "removed_count": removed_count,
            },
        )
        return {"removed": removed_count}

    def remove_silence(self, fingerprint: str = None, alert_type: str = None, actor: str = "api", db=None) -> int:
        before = len(self.silence_rules)
        removed_rules = [
            r
            for r in self.silence_rules
            if (fingerprint and r.fingerprint == fingerprint) or (alert_type and r.alert_type == alert_type)
        ]
        self.silence_rules = [
            r
            for r in self.silence_rules
            if not ((fingerprint and r.fingerprint == fingerprint) or (alert_type and r.alert_type == alert_type))
        ]
        removed = before - len(self.silence_rules)
        if removed:
            self._add_audit(
                "silence_remove",
                {
                    "fingerprint": fingerprint,
                    "alert_type": alert_type,
                    "actor": actor,
                },
            )
            if db:
                for rule in removed_rules:
                    self._remove_silence_from_db(rule, db)
        return removed

    def is_silenced(self, alert_type: str, fingerprint: str) -> bool:
        self._cleanup_expired_silences()
        return any(r.matches(alert_type, fingerprint) for r in self.silence_rules)

    def get_active_silences(self) -> list[dict[str, Any]]:
        self._cleanup_expired_silences()
        return [r.to_dict() for r in self.silence_rules if r.is_active]

    def load_silences_from_db(self, db):
        try:
            rows = db.execute("SELECT * FROM alert_silences WHERE end_time > ?", (time.time(),)).fetchall()
            self.silence_rules = []
            for row in rows:
                rule = SilenceRule(
                    alert_type=row["alert_type"],
                    fingerprint=row["fingerprint"],
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    reason=row["reason"] or "",
                    created_by=row["created_by"] or "system",
                    created_at=row["created_at"] or time.time(),
                )
                self.silence_rules.append(rule)
        except Exception as e:
            logger.warning("Silence DB load failed", error=str(e))

    def _persist_silence_to_db(self, rule: SilenceRule, db):
        try:
            db.execute(
                "INSERT OR IGNORE INTO alert_silences "
                "(alert_type, fingerprint, start_time, end_time, reason, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    rule.alert_type,
                    rule.fingerprint,
                    rule.start_time,
                    rule.end_time,
                    rule.reason,
                    rule.created_by,
                    rule.created_at,
                ),
            )
        except Exception as e:
            logger.warning("Silence DB persist failed", error=str(e))

    def _remove_silence_from_db(self, rule: SilenceRule, db):
        try:
            if rule.fingerprint:
                db.execute("DELETE FROM alert_silences WHERE fingerprint = ?", (rule.fingerprint,))
            elif rule.alert_type:
                db.execute("DELETE FROM alert_silences WHERE alert_type = ?", (rule.alert_type,))
        except Exception as e:
            logger.warning("Silence DB remove failed", error=str(e))

    # =====================================================
    # VALIDATION / QUERIES
    # =====================================================

    def validate(self) -> list[str]:
        errors = []
        for alert_type, timeout in self.escalation_timeouts.items():
            if not isinstance(timeout, (int, float)) or timeout < 0:
                errors.append(f"Invalid timeout for {alert_type}: {timeout}")
            if timeout > 86400:
                errors.append(f"Timeout too long for {alert_type}: {timeout}s")
        valid_channels = {"log", "webhook", "slack", "discord", "pagerduty", "email"}
        for severity, channels in self.notification_routing.items():
            if severity not in ("INFO", "WARNING", "CRITICAL"):
                errors.append(f"Invalid severity: {severity}")
            for ch in channels:
                if ch not in valid_channels:
                    errors.append(f"Invalid channel: {ch}")
        return errors

    def get_escalation_timeout(self, alert_type: str) -> int | None:
        return self.escalation_timeouts.get(alert_type)

    def get_notification_channels(self, severity: str) -> list[str]:
        return self.notification_routing.get(severity, ["log"])

    def get_threshold(self, key: str, default: float = 0.0) -> float:
        return self.severity_thresholds.get(key, default)

    def get_history(self) -> list[dict[str, Any]]:
        return self._history[-20:]

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._audit_log[-limit:]]

    # =====================================================
    # INTERNAL
    # =====================================================

    def _save_history(self):
        self._history.append(
            {
                "version": self._version,
                "timestamp": time.time(),
                "escalation_timeouts": dict(self.escalation_timeouts),
                "notification_routing": dict(self.notification_routing),
                "severity_thresholds": dict(self.severity_thresholds),
            }
        )
        if len(self._history) > 50:
            self._history = self._history[-50:]

    def _add_audit(self, action: str, details: dict[str, Any], diff: PolicyDiff = None):
        entry = PolicyAuditEntry(
            timestamp=time.time(),
            action=action,
            version=self._version,
            actor=details.get("actor", "system"),
            details=details,
            diff=diff.to_dict() if diff else None,
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
                f.write(orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2).decode())
        except Exception as e:
            logger.warning("Policy save failed", error=str(e))

    def _cleanup_expired_silences(self):
        self.silence_rules = [r for r in self.silence_rules if not r.is_expired]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "escalation_timeouts": self.escalation_timeouts,
            "notification_routing": self.notification_routing,
            "severity_thresholds": self.severity_thresholds,
        }

    @classmethod
    def _from_dict(cls, data: dict[str, Any], config_path: str = "") -> "AlertPolicy":
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
        f.write(orjson.dumps({"version": 1, **AlertPolicy().to_dict()}, option=orjson.OPT_INDENT_2).decode())
