"""ALPHA BIST — Features Service Audit & Hardening Tests.

Tüm 18 dosya, veri modelleri, __repr__ metotları, fail-closed davranışları,
orjson serileştirmesi ve yedi motor hesaplamaları canlı olarak test edilir.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl

from services.features.bist_features import (
    BIST_FEATURE_DEFINITIONS,
    BISTFeatureDef,
    get_all_feature_names,
    get_feature_count,
    get_high_importance_features,
    validate_all_definitions,
)
from services.features.cache_manager import FeatureCacheManager
from services.features.calculator import FeatureCalculator
from services.features.contract import FeatureContract, FeatureRegistry
from services.features.cross_sectional import CrossSectionalEngine
from services.features.doc_generator import FeatureDocGenerator
from services.features.feature_store_feast import (
    BISTFeatureStore,
    Entity,
    FeatureSpec,
    FeatureView,
)
from services.features.feature_tests import (
    FeatureTestResult,
    FeatureTestSuite,
    TestResult,
    TestSuiteSummary,
)
from services.features.incremental_state import IncrementalStateManager
from services.features.lineage import (
    FeatureLineageRecord,
    FeatureLineageTracker,
)
from services.features.macro import MacroFeatureEngine
from services.features.pipeline import (
    FeaturePipeline,
    PipelineConfig,
    PipelineResult,
)
from services.features.quality_monitor import (
    FeatureQualityMonitor,
    FeatureQualityReport,
    QualitySummary,
)
from services.features.selection import (
    FeatureImportance,
    FeatureSelector,
    SelectionResult,
)
from services.features.seven_motors import (
    MeanReversionMotor,
    MicrostructureMotor,
    MomentumMotor,
    RelativeStrengthMotor,
    SeasonalityMotor,
    VolatilityMotor,
    VolumeMotor,
    WhyFallingMotor,
)
from services.features.store import FeatureStore
from services.features.versioning import (
    CompatibilityReport,
    FeatureVersionManager,
    VersionDiff,
    VersionSnapshot,
)

# Pytest collection uyarısını önleme
TestResult.__test__ = False
TestSuiteSummary.__test__ = False
FeatureTestResult.__test__ = False


def test_feature_contracts_and_registry():
    """FeatureContract ve FeatureRegistry doğrulaması."""
    contract = FeatureContract(
        name="test_momentum_14",
        source="OHLCV",
        formula="close[-1] / close[-14]",
        lookback=14,
        frequency="daily",
        available_at="close",
        pit_safe=True,
        version=1,
        owner="features",
        description="14 günlük test momentum göstergesi",
        value_range=(-100.0, 100.0),
        category="technical",
        dependencies=["close"],
    )
    assert "FeatureContract" in repr(contract)
    assert "test_momentum_14" in repr(contract)
    assert contract.validate_value(15.5) is True
    assert contract.validate_value(float("nan")) is False

    registry = FeatureRegistry()
    assert "FeatureRegistry" in repr(registry)
    registry.register(contract)
    assert registry.get("test_momentum_14") is not None
    assert registry.get("test_momentum_14") == contract
    pit_safe_names = [c.name for c in registry.list_pit_safe()]
    assert "test_momentum_14" in pit_safe_names
    tech_names = [c.name for c in registry.list_by_category("technical")]
    assert "test_momentum_14" in tech_names


def test_feature_calculator_and_pipeline():
    """FeatureCalculator ve FeaturePipeline sınıfları doğrulaması."""
    calculator = FeatureCalculator()
    assert "FeatureCalculator" in repr(calculator)

    config = PipelineConfig(
        drift_threshold=0.25,
        enable_drift_detection=True,
    )
    assert "PipelineConfig" in repr(config)

    result = PipelineResult(
        ticker="THYAO",
        feature_count=15,
    )
    assert "PipelineResult" in repr(result)
    assert "THYAO" in repr(result)

    pipeline = FeaturePipeline(config=config)
    assert "FeaturePipeline" in repr(pipeline)


def test_feature_store_and_cache_manager():
    """FeatureStore ve FeatureCacheManager thread-safe caching doğrulaması."""
    cache = FeatureCacheManager(ttl_seconds=60.0)
    assert "FeatureCacheManager" in repr(cache)

    features = {"rsi_14": 62.0, "macd": 1.25}
    cache.set_all_features({"GARAN": features})
    cached = cache.get_features("GARAN")
    assert cached is not None
    assert cached["rsi_14"] == 62.0

    stats = cache.get_stats()
    assert "hits" in stats
    assert "misses" in stats

    store = FeatureStore()
    assert "FeatureStore" in repr(store)


def test_incremental_state_and_macro_engine():
    """IncrementalStateManager ve MacroFeatureEngine doğrulaması."""
    state_mgr = IncrementalStateManager(max_window=50)
    assert "IncrementalStateManager" in repr(state_mgr)

    state_mgr.update("AKBNK", "returns", 0.015)
    state_mgr.update("AKBNK", "returns", -0.008)
    state_mgr.update("AKBNK", "returns", 0.022)

    stats = state_mgr.get_stats("AKBNK", "returns")
    assert stats["mean"] is not None
    assert not math.isnan(stats["mean"])

    macro = MacroFeatureEngine()
    assert "MacroFeatureEngine" in repr(macro)
    macro_feats = macro.compute_features(
        macro_data={
            "vix": 18.5,
            "usdtry": 34.2,
            "brent_crude": 78.5,
            "us10y": 4.1,
        }
    )
    assert isinstance(macro_feats, dict)
    assert len(macro_feats) > 0


def test_cross_sectional_engine():
    """CrossSectionalEngine rank ve z-score doğrulaması."""
    cs_engine = CrossSectionalEngine()
    assert "CrossSectionalEngine" in repr(cs_engine)

    universe_features = {
        "THYAO": {"pe_ratio": 5.2, "return_1m": 0.12},
        "GARAN": {"pe_ratio": 4.1, "return_1m": 0.08},
        "SISE": {"pe_ratio": 7.8, "return_1m": -0.03},
        "KCHOL": {"pe_ratio": 6.0, "return_1m": 0.05},
        "EREGL": {"pe_ratio": 5.5, "return_1m": 0.02},
    }

    res = cs_engine.compute_all_cross_sectional(
        ticker="THYAO",
        features={"pe_ratio": 5.2, "return_1m": 0.12},
        universe_features=universe_features,
    )
    assert isinstance(res, dict)
    assert "cs_rank_pe_ratio" in res
    assert "cs_zscore_pe_ratio" in res


def test_seven_motors_representations_and_computation():
    """Yedi motor sınıfı __repr__ ve hesaplama fonksiyonları doğrulaması."""
    relative_strength_motor = RelativeStrengthMotor()
    seasonality_motor = SeasonalityMotor()
    momentum_motor = MomentumMotor()
    volume_motor = VolumeMotor()
    volatility_motor = VolatilityMotor()
    mean_reversion_motor = MeanReversionMotor()
    microstructure_motor = MicrostructureMotor()
    why_falling_motor = WhyFallingMotor()

    motors = [
        relative_strength_motor,
        seasonality_motor,
        momentum_motor,
        volume_motor,
        volatility_motor,
        mean_reversion_motor,
        microstructure_motor,
        why_falling_motor,
    ]

    for motor in motors:
        repr_str = repr(motor)
        assert motor.__class__.__name__ in repr_str

    # Dummy fiyat ve hacim verileri (30 bar)
    prices = np.linspace(10.0, 15.0, 30)
    volumes = np.linspace(1000.0, 5000.0, 30)

    # Momentum
    m_res = momentum_motor.compute(ticker="THYAO", close=prices, lookback=20)
    assert isinstance(m_res, dict)
    assert "momentum_mean" in m_res

    # Volume
    v_res = volume_motor.compute(ticker="THYAO", volume=volumes, lookback=20)
    assert isinstance(v_res, dict)
    assert "volume_ratio" in v_res

    # Volatility
    vol_res = volatility_motor.compute(ticker="THYAO", close=prices, lookback=20)
    assert isinstance(vol_res, dict)
    assert "volatility" in vol_res

    # Mean Reversion
    mr_res = mean_reversion_motor.compute(ticker="THYAO", close=prices, lookback=20)
    assert isinstance(mr_res, dict)
    assert "mean_reversion" in mr_res

    # Microstructure
    micro_res = microstructure_motor.compute(
        ticker="THYAO", high=prices + 0.5, low=prices - 0.5, close=prices, lookback=20
    )
    assert isinstance(micro_res, dict)
    assert "spread" in micro_res

    # Relative Strength
    rs_res = relative_strength_motor.compute(
        ticker="THYAO", stock_close=prices, benchmark_close=prices * 0.95
    )
    assert isinstance(rs_res, dict)
    assert "rs_5d" in rs_res

    # Why Falling Motor
    wf_res = why_falling_motor.compute(
        ticker="THYAO",
        stock_return_5d=-3.5,
        stock_return_20d=-8.0,
        market_return_5d=-1.0,
        market_return_20d=-2.0,
        sector_return_5d=-2.0,
        sector_return_20d=-4.0,
        volume_change=1.2,
        volume_zscore=1.5,
        news_sentiment=-0.3,
        kap_sentiment=-0.1,
    )
    assert isinstance(wf_res, dict)
    assert "is_falling_5d" in wf_res


def test_bist_features_definitions():
    """BIST-100 feature tanımları ve kuralları doğrulaması."""
    all_defs = BIST_FEATURE_DEFINITIONS
    assert len(all_defs) > 0

    first_def = all_defs[0]
    assert isinstance(first_def, BISTFeatureDef)
    assert "BISTFeatureDef" in repr(first_def)
    assert first_def.name != ""

    names = get_all_feature_names()
    assert len(names) == len(all_defs)

    count_dict = get_feature_count()
    assert sum(count_dict.values()) == len(all_defs)

    high_imp = get_high_importance_features()
    assert len(high_imp) > 0

    validation_errors = validate_all_definitions()
    assert len(validation_errors) == 0


def test_feature_selection_and_importance():
    """FeatureSelector, SelectionResult ve FeatureImportance doğrulaması."""
    fi = FeatureImportance(
        feature_name="volume_spike_ratio",
        importance=0.185,
        rank=1,
    )
    assert "FeatureImportance" in repr(fi)
    assert "volume_spike_ratio" in repr(fi)

    res = SelectionResult(
        selected_features=["volume_spike_ratio", "rsi_14"],
        removed_features=["collinear_close"],
        removal_reasons={"collinear_close": "high_correlation"},
        n_original=3,
        n_selected=2,
        n_removed=1,
        reduction_ratio=0.333,
    )
    assert "SelectionResult" in repr(res)
    assert "selected=2" in repr(res)

    selector = FeatureSelector()
    assert "FeatureSelector" in repr(selector)


def test_quality_monitor():
    """FeatureQualityMonitor, FeatureQualityReport ve QualitySummary doğrulaması."""
    report = FeatureQualityReport(
        feature_name="rsi_14",
        total_count=100,
        null_count=2,
        null_ratio=0.02,
        outlier_count=1,
        outlier_ratio=0.01,
        mean=50.5,
        std=15.2,
        min_val=12.0,
        max_val=88.0,
        q25=40.0,
        q50=50.0,
        q75=60.0,
        is_valid=True,
    )
    assert "FeatureQualityReport" in repr(report)
    assert "rsi_14" in repr(report)

    summary = QualitySummary(
        total_features=10,
        valid_features=9,
        warning_features=1,
        critical_features=0,
        avg_null_ratio=0.01,
        avg_outlier_ratio=0.02,
        completeness_score=0.95,
        timestamp=datetime.now(UTC).isoformat(),
    )
    assert "QualitySummary" in repr(summary)
    assert "total=10" in repr(summary)

    monitor = FeatureQualityMonitor()
    assert "FeatureQualityMonitor" in repr(monitor)

    clean_vals = np.array([50.0, 52.0, 48.0, 51.0, 49.0, 50.5])
    rep = monitor.check_feature("test_feature", clean_vals)
    assert rep.is_valid is True
    assert rep.null_count == 0


def test_lineage_and_versioning(tmp_path: Any):
    """Lineage tracker ve Version manager orjson uyumluluğu doğrulaması."""
    record = FeatureLineageRecord(
        feature_name="macd_signal",
        raw_sources=["close_price"],
        intermediate_features=["ema_12", "ema_26"],
        transformations=["ema_diff", "ema_9_smooth"],
        computed_by="FeatureEngine",
    )
    assert "FeatureLineageRecord" in repr(record)
    assert "macd_signal" in repr(record)

    tracker = FeatureLineageTracker()
    assert "FeatureLineageTracker" in repr(tracker)

    tracker.record(
        feature_name="macd_signal",
        raw_sources=["close_price"],
        intermediate_features=["ema_12", "ema_26"],
        transformations=["ema_diff", "ema_9_smooth"],
        computed_by="FeatureEngine",
    )
    lineage = tracker.get_lineage("macd_signal")
    assert lineage is not None
    assert lineage.feature_name == "macd_signal"

    # Mermaid graph
    graph = tracker.generate_dependency_graph()
    assert "LineageGraph" in repr(graph)
    assert "graph" in graph.mermaid.lower() or "flowchart" in graph.mermaid.lower()

    # orjson save and load test
    save_path = tmp_path / "lineage.json"
    tracker.save_to_json(save_path)
    assert save_path.exists()

    new_tracker = FeatureLineageTracker()
    loaded_count = new_tracker.load_from_json(save_path)
    assert loaded_count >= 1
    assert new_tracker.get_lineage("macd_signal") is not None

    # Versioning
    v_mgr = FeatureVersionManager()
    assert "FeatureVersionManager" in repr(v_mgr)

    contract = FeatureContract(
        name="macd_signal",
        source="OHLCV",
        formula="ema(12) - ema(26)",
        lookback=26,
        frequency="daily",
        available_at="close",
        pit_safe=True,
        version=1,
        owner="features",
    )
    v_num = v_mgr.register(contract)
    assert v_num == 1

    current = v_mgr.get_current_version("macd_signal")
    assert current is not None
    assert current.version == 1
    assert isinstance(current, VersionSnapshot)
    assert "VersionSnapshot" in repr(current)

    v_diff = VersionDiff(
        feature_name="macd_signal",
        old_version=1,
        new_version=2,
        changed_fields=["formula"],
        field_changes={"formula": {"old": "a", "new": "b"}},
        is_compatible=True,
        compatibility_notes=[],
    )
    assert "VersionDiff" in repr(v_diff)

    comp_rep = CompatibilityReport(
        feature_name="macd_signal",
        old_version=1,
        new_version=2,
        is_compatible=True,
        breaking_changes=[],
        warnings=[],
        notes=[],
    )
    assert "CompatibilityReport" in repr(comp_rep)


def test_doc_generator_and_feast_store():
    """FeatureDocGenerator ve BISTFeatureStore doğrulaması."""
    doc_gen = FeatureDocGenerator()
    assert "FeatureDocGenerator" in repr(doc_gen)

    # Test doc generation
    doc = doc_gen.generate_catalog()
    assert isinstance(doc, str)

    entity = Entity(
        name="ticker",
        join_key="ticker",
        description="BIST Pay Senedi Kodu",
    )
    assert "Entity" in repr(entity)

    spec = FeatureSpec(
        name="rsi_14",
        dtype="FLOAT",
        description="Relative Strength Index",
    )
    assert "FeatureSpec" in repr(spec)

    fv = FeatureView(
        name="daily_momentum",
        entities=["ticker"],
        features=[spec],
        ttl_days=30,
    )
    assert "FeatureView" in repr(fv)

    feast_store = BISTFeatureStore()
    assert "BISTFeatureStore" in repr(feast_store)
    feast_store.register_entity(entity)
    feast_store.register_feature_view(fv)


def test_feature_test_suite_and_results():
    """FeatureTestSuite, TestSuiteSummary ve FeatureTestResult doğrulaması."""
    tr = TestResult(
        test_name="range_check",
        passed=True,
        message="Values within [0, 100]",
        duration_ms=1.2,
    )
    assert "TestResult" in repr(tr)
    assert "range_check" in repr(tr)

    ftr = FeatureTestResult(
        feature_name="rsi_14",
        total_tests=1,
        passed=1,
        failed=0,
        skipped=0,
        results=[tr],
        overall_passed=True,
        duration_ms=1.2,
    )
    assert "FeatureTestResult" in repr(ftr)
    assert "rsi_14" in repr(ftr)

    summary = TestSuiteSummary(
        total_features=1,
        passed_features=1,
        failed_features=0,
        total_tests=1,
        passed_tests=1,
        failed_tests=0,
        timestamp=datetime.now(UTC).isoformat(),
        duration_ms=1.2,
        feature_results=[ftr],
    )
    assert "TestSuiteSummary" in repr(summary)
    assert "features=1/1" in repr(summary)

    suite = FeatureTestSuite()
    assert "FeatureTestSuite" in repr(suite)

    def compute_mock_rsi(df: Any) -> dict[str, float]:
        return {"rsi_14": 55.0}

    test_df = pl.DataFrame({
        "close": [10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5],
    })
    res = suite.test_feature("rsi_14", compute_mock_rsi, test_df)
    assert res.feature_name == "rsi_14"
    assert len(res.results) > 0
