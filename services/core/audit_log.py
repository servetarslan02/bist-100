"""
ALPHA BIST — Audit Log v1.0

Immutable audit trail:
- Decision lineage
- Risk decisions
- Order/fill tracking
- State changes
- Config changes

FAZ 14: Audit Log
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class AuditEntry:
    """Audit log kaydı (immutable)."""
    audit_id: str
    action: str           # DECISION, RISK_CHECK, ORDER, FILL, STATE_CHANGE, CONFIG_CHANGE
    entity_type: str      # ticker, portfolio, order, model
    entity_id: str
    actor: str            # system, decision_engine, risk_engine, user
    details: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = ""
    parent_audit_id: str = ""  # Lineage tracking


class AuditLog:
    """Immutable audit log.

    Bir kararın tam zincirini takip edebilmek için:
    RAW_DATA → FEATURE → SIGNAL → DECISION → RISK → ORDER → FILL
    """

    def __init__(self):
        self._entries: list[AuditEntry] = []
        self._index: dict[str, list[int]] = {}  # entity_id → [entry indices]

    def log(self, entry: AuditEntry):
        """Audit kaydı ekle (append-only)."""
        idx = len(self._entries)
        self._entries.append(entry)
        if len(self._entries) > 1000:
            self._entries = self._entries[-1000:]

        # Index güncelle
        key = f"{entry.entity_type}:{entry.entity_id}"
        if key not in self._index:
            self._index[key] = []
        self._index[key].append(idx)

        logger.debug("Audit log",
                    action=entry.action,
                    entity=f"{entry.entity_type}:{entry.entity_id}",
                    actor=entry.actor)

    def log_decision(
        self,
        ticker: str,
        action: str,
        direction: str,
        confidence: float,
        reasons: list[str],
        risks: list[str],
        correlation_id: str = "",
    ):
        """Karar kaydı."""
        self.log(AuditEntry(
            audit_id=self._generate_id(),
            action="DECISION",
            entity_type="ticker",
            entity_id=ticker,
            actor="decision_engine",
            details={
                "action": action,
                "direction": direction,
                "confidence": confidence,
                "reasons": reasons,
                "risks": risks,
            },
            correlation_id=correlation_id,
        ))

    def log_risk_check(
        self,
        ticker: str,
        approved: bool,
        checks: list[dict],
        correlation_id: str = "",
    ):
        """Risk kontrolü kaydı."""
        self.log(AuditEntry(
            audit_id=self._generate_id(),
            action="RISK_CHECK",
            entity_type="ticker",
            entity_id=ticker,
            actor="risk_engine",
            details={
                "approved": approved,
                "checks": checks,
            },
            correlation_id=correlation_id,
        ))

    def log_order(
        self,
        order_id: str,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str,
        correlation_id: str = "",
    ):
        """Emir kaydı."""
        self.log(AuditEntry(
            audit_id=self._generate_id(),
            action="ORDER",
            entity_type="order",
            entity_id=order_id,
            actor="order_service",
            details={
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
            },
            correlation_id=correlation_id,
        ))

    def log_fill(
        self,
        fill_id: str,
        order_id: str,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        commission: float,
        correlation_id: str = "",
    ):
        """Dolum kaydı."""
        self.log(AuditEntry(
            audit_id=self._generate_id(),
            action="FILL",
            entity_type="fill",
            entity_id=fill_id,
            actor="execution_simulator",
            details={
                "order_id": order_id,
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "price": price,
                "commission": commission,
            },
            correlation_id=correlation_id,
        ))

    def log_state_change(
        self,
        entity_type: str,
        entity_id: str,
        old_value: Any,
        new_value: Any,
        reason: str,
    ):
        """State değişikliği kaydı."""
        self.log(AuditEntry(
            audit_id=self._generate_id(),
            action="STATE_CHANGE",
            entity_type=entity_type,
            entity_id=entity_id,
            actor="system",
            details={
                "old": str(old_value),
                "new": str(new_value),
                "reason": reason,
            },
        ))

    def log_config_change(
        self,
        config_key: str,
        old_value: Any,
        new_value: Any,
        actor: str = "user",
    ):
        """Config değişikliği kaydı."""
        self.log(AuditEntry(
            audit_id=self._generate_id(),
            action="CONFIG_CHANGE",
            entity_type="config",
            entity_id=config_key,
            actor=actor,
            details={
                "old": str(old_value),
                "new": str(new_value),
            },
        ))

    def get_entity_history(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[dict[str, Any]]:
        """Entity'nin tüm geçmişini getir."""
        key = f"{entity_type}:{entity_id}"
        indices = self._index.get(key, [])
        return [
            {
                "audit_id": self._entries[i].audit_id,
                "action": self._entries[i].action,
                "actor": self._entries[i].actor,
                "details": self._entries[i].details,
                "timestamp": self._entries[i].timestamp.isoformat(),
                "correlation_id": self._entries[i].correlation_id,
            }
            for i in indices
        ]

    def get_decision_lineage(self, ticker: str) -> list[dict]:
        """Bir ticker için tam karar zincirini getir."""
        history = self.get_entity_history("ticker", ticker)

        # Sıralı: RAW_DATA → FEATURE → SIGNAL → DECISION → RISK → ORDER → FILL
        action_order = {
            "RAW_DATA": 0, "FEATURE": 1, "SIGNAL": 2,
            "DECISION": 3, "RISK_CHECK": 4, "ORDER": 5, "FILL": 6,
        }
        history.sort(key=lambda x: action_order.get(x["action"], 99))
        return history

    def get_recent(self, limit: int = 50) -> list[dict]:
        """Son audit kayıtları."""
        recent = self._entries[-limit:]
        return [
            {
                "audit_id": e.audit_id,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "actor": e.actor,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in reversed(recent)
        ]

    def get_stats(self) -> dict[str, Any]:
        """Audit istatistikleri."""
        action_counts = {}
        for e in self._entries:
            action_counts[e.action] = action_counts.get(e.action, 0) + 1

        return {
            "total_entries": len(self._entries),
            "action_counts": action_counts,
            "tracked_entities": len(self._index),
        }

    def _generate_id(self) -> str:
        """Unique audit ID."""
        return str(uuid.uuid4())[:16]


# Singleton
audit_log = AuditLog()
