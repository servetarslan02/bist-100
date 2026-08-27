"""ALPHA BIST — High-Performance Large Scale Model Training & Evaluation Simulator

1,000+ Historical Predictions per Model (Total 6,000+ transactions) across 5 Market Regimes:
- BULL_TREND (Güçlü Boğa)
- BEAR_MARKET (Ayı & Düzeltme)
- SIDEWAYS_RANGE (Yatay & Testere)
- HIGH_VOLATILITY (Yüksek Volatilite / Şok)
- LOW_VOLATILITY (Düşük Volatilite / Sıkışma)
"""

from datetime import UTC, datetime, timedelta

import numpy as np

from services.learning.learning_pipeline import LearningPipeline
from services.learning.model_memory_store import ModelMemoryStore


def run_large_scale_simulation():
    store = ModelMemoryStore()
    pipeline = LearningPipeline(memory_store=store)

    regimes = [
        {"code": "BULL_TREND", "weight": 0.30, "drift": 1.2, "vol": 1.5},
        {"code": "BEAR_MARKET", "weight": 0.20, "drift": -1.4, "vol": 2.2},
        {"code": "SIDEWAYS_RANGE", "weight": 0.25, "drift": 0.1, "vol": 1.0},
        {"code": "HIGH_VOLATILITY", "weight": 0.15, "drift": -0.5, "vol": 3.5},
        {"code": "LOW_VOLATILITY", "weight": 0.10, "drift": 0.4, "vol": 0.7},
    ]

    models_profile = {
        "LightGBM_LambdaRank": {
            "version": "v3.2",
            "base_acc": 0.71,
            "regime_bonus": {"BULL_TREND": 0.08, "SIDEWAYS_RANGE": 0.05, "LOW_VOLATILITY": 0.06, "BEAR_MARKET": 0.02, "HIGH_VOLATILITY": -0.04},
            "mean_win_pct": 3.4,
            "mean_loss_pct": 1.6,
        },
        "Cross_Sectional_Momentum": {
            "version": "v2.0",
            "base_acc": 0.67,
            "regime_bonus": {"BULL_TREND": 0.12, "SIDEWAYS_RANGE": -0.08, "LOW_VOLATILITY": 0.04, "BEAR_MARKET": -0.06, "HIGH_VOLATILITY": -0.05},
            "mean_win_pct": 3.8,
            "mean_loss_pct": 2.1,
        },
        "SPEC_Anomaly_Detector": {
            "version": "v1.2",
            "base_acc": 0.64,
            "regime_bonus": {"BULL_TREND": 0.06, "HIGH_VOLATILITY": 0.14, "LOW_VOLATILITY": 0.08, "SIDEWAYS_RANGE": -0.04, "BEAR_MARKET": -0.08},
            "mean_win_pct": 6.8,
            "mean_loss_pct": 2.9,
        },
        "KAP_NLP_Sentiment": {
            "version": "v3.0",
            "base_acc": 0.63,
            "regime_bonus": {"BULL_TREND": 0.06, "HIGH_VOLATILITY": 0.08, "SIDEWAYS_RANGE": 0.02, "BEAR_MARKET": -0.02, "LOW_VOLATILITY": 0.00},
            "mean_win_pct": 4.1,
            "mean_loss_pct": 2.2,
        },
        "CatBoost_Classifier": {
            "version": "v2.1",
            "base_acc": 0.62,
            "regime_bonus": {"BULL_TREND": 0.03, "BEAR_MARKET": 0.04, "SIDEWAYS_RANGE": 0.04, "LOW_VOLATILITY": 0.03, "HIGH_VOLATILITY": -0.02},
            "mean_win_pct": 2.8,
            "mean_loss_pct": 1.7,
        },
        "LSTM_Sequential": {
            "version": "v1.8",
            "base_acc": 0.58,
            "regime_bonus": {"BULL_TREND": 0.05, "LOW_VOLATILITY": 0.05, "SIDEWAYS_RANGE": -0.06, "BEAR_MARKET": -0.05, "HIGH_VOLATILITY": -0.09},
            "mean_win_pct": 3.1,
            "mean_loss_pct": 2.4,
        },
    }

    tickers = [
        "THYAO", "ASELS", "GARAN", "KCHOL", "TUPRS", "PGSUS", "FROTO", "BIMAS",
        "AKBNK", "SISE", "ENJSA", "ASTOR", "POLTK", "SDTTR", "KONYA", "REEDR",
        "FORTE", "ALFAS", "SAHOL", "CCOLA", "TCELL", "MGROS"
    ]

    total_per_model = 1000
    all_batch_records = []
    np.random.seed(42)
    start_date = datetime.now(UTC) - timedelta(days=500)

    print(f"Generating {total_per_model} walk-forward samples per model ({total_per_model * 6} total records)...")
    for m_id, prof in models_profile.items():
        for i in range(total_per_model):
            reg_probs = [r["weight"] for r in regimes]
            reg_idx = np.random.choice(len(regimes), p=reg_probs)
            selected_reg = regimes[reg_idx]
            reg_code = selected_reg["code"]

            reg_bonus = prof["regime_bonus"].get(reg_code, 0.0)
            true_prob = max(0.40, min(0.85, prof["base_acc"] + reg_bonus + np.random.normal(0, 0.02)))

            ticker = tickers[i % len(tickers)]
            pred_dir = "UP" if (selected_reg["drift"] > 0 or np.random.rand() > 0.45) else "DOWN"
            is_win = (np.random.rand() < true_prob)

            if is_win:
                ret_pct = abs(np.random.normal(prof["mean_win_pct"], selected_reg["vol"]))
            else:
                ret_pct = -abs(np.random.normal(prof["mean_loss_pct"], selected_reg["vol"]))

            entry_p = 50.0 + (i % 200) * 2.5
            act_p = entry_p * (1.0 + ret_pct / 100.0)
            eval_time = start_date + timedelta(hours=i * 6)

            all_batch_records.append({
                "prediction_id": f"PRED_{m_id}_{ticker}_{i:04d}",
                "model_id": m_id,
                "model_version": prof["version"],
                "ticker": ticker,
                "timestamp": eval_time.isoformat(),
                "predicted_direction": pred_dir,
                "confidence": 0.55 + np.random.rand() * 0.35,
                "market_regime": reg_code,
                "prediction_horizon": "1-5D" if i % 2 == 0 else "1-4W",
                "entry_price": entry_p,
                "actual_price": act_p,
                "evaluated_at": eval_time.isoformat(),
            })

    print("Saving batch records atomically into DuckDB Model Memory Store...")
    store.save_batch_records(all_batch_records)

    print("Running Master Learning Cycle over 6,000+ historical evaluations...")
    res = pipeline.run_learning_cycle(current_regime="BULL_TREND")
    print("✅ Long-horizon evaluation successfully completed!")
    print("\n" + res["markdown_report"])


if __name__ == "__main__":
    run_large_scale_simulation()
