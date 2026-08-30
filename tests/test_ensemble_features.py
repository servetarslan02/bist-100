from __future__ import annotations

from typing import Any

"""ALPHA BIST — Ensemble & Feature Engineering Yeni Modül Testleri

Test edilen modüller:
- WalkForwardEnsemble
- ModelDegradationMonitor
- FeatureSelector
- FeatureLineageTracker
- FeatureVersionManager
- FeatureDocGenerator
- EnsembleModel (auto_prune, should_use_ensemble)
- StackingEnsemble (regime_smoothing, regime_performance)
- WeightAdjuster (trigger_from_trade_result, expanding_window_recalc)
- FeatureDriftDetector (per-ticker, time_series, strengthening/weakening)

Kullanım:
    python -m pytest tests/test_ensemble_features.py -v
"""


import numpy as np

# =====================================================
# WALK-FORWARD ENSEMBLE TESTS
# =====================================================


class TestWalkForwardEnsemble:
    """WalkForwardEnsemble testleri."""

    def test_import(self) -> Any:
        """Import çalışmalı."""
        from services.learning.walkforward_ensemble import walkforward_ensemble

        assert walkforward_ensemble is not None

    def test_empty_result(self) -> Any:
        """Boş sonuç doğru yapıda olmalı."""
        from services.learning.walkforward_ensemble import WalkForwardEnsemble

        wf = WalkForwardEnsemble(min_train_size=10, min_val_size=5)
        result = wf._empty_result()

        assert result.n_folds == 0
        assert result.fold_results == []
        assert result.mean_ensemble_ic == 0.0
        assert result.final_weights == {}

    def test_create_splits(self) -> Any:
        """Split'ler doğru aralıklarda olmalı."""
        from services.learning.walkforward_ensemble import WalkForwardEnsemble

        wf = WalkForwardEnsemble(n_splits=3, min_train_size=50, min_val_size=20, embargo_days=5)
        splits = wf._create_splits(300)

        assert len(splits) > 0
        for train_idx, val_idx in splits:
            # Train ve val çakışmamalı
            assert len(set(train_idx) & set(val_idx)) == 0
            # Embargo gap olmalı
            if len(train_idx) > 0 and len(val_idx) > 0:
                assert val_idx[0] - train_idx[-1] >= wf.embargo_days

    def test_average_weights(self) -> Any:
        """Ağırlık ortalaması doğru hesaplanmalı."""
        from services.learning.walkforward_ensemble import WalkForwardEnsemble

        wf = WalkForwardEnsemble()
        weight_list = [
            {"lgbm": 0.4, "xgb": 0.3, "cat": 0.3},
            {"lgbm": 0.5, "xgb": 0.25, "cat": 0.25},
            {"lgbm": 0.45, "xgb": 0.3, "cat": 0.25},
        ]

        avg = wf._average_weights(weight_list)

        assert "lgbm" in avg
        assert "xgb" in avg
        assert "cat" in avg
        # Normalize edilmiş olmalı
        assert abs(sum(avg.values()) - 1.0) < 0.01

    def test_run_with_synthetic_data(self) -> Any:
        """Sentetik veri ile walk-forward çalışmalı."""
        from sklearn.linear_model import Ridge

        from services.learning.walkforward_ensemble import WalkForwardEnsemble

        np.random.seed(42)
        n = 300
        X = np.random.randn(n, 5)
        y = X @ np.array([1.0, -0.5, 0.3, 0.0, -0.2]) + np.random.randn(n) * 0.5

        wf = WalkForwardEnsemble(
            n_splits=3,
            embargo_days=5,
            min_train_size=50,
            min_val_size=20,
        )

        base_models = {
            "ridge1": Ridge(alpha=1.0),
            "ridge2": Ridge(alpha=10.0),
            "ridge3": Ridge(alpha=0.1),
        }

        result = wf.run(X, y, base_models)

        assert result.n_folds > 0
        assert len(result.fold_results) > 0
        assert result.final_weights
        assert -1.0 <= result.mean_ensemble_ic <= 1.0

    def test_history_tracking(self) -> Any:
        """History tracking çalışmalı."""
        from services.learning.walkforward_ensemble import WalkForwardEnsemble

        wf = WalkForwardEnsemble()
        assert wf.get_history() == []
        assert wf.get_last_result() is None


# =====================================================
# MODEL DEGRADATION MONITOR TESTS
# =====================================================


class TestModelDegradationMonitor:
    """ModelDegradationMonitor testleri."""

    def test_import(self) -> Any:
        """Import çalışmalı."""
        from services.learning.model_degradation_monitor import degradation_monitor

        assert degradation_monitor is not None

    def test_record_outcome(self) -> Any:
        """Sonuç kaydetme çalışmalı."""
        from services.learning.model_degradation_monitor import ModelDegradationMonitor

        monitor = ModelDegradationMonitor(window_size=10)
        monitor.record_outcome("test_model", predicted=0.7, actual=1.0, return_pct=2.3)

        assert "test_model" in monitor._outcomes
        assert len(monitor._outcomes["test_model"]) == 1

    def test_check_model_insufficient_data(self) -> Any:
        """Yetersiz veri ile kontrol çalışmalı."""
        from services.learning.model_degradation_monitor import ModelDegradationMonitor

        monitor = ModelDegradationMonitor(window_size=50)
        monitor.record_outcome("test_model", predicted=0.7, actual=1.0)

        report = monitor.check_model("test_model")
        assert report.severity == "OK"
        assert "Yetersiz veri" in report.recommendation

    def test_check_model_with_data(self) -> Any:
        """Yeterli veri ile kontrol çalışmalı."""
        from services.learning.model_degradation_monitor import ModelDegradationMonitor

        monitor = ModelDegradationMonitor(window_size=20)

        # İyi performans (doğru tahminler)
        for _ in range(30):
            monitor.record_outcome("good_model", predicted=0.8, actual=1.0, return_pct=2.0)

        report = monitor.check_model("good_model")
        assert report.current_accuracy > 0.5
        assert report.severity in ("OK", "WARNING", "ALERT", "CRITICAL")

    def test_auto_remove_degraded(self) -> Any:
        """Otomatik model çıkarma çalışmalı."""
        from services.learning.model_degradation_monitor import ModelDegradationMonitor

        monitor = ModelDegradationMonitor(window_size=20, auto_remove_threshold=0.30)

        # Kötü performans
        for _ in range(30):
            monitor.record_outcome("bad_model", predicted=0.8, actual=-1.0, return_pct=-2.0)

        # Manuel olarak should_remove True yapacak kadar kötü
        report = monitor.check_model("bad_model")
        # Kötü model accuracy düşük olmalı
        assert report.current_accuracy < 0.5

    def test_restore_model(self) -> Any:
        """Model geri alma çalışmalı."""
        from services.learning.model_degradation_monitor import ModelDegradationMonitor

        monitor = ModelDegradationMonitor()
        monitor._removed_models.add("test_model")

        assert monitor.restore_model("test_model")
        assert "test_model" not in monitor._removed_models
        assert not monitor.restore_model("nonexistent")

    def test_get_model_summary(self) -> Any:
        """Model özeti çalışmalı."""
        from services.learning.model_degradation_monitor import ModelDegradationMonitor

        monitor = ModelDegradationMonitor(window_size=10)
        monitor.record_outcome("model_a", predicted=0.7, actual=1.0, return_pct=1.0)
        monitor.record_outcome("model_b", predicted=0.3, actual=-1.0, return_pct=-1.0)

        summary = monitor.get_model_summary()
        assert "model_a" in summary
        assert "model_b" in summary


# =====================================================
# FEATURE SELECTOR TESTS
# =====================================================


class TestFeatureSelector:
    """FeatureSelector testleri."""

    def test_import(self) -> Any:
        """Import çalışmalı."""
        from services.features.selection import feature_selector

        assert feature_selector is not None

    def test_variance_threshold_filter(self) -> Any:
        """Varyans filtresi çalışmalı."""
        from services.features.selection import FeatureSelector

        np.random.seed(42)
        n = 100
        X = np.column_stack(
            [
                np.random.randn(n),  # Normal varyans
                np.ones(n) * 5.0,  # Sabit (düşük varyans)
                np.random.randn(n) * 0.001,  # Çok düşük varyans
                np.random.randn(n),  # Normal varyans
            ]
        )
        feature_names = ["normal", "constant", "low_var", "normal2"]

        selector = FeatureSelector(variance_threshold=0.001)
        result = selector.variance_threshold_filter(X, feature_names)

        assert "normal" in result.selected_features
        assert "normal2" in result.selected_features
        assert "constant" in result.removed_features

    def test_correlation_filter(self) -> Any:
        """Korelasyon filtresi çalışmalı."""
        from services.features.selection import FeatureSelector

        np.random.seed(42)
        n = 100
        x1 = np.random.randn(n)
        x2 = x1 + np.random.randn(n) * 0.01  # x1 ile yüksek korelasyon
        x3 = np.random.randn(n)  # Bağımsız

        X = np.column_stack([x1, x2, x3])
        feature_names = ["feat1", "feat2", "feat3"]

        selector = FeatureSelector(correlation_threshold=0.90)
        result = selector.correlation_filter(X, feature_names, threshold=0.90)

        # Yüksek korelasyonlu çiftlerden biri çıkarılmalı
        assert len(result.selected_features) < 3
        assert "feat3" in result.selected_features

    def test_select_pipeline(self) -> Any:
        """Tam pipeline çalışmalı."""
        from sklearn.linear_model import Ridge

        from services.features.selection import FeatureSelector

        np.random.seed(42)
        n = 200
        X = np.column_stack(
            [
                np.random.randn(n),
                np.random.randn(n),
                np.ones(n) * 5.0,  # Sabit
                np.random.randn(n),
                np.random.randn(n),
            ]
        )
        y = X[:, 0] * 0.5 + X[:, 1] * 0.3 + np.random.randn(n) * 0.1
        feature_names = ["f1", "f2", "constant", "f4", "f5"]

        selector = FeatureSelector(variance_threshold=0.001, default_top_k=3)
        result = selector.select(X, y, feature_names, model=Ridge(), top_k=3)

        assert result.n_original == 5
        assert result.n_selected <= 3
        assert "constant" in result.removed_features

    def test_get_feature_importances(self) -> Any:
        """Feature importance çalışmalı."""
        from sklearn.linear_model import Ridge

        from services.features.selection import FeatureSelector

        np.random.seed(42)
        n = 100
        X = np.column_stack([np.random.randn(n), np.random.randn(n)])
        y = X[:, 0] * 0.5 + np.random.randn(n) * 0.1

        selector = FeatureSelector()
        importances = selector.get_feature_importances(X, y, ["f1", "f2"], Ridge())

        assert len(importances) == 2
        assert all(imp.importance >= 0 for imp in importances)


# =====================================================
# FEATURE LINEAGE TESTS
# =====================================================


class TestFeatureLineage:
    """FeatureLineageTracker testleri."""

    def test_import(self) -> Any:
        """Import çalışmalı."""
        from services.features.lineage import feature_lineage

        assert feature_lineage is not None

    def test_record_and_get(self) -> Any:
        """Kaydetme ve sorgulama çalışmalı."""
        from services.features.lineage import FeatureLineageTracker

        tracker = FeatureLineageTracker()
        tracker.record(
            feature_name="rsi_14",
            raw_sources=["close_price"],
            transformations=["log_return", "rsi_calculation"],
            computed_by="feature-engine",
        )

        lineage = tracker.get_lineage("rsi_14")
        assert lineage is not None
        assert lineage.feature_name == "rsi_14"
        assert "close_price" in lineage.raw_sources

    def test_get_raw_sources_recursive(self) -> Any:
        """Recursive raw source bulma çalışmalı."""
        from services.features.lineage import FeatureLineageTracker

        tracker = FeatureLineageTracker()
        tracker.record(
            feature_name="log_return",
            raw_sources=["close_price"],
            transformations=["log"],
            computed_by="feature-engine",
        )
        tracker.record(
            feature_name="rsi_14",
            raw_sources=[],
            transformations=["rsi_calculation"],
            computed_by="feature-engine",
            intermediate_features=["log_return"],
        )

        sources = tracker.get_raw_sources("rsi_14")
        assert "close_price" in sources

    def test_get_dependents(self) -> Any:
        """Bağımlı feature bulma çalışmalı."""
        from services.features.lineage import FeatureLineageTracker

        tracker = FeatureLineageTracker()
        tracker.record(
            feature_name="close_price",
            raw_sources=[],
            transformations=[],
            computed_by="ingestion",
        )
        tracker.record(
            feature_name="rsi_14",
            raw_sources=["close_price"],
            transformations=["rsi"],
            computed_by="feature-engine",
        )
        tracker.record(
            feature_name="macd",
            raw_sources=["close_price"],
            transformations=["macd"],
            computed_by="feature-engine",
        )

        dependents = tracker.get_dependents("close_price")
        assert "rsi_14" in dependents
        assert "macd" in dependents

    def test_generate_dependency_graph(self) -> Any:
        """Dependency graph üretimi çalışmalı."""
        from services.features.lineage import FeatureLineageTracker

        tracker = FeatureLineageTracker()
        tracker.record(
            feature_name="rsi_14",
            raw_sources=["close_price"],
            transformations=["rsi"],
            computed_by="feature-engine",
        )

        graph = tracker.generate_dependency_graph()
        assert graph.nodes
        assert graph.edges
        assert "graph TD" in graph.mermaid

    def test_trace_to_raw(self) -> Any:
        """Raw data'ya izleme çalışmalı."""
        from services.features.lineage import FeatureLineageTracker

        tracker = FeatureLineageTracker()
        tracker.record(
            feature_name="rsi_14",
            raw_sources=["close_price"],
            transformations=["rsi"],
            computed_by="feature-engine",
        )

        trace = tracker.trace_to_raw("rsi_14")
        assert trace["feature"] == "rsi_14"
        assert "close_price" in trace["raw_sources"]

    def test_lineage_summary(self) -> Any:
        """Lineage özeti çalışmalı."""
        from services.features.lineage import FeatureLineageTracker

        tracker = FeatureLineageTracker()
        tracker.record("f1", ["raw1"], ["t1"], "engine")
        tracker.record("f2", ["raw2"], ["t2"], "engine")

        summary = tracker.get_lineage_summary()
        assert summary["total_features"] == 2
        assert summary["total_raw_sources"] == 2


# =====================================================
# FEATURE VERSION MANAGER TESTS
# =====================================================


class TestFeatureVersionManager:
    """FeatureVersionManager testleri."""

    def test_import(self) -> Any:
        """Import çalışmalı."""
        from services.features.versioning import feature_version_manager

        assert feature_version_manager is not None

    def test_register_first_version(self) -> Any:
        """İlk kayıt version 1 olmalı."""
        from services.features.contract import FeatureContract
        from services.features.versioning import FeatureVersionManager

        manager = FeatureVersionManager()
        contract = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="close / close[-1] - 1",
            lookback=2,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            description="Test feature",
        )

        version = manager.register(contract)
        assert version == 1

    def test_register_no_change_same_version(self) -> Any:
        """Değişiklik yoksa aynı version kalmalı."""
        from services.features.contract import FeatureContract
        from services.features.versioning import FeatureVersionManager

        manager = FeatureVersionManager()
        contract = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="close / close[-1] - 1",
            lookback=2,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            description="Test feature",
        )

        manager.register(contract)
        version2 = manager.register(contract)
        assert version2 == 1

    def test_register_change_version_increases(self) -> Any:
        """Değişiklik varsa version artmalı."""
        from services.features.contract import FeatureContract
        from services.features.versioning import FeatureVersionManager

        manager = FeatureVersionManager()

        contract_v1 = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="close / close[-1] - 1",
            lookback=2,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            description="Test feature v1",
        )
        manager.register(contract_v1)

        contract_v2 = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="close / close[-2] - 1",  # Formula değişti
            lookback=3,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=2,
            owner="test",
            description="Test feature v2",
        )
        version = manager.register(contract_v2)
        assert version == 2

    def test_version_history(self) -> Any:
        """Version history çalışmalı."""
        from services.features.contract import FeatureContract
        from services.features.versioning import FeatureVersionManager

        manager = FeatureVersionManager()

        for i in range(3):
            contract = FeatureContract(
                name="test_feature",
                source="OHLCV",
                formula=f"formula_{i}",
                lookback=2,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=i + 1,
                owner="test",
                description=f"v{i + 1}",
            )
            manager.register(contract)

        history = manager.get_version_history("test_feature")
        assert len(history) == 3

    def test_diff(self) -> Any:
        """Version diff çalışmalı."""
        from services.features.contract import FeatureContract
        from services.features.versioning import FeatureVersionManager

        manager = FeatureVersionManager()

        contract_v1 = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="formula_v1",
            lookback=10,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            description="v1",
        )
        manager.register(contract_v1)

        contract_v2 = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="formula_v2",
            lookback=20,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=2,
            owner="test",
            description="v2",
        )
        manager.register(contract_v2)

        diff = manager.diff("test_feature", 1, 2)
        assert diff is not None
        assert "formula" in diff.changed_fields
        assert "lookback" in diff.changed_fields

    def test_check_compatibility(self) -> Any:
        """Uyumluluk kontrolü çalışmalı."""
        from services.features.contract import FeatureContract
        from services.features.versioning import FeatureVersionManager

        manager = FeatureVersionManager()

        contract_v1 = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="formula_v1",
            lookback=10,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            description="v1",
        )
        manager.register(contract_v1)

        contract_v2 = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="formula_v2",  # Breaking change
            lookback=10,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=2,
            owner="test",
            description="v2",
        )
        manager.register(contract_v2)

        compat = manager.check_compatibility("test_feature", 1, 2)
        assert not compat.is_compatible  # Formula değişikliği breaking
        assert len(compat.breaking_changes) > 0

    def test_rollback(self) -> Any:
        """Rollback çalışmalı."""
        from services.features.contract import FeatureContract
        from services.features.versioning import FeatureVersionManager

        manager = FeatureVersionManager()

        for i in range(3):
            contract = FeatureContract(
                name="test_feature",
                source="OHLCV",
                formula=f"formula_{i}",
                lookback=2,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=i + 1,
                owner="test",
                description=f"v{i + 1}",
            )
            manager.register(contract)

        assert manager.rollback("test_feature", 1)
        current = manager.get_current_version("test_feature")
        assert current.version == 1

    def test_summary(self) -> Any:
        """Özet çalışmalı."""
        from services.features.versioning import FeatureVersionManager

        manager = FeatureVersionManager()
        summary = manager.get_summary()
        assert "total_features" in summary
        assert "total_versions" in summary


# =====================================================
# FEATURE DOC GENERATOR TESTS
# =====================================================


class TestFeatureDocGenerator:
    """FeatureDocGenerator testleri."""

    def test_import(self) -> Any:
        """Import çalışmalı."""
        from services.features.doc_generator import feature_doc_generator

        assert feature_doc_generator is not None

    def test_generate_catalog(self) -> Any:
        """Katalog üretimi çalışmalı."""
        from services.features.doc_generator import FeatureDocGenerator

        generator = FeatureDocGenerator()
        catalog = generator.generate_catalog()

        assert "Feature Catalog" in catalog
        assert "rsi_14" in catalog
        assert "PIT-Safe" in catalog

    def test_generate_dependency_graph(self) -> Any:
        """Dependency graph üretimi çalışmalı."""
        from services.features.doc_generator import FeatureDocGenerator

        generator = FeatureDocGenerator()
        graph = generator.generate_dependency_graph()

        assert "graph TD" in graph

    def test_generate_summary_report(self) -> Any:
        """Özet rapor üretimi çalışmalı."""
        from services.features.doc_generator import FeatureDocGenerator

        generator = FeatureDocGenerator()
        report = generator.generate_summary_report()

        assert "Summary Report" in report
        assert "Toplam Feature" in report
        assert "Kategori Dağılımı" in report

    def test_generate_feature_card(self) -> Any:
        """Feature kartı üretimi çalışmalı."""
        from services.features.contract import FeatureContract
        from services.features.doc_generator import FeatureDocGenerator

        generator = FeatureDocGenerator()
        contract = FeatureContract(
            name="test_feature",
            source="OHLCV",
            formula="test_formula",
            lookback=10,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            description="Test feature",
        )

        card = generator.generate_feature_card(contract)
        assert "test_feature" in card
        assert "test_formula" in card


# =====================================================
# ENSEMBLE MODEL ENHANCEMENT TESTS
# =====================================================


class TestEnsembleModelEnhancements:
    """EnsembleModel auto_prune ve should_use_ensemble testleri."""

    def test_auto_prune_redundant(self) -> Any:
        """Auto-prune çalışmalı."""
        from services.ml.ensemble import EnsembleModel

        np.random.seed(42)
        n = 100
        preds_a = np.random.randn(n)
        preds_b = preds_a + np.random.randn(n) * 0.01  # a ile yüksek korelasyon
        preds_c = np.random.randn(n)  # bağımsız

        model = EnsembleModel()
        pruned, removed = model.auto_prune_redundant(
            {"model_a": preds_a, "model_b": preds_b, "model_c": preds_c},
            model_ics={"model_a": 0.5, "model_b": 0.3, "model_c": 0.4},
            threshold=0.90,
        )

        # Yüksek korelasyonlu çiftlerden biri çıkarılmalı
        assert len(removed) > 0
        assert "model_c" in pruned  # Bağımsız model kalmalı

    def test_should_use_ensemble_beneficial(self) -> Any:
        """Faydalı ensemble onaylanmalı."""
        from services.ml.ensemble import EnsembleModel

        model = EnsembleModel()

        from services.ml.ensemble import BenefitReport, DiversityReport

        diversity = DiversityReport(
            correlation_matrix={},
            mean_correlation=0.3,
            diversity_score=0.7,
            redundant_models=[],
            recommendation="Good diversity",
        )

        benefit = BenefitReport(
            ensemble_ic=0.5,
            best_individual_ic=0.4,
            best_individual_name="model_a",
            ic_improvement=0.1,
            is_beneficial=True,
            recommendation="Ensemble better",
        )

        use, reason = model.should_use_ensemble(diversity, benefit)
        assert use
        assert "faydalı" in reason.lower()

    def test_should_use_ensemble_low_diversity(self) -> Any:
        """Düşük diversity ile ensemble reddedilmeli."""
        from services.ml.ensemble import BenefitReport, DiversityReport, EnsembleModel

        model = EnsembleModel()

        diversity = DiversityReport(
            correlation_matrix={},
            mean_correlation=0.9,
            diversity_score=0.1,
            redundant_models=["a↔b"],
            recommendation="Low diversity",
        )

        benefit = BenefitReport(
            ensemble_ic=0.5,
            best_individual_ic=0.4,
            best_individual_name="model_a",
            ic_improvement=0.1,
            is_beneficial=True,
            recommendation="Ensemble better",
        )

        use, reason = model.should_use_ensemble(diversity, benefit)
        assert not use
        assert "diversity" in reason.lower()


# =====================================================
# STACKING ENSEMBLE ENHANCEMENT TESTS
# =====================================================


class TestStackingEnsembleEnhancements:
    """StackingEnsemble regime_smoothing ve regime_performance testleri."""

    def test_regime_smoothing_same_regime(self) -> Any:
        """Aynı rejimde smoothing etkisiz olmalı."""
        from services.ml.stacking_ensemble import StackingEnsemble

        stacking = StackingEnsemble()
        X = np.random.randn(10, 3)

        # Fitted olmadan predict zeros döndürür
        pred = stacking.predict_with_regime_smoothing(X, "BULL", "BULL", 0.3)
        assert len(pred) == 10

    def test_regime_smoothing_transition(self) -> Any:
        """Rejim geçişinde smoothing çalışmalı."""
        from services.ml.stacking_ensemble import StackingEnsemble

        stacking = StackingEnsemble()
        X = np.random.randn(10, 3)

        # Fitted olmadan
        pred = stacking.predict_with_regime_smoothing(X, "BULL", "BEAR", 0.3)
        assert len(pred) == 10


# =====================================================
# WEIGHT ADJUSTER ENHANCEMENT TESTS
# =====================================================


class TestWeightAdjusterEnhancements:
    """WeightAdjuster trigger_from_trade_result ve expanding_window_recalc testleri."""

    def test_trigger_from_trade_result(self) -> Any:
        """Trade result tetikleme çalışmalı."""
        from services.learning.weight_adjuster import WeightAdjuster

        adjuster = WeightAdjuster()

        # Birkaç sonuç kaydet
        for _ in range(10):
            adjuster.trigger_from_trade_result("model_a", predicted=0.8, actual=1.0, return_pct=2.0)
            adjuster.trigger_from_trade_result("model_b", predicted=0.3, actual=-1.0, return_pct=-1.0)

        weights = adjuster.get_weights()
        assert len(weights) > 0

    def test_expanding_window_recalc(self) -> Any:
        """Expanding window recalculation çalışmalı."""
        from services.learning.weight_adjuster import WeightAdjuster

        adjuster = WeightAdjuster()

        # Yeterli veri ekle
        for _ in range(150):
            adjuster.trigger_from_trade_result("model_a", predicted=0.8, actual=1.0, return_pct=2.0)
            adjuster.trigger_from_trade_result("model_b", predicted=0.3, actual=-1.0, return_pct=-1.0)

        weights = adjuster.expanding_window_recalc(min_window=100)
        assert len(weights) > 0
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_get_weight_change_log(self) -> Any:
        """Ağırlık değişim log'u çalışmalı."""
        from services.learning.weight_adjuster import WeightAdjuster

        adjuster = WeightAdjuster()
        log = adjuster.get_weight_change_log()
        assert isinstance(log, list)


# =====================================================
# FEATURE DRIFT ENHANCEMENT TESTS
# =====================================================


class TestFeatureDriftEnhancements:
    """FeatureDriftDetector per-ticker, time_series, strengthening testleri."""

    def test_record_shap_per_ticker(self) -> Any:
        """Ticker bazlı SHAP kaydetme çalışmalı."""
        from services.ml.feature_drift import FeatureDriftDetector

        detector = FeatureDriftDetector()
        detector.record_shap_per_ticker("THYAO", {"rsi_14": 0.3, "momentum_10d": 0.2})
        detector.record_shap_per_ticker("GARAN", {"rsi_14": 0.4, "momentum_10d": 0.1})

        assert "THYAO" in detector._shap_by_ticker
        assert "GARAN" in detector._shap_by_ticker

    def test_get_importance_time_series(self) -> Any:
        """Importance zaman serisi çalışmalı."""
        from services.ml.feature_drift import FeatureDriftDetector

        detector = FeatureDriftDetector()

        # Birkaç SHAP kaydet
        for i in range(5):
            detector.record_shap({"rsi_14": 0.3 + i * 0.01, "momentum": 0.2})

        ts = detector.get_importance_time_series("rsi_14")
        assert ts["feature"] == "rsi_14"
        assert len(ts["values"]) == 5

    def test_get_strengthening_features(self) -> Any:
        """Güçlenen feature'lar çalışmalı."""
        from services.ml.feature_drift import FeatureDriftDetector

        detector = FeatureDriftDetector()

        # Düşük importance ile başla
        detector.record_shap({"rsi_14": 0.1, "momentum": 0.3})
        detector.record_shap({"rsi_14": 0.1, "momentum": 0.3})
        detector.record_shap({"rsi_14": 0.1, "momentum": 0.3})

        # Yüksek importance ile bitir
        detector.record_shap({"rsi_14": 0.5, "momentum": 0.1})

        strengthening = detector.get_strengthening_features(threshold=0.1)
        # rsi_14 güçlenmeli
        rsi_entry = [s for s in strengthening if s["feature"] == "rsi_14"]
        assert len(rsi_entry) > 0

    def test_get_weakening_features(self) -> Any:
        """Zayıflayan feature'lar çalışmalı."""
        from services.ml.feature_drift import FeatureDriftDetector

        detector = FeatureDriftDetector()

        # Yüksek importance ile başla
        detector.record_shap({"rsi_14": 0.5, "momentum": 0.3})
        detector.record_shap({"rsi_14": 0.5, "momentum": 0.3})
        detector.record_shap({"rsi_14": 0.5, "momentum": 0.3})

        # Düşük importance ile bitir
        detector.record_shap({"rsi_14": 0.1, "momentum": 0.5})

        weakening = detector.get_weakening_features(threshold=0.1)
        # momentum zayıflamalı
        mom_entry = [w for w in weakening if w["feature"] == "momentum"]
        assert len(mom_entry) > 0

    def test_get_ticker_shap_summary(self) -> Any:
        """Ticker SHAP özeti çalışmalı."""
        from services.ml.feature_drift import FeatureDriftDetector

        detector = FeatureDriftDetector()
        detector.record_shap_per_ticker("THYAO", {"rsi_14": 0.3, "momentum": 0.2})
        detector.record_shap_per_ticker("THYAO", {"rsi_14": 0.4, "momentum": 0.1})

        summary = detector.get_ticker_shap_summary("THYAO")
        assert summary["ticker"] == "THYAO"
        assert summary["n_records"] == 2
        assert len(summary["top_features"]) > 0
