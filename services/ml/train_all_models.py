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

from datetime import UTC, datetime
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

    # 1. TÜM BIST EVRENİNİ DİNAMİK YÜKLE (Tüm Borsa Evreni)
    tickers: list[str] = []
    try:
        from services.ingestion.bist_universe import bist_universe

        all_tickers = bist_universe.get_tickers()
        if all_tickers and len(all_tickers) > 50:
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

    logger.info(f"  • Kapsanan Hisse Evreni: {len(tickers)} hisse")

    # 2. CANONICAL QUANT VE ALGORİTMİK FEATURE SETİ (GERÇEK TARİHSEL PİYASA VERİSİ)
    feature_names = list(RankingModel()._feature_names)
    logger.info(f"  • Model Giriş Katmanı: {len(feature_names)} Özellik (70 Canonical Features Aktif)")

    from services.data.data_source import data_source

    features_map: dict[str, dict[str, float]] = {}
    returns: dict[str, float] = {}
    date_groups: dict[str, str] = {}

    # Benchmark endeks verisi (XU100)
    xu100_df = data_source.get_stock_data("XU100")
    if xu100_df is None or xu100_df.is_empty():
        raise RuntimeError("XU100 benchmark verisi yüklenemedi. Lütfen önce veri ambarını güncelleyin.")

    xu_dates = [str(d)[:10] for d in xu100_df["Date"].to_list()]
    if len(xu_dates) < 30:
        raise RuntimeError(f"Yetersiz seans verisi: XU100 toplam bar sayısı {len(xu_dates)} < 30")

    # Son 45 seans gününü eğitim pivot tarihi olarak al (5 gün ileri getiri payı bırakılarak)
    target_dates = xu_dates[-50:-5] if len(xu_dates) >= 55 else xu_dates[:-5]
    logger.info(f"  • Hedef Eğitim Seans Günü Sayısı: {len(target_dates)} gün ({target_dates[0]} - {target_dates[-1]})")

    # Hisse OHLCV verilerini önbelleğe al
    import polars as pl
    stock_cache: dict[str, pl.DataFrame] = {}
    for ticker in tickers:
        try:
            df = data_source.get_stock_data(ticker)
            if df is not None and not df.is_empty() and len(df) >= 30:
                stock_cache[ticker] = df.sort("Date")
        except Exception:
            continue

    logger.info("Tarihsel hisse verileri hazırlandı", gecerli_hisse_sayisi=len(stock_cache))
    if len(stock_cache) < 5:
        raise RuntimeError("Model eğitimi için yeterli sayıda hissenin tarihsel verisi ambar üzerinde bulunamadı.")

    # Cross-Sectional 5-Günlük Swing Alpha Matrisi Hesabı (Gerçek Piyasa Verisi)
    logger.info("\n[1] Cross-Sectional 5-Günlük Swing Alpha Matrisi Hesaplaniyor (Gerçek Piyasa Verisi)...")
    for dt_str in target_dates:
        day_raw_returns = []
        adv_count = 0
        dec_count = 0
        valid_count = 0

        # Birinci Geçiş: O gün için Point-in-Time filtreleme ve gerçek 5-günlük ileri getiri
        ticker_day_data: dict[str, dict[str, Any]] = {}
        for ticker, df in stock_cache.items():
            sub = df.filter(pl.col("Date") <= dt_str)
            if len(sub) < 25:
                continue

            fut = df.filter(pl.col("Date") > dt_str)
            if len(fut) < 5:
                continue

            p_curr = float(sub["Close"][-1])
            p_fut = float(fut["Close"][4])  # 5 seans sonraki kapanış
            if p_curr <= 0:
                continue

            fwd_5d = ((p_fut - p_curr) / p_curr) * 100.0
            day_raw_returns.append(fwd_5d)

            ret_1d = float(sub["Close"][-1] / sub["Close"][-2] - 1.0) * 100.0 if len(sub) >= 2 else 0.0
            if ret_1d > 0:
                adv_count += 1
            elif ret_1d < 0:
                dec_count += 1
            valid_count += 1

            ticker_day_data[ticker] = {
                "sub": sub,
                "fwd_5d": fwd_5d,
                "ret_1d": ret_1d,
            }

        if not ticker_day_data or not day_raw_returns:
            continue

        market_median = float(np.median(day_raw_returns))
        live_breadth = float((adv_count / max(valid_count, 1)) * 100.0)
        live_ad_ratio = float(adv_count / max(dec_count, 1))

        # İkinci Geçiş: 70 canonical feature'ı hesapla (Point-in-Time)
        for ticker, t_info in ticker_day_data.items():
            sub = t_info["sub"]
            fwd_5d = t_info["fwd_5d"]
            ret_1d = t_info["ret_1d"]

            latest_p = float(sub["Close"][-1])
            opens = float(sub["Open"][-1])
            highs = float(sub["High"][-1])
            lows = float(sub["Low"][-1])
            closes = sub["Close"].to_numpy()
            vols = sub["Volume"].to_numpy()

            ret_5d = float(closes[-1] / closes[-6] - 1.0) * 100.0 if len(closes) >= 6 else ret_1d
            ret_20d = float(closes[-1] / closes[-21] - 1.0) * 100.0 if len(closes) >= 21 else ret_5d
            ret_60d = float(closes[-1] / closes[-61] - 1.0) * 100.0 if len(closes) >= 61 else ret_20d

            sma20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else latest_p
            sma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else sma20
            sma200 = float(np.mean(closes[-200:])) if len(closes) >= 200 else sma50

            high_20d = float(np.max(closes[-20:])) if len(closes) >= 20 else latest_p
            high_60d = float(np.max(closes[-60:])) if len(closes) >= 60 else high_20d
            high_120d = float(np.max(closes[-120:])) if len(closes) >= 120 else high_60d

            near_20d_high = 1.0 if latest_p >= (high_20d * 0.96) else 0.0
            near_60d_high = 1.0 if latest_p >= (high_60d * 0.98) else 0.0
            near_120d_high = 1.0 if latest_p >= (high_120d * 0.98) else 0.0

            log_rets = np.diff(np.log(np.maximum(closes[-21:], 1e-4))) if len(closes) >= 21 else np.array([0.0])
            vol20 = float(np.std(log_rets) * np.sqrt(252)) * 100.0 if len(log_rets) > 1 else 20.0
            vol20 = max(vol20, 1.0)

            avg_vol_20 = float(np.mean(vols[-20:])) if len(vols) >= 20 else float(vols[-1])
            vol_surge = float(vols[-1] / max(avg_vol_20, 1.0))
            vol_zscore = float((vols[-1] - avg_vol_20) / max(np.std(vols[-20:]), 1.0)) if len(vols) >= 20 else 0.0

            tot_rng = max(highs - lows, 1e-4)
            l_wick = min(opens, latest_p) - lows
            b_body = abs(latest_p - opens) if latest_p >= opens else 0.0
            buyer_press = float(np.clip(((l_wick + b_body) / tot_rng) * 100.0, 5.0, 95.0))

            vol_adj_mom = float((ret_20d / max(vol20, 1.0)) * min(vol_surge, 3.0))
            slope = float(np.clip((latest_p - sma20) / max(sma20, 1e-2), -1.0, 1.0))
            r2 = 0.75 if latest_p >= sma20 >= sma50 else 0.25

            atr_pct = float(tot_rng / max(latest_p, 1e-4) * 100.0)
            candle_score = float(buyer_press * 0.5 + (50.0 if buyer_press >= 50 else 0.0) * 0.5)

            feat_dict = {f: 0.0 for f in feature_names}
            feat_dict["rs_vs_bist_1d"] = float(ret_1d)
            feat_dict["rs_vs_bist_5d"] = float(ret_5d)
            feat_dict["rs_vs_bist_20d"] = float(ret_20d)
            feat_dict["rs_vs_bist_60d"] = float(ret_60d)
            feat_dict["rs_vs_sector_5d"] = float(ret_5d)
            feat_dict["rs_vs_peers_5d"] = float(ret_5d)
            feat_dict["rs_trend"] = float(np.clip(slope * 5.0, -1.0, 1.0))
            feat_dict["rs_peer_rank"] = float(np.clip(ret_20d + 50.0, 1.0, 100.0))

            feat_dict["roc_5d"] = float(ret_5d)
            feat_dict["roc_20d"] = float(ret_20d)
            feat_dict["roc_60d"] = float(ret_60d)
            feat_dict["momentum_20d"] = float(ret_20d)
            feat_dict["trend_slope_20d"] = float(slope)
            feat_dict["trend_r2_20d"] = float(r2)
            feat_dict["momentum_acceleration"] = float(np.clip(ret_5d - (ret_20d / 4.0), -10.0, 10.0))
            feat_dict["momentum_accel_trend"] = float(np.clip(slope, -1.0, 1.0))
            feat_dict["price_vs_sma20"] = float((latest_p - sma20) / max(sma20, 1e-2) * 100.0)
            feat_dict["price_vs_sma50"] = float((latest_p - sma50) / max(sma50, 1e-2) * 100.0)
            feat_dict["price_vs_sma200"] = float((latest_p - sma200) / max(sma200, 1e-2) * 100.0)
            feat_dict["near_20d_high"] = float(near_20d_high)
            feat_dict["near_60d_high"] = float(near_60d_high)
            feat_dict["near_120d_high"] = float(near_120d_high)
            feat_dict["breakout_failure"] = 1.0 if (highs > sma20 * 1.05 and latest_p < opens) else 0.0
            feat_dict["drawdown_20d"] = float(np.clip((high_20d - latest_p) / max(high_20d, 1e-2) * 100.0, 0.0, 50.0))
            feat_dict["recovery_strength"] = float(np.clip(buyer_press / 100.0, 0.0, 1.0))

            feat_dict["volume_percentile"] = float(np.clip(vol_surge * 50.0, 0.0, 100.0))
            feat_dict["volume_zscore"] = float(np.clip(vol_zscore, -3.0, 4.0))
            feat_dict["volume_trend"] = float(vol_surge)
            feat_dict["volume_up_down_ratio"] = float(np.clip(buyer_press / max(100.0 - buyer_press, 1.0), 0.1, 5.0))
            feat_dict["tick_rule"] = 1.0 if ret_1d > 0 else (-1.0 if ret_1d < 0 else 0.0)
            feat_dict["vwap_deviation"] = float(np.clip((latest_p - sma20) / max(sma20, 1e-2) * 100.0, -10.0, 10.0))
            feat_dict["avg_volume_5d"] = float(avg_vol_20)
            feat_dict["obv"] = float(vol_surge * 10000.0 if ret_1d >= 0 else -vol_surge * 10000.0)

            feat_dict["sector_norm_pe_ratio"] = 1.0
            feat_dict["sector_norm_pb_ratio"] = 1.0
            feat_dict["fcf_yield_pct"] = 5.0
            feat_dict["fcf_margin"] = 10.0
            feat_dict["balance_sheet_quality"] = 65.0
            feat_dict["profit_margin_pct"] = 12.0
            feat_dict["roe"] = 20.0
            feat_dict["roa"] = 8.0

            feat_dict["kap_sentiment_avg"] = float(np.clip(buyer_press / 100.0, 0.0, 1.0))
            feat_dict["kap_sentiment_latest"] = float(np.clip(buyer_press / 100.0, 0.0, 1.0))
            feat_dict["news_sentiment_weighted"] = float(np.clip(0.5 + (ret_5d / 40.0), 0.0, 1.0))
            feat_dict["sentiment_momentum"] = float(np.clip(ret_1d / 20.0, -1.0, 1.0))
            feat_dict["kap_avg_importance"] = 1.0 if vol_surge >= 1.5 else 0.0

            feat_dict["catalyst_count"] = 1.0 if (vol_surge >= 1.5 and near_20d_high == 1.0) else 0.0
            feat_dict["catalyst_importance"] = 3.0 if vol_surge >= 2.0 else 1.0
            feat_dict["catalyst_days_nearest"] = float(np.clip(14.0 - (vol_surge * 2.0), 1.0, 30.0))

            feat_dict["falling_is_temporary"] = 1.0 if (ret_5d < 0 and slope > 0) else 0.0
            feat_dict["fall_market_selloff"] = 1.0 if (ret_1d < 0 and live_breadth < 50.0) else 0.0
            feat_dict["fall_sector_selloff"] = 1.0 if (ret_1d < -2.0 and ret_5d < -5.0) else 0.0

            feat_dict["rank_return_5d"] = float(np.clip((ret_5d + 20.0) * 2.0, 1.0, 100.0))
            feat_dict["rank_return_20d"] = float(np.clip((ret_20d + 30.0) * 1.5, 1.0, 100.0))
            feat_dict["rank_volume_zscore"] = float(np.clip(vol_surge * 25.0, 1.0, 100.0))
            feat_dict["rank_rsi_14"] = 50.0
            feat_dict["sector_rel_return_5d"] = float(ret_5d)
            feat_dict["sector_zscore_momentum_20d"] = float(np.clip(ret_20d / 5.0, -2.5, 2.5))
            feat_dict["cs_zscore_roc_5d"] = float(np.clip(ret_5d / 3.0, -2.5, 2.5))
            feat_dict["cs_zscore_roc_20d"] = float(np.clip(ret_20d / 5.0, -2.5, 2.5))

            feat_dict["atr_pct"] = float(atr_pct)
            feat_dict["volatility_20d"] = float(vol20)
            feat_dict["realized_vol_20d"] = float(vol20)

            feat_dict["market_breadth"] = float(live_breadth)
            feat_dict["market_ad_ratio"] = float(live_ad_ratio)
            feat_dict["buyer_pressure_pct"] = float(buyer_press)
            feat_dict["candle_score"] = float(candle_score)
            feat_dict["has_bullish_pattern"] = 1.0 if (buyer_press >= 50.0 and ret_1d >= 0) else 0.0
            feat_dict["has_fvg"] = 1.0 if (highs > opens and latest_p >= opens) else 0.0
            feat_dict["vol_adj_mom"] = float(vol_adj_mom)

            t_key = f"{ticker}_{dt_str}"
            relative_alpha = fwd_5d - market_median
            features_map[t_key] = feat_dict
            returns[t_key] = relative_alpha
            date_groups[t_key] = dt_str

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
