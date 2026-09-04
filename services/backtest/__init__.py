"""
ALPHA BIST — Backtest Paketi

Nihai backtest sistemi modülleri:
- bias_detector: Look-ahead bias tespit sistemi
- survivorship: Survivorship bias yönetimi
- pit_validator: Point-in-time doğrulama
- transaction_costs: BIST'e özgü gerçekçi maliyet modeli
- multi_asset_engine: Çoklu hisse backtest motoru
- event_replay: Gelişmiş event replay motoru
- deterministic: Deterministik recovery sistemi
- deflated_sharpe: Deflated Sharpe Ratio & çoklu test düzeltmesi
- benchmark: Benchmark karşılaştırma motoru
- scanner_parity: Backtest-scanner parite garantisi
- execution_engine: T+1 takas simülatörü (sinyal → trade)
- engine_v4: V4 backtest motoru (feature → sinyal → trade, full pipeline)
- walk_forward: Walk-forward doğrulama motoru
- walk_forward_engine: Walk-forward motor V5 (gelişmiş)
- enhanced_walk_forward: Purge/embargo walk-forward
- backtest_enhancements: T+1 takas, piyasa etkisi, likidite kontrolleri
- canonical_adapter: Feature'lardan canonical score üretimi
"""

# Mevcut modüller
from .benchmark import (
    BenchmarkComparator,
    BenchmarkComparison,
    benchmark_comparator,
)

# Faz 1: Bias Tespiti & PIT
from .bias_detector import (
    BiasDetectorMiddleware,
    BiasReport,
    BiasViolation,
    LookAheadBiasDetector,
)

# Faz 4: Deflated Sharpe & Benchmark
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
from .execution_engine import BacktestEngine, BacktestMetrics, BacktestResult, BacktestTrade
from .event_replay import (
    AuditRecord,
    EnhancedReplayEngine,
    ReplayDecision,
    ReplaySnapshot,
    SystemState,
    enhanced_replay,
)

# Faz 3: Çoklu Varlık, Event Replay, Deterministik
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

# Faz 5: Scanner Parite
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

# Faz 2: İşlem Maliyetleri
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

# Faz 6: Eksik Modüller (isim çakışmaları alias ile çözüldü)
from .backtest_enhancements import (
    BacktestEnhancements,
    CorporateAction,
    backtest_enhancements,
)
from .canonical_adapter import (
    BacktestCanonicalAdapter as CanonicalAdapter,
    backtest_canonical_adapter,
)
from .enhanced_walk_forward import (
    PurgeEmbargoFold,
    PurgeEmbargoResult,
    PurgeEmbargoWalkForward,
)
from .walk_forward import (
    WalkForwardEngine,
    WalkForwardFold,
    WalkForwardResult,
)
from .walk_forward_engine import (
    FoldConfig,
    FoldMetrics,
    FoldSnapshot,
    FoldStatus,
    WalkForwardEngineV5,
    WalkForwardResultV5,
)

__all__ = [
    # Mevcut
    "PortfolioSimulatorV3",
    "BacktestEngineV4",
    "BacktestConfig",
    "BacktestEngine",
    "BacktestMetrics",
    "BacktestResult",
    "BacktestTrade",
    "BacktestPersistence",
    "WalkForwardBacktestRunner",
    # Faz 1
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
    # Faz 2
    "TransactionCostEngine",
    "BISTFeeStructure",
    "SpreadModel",
    "SlippageModel",
    "MarketImpactModel",
    "LiquidityTier",
    "MarketCapCategory",
    "bist_transaction_cost",
    # Faz 3
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
    # Faz 4
    "DeflatedSharpeCalculator",
    "ProbabilisticSharpeRatio",
    "DeflatedSharpeResult",
    "deflated_sharpe",
    "probabilistic_sharpe",
    "BenchmarkComparator",
    "BenchmarkComparison",
    "benchmark_comparator",
    # Faz 5
    "BacktestScannerParity",
    "FeatureVersionLock",
    "ParityConfig",
    "ParityCheckResult",
    "ParityReport",
    "parity_checker",
    "feature_version_lock",
    # Faz 6: Eksik Modüller
    "BacktestEnhancements",
    "CorporateAction",
    "backtest_enhancements",
    "CanonicalAdapter",
    "backtest_canonical_adapter",
    "PurgeEmbargoWalkForward",
    "PurgeEmbargoFold",
    "PurgeEmbargoResult",
    "WalkForwardEngine",
    "WalkForwardFold",
    "WalkForwardResult",
    "FoldConfig",
    "FoldMetrics",
    "FoldSnapshot",
    "FoldStatus",
    "WalkForwardEngineV5",
    "WalkForwardResultV5",
]
