"""ALPHA BIST — Feature Engine Package v3.0.

Feature Contract sistemi ile standardize edilmiş feature pipeline.
"""

from .bist_features import (
    BIST_FEATURE_DEFINITIONS,
    BISTFeatureDef,
    get_all_feature_names,
    get_feature_count,
    get_feature_names_by_category,
    get_high_importance_features,
    print_feature_summary,
)
from .cache_manager import FeatureCacheManager, feature_cache_manager
from .calculator import FeatureCalculator, feature_calculator
from .contract import FeatureContract, FeatureRegistry, feature_registry
from .cross_sectional import CrossSectionalEngine, cross_sectional_engine
from .doc_generator import FeatureDocGenerator, feature_doc_generator
from .feature_store_feast import BISTFeatureStore, FeatureSpec, FeatureView
from .feature_tests import FeatureTestSuite, feature_test_suite
from .incremental_state import IncrementalStateManager, incremental_state
from .lineage import FeatureLineageTracker, feature_lineage
from .macro import MacroFeatureEngine, macro_feature_engine
from .pipeline import FeaturePipeline, PipelineConfig, feature_pipeline
from .quality_monitor import FeatureQualityMonitor, feature_quality_monitor
from .selection import FeatureSelector, feature_selector
from .store import FeatureStore, feature_store
from .versioning import FeatureVersionManager, feature_version_manager

__all__ = [
    # Calculator
    "FeatureCalculator",
    "feature_calculator",
    # Contract
    "FeatureContract",
    "FeatureRegistry",
    "feature_registry",
    # Store
    "FeatureStore",
    "feature_store",
    # Pipeline
    "FeaturePipeline",
    "PipelineConfig",
    "feature_pipeline",
    # BIST Features
    "BIST_FEATURE_DEFINITIONS",
    "BISTFeatureDef",
    "get_feature_names_by_category",
    "get_high_importance_features",
    "get_all_feature_names",
    "get_feature_count",
    "print_feature_summary",
    # Cache Manager
    "FeatureCacheManager",
    "feature_cache_manager",
    # Cross-Sectional
    "CrossSectionalEngine",
    "cross_sectional_engine",
    # Doc Generator
    "FeatureDocGenerator",
    "feature_doc_generator",
    # Feature Store Feast
    "BISTFeatureStore",
    "FeatureSpec",
    "FeatureView",
    # Feature Tests
    "FeatureTestSuite",
    "feature_test_suite",
    # Incremental State
    "IncrementalStateManager",
    "incremental_state",
    # Lineage
    "FeatureLineageTracker",
    "feature_lineage",
    # Macro
    "MacroFeatureEngine",
    "macro_feature_engine",
    # Quality Monitor
    "FeatureQualityMonitor",
    "feature_quality_monitor",
    # Selection
    "FeatureSelector",
    "feature_selector",
    # Versioning
    "FeatureVersionManager",
    "feature_version_manager",
]
