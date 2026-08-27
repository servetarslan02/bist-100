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

from .auto_circuit_breaker import AutoCircuitBreakerEngine, CircuitBreakerEvent, auto_circuit_breaker
from .bist_tick_size import get_bist_tick_size, is_valid_bist_tick, round_to_bist_tick
from .circuit_breaker_metrics import CircuitBreakerMetricsCollector, CircuitBreakerSnapshot, circuit_breaker_metrics
from .compliance import ComplianceChecker, compliance_checker
from .config_hot_reload import ConfigChange, ConfigHotReload, SettingsBridge, config_hot_reload, settings_bridge
from .dead_letter_queue import DeadLetterQueue, DLQEntry, DLQStatus, dead_letter_queue
from .distributed_tracing import (
    DistributedTracer,
    Span,
    SpanContextManager,
    Trace,
    correlation_id_var,
    distributed_tracer,
    span_id_var,
    trace,
)
from .fee_calculator import FeeCalculator, fee_calculator
from .gross_settlement import GrossSettlementMonitor, gross_settlement_monitor
from .halt_monitor import HaltMonitor, halt_monitor
from .immutable_audit import AuditEntry, ImmutableAuditLog, immutable_audit_log
from .jwt_manager import JWTClaims, JWTError, JWTManager, TokenType, jwt_manager
from .market_calendar import MarketCalendar, market_calendar
from .market_session_fsm import (
    _TZ_ISTANBUL,
    BISTMarketPhase,
    MarketSessionStateMachine,
    bist_session_fsm,
)
from .price_limits import PriceLimitMonitor, price_limit_monitor
from .risk_gate import RiskGate, risk_gate
from .settlement import SettlementCalculator, settlement_calculator
from .short_selling import ShortSellingMonitor, short_selling_monitor
from .system_governor import (
    FeatureFlag,
    HealthCheck,
    StateTransition,
    SystemState,
    SystemStateGovernor,
    system_governor,
)
from .tax import TaxResult, calculate_tax
from .tradability_mask import TradabilityMask, tradability_mask
from .transaction_helper import TransactionConnection, TransactionHelper, transaction_helper

__all__ = [
    # DLQ
    "DeadLetterQueue",
    "DLQEntry",
    "DLQStatus",
    "dead_letter_queue",
    # JWT
    "JWTManager",
    "JWTClaims",
    "JWTError",
    "TokenType",
    "jwt_manager",
    # Transaction
    "TransactionHelper",
    "TransactionConnection",
    "transaction_helper",
    # Circuit Breaker Metrics
    "CircuitBreakerMetricsCollector",
    "CircuitBreakerSnapshot",
    "circuit_breaker_metrics",
    # Config Hot-Reload
    "ConfigHotReload",
    "ConfigChange",
    "config_hot_reload",
    "SettingsBridge",
    "settings_bridge",
    # Immutable Audit
    "ImmutableAuditLog",
    "AuditEntry",
    "immutable_audit_log",
    # Distributed Tracing
    "DistributedTracer",
    "Span",
    "Trace",
    "SpanContextManager",
    "distributed_tracer",
    "correlation_id_var",
    "span_id_var",
    "trace",
    # System Governor
    "SystemStateGovernor",
    "SystemState",
    "FeatureFlag",
    "StateTransition",
    "HealthCheck",
    "system_governor",
]
