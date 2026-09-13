from __future__ import annotations

# ALPHA BIST — Portfolio Management System v2.0
#
# Modüller:
# - portfolio_manager: Pozisyon yönetimi, muhasebe, P&L, risk metrikleri, rebalancing
# - portfolio_optimizer: Risk Parity, HRP, Mean-Variance, Black-Litterman çoklu optimizasyon motoru
# - portfolio_enhancements: Turnover penalty, cost-aware rebalance, hysteresis, sector/liquidity constraints
# - main: PortfolioService (DB-backed, atomic operations, lock)
# - enhancements: Tax, dividend, benchmark, attribution, multi-currency, TCA
from .autonomous_conviction_engine import (
    AllocationPlan,
    AutonomousConvictionEngine,
    CandidateAsset,
    ExitAction,
    ExitDecision,
    OpenPositionState,
)
from .enhancements import (
    BenchmarkEngine,
    DividendHandler,
    MultiCurrencyHandler,
    PerformanceAttribution,
    TaxModel,
    TransactionCostAnalyzer,
    benchmark_engine,
    dividend_handler,
    multi_currency,
    performance_attribution,
    tax_model,
    tca,
)
from .factor_portfolio import (
    DEFAULT_FACTOR_WEIGHTS,
    FACTOR_NAMES,
    FactorPortfolioOptimizer,
    FactorScoreCalculator,
    FactorScores,
    PortfolioMethod,
    PortfolioWeights,
    factor_optimizer,
    factor_score_calculator,
)
from .portfolio_enhancements import (
    PortfolioConstraints,
    PortfolioEnhancements,
    RebalanceDecision,
    portfolio_enhancements,
)
from .portfolio_manager import (
    CashLedgerEntry,
    CommissionModel,
    EquitySnapshot,
    PortfolioManager,
    Position,
    PositionHistoryEntry,
    Trade,
    portfolio_manager,
)
from .portfolio_optimizer import (
    OptimizationMethod,
    OptimizationResult,
    PortfolioOptimizer,
    PortfolioOptimizerConstraints,
    portfolio_optimizer,
)
from .tax_loss_harvesting import (
    HarvestCandidate,
    HarvestPlan,
    TaxLossHarvestEngine,
    tax_harvest_engine,
)
from .tax_loss_harvesting import Position as HarvestPosition

__all__ = [
    # Portfolio Manager
    "PortfolioManager",
    "portfolio_manager",
    "Position",
    "Trade",
    "CashLedgerEntry",
    "EquitySnapshot",
    "PositionHistoryEntry",
    "CommissionModel",
    # Portfolio Optimizer
    "PortfolioOptimizer",
    "portfolio_optimizer",
    "OptimizationMethod",
    "OptimizationResult",
    "PortfolioOptimizerConstraints",
    # Enhancements & Constraints
    "PortfolioEnhancements",
    "portfolio_enhancements",
    "PortfolioConstraints",
    "RebalanceDecision",
    "TaxModel",
    "tax_model",
    "DividendHandler",
    "dividend_handler",
    "BenchmarkEngine",
    "benchmark_engine",
    "PerformanceAttribution",
    "performance_attribution",
    "MultiCurrencyHandler",
    "multi_currency",
    "TransactionCostAnalyzer",
    "tca",
    # Autonomous Conviction
    "AutonomousConvictionEngine",
    "CandidateAsset",
    "OpenPositionState",
    "AllocationPlan",
    "ExitDecision",
    "ExitAction",
    # Factor Portfolio
    "FactorPortfolioOptimizer",
    "factor_optimizer",
    "FactorScoreCalculator",
    "factor_score_calculator",
    "FactorScores",
    "PortfolioMethod",
    "PortfolioWeights",
    "FACTOR_NAMES",
    "DEFAULT_FACTOR_WEIGHTS",
    # Tax Loss Harvesting
    "TaxLossHarvestEngine",
    "tax_harvest_engine",
    "HarvestCandidate",
    "HarvestPlan",
    "HarvestPosition",
]
