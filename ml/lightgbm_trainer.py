# Re-export from services.ml.lightgbm_trainer
# This module exists for backward compatibility with imports like:
#   from ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig

from services.ml.lightgbm_trainer import (
    DEFAULT_TARGETS,
    LightGBMTrainer,
    MLModelConfig,
    MultiHorizonModel,
    TargetSpec,
    TrainedModel,
    compute_comprehensive_metrics,
    compute_model_confidence,
    compute_target,
    validate_feature_contract,
)

__all__ = [
    "DEFAULT_TARGETS",
    "LightGBMTrainer",
    "MLModelConfig",
    "MultiHorizonModel",
    "TargetSpec",
    "TrainedModel",
    "compute_comprehensive_metrics",
    "compute_model_confidence",
    "compute_target",
    "validate_feature_contract",
]
