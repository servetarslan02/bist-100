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
from .portfolio_sim import PortfolioSimulatorV3
from .engine_v4 import BacktestEngineV4, BacktestConfig
from .persistence import BacktestPersistence
from .walk_forward_runner import WalkForwardBacktestRunner

# New modules - Phase 1: Bias Detection & PIT
from .bias_detector import (
    LookAheadBiasDetector,
    BiasDetectorMiddleware,
    BiasViolation,
    BiasReport,
)
from .survivorship import (
    SurvivorshipBiasHandler,
    BISTSurvivorshipDataLoader,
    DelistingEvent,
    UniverseSnapshot,
    survivorship_handler,
)
from .pit_validator import (
    PointInTimeValidator,
    PITDataAdapter,
    PITRecord,
    PITViolation,
    PITValidationReport,
    pit_validator,
)

# New modules - Phase 2: Transaction Costs
from .transaction_costs import (
    TransactionCostEngine,
    BISTFeeStructure,
    SpreadModel,
    SlippageModel,
    MarketImpactModel,
    LiquidityTier,
    MarketCapCategory,
    bist_transaction_cost,
)

# New modules - Phase 3: Multi-Asset, Event Replay, Deterministic
from .multi_asset_engine import (
    MultiAssetBacktestEngine,
    MultiAssetConfig,
    MultiAssetResult,
    SectorExposure,
    AssetAllocation,
)
from .event_replay import (
    EnhancedReplayEngine,
    SystemState,
    ReplayDecision,
    AuditRecord,
    ReplaySnapshot,
    enhanced_replay,
)
from .deterministic import (
    DeterministicRecovery,
    IdempotencyGuard,
    SystemCheckpoint,
    deterministic_recovery,
    idempotency_guard,
)

# New modules - Phase 4: Deflated Sharpe & Benchmark
from .deflated_sharpe import (
    DeflatedSharpeCalculator,
    ProbabilisticSharpeRatio,
    DeflatedSharpeResult,
    deflated_sharpe,
    probabilistic_sharpe,
)
from .benchmark import (
    BenchmarkComparator,
    BenchmarkComparison,
    benchmark_comparator,
)

# New modules - Phase 5: Scanner Parity
from .scanner_parity import (
    BacktestScannerParity,
    FeatureVersionLock,
    ParityConfig,
    ParityCheckResult,
    ParityReport,
    parity_checker,
    feature_version_lock,
)

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
