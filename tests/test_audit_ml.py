"""
ALPHA BIST — ML Service Comprehensive Audit Tests
Verifies core machine learning modules:
- MLModelConfig & LightGBMTrainer
- StackingConfig, StackingEnsemble & EnsembleModel
- AdjustedMSELoss
- ModelCalibration & CalibrationResult
- FeatureDriftDetector & DriftReport
- ModelRegistry, ModelEntry, ChampionChallenger & ABTestResult
- OpportunityScore, RankingResult, RankingModel & LearningToRankModel
- CrossSectionalFeatures & TemporalFeatures
- TrainingDatasetValidator & WalkForwardValidation
"""

import numpy as np

from services.ml import (
    ABTestResult,
    AdjustedMSELoss,
    CalibrationResult,
    ChampionChallenger,
    DriftReport,
    EnsembleModel,
    FeatureDriftDetector,
    LearningToRankModel,
    LightGBMTrainer,
    MLModelConfig,
    ModelCalibration,
    ModelEntry,
    ModelRegistry,
    OpportunityScore,
    RankingModel,
    RankingResult,
    StackingConfig,
    StackingEnsemble,
    TrainingDatasetValidator,
    WalkForwardValidation,
)
from services.ml.cross_sectional import (
    CrossSectionalFeatures,
    TemporalFeatures,
    cross_sectional_features,
    temporal_features,
)


def test_model_configs_and_representations():
    """Test model configuration dataclasses and representations."""
    cfg = MLModelConfig(
        objective="regression",
        learning_rate=0.03,
        num_boost_round=100,
        num_leaves=31,
    )
    assert "MLModelConfig" in repr(cfg)
    assert cfg.objective == "regression"
    assert cfg.learning_rate == 0.03

    stack_cfg = StackingConfig(
        meta_learner_type="ridge",
        cv_folds=3,
    )
    assert "StackingConfig" in repr(stack_cfg)
    assert stack_cfg.cv_folds == 3

    # Ensembles
    ensemble = EnsembleModel()
    assert "EnsembleModel" in repr(ensemble)

    stacking = StackingEnsemble(config=stack_cfg, duckdb_path=":memory:")
    assert "StackingEnsemble" in repr(stacking)


def test_lightgbm_trainer():
    """Test LightGBMTrainer initialization and representation."""
    cfg = MLModelConfig(objective="regression", num_boost_round=10)
    trainer = LightGBMTrainer(config=cfg)
    assert "LightGBMTrainer" in repr(trainer)
    assert trainer._config.num_boost_round == 10


def test_adjusted_mse_loss():
    """Test AdjustedMSELoss for asymmetry penalty."""
    loss_fn = AdjustedMSELoss(wrong_direction_penalty=2.0)
    assert "AdjustedMSELoss" in repr(loss_fn)
    assert loss_fn.penalty == 2.0

    y_true = np.array([1.0, 2.0])
    y_pred_correct = np.array([0.5, 1.5])
    y_pred_wrong = np.array([-0.5, -1.5])

    calc_correct = loss_fn.calculate(predictions=y_pred_correct, actuals=y_true)
    calc_wrong = loss_fn.calculate(predictions=y_pred_wrong, actuals=y_true)

    assert "adjusted_mse" in calc_correct
    assert "adjusted_mse" in calc_wrong
    assert calc_wrong["adjusted_mse"] > calc_correct["adjusted_mse"]


def test_calibration_result_and_model():
    """Test ModelCalibration and CalibrationResult representations."""
    cal_res = CalibrationResult(
        is_calibrated=True,
        brier_score=0.18,
        calibration_curve=[{"bin": 0.5, "prob": 0.5}],
        miscalibration=0.02,
        overconfident=False,
        recommendation="GOOD",
        expected_calibration_error=0.05,
    )
    assert "CalibrationResult" in repr(cal_res)
    assert cal_res.is_calibrated is True

    calibrator = ModelCalibration(n_bins=10)
    assert "ModelCalibration" in repr(calibrator)


def test_feature_drift_detector():
    """Test FeatureDriftDetector and DriftReport."""
    detector = FeatureDriftDetector(psi_threshold=0.20, importance_change_threshold=0.30)
    assert "FeatureDriftDetector" in repr(detector)

    report = DriftReport(
        feature_name="momentum_20d",
        psi=0.02,
        drift_detected=False,
        importance_trend="stable",
        current_importance=0.12,
        historical_importance=0.11,
        alert=False,
    )
    assert "DriftReport" in repr(report)
    assert report.drift_detected is False


def test_model_registry_and_champion_challenger():
    """Test ModelRegistry, ModelEntry, and ChampionChallenger."""
    entry = ModelEntry(
        model_id="lgb_champion_v1",
        version="1.0.0",
        model_type="lightgbm",
        status="CHAMPION",
        metrics={"ic": 0.08, "sharpe": 1.6},
    )
    assert "ModelEntry" in repr(entry)
    assert entry.status == "CHAMPION"

    registry = ModelRegistry(registry_path="models", duckdb_path=":memory:")
    assert "ModelRegistry" in repr(registry)

    cc = ChampionChallenger(significance_level=0.05)
    assert "ChampionChallenger" in repr(cc)

    ab_res = ABTestResult(
        champion_metric=0.05,
        challenger_metric=0.08,
        p_value=0.02,
        significant=True,
        winner="challenger",
        n_samples_champion=100,
        n_samples_challenger=100,
        confidence_level=0.95,
    )
    assert "ABTestResult" in repr(ab_res)
    assert ab_res.winner == "challenger"


def test_ranking_model_and_scores():
    """Test OpportunityScore, RankingResult, and RankingModel."""
    opp = OpportunityScore(
        ticker="THYAO",
        score=88.5,
        rank=1,
        direction="UP",
        confidence=0.85,
        regime="BULL",
        signals={"rsi": 55},
        features={"momentum": 0.1},
        model_contribution={"lgb": 0.8},
    )
    assert "OpportunityScore" in repr(opp)
    assert opp.ticker == "THYAO"

    rank_res = RankingResult(
        scores=[opp],
        top_k={5: [opp]},
        feature_importance={"momentum": 0.4},
        regime_weights={"BULL": 1.0},
        ensemble_weights={"lgb": 1.0},
    )
    assert "RankingResult" in repr(rank_res)
    assert len(rank_res.scores) == 1

    rm = RankingModel()
    assert "RankingModel" in repr(rm)

    ltr = LearningToRankModel()
    assert "LearningToRankModel" in repr(ltr)


def test_cross_sectional_and_temporal_features():
    """Test CrossSectionalFeatures and TemporalFeatures engines."""
    cs = CrossSectionalFeatures()
    assert "CrossSectionalFeatures" in repr(cs)
    assert cross_sectional_features is not None

    tf = TemporalFeatures()
    assert "TemporalFeatures" in repr(tf)
    assert temporal_features is not None

    # Test sector relative calculation
    ticker_features = {"momentum_20d": 15.0, "pe_ratio": 8.5}
    sector_tickers = ["THYAO", "PGSUS"]
    all_features = {
        "THYAO": {"momentum_20d": 15.0, "pe_ratio": 8.5},
        "PGSUS": {"momentum_20d": 10.0, "pe_ratio": 9.0},
    }
    sec_res = cs.calculate_sector_relative("THYAO", ticker_features, sector_tickers, all_features)
    assert "momentum_20d_sector_ratio" in sec_res
    assert sec_res["momentum_20d_sector_ratio"] > 1.0

    # Test temporal trend calculation
    prices = [100.0 + i * 1.5 for i in range(50)]
    trend_res = tf.calculate_trend_features(prices)
    assert "trend_slope" in trend_res
    assert trend_res["trend_slope"] > 0
    assert "trend_r2" in trend_res
    assert trend_res["trend_r2"] > 0.95


def test_training_validator_and_walk_forward():
    """Test TrainingDatasetValidator and WalkForwardValidation."""
    validator = TrainingDatasetValidator()
    assert "TrainingDatasetValidator" in repr(validator)

    wfv = WalkForwardValidation(train_size=252, test_size=21, duckdb_path=":memory:")
    assert "WalkForwardValidation" in repr(wfv)
