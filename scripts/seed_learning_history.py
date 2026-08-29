import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""Seed initial realistic prediction and outcome history for ALPHA BIST learning pipeline."""

import numpy as np

from services.learning.learning_pipeline import LearningPipeline
from services.learning.model_memory_store import ModelMemoryStore


def seed_history() -> Any:
    """Otomatik eklendi."""
    store = ModelMemoryStore()
    pipeline = LearningPipeline(memory_store=store)

    np.random.seed(42)
    models_config = [
        {"id": "LightGBM_LambdaRank", "acc": 0.74, "ret_mean": 3.8, "sharpe_target": 2.4, "brier": 0.12},
        {"id": "SPEC_Anomaly_Detector", "acc": 0.71, "ret_mean": 6.5, "sharpe_target": 2.1, "brier": 0.14},
        {"id": "CatBoost_Classifier", "acc": 0.68, "ret_mean": 2.9, "sharpe_target": 1.9, "brier": 0.15},
        {"id": "Cross_Sectional_Momentum", "acc": 0.64, "ret_mean": 2.2, "sharpe_target": 1.6, "brier": 0.18},
        {"id": "KAP_NLP_Sentiment", "acc": 0.62, "ret_mean": 2.6, "sharpe_target": 1.4, "brier": 0.19},
        {"id": "LSTM_Sequential", "acc": 0.58, "ret_mean": 1.5, "sharpe_target": 1.1, "brier": 0.22},
    ]

    tickers = [
        "THYAO",
        "ASELS",
        "GARAN",
        "KCHOL",
        "TUPRS",
        "POLTK",
        "SDTTR",
        "KONYA",
        "REEDR",
        "FORTE",
        "ALFAS",
        "BIMAS",
    ]
    regimes = ["BULL_MOMENTUM", "BEAR_CORRECTION", "RANGE_BOUND", "HIGH_VOLATILITY"]

    logger.info("Populating initial 40 historical evaluations per model...")
    for m in models_config:
        m_id = m["id"]
        true_acc = m["acc"]
        for i in range(40):
            ticker = tickers[i % len(tickers)]
            regime = regimes[i % len(regimes)]
            pred_dir = "UP" if np.random.rand() > 0.35 else "DOWN"
            is_correct = np.random.rand() < true_acc
            act_dir = pred_dir if is_correct else ("DOWN" if pred_dir == "UP" else "UP")

            entry_p = 100.0 + (i * 3.5)
            ret_mag = np.random.normal(m["ret_mean"], 1.5)
            act_ret = ret_mag if act_dir == "UP" else -ret_mag
            act_p = entry_p * (1.0 + act_ret / 100.0)

            p_id = pipeline.record_model_prediction(
                model_id=m_id,
                ticker=ticker,
                predicted_direction=pred_dir,
                confidence=0.60 + np.random.rand() * 0.28,
                entry_price=entry_p,
                market_regime=regime,
                prediction_horizon="1-5D" if i % 2 == 0 else "1-4W",
            )
            pipeline.record_market_outcome(prediction_id=p_id, actual_price=act_p)

    # Run learning cycle to compute live trust and adaptive weights
    res = pipeline.run_learning_cycle(current_regime="BULL_MOMENTUM")
    logger.info("Initial learning cycle successfully executed!")
    logger.info(f"Models Evaluated: {res['models_evaluated']}")
    logger.info("Updated Adaptive Fusion Weights:")
    for k, v in res["fusion_weights"].items():
        logger.info(f"  - {k}: %{v * 100:.1f}")


if __name__ == "__main__":
    seed_history()
