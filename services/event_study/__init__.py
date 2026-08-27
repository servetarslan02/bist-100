"""ALPHA BIST — Event Study Package (Nihai Sistem).

MacKinlay (1997) metodolojisi ile BIST hisseleri için event study.
16 modül, Fama-French multi-factor + trading calendar destekli.

Modüller:
    - trading_calendar: BIST iş günleri takvimi (hafta sonu + tatil)
    - estimation_window: Look-ahead bias önleme (trading day bazlı)
    - event_window: Gün bazlı pencereleme (trading day bazlı)
    - expected_return: Multi-factor expected return (Market, FF3, FF5)
    - abnormal_return: AR hesaplama
    - car: Cumulative Abnormal Return
    - statistical_test: t-distribution, Bonferroni, BH, Wilcoxon
    - impact: Event-specific etki skoru
    - kap_event: KAP açıklaması event study
    - macro_event: TCMB, enflasyon, GSYH event study
    - multi_factor: Fama-French factor hesaplama (skor bazlı)
    - fama_french_factors: Fama-French time-series factor builder (SMB/HML/RMW/CMA)
    - cross_sectional: Birden fazla hisse için analysis
    - event_clustering: Event clustering tespiti
    - event_decay: Etki azalma analizi
    - sector_event: Sektör bazlı event study
"""

from .abnormal_return import calculate_abnormal_return, calculate_abnormal_return_batch
from .car import (
    calculate_aar,
    calculate_caar,
    calculate_car,
    calculate_car_series,
    calculate_car_sub_windows,
    calculate_car_window,
)
from .cross_sectional import CrossSectionalEventStudy
from .estimation_window import ESTIMATION_WINDOWS, EstimationWindowManager
from .event_clustering import EventClusteringDetector
from .event_decay import EventImpactDecay
from .event_window import EVENT_WINDOWS, EventWindowManager
from .expected_return import (
    calculate_expected_return,
    calculate_expected_return_simple,
    calculate_expected_return_value,
)
from .fama_french_factors import (
    FactorReturns,
    FamaFrenchDataFetcher,
    FamaFrenchFactorBuilder,
    StockData,
    build_factor_arrays_from_series,
)
from .impact import calculate_event_impact, calculate_impact_batch
from .kap_event import analyze_kap_event, analyze_kap_event_simple, analyze_kap_events_batch, classify_kap_event
from .macro_event import (
    MACRO_EVENT_TYPES,
    analyze_macro_event,
    analyze_macro_events_batch,
    analyze_tcmb_event,
)
from .multi_factor import FamaFrenchFactors, MultiFactorModel
from .sector_event import SECTOR_STOCKS, SectorEventAnalyzer
from .statistical_test import (
    benjamini_hochberg_correction,
    bonferroni_correction,
    test_significance,
    test_significance_cross_sectional,
    wilcoxon_test,
)
from .trading_calendar import BISTTradingCalendar, get_trading_calendar

__all__ = [
    # Trading Calendar
    "BISTTradingCalendar",
    "get_trading_calendar",
    # Managers
    "EstimationWindowManager",
    "EventWindowManager",
    "MultiFactorModel",
    "FamaFrenchFactors",
    "FamaFrenchFactorBuilder",
    "FamaFrenchDataFetcher",
    "CrossSectionalEventStudy",
    "EventClusteringDetector",
    "EventImpactDecay",
    "SectorEventAnalyzer",
    # Data classes
    "StockData",
    "FactorReturns",
    # Core functions
    "calculate_expected_return",
    "calculate_expected_return_value",
    "calculate_expected_return_simple",
    "calculate_abnormal_return",
    "calculate_abnormal_return_batch",
    "calculate_car",
    "calculate_car_window",
    "calculate_car_sub_windows",
    "calculate_car_series",
    "calculate_aar",
    "calculate_caar",
    "test_significance",
    "test_significance_cross_sectional",
    "bonferroni_correction",
    "benjamini_hochberg_correction",
    "wilcoxon_test",
    "calculate_event_impact",
    "calculate_impact_batch",
    "classify_kap_event",
    "analyze_kap_event",
    "analyze_kap_event_simple",
    "analyze_kap_events_batch",
    "analyze_tcmb_event",
    "analyze_macro_event",
    "analyze_macro_events_batch",
    "build_factor_arrays_from_series",
    # Constants
    "ESTIMATION_WINDOWS",
    "EVENT_WINDOWS",
    "MACRO_EVENT_TYPES",
    "SECTOR_STOCKS",
]
