from typing import Any
"""ALPHA BIST — Comprehensive Model Training & Performance Learning Test Suite

Test edilen alanlar:
1. Prediction -> Outcome Eşleşmesi ve Net PnL Hesaplaması
2. BIST İşlem Maliyetleri (Roundtrip %0.074) ve Metrik Doğruluğu
3. Dinamik Güvenilirlik (Trust) Skoru ve Shrinkage Davranışı
4. Adaptif Signal Fusion Ağırlık Dağılımı ve Sınır Güvenliği (%5 - %35)
5. Zero Look-Ahead Bias & Zamansal İzolasyon
6. Uçtan Uca Master Learning Döngüsü (Train -> Predict -> Outcome -> Trust -> Fusion)
"""

import os
import shutil
import tempfile

import numpy as np
import pytest

from services.intelligence.signal_fusion import SignalFusionEngine
from services.learning.learning_pipeline import LearningPipeline
from services.learning.model_memory_store import ModelMemoryStore
from services.learning.model_performance_engine import ModelPerformanceEngine, PerformanceMetrics
from services.learning.model_trust_engine import ModelTrustEngine, ModelTrustScore


@pytest.fixture
def temp_db() -> Any:
    """Otomatik eklendi."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_memory.db")
    yield db_path
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_prediction_to_outcome_matching(temp_db) -> Any:
    """Prediction -> Outcome eşleşmesi ve net PnL hesaplaması."""
    store = ModelMemoryStore(db_path=temp_db)

    # 1. Tahmin kaydet
    pred_id = "PRED_TEST_THYAO_001"
    store.save_prediction(
        prediction_id=pred_id,
        model_id="LightGBM_LambdaRank",
        model_version="v3.2",
        ticker="THYAO",
        predicted_direction="UP",
        confidence=0.75,
        market_regime="BULL_MOMENTUM",
        prediction_horizon="1-5D",
        entry_price=300.0,
    )

    # 2. Gerçekleşen fiyatı bağla (300 -> 315, +%5 artış)
    outcome_res = store.save_outcome(prediction_id=pred_id, actual_price=315.0)
    assert outcome_res is not None
    assert outcome_res["is_correct"] == 1
    assert outcome_res["actual_return"] == pytest.approx(5.0, abs=0.01)

    # Net PnL = 10000 * (%5 - %0.074 maliyet) = 500 - 7.4 = 492.6 TL
    assert outcome_res["net_pnl"] == pytest.approx(492.6, abs=0.5)


def test_performance_metrics_and_transaction_costs() -> Any:
    """BIST işlem maliyetli metrikler, Sharpe, Brier ve Rank IC testi."""
    mock_data = [
        {
            "predicted_direction": "UP",
            "actual_direction": "UP",
            "confidence": 0.80,
            "actual_return": 4.0,
            "position_value": 10000.0,
            "market_regime": "BULL",
        },
        {
            "predicted_direction": "UP",
            "actual_direction": "UP",
            "confidence": 0.70,
            "actual_return": 3.0,
            "position_value": 10000.0,
            "market_regime": "BULL",
        },
        {
            "predicted_direction": "DOWN",
            "actual_direction": "DOWN",
            "confidence": 0.65,
            "actual_return": -2.5,
            "position_value": 10000.0,
            "market_regime": "BEAR",
        },
        {
            "predicted_direction": "UP",
            "actual_direction": "DOWN",
            "confidence": 0.60,
            "actual_return": -1.5,
            "position_value": 10000.0,
            "market_regime": "VOLATILE",
        },
    ]

    metrics = ModelPerformanceEngine.calculate_metrics(
        model_id="CatBoost_Test",
        model_version="v2.1",
        predictions_with_outcomes=mock_data,
        risk_free_rate_annual=0.40,
    )

    # 4 işlemden 3'ü doğru -> %75 accuracy
    assert metrics.direction_accuracy == 0.75
    assert metrics.hit_rate_pct == 75.0
    assert metrics.evaluated_samples == 4
    assert metrics.brier_score < 0.25  # Rastgeleden daha iyi kalibrasyon
    assert metrics.net_pnl > 0.0  # Maliyetler sonrası pozitif kâr
    assert "BULL" in metrics.regime_breakdown


def test_dynamic_trust_score_and_shrinkage() -> Any:
    """Örneklem yetersizliğinde prior shrinkage ve yüksek örneklemde güvenilirlik artışı."""
    engine = ModelTrustEngine(min_samples_threshold=30, prior_trust=0.50)

    # Düşük örneklemli model (N=3) -> Shrinkage prior'a yaklaştırır
    low_sample_metrics = PerformanceMetrics(
        model_id="LowSampleModel",
        model_version="v1",
        total_samples=3,
        evaluated_samples=3,
        direction_accuracy=1.0,
        hit_rate_pct=100.0,
        precision=1.0,
        recall=1.0,
        f1_score=1.0,
        mean_return_pct=5.0,
        cumulative_return_pct=15.0,
        gross_pnl=1500.0,
        transaction_costs=22.2,
        net_pnl=1477.8,
        annualized_sharpe=3.0,
        max_drawdown_pct=0.0,
        brier_score=0.05,
        information_coefficient=0.8,
        rank_ic=0.8,
        win_loss_ratio=10.0,
    )
    low_trust = engine.compute_trust_score(low_sample_metrics)
    assert low_trust.confidence_shrinkage < 0.20  # Örneklem az olduğu için güven cezası
    assert low_trust.reliability_score < 0.70  # 3 işlemle %100 olsa bile abartılı güven verilmez

    # Yüksek örneklemli başarılı model (N=150)
    high_sample_metrics = PerformanceMetrics(
        model_id="HighSampleModel",
        model_version="v1",
        total_samples=150,
        evaluated_samples=150,
        direction_accuracy=0.72,
        hit_rate_pct=72.0,
        precision=0.74,
        recall=0.70,
        f1_score=0.72,
        mean_return_pct=2.5,
        cumulative_return_pct=180.0,
        gross_pnl=18000.0,
        transaction_costs=1110.0,
        net_pnl=16890.0,
        annualized_sharpe=2.4,
        max_drawdown_pct=4.2,
        brier_score=0.12,
        information_coefficient=0.25,
        rank_ic=0.22,
        win_loss_ratio=2.1,
    )
    high_trust = engine.compute_trust_score(high_sample_metrics)
    assert high_trust.confidence_shrinkage > 0.95  # Yüksek istatistiksel güven
    assert high_trust.reliability_score > 0.70  # Gerçek yüksek güven skoru


def test_signal_fusion_adaptive_weights_and_bounds() -> Any:
    """Signal fusion adaptif ağırlık dağılımı ve min/max sınırları (%5 - %35)."""
    fusion = SignalFusionEngine()
    trust_engine = ModelTrustEngine(weight_min=0.05, weight_max=0.35)

    scores = [
        ModelTrustScore("model_A", "v1", 100, 0.95, 0.95, 0.9, 0.9, 0.9, 0.9, 0.01, 0.0),
        ModelTrustScore("model_B", "v1", 100, 0.60, 0.95, 0.6, 0.6, 0.6, 0.6, 0.05, 0.0),
        ModelTrustScore("model_C", "v1", 100, 0.50, 0.95, 0.5, 0.5, 0.5, 0.5, 0.10, 0.0),
        ModelTrustScore("model_D", "v1", 100, 0.40, 0.95, 0.4, 0.4, 0.4, 0.4, 0.20, 0.0),
        ModelTrustScore("model_E", "v1", 100, 0.10, 0.95, 0.1, 0.1, 0.1, 0.1, 0.50, 0.0),
    ]

    weights = trust_engine.calculate_ensemble_weights(scores)

    # Toplam 1.0 olmalı
    assert sum(weights.values()) == pytest.approx(1.0, abs=0.01)

    # En iyi model bile %35 tavanını aşmamalı
    assert weights["model_A"] <= 0.35 + 1e-4
    # En kötü model bile %5 tabanının altına inmemeli
    assert weights["model_E"] >= 0.05 - 1e-4

    # Fusion motoruna uygula
    fusion.set_adaptive_weights(weights)
    active_w = fusion.get_current_weights("RANGE")
    assert sum(active_w.values()) == pytest.approx(1.0, abs=0.01)


def test_full_learning_pipeline_end_to_end(temp_db) -> Any:
    """Uçtan uca döngü: Predict -> Outcome -> Performance -> Trust -> Fusion -> Report."""
    store = ModelMemoryStore(db_path=temp_db)
    pipeline = LearningPipeline(memory_store=store)

    # 1. 6 model için 30'ar adet simüle edilmiş tahmin ve sonuç oluştur
    np.random.seed(42)
    models = [
        "LightGBM_LambdaRank",
        "CatBoost_Classifier",
        "SPEC_Anomaly_Detector",
        "LSTM_Sequential",
        "Cross_Sectional_Momentum",
        "KAP_NLP_Sentiment",
    ]

    for i in range(25):
        for m_id in models:
            # Her modelin kendine has doğruluk olasılığı (LightGBM %75, LSTM %55)
            true_acc = 0.75 if "LightGBM" in m_id or "SPEC" in m_id else 0.58
            pred_dir = "UP" if np.random.rand() > 0.4 else "DOWN"
            is_win = np.random.rand() < true_acc
            act_dir = pred_dir if is_win else ("DOWN" if pred_dir == "UP" else "UP")

            entry_p = 100.0 + np.random.randn() * 10.0
            act_ret = (np.random.uniform(1.0, 5.0)) if act_dir == "UP" else (-np.random.uniform(1.0, 5.0))
            act_price = entry_p * (1.0 + act_ret / 100.0)

            p_id = pipeline.record_model_prediction(
                model_id=m_id,
                ticker="THYAO" if i % 2 == 0 else "ASELS",
                predicted_direction=pred_dir,
                confidence=0.60 + np.random.rand() * 0.30,
                entry_price=entry_p,
                market_regime="BULL_MOMENTUM" if i % 3 != 0 else "BEAR_CORRECTION",
            )
            pipeline.record_market_outcome(prediction_id=p_id, actual_price=act_price)

    # 2. Öğrenme döngüsünü tetikle
    cycle_res = pipeline.run_learning_cycle(current_regime="BULL_MOMENTUM")
    assert cycle_res["success"] is True
    assert cycle_res["models_evaluated"] == 6
    assert len(cycle_res["fusion_weights"]) == 6

    # 3. Rapor üretimini kontrol et
    report_md = cycle_res["markdown_report"]
    assert "# 📊 ALPHA BIST — Otonom Model Öğrenme ve Performans Raporu" in report_md
    assert "LightGBM_LambdaRank" in report_md
    assert "SPEC_Anomaly_Detector" in report_md
