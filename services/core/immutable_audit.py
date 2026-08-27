"""
ALPHA BIST — Audit Log Immutability Enforcement

Audit log kayıtlarının değiştirilememesini garanti eder.

Özellikler:
1. Hash chain (her kayıt bir öncekine zincirli)
2. DB trigger SQL (UPDATE/DELETE yasaklama)
3. Integrity verification
4. Tamper detection
5. Compliance reporting

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.7
"""

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()


@dataclass
class AuditEntry:
    """Audit log kaydı."""

    entry_id: str
    timestamp: datetime
    user_id: str
    action: str  # CREATE, READ, UPDATE, DELETE, EXECUTE, LOGIN, LOGOUT
    resource_type: str  # portfolio, position, config, model, etc.
    resource_id: str
    details: dict[str, Any]
    ip_address: str | None = None
    user_agent: str | None = None
    previous_hash: str = ""  # Bir önceki kaydın hash'i
    entry_hash: str = ""  # Bu kaydın hash'i

    def compute_hash(self, previous_hash: str = "") -> str:
        """Hash hesapla."""
        content = orjson.dumps(
            {
                "entry_id": self.entry_id,
                "timestamp": self.timestamp.isoformat(),
                "user_id": self.user_id,
                "action": self.action,
                "resource_type": self.resource_type,
                "resource_id": self.resource_id,
                "details": self.details,
            },
            sort_keys=True,
        )

        return hashlib.sha256(f"{previous_hash}:{content}".encode()).hexdigest()[:32]

    def seal(self, previous_hash: str = ""):
        """Hash'i hesapla ve kaydet (immutable seal)."""
        self.previous_hash = previous_hash
        self.entry_hash = self.compute_hash(previous_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }


class ImmutableAuditLog:
    """
    Değiştirilemez audit log.

    Her kayıt bir öncekine zincirli (hash chain).
    Herhangi bir kayıt değiştirilirse zincir kırılır.

    Kullanım:
        audit = ImmutableAuditLog()
        audit.log(user_id="admin", action="UPDATE", resource_type="config", ...)
        is_valid = audit.verify_integrity()
    """

    def __init__(self, storage_path: str | None = None):
        self._entries: list[AuditEntry] = []
        self._last_hash: str = "genesis"
        self._storage_path = storage_path
        self._total_entries: int = 0
        self._total_verified: int = 0

    def log(
        self,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditEntry:
        """
        Audit log kaydı oluştur.

        Args:
            user_id: Kullanıcı ID
            action: İşlem tipi
            resource_type: Kaynak tipi
            resource_id: Kaynak ID
            details: Ek detaylar
            ip_address: IP adresi
            user_agent: User agent

        Returns:
            AuditEntry (sealed, immutable)
        """
        import hashlib as hl

        entry_id = hl.md5(f"audit_{user_id}_{action}_{time.time()}".encode()).hexdigest()[:16]

        entry = AuditEntry(
            entry_id=entry_id,
            timestamp=datetime.now(UTC),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Seal with hash chain
        entry.seal(self._last_hash)
        self._last_hash = entry.entry_hash

        self._entries.append(entry)
        if len(self._entries) > 1000:
            self._entries = self._entries[-1000:]
        self._total_entries += 1

        logger.info(
            "Audit log entry", entry_id=entry_id, user=user_id, action=action, resource=f"{resource_type}:{resource_id}"
        )

        # Persist if configured
        if self._storage_path:
            self._persist_entry(entry)

        return entry

    def verify_integrity(self) -> tuple[bool, str | None]:
        """
        Audit log bütünlüğünü doğrula.

        Returns:
            (is_valid, error_message)
        """
        prev_hash = "genesis"

        for i, entry in enumerate(self._entries):
            # Check previous hash chain
            if entry.previous_hash != prev_hash:
                return False, (
                    f"Hash chain broken at entry {i} "
                    f"(id={entry.entry_id}): "
                    f"expected prev_hash={prev_hash[:12]}, "
                    f"got={entry.previous_hash[:12]}"
                )

            # Verify entry hash
            expected_hash = entry.compute_hash(prev_hash)
            if entry.entry_hash != expected_hash:
                return False, (
                    f"Entry hash mismatch at entry {i} "
                    f"(id={entry.entry_id}): "
                    f"expected={expected_hash[:12]}, "
                    f"got={entry.entry_hash[:12]}"
                )

            prev_hash = entry.entry_hash

        self._total_verified += 1
        return True, None

    def get_entries(
        self,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Audit log kayıtlarını filtrele."""
        entries = self._entries

        if user_id:
            entries = [e for e in entries if e.user_id == user_id]
        if action:
            entries = [e for e in entries if e.action == action]
        if resource_type:
            entries = [e for e in entries if e.resource_type == resource_type]
        if since:
            entries = [e for e in entries if e.timestamp >= since]

        entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)
        return [e.to_dict() for e in entries[:limit]]

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler."""
        by_action = {}
        by_user = {}
        by_resource = {}

        for entry in self._entries:
            by_action[entry.action] = by_action.get(entry.action, 0) + 1
            by_user[entry.user_id] = by_user.get(entry.user_id, 0) + 1
            by_resource[entry.resource_type] = by_resource.get(entry.resource_type, 0) + 1

        return {
            "total_entries": self._total_entries,
            "total_verified": self._total_verified,
            "current_entries": len(self._entries),
            "last_hash": self._last_hash[:16] if self._last_hash else None,
            "by_action": by_action,
            "by_user": by_user,
            "by_resource_type": by_resource,
        }

    def generate_compliance_report(
        self,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """Uyumluluk raporu oluştur."""
        entries = self._entries
        if since:
            entries = [e for e in entries if e.timestamp >= since]

        # Integrity check
        is_valid, error = self.verify_integrity()

        # Action summary
        actions = {}
        for entry in entries:
            actions[entry.action] = actions.get(entry.action, 0) + 1

        # User activity
        user_activity = {}
        for entry in entries:
            if entry.user_id not in user_activity:
                user_activity[entry.user_id] = {"count": 0, "last_action": None}
            user_activity[entry.user_id]["count"] += 1
            user_activity[entry.user_id]["last_action"] = entry.timestamp.isoformat()

        return {
            "report_time": datetime.now(UTC).isoformat(),
            "period": {
                "since": since.isoformat() if since else "all_time",
                "entries_count": len(entries),
            },
            "integrity": {
                "is_valid": is_valid,
                "error": error,
                "last_verification": self._total_verified,
            },
            "actions": actions,
            "user_activity": user_activity,
            "hash_chain": {
                "genesis": "genesis",
                "latest": self._last_hash[:16] if self._last_hash else None,
                "chain_length": len(self._entries),
            },
        }

    def _persist_entry(self, entry: AuditEntry):
        """Kaydı dosyaya yaz (append-only)."""
        try:
            with open(self._storage_path, "a") as f:
                f.write(orjson.dumps(entry.to_dict()) + "\n")
        except Exception as e:
            logger.error("Audit log persist error", error=str(e))

    def export_db_triggers(self) -> str:
        """
        DB trigger SQL'i oluştur.

        Audit log tablosunda UPDATE ve DELETE'i yasaklar.
        """
        return """
-- ALPHA BIST — Audit Log Immutability Triggers
-- Bu trigger'lar audit_log tablosunda UPDATE ve DELETE'i engeller.

-- PostgreSQL version:
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit log records cannot be modified or deleted';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_modification();

CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_modification();

-- SQLite version:
-- CREATE TRIGGER audit_log_no_update
--     BEFORE UPDATE ON audit_log
--     BEGIN
--         SELECT RAISE(ABORT, 'Audit log records cannot be updated');
--     END;

-- CREATE TRIGGER audit_log_no_delete
--     BEFORE DELETE ON audit_log
--     BEGIN
--         SELECT RAISE(ABORT, 'Audit log records cannot be deleted');
--     END;
"""


# Singleton
immutable_audit_log = ImmutableAuditLog()
