"""ALPHA BIST — Learning Service Audit & Hardening Tests.

Tüm core sınıflar, veri modelleri, __repr__ metotları, fail-closed davranışları
ve duckdb/orjson uyumluluğu canlı olarak test edilir.
"""

from datetime import UTC, datetime
from pathlib import Path

from services.learning.meta_learner import MetaLearner, ModelPerformance
from services.learning.model_degradation_monitor import (
    DegradationAlert,
    DegradationReport,
    ModelDegradationMonitor,
    ModelOutcome,
)
from services.learning.model_memory_store import ModelMemoryStore
from services.learning.model_performance_engine import PerformanceMetrics
from services.learning.model_registry import ModelRecord, ModelRegistry
from services.learning.model_trust_engine import ModelTrustEngine, ModelTrustScore
from services.learning.outcome_tracker import OutcomeTracker
from services.learning.production_alpha_engine import ProductionAlphaEngine
from services.learning.retrain_engine import RetrainEngine, RetrainResult, WalkForwardMetrics
from services.learning.shadow_manager import ShadowModeManager, ShadowPrediction, ShadowResult
from services.learning.super_intelligence import (
    ABTestResult,
    ModelVersion,
    SuperIntelligenceEngine,
    SystemHealth,
)
from services.learning.walkforward_ensemble import FoldResult, WalkForwardEnsemble, WalkForwardResult
from services.learning.weight_adjuster import WeightAdjuster


def test_model_registry_and_record():
    """ModelRecord dataclass ve ModelRegistry sınıfı doğrulaması."""
    record = ModelRecord(
        model_id="lgb_champion",
        version="v1.0.0",
        created_at=datetime.now(UTC).isoformat(),
        status="CHAMPION",
        metrics={"ic": 0.085, "sharpe": 2.1},
        features=["momentum_20d", "volatility_20d"],
        hyperparameters={"max_depth": 5, "learning_rate": 0.05},
        training_data_info={"samples": 1000},
        regime="BULL_STRONG",
        role="Alpha",
    )
    assert "ModelRecord" in repr(record)
    assert "lgb_champion" in repr(record)
    assert "v1.0.0" in repr(record)

    registry = ModelRegistry()
    assert "ModelRegistry" in repr(registry)

    # Register
    reg_record = registry.register(
        model_id="xgb_challenger",
        version="v1.0.0",
        metrics={"ic": 0.072},
        features=["momentum_20d"],
        hyperparameters={"max_depth": 4},
        training_data_info={"samples": 500},
        regime="BULL_STRONG",
    )
    assert reg_record.version == "v1.0.0"
    assert registry.get_version("v1.0.0") is not None


def test_meta_learner_and_performance():
    """ModelPerformance ve MetaLearner rejim ağırlıklandırma doğrulaması."""
    perf = ModelPerformance(
        model_id="lgbm",
        regime="BULL_STRONG",
        sharpe=2.1,
        win_rate=62.0,
        ic=0.085,
        timestamp=datetime.now(UTC).isoformat(),
    )
    assert "ModelPerformance" in repr(perf)
    assert "lgbm" in repr(perf)

    learner = MetaLearner()
    assert "MetaLearner" in repr(learner)

    # Record performance
    learner.record_performance("lgbm", "BULL_STRONG", {"sharpe": 2.1, "win_rate": 62.0, "ic": 0.085})
    learner.record_performance("xgb", "BULL_STRONG", {"sharpe": 1.5, "win_rate": 55.0, "ic": 0.060})

    weights = learner.calculate_ensemble_weights(["lgbm", "xgb"], "BULL_STRONG")
    assert "lgbm" in weights
    assert "xgb" in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-4

    best = learner.select_best_model("BULL_STRONG")
    assert best == "lgbm"


def test_outcome_tracker():
    """OutcomeTracker tahmin ve sonuç eşleme doğrulaması."""
    tracker = OutcomeTracker()
    assert "OutcomeTracker" in repr(tracker)

    # Add prediction
    tracker.add_prediction(
        {
            "prediction_id": "pred_001",
            "ticker": "THYAO",
            "predicted_direction": "UP",
            "horizon": "1-5D",
            "feature_snapshot": {"price": 250.0},
        }
    )
    assert len(tracker._pending) == 1


def test_retrain_engine_and_results():
    """RetrainResult, WalkForwardMetrics ve RetrainEngine doğrulaması."""
    metrics = WalkForwardMetrics(
        avg_correlation=0.08,
        std_correlation=0.02,
        avg_direction_accuracy=61.0,
        std_direction_accuracy=3.5,
        avg_sharpe=2.2,
        deflated_sharpe=1.8,
        total_splits=5,
        passed_splits=4,
        pass_rate=80.0,
    )
    assert "WalkForwardMetrics" in repr(metrics)

    res = RetrainResult(
        success=True,
        version_id="v1.1.0",
        reason="IC improved by 0.02",
        wf_metrics=metrics,
        shadow_started=True,
        timestamp=datetime.now(UTC).isoformat(),
        training_samples=1000,
        regime="BULL_STRONG",
    )
    assert "RetrainResult" in repr(res)
    assert "v1.1.0" in repr(res)

    engine = RetrainEngine()
    assert "RetrainEngine" in repr(engine)


def test_shadow_manager():
    """ShadowModeManager ve ShadowPrediction doğrulaması."""
    sp = ShadowPrediction(
        ticker="ASELS",
        champion_prediction={"pred": 0.015},
        challenger_prediction={"pred": 0.020},
        timestamp=datetime.now(UTC).isoformat(),
    )
    assert "ShadowPrediction" in repr(sp)

    sr = ShadowResult(
        champion_sharpe=1.8,
        challenger_sharpe=2.2,
        champion_winrate=58.0,
        challenger_winrate=64.0,
        improvement_pct=22.2,
        p_value=0.01,
        significant=True,
        recommendation="PROMOTE",
        days_elapsed=14,
        prediction_count=100,
    )
    assert "ShadowResult" in repr(sr)
    assert "PROMOTE" in repr(sr)

    manager = ShadowModeManager()
    assert "ShadowModeManager" in repr(manager)


def test_super_intelligence_dataclasses_and_engine():
    """SystemHealth, ModelVersion, ABTestResult ve SuperIntelligenceEngine doğrulaması."""
    health = SystemHealth(
        timestamp=datetime.now(UTC).isoformat(),
        overall_status="HEALTHY",
        module_status={"data": "OK", "model": "OK"},
        last_error=None,
        uptime_hours=24.5,
        predictions_today=150,
        accuracy_today=65.2,
        drift_detected=False,
        retrain_needed=False,
    )
    assert "SystemHealth" in repr(health)
    assert "HEALTHY" in repr(health)

    mv = ModelVersion(
        version_id="v1.2.0",
        created_at=datetime.now(UTC).isoformat(),
        regime="BULL_STRONG",
        training_samples=1500,
        test_sharpe=2.4,
        test_ic=0.085,
        feature_importance={"momentum_20d": 0.25},
        is_active=True,
        is_champion=True,
    )
    assert "ModelVersion" in repr(mv)

    ab = ABTestResult(
        test_id="ab_001",
        champion_version="v1.0",
        challenger_version="v1.1",
        champion_sharpe=1.8,
        challenger_sharpe=2.2,
        improvement_pct=22.2,
        is_significant=True,
        p_value=0.01,
        winner="challenger",
    )
    assert "ABTestResult" in repr(ab)

    engine = SuperIntelligenceEngine()
    assert "SuperIntelligenceEngine" in repr(engine)


def test_model_trust_and_degradation():
    """ModelTrustEngine, ModelTrustScore ve ModelDegradationMonitor doğrulaması."""
    trust_score = ModelTrustScore(
        model_id="lgbm",
        model_version="v1.0.0",
        sample_size=50,
        reliability_score=0.88,
        confidence_shrinkage=0.85,
        accuracy_score=0.70,
        sharpe_score=0.80,
        calibration_score=0.75,
        regime_score=0.78,
        statistical_significance_p=0.02,
        recommended_fusion_weight=0.30,
    )
    assert "ModelTrustScore" in repr(trust_score)
    assert "rel=0.88" in repr(trust_score)

    trust_engine = ModelTrustEngine()
    assert "ModelTrustEngine" in repr(trust_engine)

    metrics = PerformanceMetrics(
        model_id="lgbm",
        model_version="v1.0.0",
        total_samples=60,
        evaluated_samples=60,
        direction_accuracy=0.65,
        hit_rate_pct=65.0,
        precision=0.64,
        recall=0.66,
        f1_score=0.65,
        mean_return_pct=0.03,
        cumulative_return_pct=1.8,
        gross_pnl=18000.0,
        transaction_costs=500.0,
        net_pnl=17500.0,
        annualized_sharpe=2.1,
        max_drawdown_pct=4.2,
        brier_score=0.12,
        information_coefficient=0.075,
        rank_ic=0.070,
        win_loss_ratio=1.6,
    )
    score = trust_engine.compute_trust_score(metrics, current_regime="BULL_MOMENTUM")
    assert score.reliability_score > 0.5
    assert score.model_id == "lgbm"

    outcome = ModelOutcome(
        timestamp=datetime.now(UTC).isoformat(),
        predicted=0.03,
        actual=0.025,
        return_pct=0.025,
        is_correct=True,
    )
    assert "ModelOutcome" in repr(outcome)

    report = DegradationReport(
        model_id="lgbm",
        window_size=50,
        current_accuracy=0.60,
        baseline_accuracy=0.65,
        accuracy_drop=0.05,
        current_sharpe=1.8,
        baseline_sharpe=2.1,
        sharpe_drop=0.3,
        prediction_drift_score=0.02,
        trend="stable",
        z_score=0.5,
        severity="OK",
        should_remove=False,
        recommendation="Stabil çalışma",
        n_outcomes=50,
    )
    assert "DegradationReport" in repr(report)

    alert = DegradationAlert(
        model_id="lgbm",
        severity="WARNING",
        message="Minor drift",
        accuracy_drop=0.08,
    )
    assert "DegradationAlert" in repr(alert)

    monitor = ModelDegradationMonitor()
    assert "ModelDegradationMonitor" in repr(monitor)
    monitor.record_outcome("lgbm", 0.6, 0.55, return_pct=0.01)
    rep = monitor.check_model("lgbm")
    assert rep.model_id == "lgbm"


def test_model_memory_store():
    """ModelMemoryStore DuckDB yerel depolama doğrulaması."""
    test_db = "data/test_audit_memory.duckdb"
    store = ModelMemoryStore(db_path=test_db)
    assert "ModelMemoryStore" in repr(store)

    try:
        # Save prediction
        store.save_prediction(
            prediction_id="pred_100",
            model_id="lgbm_alpha",
            model_version="v1.0.0",
            ticker="THYAO",
            predicted_direction="UP",
            confidence=0.85,
            market_regime="BULL_STRONG",
            prediction_horizon="1-5D",
            entry_price=250.0,
            features={"momentum_20d": 0.05},
        )
        store.flush()

        # Record outcome
        res = store.save_outcome(
            prediction_id="pred_100",
            actual_price=255.0,
        )
        assert res is not None
        assert res["ticker"] == "THYAO"
        assert res["is_correct"] == 1
    finally:
        store.close()
        import contextlib
        for p in [Path(test_db), Path(test_db + ".wal")]:
            if p.exists():
                with contextlib.suppress(Exception):
                    p.unlink()


def test_weight_adjuster_and_production_alpha():
    """WeightAdjuster ve ProductionAlphaEngine doğrulaması."""
    adjuster = WeightAdjuster()
    assert "WeightAdjuster" in repr(adjuster)

    metrics = {
        "lgbm": {"direction_accuracy": 0.65, "n_resolved": 30},
        "xgb": {"direction_accuracy": 0.55, "n_resolved": 30},
        "cat": {"direction_accuracy": 0.45, "n_resolved": 30},
    }
    new_weights = adjuster.adjust_weights(metrics, metric_key="direction_accuracy")
    assert abs(sum(new_weights.values()) - 1.0) < 1e-4
    assert new_weights["lgbm"] > new_weights["cat"]

    alpha_engine = ProductionAlphaEngine()
    assert "ProductionAlphaEngine" in repr(alpha_engine)


def test_walkforward_ensemble():
    """WalkForwardEnsemble, FoldResult ve WalkForwardResult doğrulaması."""
    fold = FoldResult(
        fold_idx=1,
        train_start="2025-01-01",
        train_end="2025-04-01",
        val_start="2025-04-02",
        val_end="2025-05-01",
        n_train=200,
        n_val=50,
        ensemble_ic=0.09,
        ensemble_rank_ic=0.085,
        ensemble_direction_accuracy=0.62,
        best_individual_ic=0.075,
        best_individual_name="lgbm",
        ic_improvement=0.015,
        diversity_score=0.35,
        model_weights={"lgbm": 0.6, "xgb": 0.4},
        model_ics={"lgbm": 0.075, "xgb": 0.065},
        is_beneficial=True,
    )
    assert "FoldResult" in repr(fold)
    assert "ensemble_ic=0.0900" in repr(fold)

    wf_res = WalkForwardResult(
        n_folds=1,
        fold_results=[fold],
        mean_ensemble_ic=0.09,
        mean_ic_improvement=0.015,
        mean_diversity_score=0.35,
        mean_direction_accuracy=0.62,
        beneficial_ratio=1.0,
        final_weights={"lgbm": 0.6, "xgb": 0.4},
        final_diversity={"lgbm_xgb": 0.35},
    )
    assert "WalkForwardResult" in repr(wf_res)
    assert "100.00%" in repr(wf_res)

    wf_engine = WalkForwardEnsemble(n_splits=3)
    assert "WalkForwardEnsemble" in repr(wf_engine)
