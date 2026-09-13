"""ALPHA BIST — Günlük, EOD ve Telafi Pipeline Servisleri.

Bu paket, Borsa İstanbul (BIST) işlem döngülerini, gün sonu sinyal üretimini (EOD),
sabah seans açılışı mikro-yapı emir yürütümünü ve sistem kapalı kaldığında kaçırılan
seansları otonom olarak telafi eden MasterStartupCatchup motorunu sağlar.
"""
from __future__ import annotations

from services.pipeline.dag_executor import (
    DAGExecutionResult,
    DAGTask,
    PipelineDAGExecutor,
    TaskState,
)
from services.pipeline.main_backtest import (
    DEFAULT_BACKTEST_END_DATE,
    DEFAULT_BACKTEST_START_DATE,
    DEFAULT_COMMISSION_RATE,
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_PURGE_DAYS,
    DEFAULT_SLIPPAGE_PCT,
    DEFAULT_STEP_DAYS,
    DEFAULT_TEST_DAYS,
    DEFAULT_TOP_PICKS,
    DEFAULT_TRAIN_DAYS,
    run_final,
)
from services.pipeline.pipeline_monitor import (
    PipelineMonitor,
    PipelineStatus,
    StageMetric,
    pipeline_monitor,
)
from services.pipeline.recovery_engine import (
    CircuitBreaker,
    CircuitBreakerState,
    DLQEntry,
    ErrorCategory,
    RecoveryAttempt,
    RecoveryEngine,
    RecoveryResult,
    recovery_engine,
)
from services.pipeline.run_daily_inference import (
    DEFAULT_LOOKBACK_DAYS,
    MIN_COMMON_DATES_THRESHOLD,
    REGIME_CASH_THRESHOLD,
    run_alpha_engine_sync,
)
from services.pipeline.run_unified_daily import (
    DEFAULT_INVESTABLE_POOL_FLOOR,
    DEFAULT_MAX_POSITION_CAP,
    DEFAULT_MIN_EXIT_SCORE,
    DEFAULT_MIN_POSITION_FLOOR,
    DEFAULT_MIN_SCORE_THRESHOLD,
    DEFAULT_SCAN_LIMIT,
    HOLDING_PERIOD_DAYS,
    get_last_rebalance_date,
    run_eod_signal_cycle,
    run_morning_execution_cycle,
    run_unified_daily_cycle,
)
from services.pipeline.startup_catchup import (
    DEFAULT_CATCHUP_SCAN_LIMIT,
    DEFAULT_REDIS_PORT,
    TR_TZ,
    MasterStartupCatchup,
    master_catchup,
)

__all__ = [
    "DEFAULT_BACKTEST_END_DATE",
    "DEFAULT_BACKTEST_START_DATE",
    "DEFAULT_CATCHUP_SCAN_LIMIT",
    "DEFAULT_COMMISSION_RATE",
    "DEFAULT_EMBARGO_DAYS",
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_INVESTABLE_POOL_FLOOR",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_MAX_POSITION_CAP",
    "DEFAULT_MIN_EXIT_SCORE",
    "DEFAULT_MIN_POSITION_FLOOR",
    "DEFAULT_MIN_SCORE_THRESHOLD",
    "DEFAULT_PURGE_DAYS",
    "DEFAULT_REDIS_PORT",
    "DEFAULT_SCAN_LIMIT",
    "DEFAULT_SLIPPAGE_PCT",
    "DEFAULT_STEP_DAYS",
    "DEFAULT_TEST_DAYS",
    "DEFAULT_TOP_PICKS",
    "DEFAULT_TRAIN_DAYS",
    "HOLDING_PERIOD_DAYS",
    "MIN_COMMON_DATES_THRESHOLD",
    "MasterStartupCatchup",
    "REGIME_CASH_THRESHOLD",
    "TR_TZ",
    "get_last_rebalance_date",
    "master_catchup",
    "run_alpha_engine_sync",
    "run_eod_signal_cycle",
    "run_final",
    "run_morning_execution_cycle",
    "run_unified_daily_cycle",
    # recovery engine
    "CircuitBreaker",
    "CircuitBreakerState",
    "DLQEntry",
    "ErrorCategory",
    "RecoveryAttempt",
    "RecoveryEngine",
    "RecoveryResult",
    "recovery_engine",
    # pipeline monitor
    "PipelineMonitor",
    "PipelineStatus",
    "StageMetric",
    "pipeline_monitor",
    # dag executor
    "DAGExecutionResult",
    "DAGTask",
    "PipelineDAGExecutor",
    "TaskState",
]
