from __future__ import annotations

# ALPHA BIST — Scanner System v2.0
#
# Modüller:
# - scanner_interface: Abstract interface (backtest-scanner parity)
# - alpha_engine: Ana motor (3 katmanlı tarama)
# - alpha_scanner: Alpha tarama (quant scan + signal generation)
# - tiered_scanner: 6 katmanlı tarama (Tier 0-5)
# - opportunity_engine: 10 bileşenli fırsat skoru
# - event_scanner: Event-driven tarama (KAP/haber/macro)
# - live_scanner: Gerçek zamanlı tick tarama
# - event_queue: Öncelikli event kuyruğu
# - backtest_runner: Scanner backtest runner
# - deduplicator: Tarama deduplication (cooldown)
# - scan_scheduler: Adaptif tarama zamanlaması
# - scan_persistence: Tarama sonuçları persistence
# - performance_tracker: Performans takibi
# - scan_alerts: Alert sistemi
# - custom_filters: BIST'e özel filtreler
# - scan_api: Scan metrics API
from .alpha_scanner import AlphaScanner, ScannerResult, SignalType, alpha_scanner
from .backtest_runner import BacktestResult, BacktestSignal, BacktestTrade, ScannerBacktestRunner
from .bist_ml_scanner import BistMLScanner
from .custom_filters import CustomFilter, CustomFilterEngine, custom_filter_engine
from .deduplicator import ScanDeduplicator, scan_deduplicator
from .dynamic_opportunity_scanner import DynamicOpportunityScanner
from .event_queue import EventPriorityQueue, EventTask
from .event_scanner import EventScanner
from .live_scanner import LiveScanner
from .opportunity_engine import OpportunityDiscoveryEngine, OpportunityScore
from .performance_tracker import ScanMetric, ScanPerformanceTracker, SignalOutcome, performance_tracker
from .scan_alerts import (
    ScanAlert,
    ScanAlertManager,
    ScanAlertRule,
    ScanAlertSeverity,
    ScanAlertType,
    scan_alert_manager,
)
from .scan_api import ScanAPI, scan_api
from .scan_persistence import ScanPersistence, ScanResultRecord, scan_persistence
from .scan_scheduler import AdaptiveScanScheduler, ScanMode, scan_scheduler
from .scanner_interface import ScannerInterface, ScanResult
from .tiered_scanner import AssetTierState, MarketRegime, Tier, TieredScanner, tiered_scanner

__all__ = [
    # Interface
    "ScannerInterface",
    "ScanResult",
    # Alpha Scanner
    "AlphaScanner",
    "ScannerResult",
    "SignalType",
    "alpha_scanner",
    # Tiered Scanner
    "TieredScanner",
    "tiered_scanner",
    "Tier",
    "AssetTierState",
    "MarketRegime",
    # ML & Opportunity Engines
    "BistMLScanner",
    "OpportunityDiscoveryEngine",
    "OpportunityScore",
    "DynamicOpportunityScanner",
    # Event & Live
    "EventScanner",
    "LiveScanner",
    "EventPriorityQueue",
    "EventTask",
    # Backtest Runner
    "ScannerBacktestRunner",
    "BacktestResult",
    "BacktestSignal",
    "BacktestTrade",
    # Deduplication
    "ScanDeduplicator",
    "scan_deduplicator",
    # Scheduler
    "AdaptiveScanScheduler",
    "scan_scheduler",
    "ScanMode",
    # Persistence
    "ScanPersistence",
    "ScanResultRecord",
    "scan_persistence",
    # Performance
    "ScanPerformanceTracker",
    "ScanMetric",
    "SignalOutcome",
    "performance_tracker",
    # Alerts
    "ScanAlert",
    "ScanAlertRule",
    "ScanAlertManager",
    "scan_alert_manager",
    "ScanAlertSeverity",
    "ScanAlertType",
    # Filters
    "CustomFilterEngine",
    "custom_filter_engine",
    "CustomFilter",
    # API
    "ScanAPI",
    "scan_api",
]
