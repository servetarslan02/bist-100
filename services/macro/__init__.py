"""
ALPHA BIST — Macro System

Modüller:
- config: Merkezi konfigürasyon
- surprise_model: Macro surprise hesaplama
- regime_detector: Macro regime detection (6 rejim)
- impact_analyzer: Şok etki analizi + decay modeli
- stress_test: Portfolio bazlı stres testi
- correlation_tracker: Macro değişken korelasyon takibi
- calendar_engine: Takvim entegrasyonu + otomatik tetikleme
- historical_store: Tarihsel veri deposu (PIT)
- factor_decomposition: Faktör ayrıştırması
- sensitivity_engine: Dinamik sektör hassasiyeti

Mevcut modüller:
- tcmb: TCMB faiz features
- inflation: Enflasyon features
- fx: Döviz kuru features
- cds: CDS spread features
- credit: Kredi büyüme features
- current_account: Cari açık features
- calendar: Takvim olayları
"""

from .calendar import get_event_impact, get_macro_events, get_upcoming_events
from .calendar_engine import MacroCalendarEngine, MacroEvent, macro_calendar_engine
from .cds import CDSMetricsResult, CDSRiskLevel, SovereignCDSEngine, compute_cds_features
from .config.macro_config import MacroConfig, macro_config
from .correlation_tracker import (
    CorrelationBreakdown,
    CorrelationResult,
    MacroCorrelationTracker,
    macro_correlation_tracker,
)
from .credit import CreditCycleEngine, CreditMetricsResult, CreditRegimeType, compute_credit_features
from .current_account import CARegimeType, CurrentAccountEngine, CurrentAccountMetricsResult, compute_ca_features
from .factor_decomposition import (
    DecompositionResult,
    FactorContribution,
    MacroFactorDecomposition,
    macro_factor_decomposition,
)
from .fx import compute_fx_features
from .historical_store import MacroDataPoint, MacroHistoricalStore, macro_historical_store
from .impact_analyzer import ImpactResult, MacroImpactAnalyzer, ShockEvent, macro_impact_analyzer
from .inflation import compute_inflation_features, compute_subindex_pressure_score
from .regime_detector import MacroRegimeDetector, RegimeResult, RegimeTransition, macro_regime_detector
from .sensitivity_engine import (
    CompanySensitivity,
    DynamicSensitivityEngine,
    SensitivityResult,
    macro_sensitivity_engine,
)
from .stress_test import (
    BreakingPointResult,
    MacroStressTest,
    PositionImpact,
    StressTestResult,
    macro_stress_test,
)
from .surprise_model import MacroSurpriseModel, SurpriseImpact, SurpriseResult, macro_surprise_model
from .tcmb import compute_tcmb_features

__all__ = [
    # Config
    "MacroConfig",
    "macro_config",
    # Engines & Models
    "MacroSurpriseModel",
    "macro_surprise_model",
    "SurpriseResult",
    "SurpriseImpact",
    "MacroRegimeDetector",
    "macro_regime_detector",
    "RegimeResult",
    "RegimeTransition",
    "MacroImpactAnalyzer",
    "macro_impact_analyzer",
    "ShockEvent",
    "ImpactResult",
    "MacroStressTest",
    "macro_stress_test",
    "PositionImpact",
    "StressTestResult",
    "BreakingPointResult",
    "MacroCorrelationTracker",
    "macro_correlation_tracker",
    "CorrelationResult",
    "CorrelationBreakdown",
    "MacroCalendarEngine",
    "macro_calendar_engine",
    "MacroEvent",
    "MacroHistoricalStore",
    "macro_historical_store",
    "MacroDataPoint",
    "MacroFactorDecomposition",
    "macro_factor_decomposition",
    "FactorContribution",
    "DecompositionResult",
    "DynamicSensitivityEngine",
    "SensitivityResult",
    "CompanySensitivity",
    "macro_sensitivity_engine",
    "SovereignCDSEngine",
    "CDSMetricsResult",
    "CDSRiskLevel",
    "CreditCycleEngine",
    "CreditMetricsResult",
    "CreditRegimeType",
    "CurrentAccountEngine",
    "CurrentAccountMetricsResult",
    "CARegimeType",
    # Feature functions
    "compute_tcmb_features",
    "compute_inflation_features",
    "compute_subindex_pressure_score",
    "compute_fx_features",
    "compute_cds_features",
    "compute_credit_features",
    "compute_ca_features",
    # Calendar functions
    "get_macro_events",
    "get_upcoming_events",
    "get_event_impact",
]

