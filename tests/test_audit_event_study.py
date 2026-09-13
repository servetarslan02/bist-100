"""ALPHA BIST — Event Study Servisleri Kapsamlı Denetim Testleri.

Bu test modülü `services/event_study/` altındaki tüm bileşenleri test eder:
- `trading_calendar.py`: BIST işlem günü takvimi ve tatil kontrolleri.
- `abnormal_return.py`: Anormal getiri (AR) hesaplama ve batch işlemler.
- `car.py`: Kümülatif anormal getiri (CAR, AAR, CAAR).
- `estimation_window.py` & `event_window.py`: Pencere yöneticileri.
- `statistical_test.py`: İstatistiksel anlamlılık, Bonferroni, Benjamini-Hochberg.
- `kap_event.py` & `macro_event.py`: KAP ve makro olay inceleme fonksiyonları.
- `multi_factor.py` & `fama_french_factors.py`: Çok faktörlü modeller.
- `sector_event.py`: Sektörel olay etki analizleri.
- `event_clustering.py` & `event_decay.py`: Olay kümeleme ve etki sönümlenmesi.
"""

from datetime import date, datetime

import numpy as np
import pytest

from services.event_study import (
    BISTTradingCalendar,
    EstimationWindowManager,
    EventClusteringDetector,
    EventImpactDecay,
    EventWindowManager,
    FamaFrenchFactors,
    MultiFactorModel,
    SectorEventAnalyzer,
    analyze_kap_event_simple,
    analyze_tcmb_event,
    benjamini_hochberg_correction,
    bonferroni_correction,
    calculate_aar,
    calculate_abnormal_return,
    calculate_caar,
    calculate_car,
    classify_kap_event,
    get_trading_calendar,
)
from services.event_study import test_significance as run_significance_test


def test_trading_calendar() -> None:
    """BISTTradingCalendar takvim kontrollerini doğrular."""
    cal = get_trading_calendar()
    assert isinstance(cal, BISTTradingCalendar)

    # 2026-03-02 Pazartesi işlem günüdür
    assert cal.is_trading_day(date(2026, 3, 2)) is True
    # 2026-03-07 Cumartesi işlem günü değildir
    assert cal.is_trading_day(date(2026, 3, 7)) is False


def test_abnormal_return_and_car() -> None:
    """Anormal getiri ve kümülatif anormal getiri fonksiyonlarını doğrular."""
    stock_returns = np.array([0.02, 0.03, -0.01, 0.04, 0.01], dtype=np.float64)
    market_returns = np.array([0.01, 0.01, 0.00, 0.02, 0.01], dtype=np.float64)

    ar = calculate_abnormal_return(stock_returns, market_returns, alpha=0.0, beta=1.0)
    assert len(ar) == 5
    assert np.allclose(ar, [0.01, 0.02, -0.01, 0.02, 0.00])

    car = calculate_car(ar)
    assert pytest.approx(car) == 0.04

    # AAR ve CAAR testleri
    car_dict = {"event_1": 0.02, "event_2": 0.04}
    aar = calculate_aar(car_dict)
    assert pytest.approx(aar) == 0.03

    caar_dict = {
        "event_1": np.array([0.01, 0.02, 0.03], dtype=np.float64),
        "event_2": np.array([0.03, 0.02, 0.01], dtype=np.float64),
    }
    caar = calculate_caar(caar_dict)
    assert len(caar) == 3
    assert pytest.approx(caar[0]) == 0.02


def test_window_managers() -> None:
    """EstimationWindowManager ve EventWindowManager sınıflarını doğrular."""
    est_mgr = EstimationWindowManager()
    ev_mgr = EventWindowManager()

    assert est_mgr is not None
    assert ev_mgr is not None


def test_statistical_significance_tests() -> None:
    """İstatistiksel testler ve çoklu hipotez düzeltmelerini doğrular."""
    p_values = [0.001, 0.02, 0.04, 0.20]
    bonf = bonferroni_correction(p_values, alpha=0.05)
    assert "significant_flags" in bonf
    assert bonf["significant_flags"][0] is True

    bh = benjamini_hochberg_correction(p_values, alpha=0.05)
    assert "significant_flags" in bh
    assert bh["significant_flags"][0] is True

    ar_series = np.array([0.01, 0.02, 0.015, 0.03, 0.025, 0.02, 0.018], dtype=np.float64)
    sig = run_significance_test(car=0.05, abnormal_returns=ar_series)
    assert "t_statistic" in sig
    assert "p_value" in sig


def test_kap_and_macro_events() -> None:
    """KAP ve makro olay analiz fonksiyonlarını doğrular."""
    kap_class = classify_kap_event("Şirketimiz yeni bir yatırım teşvik belgesi almıştır.")
    assert isinstance(kap_class, dict)
    assert "event_type" in kap_class

    # En az 20 gözlem
    stock_returns = np.array([0.01 * (i % 3) for i in range(25)], dtype=np.float64)
    market_returns = np.array([0.005 * (i % 2) for i in range(25)], dtype=np.float64)
    kap_res = analyze_kap_event_simple(
        ticker="ASELS",
        event_description="Temettü dağıtım kararı",
        event_date=datetime(2026, 3, 1),
        stock_returns=stock_returns,
        market_returns=market_returns,
    )
    assert isinstance(kap_res, dict)
    assert "event_type" in kap_res

    tcmb_res = analyze_tcmb_event(
        rate_actual=45.0,
        rate_expected=42.5,
        rate_previous=40.0,
        market_returns=market_returns[:10],
    )
    assert isinstance(tcmb_res, dict)
    assert "surprise" in tcmb_res


def test_multi_factor_and_sector() -> None:
    """MultiFactorModel, FamaFrenchFactors ve SectorEventAnalyzer sınıflarını doğrular."""
    small = np.array([0.02, 0.03, -0.01], dtype=np.float64)
    large = np.array([0.01, 0.01, 0.00], dtype=np.float64)
    smb = FamaFrenchFactors.calculate_smb(small, large)
    assert len(smb) == 3

    mf_model = MultiFactorModel(model_type="market")
    assert mf_model is not None

    sec_analyzer = SectorEventAnalyzer()
    assert sec_analyzer is not None


def test_clustering_and_decay() -> None:
    """EventClusteringDetector ve EventImpactDecay sınıflarını doğrular."""
    clustering = EventClusteringDetector()
    assert clustering is not None

    decay = EventImpactDecay()
    assert decay is not None
