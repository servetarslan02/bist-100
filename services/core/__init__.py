"""
ALPHA BIST — Core Package

Nihai core modülleri:
- dead_letter_queue: Başarısız event'ler için DLQ
- jwt_manager: JWT token yönetimi
- transaction_helper: Database transaction yardımcısı
- circuit_breaker_metrics: Circuit breaker metrics export
- config_hot_reload: Config dosyası hot-reload
- immutable_audit: Değiştirilemez audit log
- distributed_tracing: Distributed tracing & correlation ID
- system_governor: Graceful degradation & feature flags
"""

from .dead_letter_queue import DeadLetterQueue, DLQEntry, DLQStatus, dead_letter_queue
from .jwt_manager import JWTManager, JWTClaims, JWTError, TokenType, jwt_manager
from .transaction_helper import TransactionHelper, TransactionConnection, transaction_helper
from .circuit_breaker_metrics import CircuitBreakerMetricsCollector, CircuitBreakerSnapshot, circuit_breaker_metrics
from .config_hot_reload import ConfigHotReload, ConfigChange, config_hot_reload
from .immutable_audit import ImmutableAuditLog, AuditEntry, immutable_audit_log
from .distributed_tracing import (
    DistributedTracer, Span, Trace, SpanContextManager,
    distributed_tracer, correlation_id_var, span_id_var, trace,
)
from .system_governor import (
    SystemStateGovernor, SystemState, FeatureFlag,
    StateTransition, HealthCheck, system_governor,
)

__all__ = [
    # DLQ
    "DeadLetterQueue", "DLQEntry", "DLQStatus", "dead_letter_queue",
    # JWT
    "JWTManager", "JWTClaims", "JWTError", "TokenType", "jwt_manager",
    # Transaction
    "TransactionHelper", "TransactionConnection", "transaction_helper",
    # Circuit Breaker Metrics
    "CircuitBreakerMetricsCollector", "CircuitBreakerSnapshot", "circuit_breaker_metrics",
    # Config Hot-Reload
    "ConfigHotReload", "ConfigChange", "config_hot_reload",
    # Immutable Audit
    "ImmutableAuditLog", "AuditEntry", "immutable_audit_log",
    # Distributed Tracing
    "DistributedTracer", "Span", "Trace", "SpanContextManager",
    "distributed_tracer", "correlation_id_var", "span_id_var", "trace",
    # System Governor
    "SystemStateGovernor", "SystemState", "FeatureFlag",
    "StateTransition", "HealthCheck", "system_governor",
]
