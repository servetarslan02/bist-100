"""
ALPHA BIST — Backtest Package

Nihai backtest sistemi modülleri:
- bias_detector: Look-ahead bias tespit sistemi
- survivorship: Survivorship bias yönetimi
- pit_validator: Point-in-time doğrulama
- transaction_costs: BIST'e özgü gerçekçi maliyet modeli
- multi_asset_engine: Çoklu hisse backtest motoru
- event_replay: Gelişmiş event replay motoru
- deterministic: Deterministik recovery sistemi
- deflated_sharpe: Deflated Sharpe Ratio & multiple testing correction
- benchmark: Benchmark karşılaştırma motoru
- scanner_parity: Backtest-scanner parity garantisi
"""

# Existing modules
from .benchmark import (
    BenchmarkComparator,
    BenchmarkComparison,
    benchmark_comparator,
)

# New modules - Phase 1: Bias Detection & PIT
from .bias_detector import (
    BiasDetectorMiddleware,
    BiasReport,
    BiasViolation,
    LookAheadBiasDetector,
)

# New modules - Phase 4: Deflated Sharpe & Benchmark
from .deflated_sharpe import (
    DeflatedSharpeCalculator,
    DeflatedSharpeResult,
    ProbabilisticSharpeRatio,
    deflated_sharpe,
    probabilistic_sharpe,
)
from .deterministic import (
    DeterministicRecovery,
    IdempotencyGuard,
    SystemCheckpoint,
    deterministic_recovery,
    idempotency_guard,
)
from .engine_v4 import BacktestConfig, BacktestEngineV4
from .event_replay import (
    AuditRecord,
    EnhancedReplayEngine,
    ReplayDecision,
    ReplaySnapshot,
    SystemState,
    enhanced_replay,
)

# New modules - Phase 3: Multi-Asset, Event Replay, Deterministic
from .multi_asset_engine import (
    AssetAllocation,
    MultiAssetBacktestEngine,
    MultiAssetConfig,
    MultiAssetResult,
    SectorExposure,
)
from .persistence import BacktestPersistence
from .pit_validator import (
    PITDataAdapter,
    PITRecord,
    PITValidationReport,
    PITViolation,
    PointInTimeValidator,
    pit_validator,
)
from .portfolio_sim import PortfolioSimulatorV3

# New modules - Phase 5: Scanner Parity
from .scanner_parity import (
    BacktestScannerParity,
    FeatureVersionLock,
    ParityCheckResult,
    ParityConfig,
    ParityReport,
    feature_version_lock,
    parity_checker,
)
from .survivorship import (
    BISTSurvivorshipDataLoader,
    DelistingEvent,
    SurvivorshipBiasHandler,
    UniverseSnapshot,
    survivorship_handler,
)

# New modules - Phase 2: Transaction Costs
from .transaction_costs import (
    BISTFeeStructure,
    LiquidityTier,
    MarketCapCategory,
    MarketImpactModel,
    SlippageModel,
    SpreadModel,
    TransactionCostEngine,
    bist_transaction_cost,
)
from .walk_forward_runner import WalkForwardBacktestRunner

__all__ = [
    # Existing
    "PortfolioSimulatorV3",
    "BacktestEngineV4",
    "BacktestConfig",
    "BacktestPersistence",
    "WalkForwardBacktestRunner",
    # Phase 1
    "LookAheadBiasDetector",
    "BiasDetectorMiddleware",
    "BiasViolation",
    "BiasReport",
    "SurvivorshipBiasHandler",
    "BISTSurvivorshipDataLoader",
    "DelistingEvent",
    "UniverseSnapshot",
    "survivorship_handler",
    "PointInTimeValidator",
    "PITDataAdapter",
    "PITRecord",
    "PITViolation",
    "PITValidationReport",
    "pit_validator",
    # Phase 2
    "TransactionCostEngine",
    "BISTFeeStructure",
    "SpreadModel",
    "SlippageModel",
    "MarketImpactModel",
    "LiquidityTier",
    "MarketCapCategory",
    "bist_transaction_cost",
    # Phase 3
    "MultiAssetBacktestEngine",
    "MultiAssetConfig",
    "MultiAssetResult",
    "SectorExposure",
    "AssetAllocation",
    "EnhancedReplayEngine",
    "SystemState",
    "ReplayDecision",
    "AuditRecord",
    "ReplaySnapshot",
    "enhanced_replay",
    "DeterministicRecovery",
    "IdempotencyGuard",
    "SystemCheckpoint",
    "deterministic_recovery",
    "idempotency_guard",
    # Phase 4
    "DeflatedSharpeCalculator",
    "ProbabilisticSharpeRatio",
    "DeflatedSharpeResult",
    "deflated_sharpe",
    "probabilistic_sharpe",
    "BenchmarkComparator",
    "BenchmarkComparison",
    "benchmark_comparator",
    # Phase 5
    "BacktestScannerParity",
    "FeatureVersionLock",
    "ParityConfig",
    "ParityCheckResult",
    "ParityReport",
    "parity_checker",
    "feature_version_lock",
]
