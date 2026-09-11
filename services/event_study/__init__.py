"""ALPHA BIST — Olay İnceleme Paketi (Nihai Sistem).

MacKinlay (1997) metodolojisi ile BIST hisseleri için olay incelemesi (event study).
16 modül, Fama-French çok faktörlü model + işlem takvimi destekli.

Modüller:
    - trading_calendar: BIST iş günleri takvimi (hafta sonu + resmi tatiller)
    - estimation_window: İleriye bakış önyargısını önleme (işlem günü bazlı)
    - event_window: Gün bazlı pencereleme (işlem günü bazlı)
    - expected_return: Çok faktörlü beklenen getiri (Piyasa, FF3, FF5)
    - abnormal_return: Anormal getiri (AR) hesaplama
    - car: Kümülatif Anormal Getiri (CAR)
    - statistical_test: t-dağılımı, Bonferroni, Benjamini-Hochberg, Wilcoxon
    - impact: Olaya özel etki skoru
    - kap_event: KAP açıklaması olay incelemesi
    - macro_event: TCMB, enflasyon, GSYH olay incelemesi
    - multi_factor: Fama-French faktör hesaplama (skor bazlı)
    - fama_french_factors: Fama-French zaman serisi faktör oluşturucu (SMB/HML/RMW/CMA)
    - cross_sectional: Birden fazla hisse için çapraz kesit analizi
    - event_clustering: Olay kümeleme tespiti
    - event_decay: Etki azalma analizi
    - sector_event: Sektör bazlı olay incelemesi
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
    "BISTTradingCalendar",
    "CrossSectionalEventStudy",
    "ESTIMATION_WINDOWS",
    "EVENT_WINDOWS",
    "EstimationWindowManager",
    "EventClusteringDetector",
    "EventImpactDecay",
    "EventWindowManager",
    "FactorReturns",
    "FamaFrenchDataFetcher",
    "FamaFrenchFactorBuilder",
    "FamaFrenchFactors",
    "MACRO_EVENT_TYPES",
    "MultiFactorModel",
    "SECTOR_STOCKS",
    "SectorEventAnalyzer",
    "StockData",
    "analyze_kap_event",
    "analyze_kap_event_simple",
    "analyze_kap_events_batch",
    "analyze_macro_event",
    "analyze_macro_events_batch",
    "analyze_tcmb_event",
    "benjamini_hochberg_correction",
    "bonferroni_correction",
    "build_factor_arrays_from_series",
    "calculate_aar",
    "calculate_abnormal_return",
    "calculate_abnormal_return_batch",
    "calculate_caar",
    "calculate_car",
    "calculate_car_series",
    "calculate_car_sub_windows",
    "calculate_car_window",
    "calculate_event_impact",
    "calculate_expected_return",
    "calculate_expected_return_simple",
    "calculate_expected_return_value",
    "calculate_impact_batch",
    "classify_kap_event",
    "get_trading_calendar",
    "test_significance",
    "test_significance_cross_sectional",
    "wilcoxon_test",
]
