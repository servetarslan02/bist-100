"""
ALPHA BIST — Feature Engine Package v2.0

Tüm feature modülleri:
- calculator: Teknik feature hesaplama (mask-first)
- store: Feature store (PIT-aware, versioned, lineage)
- drift_detector: Feature drift detection (KS, PSI, z-score)
- importance_tracker: Feature importance tracking (SHAP, RFE)
- bist_features: BIST'e özgü feature'lar
- feature_selector: Feature selection (correlation, variance, importance)
- feature_contract: Feature data contract
- pipeline: Pipeline orchestrator
- seven_motors: 7 motor feature engine
- cross_sectional: Cross-sectional features
- fundamental: Fundamental features
- macro: Macro features
- sentiment: Sentiment features
- incremental_state: Incremental feature state
- panel_engine: Panel feature engine
- bar_engine: Canonical bar engine
- data_adapter: Data adapter
- discovery: Feature discovery
- extended_indicators: Extended technical indicators
- technical_features: Technical features
- main: Feature engine service (event-driven)
"""

# Core
from .calculator import FeatureCalculator

# Feature Store v2.0
from .store import (
    FeatureStore, FeatureMeta, FeatureSnapshot, LineageRecord,
    FeatureSource, LineageStage, feature_store,
)

# Drift Detection
from .drift_detector import (
    FeatureDriftDetector, DriftResult, DriftReport, DriftAlert,
    DriftSeverity, DriftMethod, drift_detector,
)

# Importance Tracking
from .importance_tracker import (
    FeatureImportanceTracker, FeatureImportance, ImportanceSnapshot,
    RFEResult, ImportanceDrift, importance_tracker,
)

# BIST Features
from .bist_features import (
    BISTFeatureEngine, BISTFeatureSet, bist_feature_engine,
)

# Feature Selection
from .feature_selector import FeatureSelector, feature_selector

# Feature Contract
from .feature_contract import (
    FeatureDataPoint, TickerFeatureContract, FeatureStatus,
    make_fresh, make_missing, make_unknown, make_stale,
    features_to_contract, merge_feature_dicts,
)

# Pipeline
from .pipeline import (
    FeaturePipelineOrchestrator, PipelineConfig, PipelineResult,
    feature_pipeline,
)

__all__ = [
    # Core
    "FeatureCalculator",
    # Store
    "FeatureStore", "FeatureMeta", "FeatureSnapshot", "LineageRecord",
    "FeatureSource", "LineageStage", "feature_store",
    # Drift
    "FeatureDriftDetector", "DriftResult", "DriftReport", "DriftAlert",
    "DriftSeverity", "DriftMethod", "drift_detector",
    # Importance
    "FeatureImportanceTracker", "FeatureImportance", "ImportanceSnapshot",
    "RFEResult", "ImportanceDrift", "importance_tracker",
    # BIST
    "BISTFeatureEngine", "BISTFeatureSet", "bist_feature_engine",
    # Selection
    "FeatureSelector", "feature_selector",
    # Contract
    "FeatureDataPoint", "TickerFeatureContract", "FeatureStatus",
    "make_fresh", "make_missing", "make_unknown", "make_stale",
    "features_to_contract", "merge_feature_dicts",
    # Pipeline
    "FeaturePipelineOrchestrator", "PipelineConfig", "PipelineResult",
    "feature_pipeline",
]
