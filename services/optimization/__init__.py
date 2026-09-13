"""
ALPHA BIST — Optimizasyon ve Sağlamlık Test Modülü (Optimization & Robustness Suite)
=====================================================================================
Bu paket, BIST 100 verisi üzerinde çok çekirdekli Bayesian hiperparametre optimizasyonu,
asimetrik boğa/ayı rejim optimizasyonu, genetik algoritma, grid/random search,
walk-forward optimizasyon ve parametre platosu sağlamlık testlerini sağlar.
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
from .genetic_optimizer import (
    GeneticIndividual,
    GeneticOptimizationResult,
    GeneticOptimizer,
    GeneticParamSpace,
    genetic_optimizer,
)
from .grid_search import (
    GridSearchOptimizer,
    GridSearchResult,
    WalkForwardGridResult,
    grid_search_optimizer,
)
from .meta_optimizer import (
    MetaOptimizationReport,
    MetaOptimizer,
    TrialResult,
    meta_optimizer,
)
from .robustness_tester import RobustnessReport, RobustnessTester
from .walk_forward_optimizer import (
    ParameterStabilityReport,
    WalkForwardOptimizationResult,
    WalkForwardOptimizer,
    WFOFoldResult,
    walk_forward_optimizer,
)

__all__ = [
    # bayesian
    "AsymmetricBayesianOptimizer",
    "AsymmetricStrategyParameters",
    "AsymmetricTrialResult",
    "BayesianMetricOptimizer",
    "OptimizationTrialResult",
    "StrategyParameters",
    # genetic
    "GeneticIndividual",
    "GeneticOptimizationResult",
    "GeneticOptimizer",
    "GeneticParamSpace",
    "genetic_optimizer",
    # grid/random search
    "GridSearchOptimizer",
    "GridSearchResult",
    "WalkForwardGridResult",
    "grid_search_optimizer",
    # walk forward
    "ParameterStabilityReport",
    "WFOFoldResult",
    "WalkForwardOptimizationResult",
    "WalkForwardOptimizer",
    "walk_forward_optimizer",
    # robustness
    "RobustnessReport",
    "RobustnessTester",
    # meta optimizer
    "MetaOptimizationReport",
    "MetaOptimizer",
    "TrialResult",
    "meta_optimizer",
]
