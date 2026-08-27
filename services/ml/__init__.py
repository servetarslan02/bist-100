"""ALPHA BIST — ML Package (Nihai).

LightGBM, XGBoost, CatBoost, Stacking Ensemble, Model Registry,
Champion-Challenger, Hyperparameter Tuning, Calibration, Feature Drift, Monitoring.
"""

import structlog

logger = structlog.get_logger(__name__)

# Core models
try:
    from .catboost_model import CatBoostConfig, CatBoostModel
except ImportError:
    logger.debug("Optional import not available in module_level", exc_info=True)

from .adjusted_loss import AdjustedMSELoss
from .calibration import CalibrationResult, ModelCalibration
from .champion_challenger import ABTestResult, ChampionChallenger
from .ensemble import EnsembleModel

# Monitoring
from .feature_drift import DriftReport, FeatureDriftDetector

# Special
from .fingpt import AggregatedSentiment, FinGPTSentiment, SentimentResult
from .finrl_bist import BISTEnvConfig, BISTTradingEnv
from .hybrid_model import HybridModel, HybridSignal, hybrid_predict

# Tuning & Calibration
from .hyperparameter_tuner import HyperparameterTuner, TuningResult
from .lightgbm_trainer import LightGBMTrainer, MLModelConfig

# Deep Learning
from .lstm_model import StockLSTM

# Backtest Integration
from .ml_backtest import BacktestResult, ComparisonResult, MLBacktestEngine
from .model_comparator import ModelComparator, ModelResult
from .model_monitor import ModelMonitor, MonitorReport

# Registry & Lifecycle
from .model_registry import ModelEntry, ModelRegistry
from .qlib_integration import QlibBIST, QlibConfig
from .ranker import LearningToRankModel

# Ranking
from .ranking_model import OpportunityScore, RankingModel, RankingResult
from .rl_agent import RLConfig, evaluate_rl_agent, train_rl_agent

# Ensemble
from .stacking_ensemble import StackingConfig, StackingEnsemble

# Validation
from .training_validator import CrossSectionalNormalizer, TrainingDatasetValidator
from .transformer_model import StockTransformer
from .walk_forward import WalkForwardValidation
from .xgboost_model import XGBoostConfig, XGBoostModel

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
    "CrossSectionalNormalizer", "ModelComparator", "ModelResult",
    # Deep Learning
    "StockLSTM", "StockTransformer",
    # Backtest Integration
    "MLBacktestEngine", "BacktestResult", "ComparisonResult",
    # Special
    "FinGPTSentiment", "SentimentResult", "AggregatedSentiment",
    "hybrid_predict", "HybridModel", "HybridSignal",
    "BISTTradingEnv", "BISTEnvConfig",
    "train_rl_agent", "evaluate_rl_agent", "RLConfig",
    "QlibBIST", "QlibConfig",
]
