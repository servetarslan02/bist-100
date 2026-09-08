"""ALPHA BIST — Makine Öğrenimi ve Tahmin Modelleri Paketi (Machine Learning Engine).

Bu paket; Borsa İstanbul (BIST) pay piyasası için point-in-time uyumlu,
sıfır veri sızıntısı (zero data leakage) ilkelerine bağlı ve kurumsal kalitede
makine öğrenimi altyapısı sunar.

Mimari Standartlar:
- Şampiyon Model: LightGBM (Gradient Boosting Champion).
- Meydan Okuyan (Challenger) Modeller: XGBoost ve CatBoost.
- Ensemble Stratejileri: Ağırlıklı Ensemble, Stacking ve Dynamic Champion-Challenger.
- Olasılık Kalibrasyonu: Isotonic & Sigmoid Probability Calibration.
- Doğrulama & Sürüklenme: Purge + Embargo Walk-Forward Validation, Feature Drift (Evidently/KS).
"""

from __future__ import annotations

from typing import Final

import structlog

logger = structlog.get_logger(__name__)

# Core models
try:
    from .catboost_model import CatBoostConfig, CatBoostModel
except ImportError:
    CatBoostConfig = None  # type: ignore[assignment, misc]
    CatBoostModel = None  # type: ignore[assignment, misc]
    logger.debug("CatBoost modelleri opsiyonel içe aktarılamadı", exc_info=True)

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

__all__: Final[list[str]] = [
    # Core models
    "MLModelConfig",
    "LightGBMTrainer",
    "XGBoostModel",
    "XGBoostConfig",
    "CatBoostModel",
    "CatBoostConfig",
    # Ensemble
    "StackingEnsemble",
    "StackingConfig",
    "EnsembleModel",
    # Registry
    "ModelRegistry",
    "ModelEntry",
    "ChampionChallenger",
    "ABTestResult",
    # Tuning
    "HyperparameterTuner",
    "TuningResult",
    "ModelCalibration",
    "CalibrationResult",
    # Monitoring
    "FeatureDriftDetector",
    "DriftReport",
    "ModelMonitor",
    "MonitorReport",
    # Ranking
    "RankingModel",
    "OpportunityScore",
    "RankingResult",
    "LearningToRankModel",
    "AdjustedMSELoss",
    # Validation
    "TrainingDatasetValidator",
    "WalkForwardValidation",
    "CrossSectionalNormalizer",
    "ModelComparator",
    "ModelResult",
    # Deep Learning
    "StockLSTM",
    "StockTransformer",
    # Backtest Integration
    "MLBacktestEngine",
    "BacktestResult",
    "ComparisonResult",
    # Special
    "FinGPTSentiment",
    "SentimentResult",
    "AggregatedSentiment",
    "hybrid_predict",
    "HybridModel",
    "HybridSignal",
    "BISTTradingEnv",
    "BISTEnvConfig",
    "train_rl_agent",
    "evaluate_rl_agent",
    "RLConfig",
    "QlibBIST",
    "QlibConfig",
]
