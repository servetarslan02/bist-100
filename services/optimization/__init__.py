"""
ALPHA BIST — Optimizasyon ve Sağlamlık Test Modülü (Optimization & Robustness Suite)
=====================================================================================
Bu paket, BIST 100 verisi üzerinde çok çekirdekli Bayesian hiperparametre optimizasyonu,
asimetrik boğa/ayı rejim optimizasyonu ve parametre platosu sağlamlık testlerini sağlar.
"""
from __future__ import annotations

from .asymmetric_optimizer import (
    AsymmetricBayesianOptimizer,
)
from .asymmetric_optimizer import (
    OptimizationTrialResult as AsymmetricTrialResult,
)
from .asymmetric_optimizer import (
    StrategyParameters as AsymmetricStrategyParameters,
)
from .bayesian_optimizer import (
    BayesianMetricOptimizer,
    OptimizationTrialResult,
    StrategyParameters,
)
from .robustness_tester import RobustnessReport, RobustnessTester

__all__ = [
    "AsymmetricBayesianOptimizer",
    "AsymmetricStrategyParameters",
    "AsymmetricTrialResult",
    "BayesianMetricOptimizer",
    "OptimizationTrialResult",
    "RobustnessReport",
    "RobustnessTester",
    "StrategyParameters",
]
