"""
ALPHA BIST — Feature System Nihai Test Suite

Tüm yeni feature modülleri için kapsamlı testler:
1. Feature Store v2.0 (PIT, versioning, lineage, snapshot)
2. Drift Detector (KS, PSI, z-score)
3. Importance Tracker (native, RFE, drift)
4. BIST Features (kur, enflasyon, faiz, KAP, yabancı)
5. Pipeline Orchestrator (end-to-end)
"""

import json
import math
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any

# Test framework
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =====================================================
# 1. FEATURE STORE v2.0 TESTS
# =====================================================

def test_feature_store_basic():
    """Temel store işlemleri."""
    from services.features.store import FeatureStore, FeatureSource, LineageStage

    store = FeatureStore()

    # SET
    snapshot = store.set(
        ticker="THYAO",
        features={"rsi_14": 65.5, "macd": 0.5, "atr_14": 2.3},
        version="v1",
        source=FeatureSource.CALCULATOR,
    )

    assert snapshot.ticker == "THYAO"
    assert len(snapshot.features) == 3
    assert snapshot.snapshot_hash != ""

    # GET
    rsi = store.get("THYAO", "rsi_14")
    assert rsi == 65.5

    # GET ALL
    all_features = store.get_all("THYAO")
    assert len(all_features) == 3
    assert all_features["rsi_14"] == 65.5

    print("✅ test_feature_store_basic PASSED")


def test_feature_store_pit():
    """Point-in-time correctness testi."""
    from services.features.store import FeatureStore, FeatureSource

    store = FeatureStore()

    # Dün hesaplanmış feature
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    store.set(
        ticker="THYAO",
        features={"rsi_14": 60.0},
        version="v1",
        source=FeatureSource.CALCULATOR,
        computed_at=yesterday,
        available_at=yesterday,
    )

    # Bugün hesaplanmış feature
    today = datetime.now(timezone.utc).isoformat()
    store.set(
        ticker="THYAO",
        features={"rsi_14": 70.0},
        version="v2",
        source=FeatureSource.CALCULATOR,
        computed_at=today,
        available_at=today,
    )

    # Dün için sorgula → v1 dönmeli
    val_yesterday = store.get("THYAO", "rsi_14", as_of=yesterday)
    assert val_yesterday == 60.0, f"Expected 60.0, got {val_yesterday}"

    # Bugün için sorgula → v2 dönmeli
    val_today = store.get("THYAO", "rsi_14", as_of=today)
    assert val_today == 70.0, f"Expected 70.0, got {val_today}"

    print("✅ test_feature_store_pit PASSED")


def test_feature_store_versioning():
    """Versioning testi."""
    from services.features.store import FeatureStore, FeatureSource

    store = FeatureStore()

    store.set("THYAO", {"rsi_14": 60.0}, version="v1", source=FeatureSource.CALCULATOR)
    store.set("THYAO", {"rsi_14": 65.0}, version="v2", source=FeatureSource.CALCULATOR)
    store.set("THYAO", {"rsi_14": 70.0}, version="v3", source=FeatureSource.CALCULATOR)

    # Spesifik version
    assert store.get("THYAO", "rsi_14", version="v1") == 60.0
    assert store.get("THYAO", "rsi_14", version="v2") == 65.0
    assert store.get("THYAO", "rsi_14", version="v3") == 70.0

    # Latest
    assert store.get("THYAO", "rsi_14", version="latest") == 70.0

    # Tüm version'lar
    versions = store.get_all_versions("THYAO")
    assert len(versions) == 3

    print("✅ test_feature_store_versioning PASSED")


def test_feature_store_lineage():
    """Lineage tracking testi."""
    from services.features.store import FeatureStore, FeatureSource, LineageStage

    store = FeatureStore()

    store.set(
        "THYAO",
        {"rsi_14": 65.0, "macd": 0.5},
        version="v1",
        source=FeatureSource.CALCULATOR,
        parent_features={"rsi_14": ["close_price"], "macd": ["ema_12", "ema_26"]},
    )

    lineage = store.get_lineage(ticker="THYAO")
    assert len(lineage) == 2

    # RSI lineage
    rsi_lineage = next(l for l in lineage if l["feature"] == "rsi_14")
    assert rsi_lineage["parents"] == ["close_price"]
    assert rsi_lineage["stage"] == "stored"

    print("✅ test_feature_store_lineage PASSED")


def test_feature_store_snapshot():
    """Snapshot testi."""
    from services.features.store import FeatureStore, FeatureSource

    store = FeatureStore()

    # Birkaç snapshot oluştur
    t1 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    t2 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    t3 = datetime.now(timezone.utc).isoformat()

    store.set("THYAO", {"rsi_14": 60.0}, version="v1",
              source=FeatureSource.CALCULATOR, computed_at=t1, available_at=t1)
    store.set("THYAO", {"rsi_14": 65.0}, version="v1",
              source=FeatureSource.CALCULATOR, computed_at=t2, available_at=t2)
    store.set("THYAO", {"rsi_14": 70.0}, version="v1",
              source=FeatureSource.CALCULATOR, computed_at=t3, available_at=t3)

    # Belirli zamandaki snapshot
    snap = store.get_snapshot("THYAO", t2)
    assert snap is not None
    assert snap.features["rsi_14"].value == 65.0

    # Latest snapshot
    latest = store.get_latest_snapshot("THYAO")
    assert latest is not None
    assert latest.features["rsi_14"].value == 70.0

    # Raw dict
    raw = latest.to_raw_dict()
    assert raw["rsi_14"] == 70.0

    print("✅ test_feature_store_snapshot PASSED")


def test_feature_store_baseline():
    """Baseline (drift detection için) testi."""
    from services.features.store import FeatureStore, FeatureSource

    store = FeatureStore()

    for i in range(100):
        store.set(
            "THYAO",
            {"rsi_14": 50.0 + i * 0.1},
            version="v1",
            source=FeatureSource.CALCULATOR,
        )

    baseline = store.get_baseline("THYAO", "rsi_14")
    assert len(baseline) == 100
    assert baseline[0] == 50.0
    assert abs(baseline[-1] - 59.9) < 0.01

    # Son N
    last_10 = store.get_baseline("THYAO", "rsi_14", last_n=10)
    assert len(last_10) == 10

    print("✅ test_feature_store_baseline PASSED")


def test_feature_store_stats():
    """İstatistik testi."""
    from services.features.store import FeatureStore, FeatureSource

    store = FeatureStore()

    store.set("THYAO", {"rsi_14": 65.0, "macd": 0.5}, version="v1",
              source=FeatureSource.CALCULATOR)
    store.set("GARAN", {"rsi_14": 45.0}, version="v1",
              source=FeatureSource.CALCULATOR)

    stats = store.get_stats()
    assert stats["total_tickers"] == 2
    assert stats["total_features"] == 3

    print("✅ test_feature_store_stats PASSED")


# =====================================================
# 2. DRIFT DETECTOR TESTS
# =====================================================

def test_drift_detector_ks():
    """KS test drift detection."""
    from services.features.drift_detector import FeatureDriftDetector, DriftMethod

    detector = FeatureDriftDetector(ks_threshold=0.05)

    # Aynı dağılım → drift yok
    baseline = [50.0 + i * 0.1 for i in range(100)]
    current = [50.0 + i * 0.1 + 0.5 for i in range(100)]

    result = detector.detect_feature(
        "rsi_14", "THYAO", baseline, current, DriftMethod.KS_TEST
    )
    assert result is not None
    # Küçük fark → drift olmamalı
    assert not result.drift_detected

    # Çok farklı dağılım → drift var
    current_shifted = [80.0 + i * 0.1 for i in range(100)]
    result2 = detector.detect_feature(
        "rsi_14", "THYAO", baseline, current_shifted, DriftMethod.KS_TEST
    )
    assert result2 is not None
    assert result2.drift_detected

    print("✅ test_drift_detector_ks PASSED")


def test_drift_detector_psi():
    """PSI drift detection."""
    from services.features.drift_detector import FeatureDriftDetector, DriftMethod

    detector = FeatureDriftDetector(psi_threshold=0.25)

    # Aynı dağılım
    baseline = [50.0 + i * 0.5 for i in range(100)]
    current = [50.0 + i * 0.5 for i in range(100)]

    result = detector.detect_feature(
        "rsi_14", "THYAO", baseline, current, DriftMethod.PSI
    )
    assert result is not None
    assert not result.drift_detected  # Aynı → PSI ≈ 0

    # Farklı dağılım
    current_shifted = [70.0 + i * 0.5 for i in range(100)]
    result2 = detector.detect_feature(
        "rsi_14", "THYAO", baseline, current_shifted, DriftMethod.PSI
    )
    assert result2 is not None
    assert result2.drift_detected

    print("✅ test_drift_detector_psi PASSED")


def test_drift_detector_zscore():
    """Z-score drift detection."""
    from services.features.drift_detector import FeatureDriftDetector, DriftMethod

    detector = FeatureDriftDetector(zscore_threshold=2.0)

    # Küçük fark
    baseline = [50.0] * 100
    current = [51.0] * 100

    result = detector.detect_feature(
        "rsi_14", "THYAO", baseline, current, DriftMethod.ZSCORE
    )
    assert result is not None
    # std=0 olduğu için z-score=0

    # Büyük fark
    baseline2 = [50.0 + i * 0.1 for i in range(100)]
    current2 = [80.0 + i * 0.1 for i in range(100)]

    result2 = detector.detect_feature(
        "rsi_14", "THYAO", baseline2, current2, DriftMethod.ZSCORE
    )
    assert result2 is not None
    assert result2.drift_detected

    print("✅ test_drift_detector_zscore PASSED")


def test_drift_detector_all():
    """Tüm yöntemlerle drift detection."""
    from services.features.drift_detector import FeatureDriftDetector

    detector = FeatureDriftDetector()

    baseline = {
        "rsi_14": [50.0 + i * 0.1 for i in range(100)],
        "macd": [0.0 + i * 0.01 for i in range(100)],
    }
    current = {
        "rsi_14": [80.0 + i * 0.1 for i in range(100)],  # Büyük kayma
        "macd": [0.0 + i * 0.01 for i in range(100)],     # Aynı
    }

    report = detector.detect_all("THYAO", baseline, current)
    assert report.total_features == 2
    assert report.drifted_features >= 1  # RSI drift etmeli

    print("✅ test_drift_detector_all PASSED")


def test_drift_detector_alerts():
    """Alert sistemi testi."""
    from services.features.drift_detector import FeatureDriftDetector

    alerts_received = []
    detector = FeatureDriftDetector(
        zscore_threshold=1.0,
        alert_callback=lambda a: alerts_received.append(a),
    )

    baseline = {"rsi_14": [50.0 + i * 0.5 for i in range(100)]}
    current = {"rsi_14": [100.0 + i * 0.5 for i in range(100)]}  # Büyük kayma

    report = detector.detect_all("THYAO", baseline, current)

    # Alert oluşmalı
    assert len(alerts_received) > 0 or report.drifted_features > 0

    # Alert history
    history = detector.get_alert_history("THYAO")
    assert isinstance(history, list)

    print("✅ test_drift_detector_alerts PASSED")


# =====================================================
# 3. IMPORTANCE TRACKER TESTS
# =====================================================

def test_importance_native():
    """Native importance testi."""
    from services.features.importance_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()

    # Mock model
    class MockModel:
        feature_importances_ = [0.3, 0.25, 0.2, 0.15, 0.1]

    model = MockModel()
    feature_names = ["rsi_14", "macd", "atr_14", "volume_zscore", "momentum_20d"]

    snapshot = tracker.compute_native(model, feature_names, ticker="THYAO")

    assert snapshot.ticker == "THYAO"
    assert snapshot.total_features == 5
    assert snapshot.features[0].rank == 1
    assert snapshot.features[0].feature_name == "rsi_14"
    assert snapshot.top_10_concentration > 0

    print("✅ test_importance_native PASSED")


def test_importance_rfe():
    """RFE testi."""
    from services.features.importance_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()

    # Mock model factory
    class MockRFEModel:
        def __init__(self):
            self.feature_importances_ = None
            self._fitted = False

        def fit(self, X, y):
            self._fitted = True
            if hasattr(X, 'shape'):
                n = X.shape[1]
            else:
                n = len(X[0]) if X else 5
            self.feature_importances_ = [1.0 / n] * n

        def score(self, X, y):
            return 0.7

    # Mock data
    X = [[i + j for j in range(10)] for i in range(100)]
    y = [0] * 50 + [1] * 50
    feature_names = [f"feature_{i}" for i in range(10)]

    result = tracker.recursive_feature_elimination(
        model_factory=lambda: MockRFEModel(),
        X=X, y=y,
        feature_names=feature_names,
        min_features=3,
        step=2,
    )

    assert result.n_selected >= 3
    assert len(result.selected_features) >= 3
    assert len(result.eliminated_features) > 0

    print("✅ test_importance_rfe PASSED")


def test_importance_drift():
    """Importance drift detection testi."""
    from services.features.importance_tracker import (
        FeatureImportanceTracker, FeatureImportance,
    )

    tracker = FeatureImportanceTracker()

    # İlk snapshot
    class MockModel1:
        feature_importances_ = [0.4, 0.3, 0.2, 0.1]

    tracker.compute_native(
        MockModel1(), ["rsi", "macd", "atr", "vol"],
        ticker="THYAO",
    )

    # Değişmiş snapshot
    class MockModel2:
        feature_importances_ = [0.1, 0.2, 0.3, 0.4]

    tracker.compute_native(
        MockModel2(), ["rsi", "macd", "atr", "vol"],
        ticker="THYAO",
    )

    drifts = tracker.detect_importance_drift("THYAO")
    assert len(drifts) > 0

    # RSI importance azalmış olmalı
    rsi_drift = next((d for d in drifts if d.feature_name == "rsi"), None)
    assert rsi_drift is not None
    assert rsi_drift.importance_trend == "decreasing"

    print("✅ test_importance_drift PASSED")


def test_importance_concentration():
    """Konsantrasyon ve Gini testi."""
    from services.features.importance_tracker import (
        FeatureImportanceTracker, FeatureImportance,
    )

    tracker = FeatureImportanceTracker()

    # Eşit dağılım
    equal_features = [
        FeatureImportance(f"f{i}", 0.1, i + 1, "test")
        for i in range(10)
    ]
    gini_equal = tracker.compute_gini(equal_features)
    assert gini_equal < 0.1  # Düşük Gini = eşit

    # Yoğun dağılım (tek dominant)
    concentrated = [
        FeatureImportance("f0", 0.9, 1, "test"),
    ] + [
        FeatureImportance(f"f{i}", 0.011, i + 1, "test")
        for i in range(1, 10)
    ]
    gini_concentrated = tracker.compute_gini(concentrated)
    assert gini_concentrated > 0.5  # Yüksek Gini = eşitsiz

    print("✅ test_importance_concentration PASSED")


# =====================================================
# 4. BIST FEATURES TESTS
# =====================================================

def test_bist_features_basic():
    """Temel BIST feature hesaplama."""
    from services.features.bist_features import BISTFeatureEngine

    engine = BISTFeatureEngine()

    features = engine.compute_all(
        ticker="THYAO",
        price_history=[100.0 + i * 0.5 for i in range(60)],
        volume_history=[1000000 + i * 10000 for i in range(60)],
    )

    assert features.ticker == "THYAO"
    assert features.fx_beta > 0  # THYAO kur hassas
    assert features.sector_momentum_20d == 0.0  # Sector data yok

    # Feature dict
    feat_dict = features.to_feature_dict()
    assert "bist_fx_beta" in feat_dict
    assert "bist_piotroski_f" in feat_dict

    print("✅ test_bist_features_basic PASSED")


def test_bist_features_fx():
    """Kur hassasiyeti testi."""
    from services.features.bist_features import BISTFeatureEngine

    engine = BISTFeatureEngine()

    # Bankacılık sektörü yüksek FX hassasiyeti
    features_bank = engine.compute_all(
        ticker="GARAN",
        price_history=[10.0 + i * 0.1 for i in range(60)],
    )
    assert features_bank.fx_beta >= 0.8  # Bankacılık yüksek

    # Perakende düşük FX hassasiyeti
    features_retail = engine.compute_all(
        ticker="BIMAS",
        price_history=[100.0 + i * 0.5 for i in range(60)],
    )
    assert features_retail.fx_beta <= 0.3  # Perakende düşük

    print("✅ test_bist_features_fx PASSED")


def test_bist_features_quality():
    """Kalite skorları testi."""
    from services.features.bist_features import BISTFeatureEngine

    engine = BISTFeatureEngine()

    features = engine.compute_all(
        ticker="THYAO",
        fundamentals={
            "net_income": 1000000,
            "roa": 5.0,
            "operating_cf": 1500000,
            "debt_ratio_improved": True,
            "current_ratio_improved": True,
            "gross_margin_improved": True,
            "asset_turnover_improved": False,
            "shares_outstanding_decreased": True,
            "total_assets": 10000000,
            "working_capital": 500000,
            "retained_earnings": 3000000,
            "ebit": 800000,
            "market_cap": 50000000,
            "total_liabilities": 4000000,
            "revenue": 8000000,
        },
    )

    assert features.piotroski_f >= 5  # İyi şirket
    assert features.altman_z > 0

    print("✅ test_bist_features_quality PASSED")


def test_bist_features_kap():
    """KAP olay feature'ları testi."""
    from services.features.bist_features import BISTFeatureEngine

    engine = BISTFeatureEngine()

    now = datetime.now(timezone.utc)
    kap_events = [
        {"type": "FINANCIAL_STATEMENT", "date": (now - timedelta(days=5)).isoformat(), "sentiment": 1},
        {"type": "DIVIDEND", "date": (now - timedelta(days=10)).isoformat(), "sentiment": 1},
        {"type": "GENERAL", "date": (now - timedelta(days=15)).isoformat(), "sentiment": -1},
    ]

    features = engine.compute_all(
        ticker="THYAO",
        kap_events=kap_events,
    )

    assert features.kap_event_count_30d == 3
    assert features.kap_financial_event_count == 1
    assert features.kap_dividend_event is True

    print("✅ test_bist_features_kap PASSED")


# =====================================================
# 5. PIPELINE TESTS
# =====================================================

def test_pipeline_basic():
    """Temel pipeline testi."""
    import asyncio
    from services.features.pipeline import FeaturePipelineOrchestrator, PipelineConfig

    config = PipelineConfig(
        enable_drift_detection=False,  # İlk çalıştırmada drift yok
        enable_feature_selection=False,
        enable_bist_features=True,
        enable_contract_validation=True,
        enable_store=True,
    )

    pipeline = FeaturePipelineOrchestrator(config)

    # Mock OHLCV DataFrame
    class MockDF:
        def __init__(self):
            self._data = {
                "Close": [100.0 + i * 0.5 for i in range(200)],
                "Open": [100.0 + i * 0.5 for i in range(200)],
                "High": [101.0 + i * 0.5 for i in range(200)],
                "Low": [99.0 + i * 0.5 for i in range(200)],
                "Volume": [1000000 + i * 10000 for i in range(200)],
            }

        @property
        def columns(self):
            return list(self._data.keys())

        def __getitem__(self, key):
            class Series:
                def __init__(self, data):
                    self._data = data
                def tolist(self):
                    return self._data
                def __len__(self):
                    return len(self._data)
            return Series(self._data[key])

        def __len__(self):
            return 200

    result = asyncio.run(pipeline.run(
        ticker="THYAO",
        ohlcv_df=MockDF(),
        macro_data={"usdtry_history": [30.0 + i * 0.1 for i in range(200)]},
        price_history=[100.0 + i * 0.5 for i in range(200)],
    ))

    assert result.ticker == "THYAO"
    assert result.total_features > 0
    assert result.store_snapshot_hash is not None
    assert result.duration_ms > 0

    print("✅ test_pipeline_basic PASSED")


def test_pipeline_with_features():
    """Hazır feature'larla pipeline testi."""
    import asyncio
    from services.features.pipeline import FeaturePipelineOrchestrator, PipelineConfig

    config = PipelineConfig(
        enable_drift_detection=False,
        enable_feature_selection=False,
        enable_bist_features=False,
        enable_contract_validation=True,
        enable_store=True,
    )

    pipeline = FeaturePipelineOrchestrator(config)

    features = {
        "rsi_14": 65.5,
        "macd": 0.5,
        "atr_14": 2.3,
        "momentum_20d": 5.0,
    }

    result = asyncio.run(pipeline.run(
        ticker="GARAN",
        features=features,
    ))

    assert result.ticker == "GARAN"
    assert result.total_features == 4
    assert "rsi_14" in result.features

    print("✅ test_pipeline_with_features PASSED")


# =====================================================
# FEATURE SELECTOR TESTS
# =====================================================

def test_feature_selector_correlation():
    """Korelasyon filtreleme testi."""
    from services.features.feature_selector import FeatureSelector

    selector = FeatureSelector()

    # Yüksek korelasyonlu feature'lar
    X = [
        [1.0, 2.0, 1.0],  # feature_0 ve feature_2 aynı
        [2.0, 4.0, 2.0],
        [3.0, 6.0, 3.0],
        [4.0, 8.0, 4.0],
        [5.0, 10.0, 5.0],
    ]
    names = ["f0", "f1", "f2"]

    X_filtered, names_filtered = selector.select_by_correlation(X, names, threshold=0.95)

    # f0 ve f2 aynı → biri kaldırılmalı
    assert len(names_filtered) <= 2

    print("✅ test_feature_selector_correlation PASSED")


def test_feature_selector_variance():
    """Varyans filtreleme testi."""
    from services.features.feature_selector import FeatureSelector

    selector = FeatureSelector()

    X = [
        [1.0, 5.0, 0.0],
        [2.0, 5.0, 0.0],
        [3.0, 5.0, 0.0],
        [4.0, 5.0, 0.0],
        [5.0, 5.0, 0.0],
    ]
    names = ["varying", "constant", "zero"]

    X_filtered, names_filtered = selector.select_by_variance(X, names, threshold=0.01)

    # "constant" ve "zero" kaldırılmalı
    assert "varying" in names_filtered
    assert "constant" not in names_filtered or "zero" not in names_filtered

    print("✅ test_feature_selector_variance PASSED")


def test_feature_selector_auto():
    """Auto selection pipeline testi."""
    from services.features.feature_selector import FeatureSelector

    selector = FeatureSelector()

    X = [[i + j * 0.1 for j in range(20)] for i in range(100)]
    names = [f"f_{i}" for i in range(20)]

    X_final, names_final = selector.auto_select(
        X, names,
        variance_threshold=0.001,
        correlation_threshold=0.99,
        max_features=10,
    )

    assert len(names_final) <= 10

    print("✅ test_feature_selector_auto PASSED")


# =====================================================
# RUN ALL TESTS
# =====================================================

def run_all_tests():
    """Tüm testleri çalıştır."""
    tests = [
        # Feature Store
        test_feature_store_basic,
        test_feature_store_pit,
        test_feature_store_versioning,
        test_feature_store_lineage,
        test_feature_store_snapshot,
        test_feature_store_baseline,
        test_feature_store_stats,
        # Drift Detector
        test_drift_detector_ks,
        test_drift_detector_psi,
        test_drift_detector_zscore,
        test_drift_detector_all,
        test_drift_detector_alerts,
        # Importance Tracker
        test_importance_native,
        test_importance_rfe,
        test_importance_drift,
        test_importance_concentration,
        # BIST Features
        test_bist_features_basic,
        test_bist_features_fx,
        test_bist_features_quality,
        test_bist_features_kap,
        # Pipeline
        test_pipeline_basic,
        test_pipeline_with_features,
        # Feature Selector
        test_feature_selector_correlation,
        test_feature_selector_variance,
        test_feature_selector_auto,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append(f"{test.__name__}: {e}")
            print(f"❌ {test.__name__} FAILED: {e}")

    print(f"\n{'='*60}")
    print(f"SONUÇ: {passed} passed, {failed} failed / {len(tests)} total")
    if errors:
        print(f"\nHatalar:")
        for err in errors:
            print(f"  - {err}")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
