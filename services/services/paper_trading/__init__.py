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

from .state_store import PaperStateStore, paper_state_store
from .virtual_portfolio import VirtualPortfolio, virtual_portfolio
from .paper_execution import PaperExecutionEngine, paper_execution
from .paper_risk_gate import PaperRiskGate, paper_risk_gate
from .paper_orchestrator import PaperTradingOrchestrator, paper_orchestrator
from .performance_tracker import PerformanceTracker, performance_tracker

__all__ = [
    "PaperStateStore", "paper_state_store",
    "VirtualPortfolio", "virtual_portfolio",
    "PaperExecutionEngine", "paper_execution",
    "PaperRiskGate", "paper_risk_gate",
    "PaperTradingOrchestrator", "paper_orchestrator",
    "PerformanceTracker", "performance_tracker",
]
