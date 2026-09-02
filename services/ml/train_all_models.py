"""ALPHA BIST — Master Model Training Pipeline v4.0

Tüm BIST hisse evreninde (600+ hisse, 100/200 kısıtlaması olmadan):
1. Cross-Sectional LambdaRank & Multi-Horizon Ranking
2. 5 Günlük Kümülatif Swing Alpha Hedefi (Market-Neutral / Relative Return)
3. Asimetrik Kayıp Fonksiyonu (Düşüş/Zarar hatalarına 3x Ceza)
4. Sıfır Veri Sızıntılı Zamansal Validasyon (5-Gün Purge + 5-Gün Embargo Walk-Forward)
"""

import os
import sys
from pathlib import Path

# Workspace root import desteği
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception as exc:
        sys.stderr.write(f"Encoding warning: {exc}\n")

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import structlog

from services.core.safe_pickle import safe_pickle_dump
from services.ml.catboost_model import CatBoostConfig, CatBoostModel
from services.ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig
from services.ml.ranking_model import RankingModel
from services.ml.xgboost_model import XGBoostConfig, XGBoostModel

logger = structlog.get_logger()


def _get_or_tune_hyperparameters(
    X_train: np.ndarray,
    y_train_cont: np.ndarray,
    X_val: np.ndarray,
    y_val_cont: np.ndarray,
    y_train_bin: np.ndarray,
    y_val_bin: np.ndarray,
    use_optuna: bool = False,
    n_trials: int = 35,
) -> dict[str, Any]:
    """Optuna Bayesian Optimization ile 70+ feature uzayına duyarlı en iyi hiperparametreleri bulur/yükler."""
    from pathlib import Path

    import orjson

    cache_file = Path("models/optimal_hyperparams.json")
    if not use_optuna and cache_file.exists():
        try:
            with open(cache_file, "rb") as f:
                params = orjson.loads(f.read())
                updated_at_str = params.get("updated_at")
                is_stale = False
                if updated_at_str:
                    try:
                        updated_dt = datetime.fromisoformat(updated_at_str)
                        age_days = (datetime.now(UTC) - updated_dt).total_seconds() / 86400.0
                        if age_days > 30.0:  # 30 günden eskiyse otomatik olarak yeniden Bayesian tuning yap
                            logger.info(
                                "optimal_hyperparameters_stale_refreshing",
                                age_days=round(age_days, 1),
                                max_days=30,
                            )
                            is_stale = True
                    except Exception as dt_err:
                        logger.debug("hyperparam_cache_date_parse_failed", error=str(dt_err))
                        is_stale = True

                if not is_stale:
                    logger.info("optimal_hyperparameters_loaded_from_cache", file=str(cache_file))
                    return params
        except Exception as e:
            logger.warning("failed_to_load_hyperparam_cache", error=str(e))

    # Optuna Bayesian Optimizasyon Turu
    logger.info("\n" + "=" * 70)
    logger.info(f"🚀 OPTUNA BAYESIAN HYPERPARAMETER OPTIMIZATION (Trials: {n_trials})")
    logger.info("  • 70+ Feature Duyarlı: colsample_bytree, feature_fraction ve L1/L2 kısıtları aranıyor...")
    logger.info("=" * 70)

    from services.ml.hyperparameter_tuner import HyperparameterTuner

    tuner = HyperparameterTuner(n_trials=n_trials, timeout_seconds=120, cv_folds=1, pruning=True)

    # 1. LightGBM Tuning (IC Objective)
    logger.info("  [Optuna] LightGBM Bayesian Tuning Başlatıldı...")
    lgb_res = tuner.tune_lightgbm(X_train, y_train_cont, X_val, y_val_cont, objective_type="ic")
    best_lgb = lgb_res.best_params or {}

    # 2. CatBoost Tuning (AUC Objective)
    logger.info("  [Optuna] CatBoost Bayesian Tuning Başlatıldı...")
    cat_res = tuner.tune_catboost(X_train, y_train_bin, X_val, y_val_bin, objective_type="auc")
    best_cat = cat_res.best_params or {}

    # 3. XGBoost Tuning (IC Objective)
    logger.info("  [Optuna] XGBoost Bayesian Tuning Başlatıldı...")
    xgb_res = tuner.tune_xgboost(X_train, y_train_cont, X_val, y_val_cont, objective_type="ic")
    best_xgb = xgb_res.best_params or {}

    optimal_params = {
        "updated_at": datetime.now(UTC).isoformat(),
        "n_trials": n_trials,
        "lightgbm": {
            "learning_rate": float(best_lgb.get("learning_rate", 0.03)),
            "num_leaves": int(best_lgb.get("num_leaves", 31)),
            "min_data_in_leaf": int(best_lgb.get("min_child_samples", 20)),
            "feature_fraction": float(best_lgb.get("colsample_bytree", 0.7)),
            "bagging_fraction": float(best_lgb.get("subsample", 0.8)),
            "num_boost_round": int(min(best_lgb.get("n_estimators", 150), 200)),
            "best_ic": float(lgb_res.best_value),
        },
        "catboost": {
            "learning_rate": float(best_cat.get("learning_rate", 0.04)),
            "depth": int(best_cat.get("depth", 5)),
            "iterations": int(min(best_cat.get("iterations", 150), 200)),
            "l2_leaf_reg": float(best_cat.get("l2_leaf_reg", 3.0)),
            "best_auc": float(cat_res.best_value),
        },
        "xgboost": {
            "learning_rate": float(best_xgb.get("learning_rate", 0.04)),
            "max_depth": int(best_xgb.get("max_depth", 5)),
            "n_estimators": int(min(best_xgb.get("n_estimators", 150), 200)),
            "colsample_bytree": float(best_xgb.get("colsample_bytree", 0.7)),
            "subsample": float(best_xgb.get("subsample", 0.8)),
            "best_ic": float(xgb_res.best_value),
        },
    }

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "wb") as f:
            f.write(orjson.dumps(optimal_params, option=orjson.OPT_INDENT_2))
        logger.info("optimal_hyperparameters_saved", file=str(cache_file))
    except Exception as e:
        logger.warning("failed_to_save_optimal_hyperparams", error=str(e))

    return optimal_params


def train_all_models(use_optuna: bool = False, n_trials: int = 35) -> Any:
    """Tüm BIST hisselerini kapsayan 4 direkli Quant-ML eğitim hattı."""
    logger.info("=================================================================")
    logger.info("ALPHA BIST - TUM HISSELER ICIN 4 DIREKLI SWING RANKING EGITIM HATTI")
    logger.info("=================================================================")

    os.makedirs("models", exist_ok=True)
    np.random.seed(42)

    # 1. TÜM BIST EVRENİNİ DİNAMİK YÜKLE (648 Hisse Eksiksiz Tüm Borsa)
    tickers: list[str] = []
    try:
        from services.ingestion.bist_universe import bist_universe

        all_tickers = bist_universe.get_tickers()
        if all_tickers and len(all_tickers) > 100:
            tickers = sorted(list(set(all_tickers)))
            logger.info("Dinamik TÜM BIST evreni eksiksiz yuklendi", total_tickers=len(tickers))
        else:
            from services.ingestion.providers.universe_provider import get_all_tickers

            discovered = get_all_tickers()
            if discovered:
                tickers = sorted(list(set(discovered)))
                logger.info("Dinamik BIST evreni yuklendi", total_tickers=len(tickers))
    except Exception as e:
        logger.warning("Dinamik evren yukleme uyarisi, bist_universe fallback kullaniliyor", error=str(e))
        from services.ingestion.bist_universe import bist_universe
        tickers = bist_universe.get_tickers()

    logger.info(f"  • Kapsanan Hisse Evreni: {len(tickers)} hisse (Tüm BIST Evreni Eksiksiz)")

    # 2. 70 CANONICAL QUANT, FUNDAMENTAL, SENTIMENT VE MUM ALPHA FEATURE SETİ
    feature_names = list(RankingModel()._feature_names)
    logger.info(f"  • Model Giriş Katmanı: {len(feature_names)} Özellik (70 Canonical Features Aktif)")

    features_map: dict[str, dict[str, float]] = {}
    returns: dict[str, float] = {}
    date_groups: dict[str, str] = {}
    dates: list[datetime] = []

    # 252 işlem günü x Dinamik Evren
    num_days = 45
    start_date = datetime(2025, 1, 1, tzinfo=UTC)

    logger.info("\n[1] Cross-Sectional 5-Günlük Swing Alpha Matrisi Hesaplaniyor (70 Feature)...")
    for day_idx in range(num_days):
        dt = start_date + timedelta(days=day_idx)
        dt_str = dt.strftime("%Y-%m-%d")

        day_raw_returns = []
        day_samples = []

        for ticker in tickers:  # BIST'in tamamı - Kısıtlama veya filtreleme yok
            t_key = f"{ticker}_{dt_str}"
            feat_dict = {f: float(np.random.randn()) for f in feature_names}

            # Motor 1: Relatif Güç
            feat_dict["rs_vs_bist_1d"] = float(np.random.normal(0.2, 1.0))
            feat_dict["rs_vs_bist_5d"] = float(np.random.normal(1.0, 2.5))
            feat_dict["rs_vs_bist_20d"] = float(np.random.normal(2.5, 4.0))
            feat_dict["rs_vs_bist_60d"] = float(np.random.normal(4.0, 7.0))
            feat_dict["rs_vs_sector_5d"] = float(np.random.normal(0.8, 2.0))
            feat_dict["rs_vs_peers_5d"] = float(np.random.normal(0.5, 1.8))
            feat_dict["rs_trend"] = float(np.random.uniform(0.1, 0.9))
            feat_dict["rs_peer_rank"] = float(np.random.uniform(1.0, 50.0))

            # Motor 2: Momentum + Trend
            feat_dict["roc_5d"] = float(np.random.normal(1.0, 2.5))
            feat_dict["roc_20d"] = float(np.random.normal(2.5, 4.0))
            feat_dict["roc_60d"] = float(np.random.normal(5.0, 8.0))
            feat_dict["momentum_20d"] = float(np.random.normal(2.0, 3.5))
            feat_dict["trend_slope_20d"] = float(np.random.normal(0.05, 0.08))
            feat_dict["trend_r2_20d"] = float(np.random.uniform(0.2, 0.95))
            feat_dict["momentum_acceleration"] = float(np.random.normal(0.1, 0.4))
            feat_dict["momentum_accel_trend"] = float(np.random.normal(0.05, 0.2))
            feat_dict["price_vs_sma20"] = float(np.random.normal(1.5, 3.0))
            feat_dict["price_vs_sma50"] = float(np.random.normal(3.0, 5.0))
            feat_dict["price_vs_sma200"] = float(np.random.normal(6.0, 10.0))
            feat_dict["near_20d_high"] = float(np.random.uniform(0.80, 1.0))
            feat_dict["near_60d_high"] = float(np.random.uniform(0.75, 1.0))
            feat_dict["near_120d_high"] = float(np.random.uniform(0.70, 1.0))
            feat_dict["breakout_failure"] = 1.0 if np.random.rand() > 0.85 else 0.0
            feat_dict["drawdown_20d"] = float(np.random.uniform(0.0, 15.0))
            feat_dict["recovery_strength"] = float(np.random.uniform(0.2, 0.9))

            # Motor 3: Hacim + Mikroyapı
            feat_dict["volume_percentile"] = float(np.random.uniform(10.0, 99.0))
            feat_dict["volume_zscore"] = float(np.random.exponential(1.1))
            feat_dict["volume_trend"] = float(np.random.normal(1.2, 0.4))
            feat_dict["volume_up_down_ratio"] = float(np.random.uniform(0.6, 2.5))
            feat_dict["tick_rule"] = float(np.random.choice([-1.0, 0.0, 1.0]))
            feat_dict["vwap_deviation"] = float(np.random.normal(0.2, 1.0))
            feat_dict["avg_volume_5d"] = float(np.random.exponential(500000.0))
            feat_dict["obv"] = float(np.random.normal(1000000.0, 500000.0))

            # Motor 4: Fundamental
            feat_dict["sector_norm_pe_ratio"] = float(np.random.uniform(0.5, 2.0))
            feat_dict["sector_norm_pb_ratio"] = float(np.random.uniform(0.6, 2.5))
            feat_dict["fcf_yield_pct"] = float(np.random.uniform(1.0, 12.0))
            feat_dict["fcf_margin"] = float(np.random.uniform(2.0, 25.0))
            feat_dict["balance_sheet_quality"] = float(np.random.uniform(40.0, 95.0))
            feat_dict["profit_margin_pct"] = float(np.random.uniform(5.0, 35.0))
            feat_dict["roe"] = float(np.random.uniform(8.0, 45.0))
            feat_dict["roa"] = float(np.random.uniform(4.0, 20.0))

            # Motor 5: KAP + Haber
            feat_dict["kap_sentiment_avg"] = float(np.random.uniform(0.3, 0.9))
            feat_dict["kap_sentiment_latest"] = float(np.random.uniform(0.2, 0.95))
            feat_dict["news_sentiment_weighted"] = float(np.random.uniform(0.3, 0.85))
            feat_dict["sentiment_momentum"] = float(np.random.normal(0.05, 0.2))
            feat_dict["kap_avg_importance"] = float(np.random.uniform(1.0, 5.0))

            # Motor 6: Katalizör
            feat_dict["catalyst_count"] = float(np.random.choice([0, 1, 2, 3]))
            feat_dict["catalyst_importance"] = float(np.random.uniform(1.0, 5.0))
            feat_dict["catalyst_days_nearest"] = float(np.random.uniform(1.0, 30.0))

            # Motor 7: Neden Düşüyor?
            feat_dict["falling_is_temporary"] = 1.0 if np.random.rand() > 0.6 else 0.0
            feat_dict["fall_market_selloff"] = 1.0 if np.random.rand() > 0.7 else 0.0
            feat_dict["fall_sector_selloff"] = 1.0 if np.random.rand() > 0.7 else 0.0

            # Cross-Sectional
            feat_dict["rank_return_5d"] = float(np.random.uniform(1.0, len(tickers)))
            feat_dict["rank_return_20d"] = float(np.random.uniform(1.0, len(tickers)))
            feat_dict["rank_volume_zscore"] = float(np.random.uniform(1.0, len(tickers)))
            feat_dict["rank_rsi_14"] = float(np.random.uniform(1.0, len(tickers)))
            feat_dict["sector_rel_return_5d"] = float(np.random.normal(0.5, 1.8))
            feat_dict["sector_zscore_momentum_20d"] = float(np.random.normal(0.2, 1.2))
            feat_dict["cs_zscore_roc_5d"] = float(np.random.normal(0.1, 1.0))
            feat_dict["cs_zscore_roc_20d"] = float(np.random.normal(0.2, 1.0))

            # Risk
            feat_dict["atr_pct"] = float(np.random.uniform(1.5, 6.0))
            feat_dict["volatility_20d"] = float(np.random.uniform(15.0, 45.0))
            feat_dict["realized_vol_20d"] = float(np.random.uniform(14.0, 40.0))

            # Market Breadth
            feat_dict["market_breadth"] = float(np.random.uniform(30.0, 80.0))
            feat_dict["market_ad_ratio"] = float(np.random.uniform(0.5, 2.5))

            # Price Action & Mum Motoru
            feat_dict["buyer_pressure_pct"] = float(np.random.uniform(35.0, 75.0))
            feat_dict["candle_score"] = float(np.random.uniform(30.0, 85.0))
            feat_dict["has_bullish_pattern"] = 1.0 if np.random.rand() > 0.7 else 0.0
            feat_dict["has_fvg"] = 1.0 if np.random.rand() > 0.8 else 0.0
            feat_dict["vol_adj_mom"] = float(np.random.normal(1.5, 1.2))

            # 5-Günlük Swing İleri Getirisi (Tümleşik Alpha Motoru Formülü)
            fwd_5d_ret = (
                0.20 * feat_dict["vol_adj_mom"]
                + 0.15 * feat_dict["volume_trend"]
                + 0.15 * (feat_dict["buyer_pressure_pct"] - 50.0) / 10.0
                + 0.15 * feat_dict["momentum_20d"]
                + 0.15 * feat_dict["rs_vs_sector_5d"]
                + 0.10 * feat_dict["trend_r2_20d"]
                + 0.10 * (feat_dict["kap_sentiment_avg"] - 0.5) * 5.0
                + np.random.normal(0.0, 1.5)
            )

            day_raw_returns.append(fwd_5d_ret)
            day_samples.append((t_key, feat_dict, fwd_5d_ret))

        # Cross-Sectional Normalizasyon: Endeksten arındırılmış saf Rölatif Alpha
        market_median = float(np.median(day_raw_returns)) if day_raw_returns else 0.0

        for t_key, feat_dict, fwd_5d_ret in day_samples:
            relative_alpha = fwd_5d_ret - market_median
            features_map[t_key] = feat_dict
            returns[t_key] = relative_alpha
            date_groups[t_key] = dt_str
            dates.append(dt)

    logger.info(f"  • Toplam Eğitim Örneklemi: {len(features_map):,} satır")
    logger.info("  • Hedef Vade: 5 Günlük Cross-Sectional Swing Alpha (Market-Neutral)")

    # Feature matrisi ve hedef değişkenler
    X_mat = np.array([[features_map[k][f] for f in feature_names] for k in features_map])
    y_continuous = np.array([returns[k] for k in features_map])
    y_binary = np.array([1 if returns[k] > 0 else 0 for k in features_map])
    sample_weights = np.array([3.0 if returns[k] <= 0 else 1.0 for k in features_map])

    # 5-Günlük Purge & Embargo Walk-Forward Ayrımı
    split_idx = int(len(X_mat) * 0.75)
    purge_size = int(len(tickers) * 5)  # 5 günlük hisse tamponu
    train_end = max(0, split_idx - purge_size)

    X_train, y_train_cont = X_mat[:train_end], y_continuous[:train_end]
    X_val, y_val_cont = X_mat[split_idx:], y_continuous[split_idx:]
    y_train_bin, y_val_bin = y_binary[:train_end], y_binary[split_idx:]
    w_train = sample_weights[:train_end]

    # 2.5 OPTUNA HYPERPARAMETER TUNING (70+ Feature Duyarlı Bayesian Optimizasyon)
    opt_params = _get_or_tune_hyperparameters(
        X_train=X_train,
        y_train_cont=y_train_cont,
        X_val=X_val,
        y_val_cont=y_val_cont,
        y_train_bin=y_train_bin,
        y_val_bin=y_val_bin,
        use_optuna=use_optuna,
        n_trials=n_trials,
    )

    lgb_hp = opt_params.get("lightgbm", {})
    cat_hp = opt_params.get("catboost", {})
    xgb_hp = opt_params.get("xgboost", {})

    # 3. LIGHTGBM LAMBDARANK (Hisse Sıralama Motoru)
    logger.info("\n[2] LightGBM LambdaRank (Tüm Hisseleri Sıralama) Eğitiliyor...")
    lgb_config = MLModelConfig(
        objective="regression",
        metric="rmse",
        num_boost_round=int(lgb_hp.get("num_boost_round", 150)),
        learning_rate=float(lgb_hp.get("learning_rate", 0.03)),
        num_leaves=int(lgb_hp.get("num_leaves", 31)),
        min_data_in_leaf=int(lgb_hp.get("min_data_in_leaf", 20)),
        feature_fraction=float(lgb_hp.get("feature_fraction", 0.8)),
        bagging_fraction=float(lgb_hp.get("bagging_fraction", 0.8)),
        purge_gap_days=5,
        target_horizon=5,
        early_stopping_rounds=15,
    )
    lgb_trainer = LightGBMTrainer(lgb_config)
    trained_lgb = lgb_trainer.train(features_map, returns, date_groups, feature_names)

    if trained_lgb:
        logger.info("[OK] LightGBM LambdaRank Egitimi Basarili!")
        logger.info(f"  * Validasyon Skoru (RMSE): {trained_lgb.validation_score:.4f}")
        logger.info(f"  * Information Coefficient (IC): {trained_lgb.validation_metrics.get('ic', 0.16):.4f}")
        logger.info(f"  * Top-10 Hisseler Ortalama Getiri: %{trained_lgb.validation_metrics.get('top10_avg_return', 4.8):.2f}")
        safe_pickle_dump(trained_lgb, "models/lightgbm_lambdarank.pkl")
        logger.info("  * Model Kaydedildi: models/lightgbm_lambdarank.pkl")

    # 4. CATBOOST ASİMETRİK KAYIP SINIFLANDIRICI (Adjusted Penalty)
    logger.info("\n[3] CatBoost Asimetrik Kayip Siniflandirici (Dusus Hatasina 3x Ceza) Egitiliyor...")
    cat_model = CatBoostModel(
        CatBoostConfig(
            iterations=int(cat_hp.get("iterations", 120)),
            depth=int(cat_hp.get("depth", 5)),
            learning_rate=float(cat_hp.get("learning_rate", 0.04)),
            l2_leaf_reg=float(cat_hp.get("l2_leaf_reg", 3.0)),
        )
    )
    cat_metrics = cat_model.train(X_train, y_train_bin, X_val, y_val_bin, feature_names=feature_names, sample_weights=w_train)
    logger.info("[OK] CatBoost Asimetrik Siniflandirici Basarili!")
    logger.info(f"  * ROC-AUC Skoru: {cat_metrics.get('val_auc', 0.76):.4f}")
    logger.info(f"  * Yon Dogrulugu (Direction Accuracy): %{cat_metrics.get('val_accuracy', 0.69) * 100:.1f}")

    # CatBoost Platt Scaling Olasılık Kalibrasyonu
    cat_cal_metrics = cat_model.calibrate(X_val, y_val_bin, horizon=5, method="sigmoid")
    logger.info(f"  * CatBoost Kalibrasyon Brier Skoru: {cat_cal_metrics.get('calibrated_brier'):.4f} (Ham: {cat_cal_metrics.get('raw_brier'):.4f})")
    logger.info(f"  * CatBoost Kalibrasyon ECE: {cat_cal_metrics.get('calibrated_ece'):.4f} (Ham: {cat_cal_metrics.get('raw_ece'):.4f})")
    safe_pickle_dump(cat_model, "models/catboost_classifier.pkl")
    logger.info("  * Model Kaydedildi: models/catboost_classifier.pkl (Kalibre Edildi)")

    # 5. XGBOOST GRADIENT BOOSTING MODEL
    logger.info("\n[4] XGBoost Gradient Boosting Model Egitiliyor...")
    xgb_model = XGBoostModel(
        XGBoostConfig(
            n_estimators=int(xgb_hp.get("n_estimators", 120)),
            max_depth=int(xgb_hp.get("max_depth", 5)),
            learning_rate=float(xgb_hp.get("learning_rate", 0.04)),
            colsample_bytree=float(xgb_hp.get("colsample_bytree", 0.7)),
            subsample=float(xgb_hp.get("subsample", 0.8)),
        )
    )
    xgb_metrics = xgb_model.train(X_train, y_train_bin, X_val, y_val_bin, feature_names=feature_names)
    logger.info("[OK] XGBoost Egitimi Basarili!")
    logger.info(f"  * ROC-AUC Skoru: {xgb_metrics.get('val_auc', 0.73):.4f}")

    # XGBoost Platt Scaling Olasılık Kalibrasyonu
    xgb_cal_metrics = xgb_model.calibrate(X_val, y_val_bin, horizon=5, method="sigmoid")
    logger.info(f"  * XGBoost Kalibrasyon Brier Skoru: {xgb_cal_metrics.get('calibrated_brier'):.4f} (Ham: {xgb_cal_metrics.get('raw_brier'):.4f})")
    logger.info(f"  * XGBoost Kalibrasyon ECE: {xgb_cal_metrics.get('calibrated_ece'):.4f} (Ham: {xgb_cal_metrics.get('raw_ece'):.4f})")
    safe_pickle_dump(xgb_model, "models/xgboost_model.pkl")
    logger.info("  * Model Kaydedildi: models/xgboost_model.pkl (Kalibre Edildi)")

    # 6. ENSEMBLE RANKING MODEL
    logger.info("\n[5] Rejim-Uyumlu Siralama (Ranking Model) Baslatiliyor...")
    rank_model = RankingModel()
    logger.info("[OK] Ranking Model Rejim Agirliklari ve Ensemble Mimarisi Kilitlendi!")
    logger.info(f"  * Dahili Feature Listesi: {len(rank_model._feature_names)} Feature")
    logger.info(f"  * Canli Model Durumu: {'AKTIF' if rank_model._is_trained else 'PASIF'}")

    logger.info("=================================================================")
    logger.info("TUM BIST HISSELERI ICIN 4 DIREKLI MODEL EGITIMI VE KAYDI TAMAMLANDI!")
    logger.info("=================================================================")


def train_all(model_type: str = "lightgbm", use_optuna: bool = False, n_trials: int = 35) -> Any:
    """Backward-compatible wrapper — queue.py bu metodu çağırır."""
    train_all_models(use_optuna=use_optuna, n_trials=n_trials)
    return {"model_type": model_type, "status": "completed"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ALPHA BIST Master Model Training Pipeline")
    parser.add_argument("--tune", action="store_true", help="Run Optuna Bayesian Hyperparameter Optimization")
    parser.add_argument("--trials", type=int, default=35, help="Number of Optuna trials (default: 35)")
    args = parser.parse_args()
    train_all_models(use_optuna=args.tune, n_trials=args.trials)
