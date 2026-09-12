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
from .calendar_engine import MacroCalendarEngine, macro_calendar_engine
from .cds import compute_cds_features
from .config.macro_config import MacroConfig, macro_config
from .correlation_tracker import MacroCorrelationTracker, macro_correlation_tracker
from .credit import compute_credit_features
from .current_account import compute_ca_features
from .factor_decomposition import MacroFactorDecomposition, macro_factor_decomposition
from .fx import compute_fx_features
from .historical_store import MacroHistoricalStore, macro_historical_store
from .impact_analyzer import MacroImpactAnalyzer, macro_impact_analyzer
from .inflation import compute_inflation_features
from .regime_detector import MacroRegimeDetector, macro_regime_detector
from .sensitivity_engine import (
    CompanySensitivity,
    DynamicSensitivityEngine,
    SensitivityResult,
    macro_sensitivity_engine,
)
from .stress_test import MacroStressTest, macro_stress_test
from .surprise_model import MacroSurpriseModel, macro_surprise_model
from .tcmb import compute_tcmb_features

__all__ = [
    # Config
    "MacroConfig",
    "macro_config",
    # Engines & Models
    "MacroSurpriseModel",
    "macro_surprise_model",
    "MacroRegimeDetector",
    "macro_regime_detector",
    "MacroImpactAnalyzer",
    "macro_impact_analyzer",
    "MacroStressTest",
    "macro_stress_test",
    "MacroCorrelationTracker",
    "macro_correlation_tracker",
    "MacroCalendarEngine",
    "macro_calendar_engine",
    "MacroHistoricalStore",
    "macro_historical_store",
    "MacroFactorDecomposition",
    "macro_factor_decomposition",
    "DynamicSensitivityEngine",
    "SensitivityResult",
    "CompanySensitivity",
    "macro_sensitivity_engine",
    # Feature functions
    "compute_tcmb_features",
    "compute_inflation_features",
    "compute_fx_features",
    "compute_cds_features",
    "compute_credit_features",
    "compute_ca_features",
    # Calendar functions
    "get_macro_events",
    "get_upcoming_events",
    "get_event_impact",
]

