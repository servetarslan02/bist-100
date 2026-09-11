"""ALPHA BIST — Feature Engine Package v3.0.

BIST-100 piyasası için kurumsal seviye feature hesaplama,
depolama ve yönetim paketi.

Paket yapısı:
    - contract: Feature metadata, validasyon ve kayıt sistemi
    - store: Redis tabanlı canlı feature deposu
    - feature_store_feast: Feast-uyumlu PIT-safe tarihsel store
    - pipeline: End-to-end feature pipeline
    - calculator: Polars-native feature hesaplama bridge'i
    - selection: Feature selection motoru
    - versioning: Feature version yönetimi
    - lineage: Feature lineage tracking
    - quality_monitor: Feature kalite izleme
    - cache_manager: RAM & matris önbellek yöneticisi
    - cross_sectional: Cross-sectional feature hesaplama
    - macro: Makro-ekonomik feature hesaplama
    - incremental_state: Artan rolling state yönetimi
    - seven_motors: Yedi motor — momentum, volatilite, hacim,
                    mevsimsellik, ortalama geri dönüş, mikro yapı
                    ve düşüş analizi motorları
    - bist_features: BIST-100'e özgü feature tanımları
    - doc_generator: Feature dokümantasyon üretici
    - feature_tests: Feature test suite

Not: FeatureStore (store.py) Redis tabanlı CANLI erişim için,
     BISTFeatureStore (feature_store_feast.py) ise PIT-safe
     TARİHSEL sorgular için kullanılır.

Kullanım:
    from services.features import (
        feature_registry, feature_pipeline, feature_store
    )
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
from .feature_store_feast import BISTFeatureStore
from .feature_tests import FeatureTestSuite, feature_test_suite
from .incremental_state import IncrementalStateManager, incremental_state
from .lineage import FeatureLineageTracker, feature_lineage
from .macro import MacroFeatureEngine, macro_feature_engine
from .pipeline import FeaturePipeline, PipelineConfig, feature_pipeline
from .quality_monitor import FeatureQualityMonitor, feature_quality_monitor
from .selection import FeatureSelector, feature_selector
from .seven_motors import (
    MeanReversionMotor,
    MicrostructureMotor,
    MomentumMotor,
    RelativeStrengthMotor,
    SeasonalityMotor,
    VolatilityMotor,
    VolumeMotor,
    WhyFallingMotor,
)
from .store import FeatureStore, feature_store
from .versioning import FeatureVersionManager, feature_version_manager

__all__ = [
    "BISTFeatureDef",
    "BISTFeatureStore",
    "BIST_FEATURE_DEFINITIONS",
    "CrossSectionalEngine",
    "FeatureCacheManager",
    "FeatureCalculator",
    "FeatureContract",
    "FeatureDocGenerator",
    "FeatureLineageTracker",
    "FeaturePipeline",
    "FeatureQualityMonitor",
    "FeatureRegistry",
    "FeatureSelector",
    "FeatureStore",
    "FeatureTestSuite",
    "FeatureVersionManager",
    "IncrementalStateManager",
    "MacroFeatureEngine",
    "MeanReversionMotor",
    "MicrostructureMotor",
    "MomentumMotor",
    "PipelineConfig",
    "RelativeStrengthMotor",
    "SeasonalityMotor",
    "VolatilityMotor",
    "VolumeMotor",
    "WhyFallingMotor",
    "cross_sectional_engine",
    "feature_cache_manager",
    "feature_calculator",
    "feature_doc_generator",
    "feature_lineage",
    "feature_pipeline",
    "feature_quality_monitor",
    "feature_registry",
    "feature_selector",
    "feature_store",
    "feature_test_suite",
    "feature_version_manager",
    "get_all_feature_names",
    "get_feature_count",
    "get_feature_names_by_category",
    "get_high_importance_features",
    "incremental_state",
    "macro_feature_engine",
    "print_feature_summary",
]
