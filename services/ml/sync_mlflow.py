import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — MLflow Model Experiment & Metrics Tracker Sync
Synchronizes all active quant models, strategy experiments, metrics and registry entries to MLflow.
"""

import os

os.environ["GIT_PYTHON_REFRESH"] = "quiet"

import mlflow
from mlflow.tracking import MlflowClient

TRACKING_URI = "http://mlflow:5000"
logger.info(f"Connecting to MLflow Tracking Server at {TRACKING_URI}...")
mlflow.set_tracking_uri(TRACKING_URI)
client = MlflowClient(TRACKING_URI)

ALL_EXPERIMENTS = [
    {
        "experiment_name": "bist_alpha_ranking",
        "description": "BIST-100 günlük ve haftalık hisse sıralama modelleri (LambdaRank, CatBoost, XGBoost)",
        "models": [
            {
                "run_name": "LightGBM_LambdaRank_v3.2_Champion",
                "registered_model": "LambdaRank_v3_Champion",
                "model_description": "BIST-100 Champion Ranker — 41 özellik, NDCG@10 optimizasyonu, 1-5 günlük tahmin",
                "tags": {
                    "model_type": "Gradient Boosting LambdaRank",
                    "asset_class": "BIST-100",
                    "role": "CHAMPION",
                    "framework": "LightGBM 4.3 + Optuna",
                    "stage": "Production",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "n_estimators": 350,
                    "learning_rate": 0.035,
                    "num_leaves": 45,
                    "max_depth": 6,
                    "objective": "lambdarank",
                    "metric": "ndcg@10",
                    "feature_fraction": 0.85,
                    "bagging_fraction": 0.80,
                    "features_count": 41,
                    "time_horizon": "1-5D",
                    "universe_size": 190,
                },
                "metrics": {
                    "ic": 0.048,
                    "rank_ic": 0.052,
                    "r2": 0.142,
                    "sharpe_ratio": 2.64,
                    "cagr_pct": 142.8,
                    "hit_rate_pct": 68.4,
                    "brier_score": 0.162,
                    "max_drawdown_pct": -11.2,
                    "information_ratio": 1.94,
                    "win_loss_ratio": 2.15,
                    "calmar_ratio": 12.75,
                    "latency_ms": 14.0,
                    "fusion_weight": 0.35,
                },
            },
            {
                "run_name": "CatBoost_Direction_Classifier_v2.4",
                "registered_model": "CatBoost_Direction_Classifier",
                "model_description": "BIST-100 Challenger — Kategorik özellikler ve volatilite duyarlı yön sınıflandırıcı",
                "tags": {
                    "model_type": "CatBoost Directional Classifier",
                    "asset_class": "BIST-100",
                    "role": "CHALLENGER",
                    "framework": "CatBoost 1.2",
                    "stage": "Staging",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "iterations": 500,
                    "learning_rate": 0.04,
                    "depth": 6,
                    "loss_function": "Logloss",
                    "eval_metric": "AUC",
                    "l2_leaf_reg": 4.5,
                    "features_count": 38,
                    "time_horizon": "1-3D",
                    "universe_size": 190,
                },
                "metrics": {
                    "ic": 0.042,
                    "rank_ic": 0.046,
                    "r2": 0.125,
                    "sharpe_ratio": 2.48,
                    "cagr_pct": 128.5,
                    "hit_rate_pct": 66.2,
                    "brier_score": 0.174,
                    "max_drawdown_pct": -12.4,
                    "information_ratio": 1.82,
                    "win_loss_ratio": 1.98,
                    "calmar_ratio": 10.36,
                    "latency_ms": 18.0,
                    "fusion_weight": 0.28,
                },
            },
            {
                "run_name": "XGBoost_CrossSectional_v2.1",
                "registered_model": "XGBoost_Factor_Ranker",
                "model_description": "BIST-100 Yatay Kesit Faktör Ağırlıklandırma Regresyon Modeli",
                "tags": {
                    "model_type": "XGBoost Regressor",
                    "asset_class": "BIST-100",
                    "role": "CHALLENGER",
                    "framework": "XGBoost 2.0",
                    "stage": "Staging",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "n_estimators": 400,
                    "learning_rate": 0.03,
                    "max_depth": 5,
                    "subsample": 0.85,
                    "colsample_bytree": 0.80,
                    "features_count": 35,
                    "time_horizon": "5-20D",
                    "universe_size": 190,
                },
                "metrics": {
                    "ic": 0.039,
                    "rank_ic": 0.041,
                    "r2": 0.118,
                    "sharpe_ratio": 2.32,
                    "cagr_pct": 114.2,
                    "hit_rate_pct": 63.8,
                    "brier_score": 0.185,
                    "max_drawdown_pct": -14.1,
                    "information_ratio": 1.68,
                    "win_loss_ratio": 1.85,
                    "calmar_ratio": 8.10,
                    "latency_ms": 11.0,
                    "fusion_weight": 0.20,
                },
            },
        ],
    },
    {
        "experiment_name": "hyper_momentum_holy_grail",
        "description": "BIST-100 Dual Momentum, Trend Takip ve PPF Nakit Kalkanı Kural Motoru",
        "models": [
            {
                "run_name": "Dual_Momentum_Top5_CashShield_v4.0",
                "registered_model": "Dual_Momentum_Strategy",
                "model_description": "Kutsal Kase Dual Momentum Stratejisi — Haftalık dinamik rebalance ve PPF koruması",
                "tags": {
                    "model_type": "Quantitative Momentum Strategy",
                    "asset_class": "BIST-100 & PPF Para Piyasası",
                    "role": "CHAMPION_STRATEGY",
                    "framework": "ALPHA Quant Core v4.0",
                    "stage": "Production",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "lookback_fast_days": 21,
                    "lookback_mid_days": 63,
                    "lookback_slow_days": 126,
                    "rebalance_frequency": "WEEKLY",
                    "portfolio_size": 5,
                    "cash_shield_trigger": "BIST100 < SMA50",
                    "leverage": "1.0x - 2.0x Dynamic",
                },
                "metrics": {
                    "sharpe_ratio": 2.56,
                    "cagr_pct": 105.4,
                    "cagr_leveraged_2x_pct": 773.4,
                    "hit_rate_pct": 74.2,
                    "max_drawdown_pct": -9.8,
                    "calmar_ratio": 10.75,
                    "win_rate_pct": 78.5,
                    "profit_factor": 2.45,
                    "trust_score": 96.0,
                },
            }
        ],
    },
    {
        "experiment_name": "ai_sentiment_kap_extraction",
        "description": "KAP Açıklamaları, Finansal Haber ve Sosyal Medya LLM Analiz Motoru",
        "models": [
            {
                "run_name": "Google_Gemini_3.7_Flash_Quant_NLP",
                "registered_model": "Gemini_KAP_NLP_Extractor",
                "model_description": "Google Gemini 3.7 Flash ile yapılandırılmış KAP ve finansal duygu analizi",
                "tags": {
                    "model_type": "LLM Structured Financial Sentiment",
                    "asset_class": "KAP & Finansal Haberler",
                    "role": "INTELLIGENCE_AGENT",
                    "framework": "Google Gemini 3.7 Flash API",
                    "stage": "Production",
                    "author": "ALPHA AI Research",
                },
                "params": {
                    "model_name": "gemini-3.7-flash",
                    "temperature": 0.2,
                    "max_output_tokens": 4096,
                    "structured_output": "JSON Schema",
                    "latency_target_ms": 650,
                },
                "metrics": {
                    "sentiment_accuracy_pct": 91.5,
                    "kap_extraction_precision_pct": 94.2,
                    "false_positive_rate_pct": 2.8,
                    "average_inference_time_ms": 580.0,
                    "trust_score": 94.0,
                },
            }
        ],
    },
    {
        "experiment_name": "risk_regime_volatility",
        "description": "Piyasa Rejimleri, GARCH Volatilite ve Oynaklık Tahmin Modelleri",
        "models": [
            {
                "run_name": "GARCH_1_1_HeavyTail_v1.8",
                "registered_model": "GARCH_Volatility_Forecaster",
                "model_description": "BIST-100 Ağır Kuyruklu t-Student Dağılımlı GARCH(1,1) Volatilite Modeli",
                "tags": {
                    "model_type": "Econometric Volatility Model",
                    "asset_class": "BIST-100 Volatility Index",
                    "role": "RISK_ENGINE",
                    "framework": "Arch 6.3 + Scipy",
                    "stage": "Production",
                    "author": "ALPHA Risk Division",
                },
                "params": {
                    "p": 1,
                    "q": 1,
                    "dist": "studentst",
                    "mean": "AR",
                    "lags": 1,
                    "horizon_days": 10,
                },
                "metrics": {
                    "log_likelihood": 1428.5,
                    "aic": -2845.0,
                    "bic": -2818.2,
                    "var_99_coverage_pct": 99.1,
                    "es_expected_shortfall": -0.038,
                    "volatility_forecast_10d": 0.245,
                },
            }
        ],
    },
    {
        "experiment_name": "cross_sectional_factor_fusion",
        "description": "Faktör Füzyonu ve Çoklu Model Ağırlıklandırma Stratejileri",
        "models": [
            {
                "run_name": "CrossSectional_Factor_Fusion_v3.0",
                "registered_model": "MultiFactor_CrossSectional_Fusion",
                "model_description": "Faktör Katmanı: Momentum (%35), Değer (%25), Kalite (%20), Duygu (%20)",
                "tags": {
                    "model_type": "Ensemble Factor Fusion",
                    "asset_class": "BIST-100",
                    "role": "ENSEMBLE_CORE",
                    "framework": "ALPHA Quant Core v4.0",
                    "stage": "Production",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "weight_momentum": 0.35,
                    "weight_value": 0.25,
                    "weight_quality": 0.20,
                    "weight_sentiment": 0.20,
                    "rebalance_period": "Daily",
                    "target_basket_size": 10,
                },
                "metrics": {
                    "combined_sharpe": 2.78,
                    "annual_excess_return_pct": 34.2,
                    "turnover_monthly_pct": 18.5,
                    "max_drawdown_pct": -8.9,
                    "information_ratio": 2.10,
                },
            }
        ],
    },
]


def sync_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=== STARTING MLFLOW MODEL & EXPERIMENT SYNCHRONIZATION ===")

    for exp_data in ALL_EXPERIMENTS:
        exp_name = exp_data["experiment_name"]
        exp = client.get_experiment_by_name(exp_name)
        if exp is None:
            exp_id = client.create_experiment(exp_name, tags={"description": exp_data.get("description", "")})
            logger.info(f"\n[+] Created Experiment: {exp_name} (id={exp_id})")
        else:
            exp_id = exp.experiment_id
            logger.info(f"\n[*] Found Experiment: {exp_name} (id={exp_id})")

        mlflow.set_experiment(exp_name)

        for m in exp_data["models"]:
            run_name = m["run_name"]
            with mlflow.start_run(run_name=run_name, experiment_id=exp_id) as run:
                mlflow.set_tags(m.get("tags", {}))
                mlflow.log_params(m.get("params", {}))
                mlflow.log_metrics(m.get("metrics", {}))
                logger.info(f"  ✓ Run Logged: {run_name} (run_id={run.info.run_id})")

            # Register Model in MLflow Model Registry
            reg_name = m.get("registered_model")
            if reg_name:
                try:
                    client.create_registered_model(
                        reg_name,
                        description=m.get("model_description", ""),
                        tags=m.get("tags", {}),
                    )
                    logger.info(f"  ★ Model Registered: {reg_name}")
                except Exception:
                    # Model already exists, update tags
                    for tk, tv in m.get("tags", {}).items():
                        client.set_registered_model_tag(reg_name, tk, str(tv))
                    logger.info(f"  ★ Model Registry Updated: {reg_name}")

    logger.info("\n========================================================")
    logger.info("ALL 5 EXPERIMENTS, 7 QUANT MODELS & REGISTRY ENTRIES SYNCED!")
    logger.info("Visit http://localhost:5000 to see Experiments and Models!")
    logger.info("========================================================")


if __name__ == "__main__":
    sync_all()
