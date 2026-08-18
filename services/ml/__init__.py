"""ALPHA BIST — ML Package (Nihai).

LightGBM, XGBoost, CatBoost, Stacking Ensemble, Model Registry,
Champion-Challenger, Hyperparameter Tuning, Calibration, Feature Drift, Monitoring.
"""

# Core models
try:
    from .catboost_model import CatBoostModel, CatBoostConfig
except ImportError:
    pass
from .lightgbm_trainer import MLModelConfig, LightGBMTrainer
from .xgboost_model import XGBoostModel, XGBoostConfig

# Ensemble
from .stacking_ensemble import StackingEnsemble, StackingConfig
from .ensemble import EnsembleModel

# Registry & Lifecycle
from .model_registry import ModelRegistry, ModelEntry
from .champion_challenger import ChampionChallenger, ABTestResult

# Tuning & Calibration
from .hyperparameter_tuner import HyperparameterTuner, TuningResult
from .calibration import ModelCalibration, CalibrationResult

# Monitoring
from .feature_drift import FeatureDriftDetector, DriftReport
from .model_monitor import ModelMonitor, MonitorReport

# Ranking
from .ranking_model import RankingModel, OpportunityScore, RankingResult
from .ranker import LearningToRankModel
from .adjusted_loss import AdjustedMSELoss

# Validation
from .training_validator import TrainingDatasetValidator, CrossSectionalNormalizer
from .walk_forward import WalkForwardValidation
from .model_comparator import ModelComparator

# Deep Learning
from .lstm_model import StockLSTM
from .transformer_model import StockTransformer

# Special
from .fingpt import FinGPTSentiment
from .hybrid_model import hybrid_predict
from .finrl_bist import BISTTradingEnv
from .rl_agent import train_rl_agent
from .qlib_integration import QlibBIST

__all__ = [
    # Core models
    "MLModelConfig", "LightGBMTrainer",
    "XGBoostModel", "XGBoostConfig",
    "CatBoostModel", "CatBoostConfig",
    # Ensemble
    "StackingEnsemble", "StackingConfig",
    "EnsembleModel",
    # Registry
    "ModelRegistry", "ModelEntry",
    "ChampionChallenger", "ABTestResult",
    # Tuning
    "HyperparameterTuner", "TuningResult",
    "ModelCalibration", "CalibrationResult",
    # Monitoring
    "FeatureDriftDetector", "DriftReport",
    "ModelMonitor", "MonitorReport",
    # Ranking
    "RankingModel", "OpportunityScore", "RankingResult",
    "LearningToRankModel",
    "AdjustedMSELoss",
    # Validation
    "TrainingDatasetValidator", "WalkForwardValidation",
    "CrossSectionalNormalizer", "ModelComparator",
    # Deep Learning
    "StockLSTM", "StockTransformer",
    # Special
    "FinGPTSentiment", "hybrid_predict",
    "BISTTradingEnv", "train_rl_agent", "QlibBIST",
]
