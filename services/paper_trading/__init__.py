"""
ALPHA BIST — Paper Trading Engine v1.0

Autonomous Paper Trading Altyapisi:
- Virtual Portfolio (persistent)
- Signal -> Order Simulation
- Portfolio Risk Gate
- Immutable Audit Log
- Performance Engine
- Daily Autonomous Loop

GERCEK PARA YOK. GERCEK BROKER/API YOK.
Champion LOCKED — otomatik degistirilmez.

Mevcut modelleri kullanir:
- services.core.models (Portfolio, Position, Signal)
- services.core.audit_log (AuditLog, AuditEntry)
- services.ml.ranking_model (OpportunityScore)
- services.learning.continuous_learning (ModelRegistry)
"""
from __future__ import annotations

from .kap_corporate_action_registry import CorporateActionRecord, KAPCorporateActionRegistry
from .kap_market_restriction_registry import KAPMarketRestrictionRegistry, MarketRestrictionRecord
from .live_feed_bridge import (
    LiveFeedBridge,
    MarketDepthSnapshot,
    OrderbookLevel,
    live_feed_bridge,
)
from .market_microstructure_engine import MarketMicrostructureEngine, market_microstructure
from .paper_execution import PaperExecutionEngine, paper_execution
from .paper_orchestrator import PaperTradingOrchestrator, paper_orchestrator
from .paper_reporting import (
    PaperReportingEngine,
    PerformanceSummary,
    TradeRecord,
    paper_reporting_engine,
)
from .paper_risk_gate import PaperRiskGate, paper_risk_gate
from .performance_tracker import PerformanceTracker, performance_tracker
from .pre_trade_risk import PreTradeRiskEngine, PreTradeValidationResult
from .scenario_manager import LiquidityScenarioManager, ScenarioResult
from .slippage_model import (
    BISTTickSizer,
    EmpiricalBISTModel,
    KyleLambdaModel,
    OrderSide,
    SlippageCalculator,
    SlippageEstimate,
    SlippageModel,
    SquareRootModel,
    TCAResult,
    slippage_calculator,
)
from .state_store import PaperStateStore, paper_state_store
from .virtual_portfolio import VirtualPortfolio, virtual_portfolio

__all__ = [
    "PaperStateStore",
    "paper_state_store",
    "VirtualPortfolio",
    "virtual_portfolio",
    "PaperExecutionEngine",
    "paper_execution",
    "PaperRiskGate",
    "paper_risk_gate",
    "PaperTradingOrchestrator",
    "paper_orchestrator",
    "PerformanceTracker",
    "performance_tracker",
    "PreTradeRiskEngine",
    "PreTradeValidationResult",
    "LiquidityScenarioManager",
    "ScenarioResult",
    "MarketMicrostructureEngine",
    "market_microstructure",
    "KAPMarketRestrictionRegistry",
    "MarketRestrictionRecord",
    "KAPCorporateActionRegistry",
    "CorporateActionRecord",
    # Slippage Model (TCA)
    "BISTTickSizer",
    "EmpiricalBISTModel",
    "KyleLambdaModel",
    "OrderSide",
    "SlippageCalculator",
    "SlippageEstimate",
    "SlippageModel",
    "SquareRootModel",
    "TCAResult",
    "slippage_calculator",
    # Live Feed Bridge
    "LiveFeedBridge",
    "MarketDepthSnapshot",
    "OrderbookLevel",
    "live_feed_bridge",
    # Paper Reporting
    "PaperReportingEngine",
    "PerformanceSummary",
    "TradeRecord",
    "paper_reporting_engine",
]
