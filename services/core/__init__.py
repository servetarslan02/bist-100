"""ALPHA BIST — Çekirdek (Core) Servis Paketi.

Bu paket, platform genelinde kullanılan operasyonel, altyapısal ve finansal
çekirdek modülleri barındırır:
- auto_circuit_breaker / circuit_breaker_metrics: Otomatik devre kesici ve metrikleri
- bist_tick_size / price_limits / tradability_mask: BIST fiyat adımı, tavan/taban ve alım-satım maskeleri
- compliance / risk_gate: Mevzuat ve risk filtreleri
- config_hot_reload: Dinamik konfigürasyon izleme ve hot-reload
- dead_letter_queue: Başarısız olaylar için DuckDB tabanlı kalıcı DLQ
- distributed_tracing: Dağıtık izleme ve correlation ID yönetimi
- fee_calculator / tax / settlement / gross_settlement: Komisyon, vergi, takas ve brüt takas hesaplamaları
- halt_monitor / short_selling: İşlem durdurma ve açığa satış kontrolleri
- immutable_audit: Değiştirilemez güvenlik ve denetim logu
- jwt_manager: JWT kimlik ve yetkilendirme yönetimi
- market_calendar / market_session_fsm: BIST işlem takvimi ve seans durum makinesi
- system_governor: Zarif bozulma (graceful degradation) ve özellik bayrakları
- transaction_helper: Veritabanı işlem (transaction) yardımcısı
"""

from .alert_policy import (
    DEFAULT_POLICY_PATH,
    FALLBACK_ESCALATION_TIMEOUT_S,
    FALLBACK_NOTIFICATION_ROUTING,
    FALLBACK_SEVERITY_THRESHOLDS,
    AlertPolicy,
    PolicyAuditEntry,
    PolicyDiff,
    SilenceRule,
    VersionConflictError,
    ensure_default_config,
)
from .alerting import (
    Alert,
    AlertingSystem,
    AlertSeverity,
    AlertStatus,
    AlertType,
    DiscordProvider,
    EmailProvider,
    LogProvider,
    NotificationProvider,
    NotificationResult,
    NotificationRouter,
    PagerDutyProvider,
    RetryConfig,
    SlackProvider,
    WebhookProvider,
    alerting,
)
from .algo_notification import (
    AlgoNotification,
    AlgoNotificationStore,
    generate_algo_notification,
)
from .alpha_engine import AlphaEngine
from .arrow_pipeline import ArrowPipeline, arrow_pipeline
from .async_http import AsyncHTTPClient
from .audit_log import AuditLog, audit_log
from .auto_circuit_breaker import AutoCircuitBreakerEngine, CircuitBreakerEvent, auto_circuit_breaker
from .bist_tick_size import (
    add_bist_ticks,
    get_bist_tick_count_between,
    get_bist_tick_size,
    is_valid_bist_tick,
    round_to_bist_tick,
)
from .circuit_breaker import CircuitBreaker, CircuitState
from .circuit_breaker_metrics import CircuitBreakerMetricsCollector, CircuitBreakerSnapshot, circuit_breaker_metrics
from .clickhouse_replication_health import (
    ReplicaHealthInfo,
    ReplicationHealthReport,
    check_replication_health,
    check_replication_health_async,
    is_replication_healthy,
    is_replication_healthy_async,
)
from .compliance import (
    ComplianceAction,
    ComplianceChecker,
    ComplianceResult,
    compliance_checker,
)
from .config_hot_reload import ConfigChange, ConfigHotReload, SettingsBridge, config_hot_reload, settings_bridge
from .dead_letter_queue import DeadLetterQueue, DLQEntry, DLQStatus, dead_letter_queue
from .decision_engine import (
    Action,
    Decision,
    DecisionEngine,
    DecisionInput,
    decision_engine,
)
from .distributed_tracing import (
    DistributedTracer,
    Span,
    Trace,
    TraceSpan,
    correlation_id_var,
    distributed_tracer,
    span_id_var,
    trace,
    trace_async,
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
    # Alarm ve Politika Sistemi
    "Alert",
    "AlertPolicy",
    "AlertSeverity",
    "AlertStatus",
    "AlertType",
    "AlertingSystem",
    "DiscordProvider",
    "EmailProvider",
    "LogProvider",
    "NotificationProvider",
    "NotificationResult",
    "NotificationRouter",
    "PagerDutyProvider",
    "PolicyAuditEntry",
    "PolicyDiff",
    "RetryConfig",
    "SilenceRule",
    "SlackProvider",
    "VersionConflictError",
    "WebhookProvider",
    "alerting",
    "ensure_default_config",
    # Algoritmik İşlem Bildirimi (SPK)
    "AlgoNotification",
    "AlgoNotificationStore",
    "generate_algo_notification",
    # Alpha Motoru ve Veri Boru Hattı
    "AlphaEngine",
    "ArrowPipeline",
    "arrow_pipeline",
    "AsyncHTTPClient",
    "AuditLog",
    "audit_log",
    # Devre Kesici ve Metrikler
    "AutoCircuitBreakerEngine",
    "CircuitBreaker",
    "CircuitBreakerEvent",
    "CircuitBreakerMetricsCollector",
    "CircuitBreakerSnapshot",
    "CircuitState",
    "auto_circuit_breaker",
    "circuit_breaker_metrics",
    # ClickHouse Replikasyon İzleme
    "ReplicaHealthInfo",
    "ReplicationHealthReport",
    "check_replication_health",
    "check_replication_health_async",
    "is_replication_healthy",
    "is_replication_healthy_async",
    # BIST Fiyat Adımı ve Limitler
    "add_bist_ticks",
    "get_bist_tick_count_between",
    "get_bist_tick_size",
    "is_valid_bist_tick",
    "round_to_bist_tick",
    "PriceLimitMonitor",
    "price_limit_monitor",
    "TradabilityMask",
    "tradability_mask",
    # Mevzuat ve Risk
    "ComplianceAction",
    "ComplianceChecker",
    "ComplianceResult",
    "compliance_checker",
    "RiskGate",
    "risk_gate",
    # Konfigürasyon
    "ConfigHotReload",
    "ConfigChange",
    "config_hot_reload",
    "SettingsBridge",
    "settings_bridge",
    # DLQ (Dead Letter Queue)
    "DeadLetterQueue",
    "DLQEntry",
    "DLQStatus",
    "dead_letter_queue",
    # Karar Motoru (Decision Engine)
    "Action",
    "Decision",
    "DecisionEngine",
    "DecisionInput",
    "decision_engine",
    # Dağıtık İzleme (Tracing)
    "DistributedTracer",
    "Span",
    "Trace",
    "TraceSpan",
    "distributed_tracer",
    "correlation_id_var",
    "span_id_var",
    "trace",
    "trace_async",
    # Finansal Hesaplamalar (Komisyon, Vergi, Takas)
    "FeeCalculator",
    "fee_calculator",
    "TaxResult",
    "calculate_tax",
    "SettlementCalculator",
    "settlement_calculator",
    "GrossSettlementMonitor",
    "gross_settlement_monitor",
    # Piyasa İzleme ve Açığa Satış
    "HaltMonitor",
    "halt_monitor",
    "ShortSellingMonitor",
    "short_selling_monitor",
    # Güvenlik ve Denetim
    "ImmutableAuditLog",
    "AuditEntry",
    "immutable_audit_log",
    "JWTManager",
    "JWTClaims",
    "JWTError",
    "TokenType",
    "jwt_manager",
    # Takvim ve Seans FSM
    "MarketCalendar",
    "market_calendar",
    "MarketSessionStateMachine",
    "BISTMarketPhase",
    "bist_session_fsm",
    "_TZ_ISTANBUL",
    # Sistem Durumu (Governor)
    "SystemStateGovernor",
    "SystemState",
    "FeatureFlag",
    "StateTransition",
    "HealthCheck",
    "system_governor",
    # Veritabanı İşlemleri
    "TransactionHelper",
    "TransactionConnection",
    "transaction_helper",
]
