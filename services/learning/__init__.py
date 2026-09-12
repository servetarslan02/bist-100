"""
ALPHA BIST — Learning System

Modüller:
- calibration: Confidence kalibrasyon (Brier, ECE, Platt scaling)
- drift_detector: Çoklu drift tespit (PSI, KS, ADWIN, Page-Hinkley)
- retrain_engine: Walk-forward validated retrain
- feature_tracker: SHAP-based feature importance tracking
- shadow_manager: Shadow mode yönetimi
- champion_challenger: Champion-challenger otomasyonu
- model_registry: Model versiyon kayıt defteri
- meta_learner: Rejim-specific model selection
- health_monitor: Sistem sağlık izleme
- continuous_learning: Günlük pipeline
- super_intelligence: Self-healing, auto-retrain
- integrated_learning: Prediction/outcome tracking
- attribution: İşlem atfedilmesi
- outcome_tracker: Otomatik outcome takibi
- learning_loop: Otonom öğrenme döngüsü
"""

from .attribution import AttributionEngine, attribution_engine
from .calibration import ConfidenceCalibrator, confidence_calibrator
from .champion_challenger import ChampionChallengerEngine, champion_challenger
from .config.learning_config import LearningSettings, learning_settings
from .continuous_learning import ContinuousLearningPipeline, continuous_learning
from .drift_detector import AdvancedDriftDetector, advanced_drift_detector
from .feature_tracker import FeatureImportanceTracker, feature_importance_tracker
from .health_monitor import LearningHealthMonitor, learning_health_monitor
from .integrated_learning import IntegratedLearningSystem, learning_system
from .learning_loop import LearningLoop, learning_loop
from .meta_learner import MetaLearner, meta_learner
from .model_degradation_monitor import ModelDegradationMonitor, model_degradation_monitor
from .model_memory_store import ModelMemoryStore, model_memory_store
from .model_registry import ModelRegistry, model_registry
from .model_trust_engine import ModelTrustEngine, model_trust_engine
from .outcome_tracker import OutcomeTracker, outcome_tracker
from .production_alpha_engine import ProductionAlphaEngine, production_alpha_engine
from .retrain_engine import RetrainEngine, retrain_engine
from .shadow_manager import ShadowModeManager, shadow_manager
from .super_intelligence import SuperIntelligenceEngine, super_intelligence
from .walkforward_ensemble import WalkForwardEnsemble, walkforward_ensemble
from .weight_adjuster import WeightAdjuster, weight_adjuster

__all__ = [
    # Config
    "LearningSettings",
    "learning_settings",
    # New modules
    "ConfidenceCalibrator",
    "confidence_calibrator",
    "AdvancedDriftDetector",
    "advanced_drift_detector",
    "RetrainEngine",
    "retrain_engine",
    "FeatureImportanceTracker",
    "feature_importance_tracker",
    "ShadowModeManager",
    "shadow_manager",
    "ChampionChallengerEngine",
    "champion_challenger",
    "ModelRegistry",
    "model_registry",
    "MetaLearner",
    "meta_learner",
    "LearningHealthMonitor",
    "learning_health_monitor",
    "ModelDegradationMonitor",
    "model_degradation_monitor",
    "ModelMemoryStore",
    "model_memory_store",
    "ModelTrustEngine",
    "model_trust_engine",
    "ProductionAlphaEngine",
    "production_alpha_engine",
    "WalkForwardEnsemble",
    "walkforward_ensemble",
    "WeightAdjuster",
    "weight_adjuster",
    # Existing modules
    "ContinuousLearningPipeline",
    "continuous_learning",
    "SuperIntelligenceEngine",
    "super_intelligence",
    "IntegratedLearningSystem",
    "learning_system",
    "AttributionEngine",
    "attribution_engine",
    "OutcomeTracker",
    "outcome_tracker",
    "LearningLoop",
    "learning_loop",
]
