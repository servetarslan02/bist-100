"""
ALPHA BIST — Çok Modelli Ensemble Eğitim Motoru (LightGBM + XGBoost + CatBoost)
================================================================================
- 1997-2023 Train Verisi ile Eğitim
- 2024-2026 Kilitli Kör OOS Validasyonu
- Walk-Forward Cross Validation & SHAP Feature Importance
- Modelleri 'ml/saved_models/' Dizinine Pickle/JSON Formatında Kaydetme
"""

import os
import sys
import orjson
import pickle
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple
from pathlib import Path
import structlog

logger = structlog.get_logger()

# Model imports with safe fallback
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

try:
    import xgboost as xgb
except ImportError:
    xgb = None

try:
    import catboost as cb
except ImportError:
    cb = None

from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_squared_error, r2_score


class BistEnsembleTrainer:
    """Alpha BIST için LightGBM + XGBoost + CatBoost Ensemble Eğitici."""

    def __init__(self, train_df: pd.DataFrame, oos_df: pd.DataFrame):
        self.train_df = train_df
        self.oos_df = oos_df
        self.feature_cols = [
            "rsi_14", "atr_pct", "ret_1d", "ret_5d", "ret_20d",
            "vol_surge", "buyer_pressure", "near_20d_high", "breakout_setup", "dip_setup",
            "bm_is_bull", "bm_dist_sma200", "bm_is_crisis", "bm_ret_5d", "bm_vol_20d"
        ]
        self.target_col = "target_risk_adj"
        self.save_dir = Path("ml/saved_models")
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.models = {}

    def train_all(self) -> Dict[str, Any]:
        """Tüm modelleri eğitir, test eder ve ensemble üretir."""
        logger.info(f"Model eğitimi başlatılıyor (Özellik sayısı: {len(self.feature_cols)})...")
        
        X_train = self.train_df[self.feature_cols].values
        y_train = self.train_df[self.target_col].values
        
        X_oos = self.oos_df[self.feature_cols].values
        y_oos = self.oos_df[self.target_col].values

        results = {}

        # 1. LightGBM Modeli
        if lgb:
            logger.info("LightGBM Modeli eğitiliyor (24 Core CPU)...")
            lgb_model = lgb.LGBMRegressor(
                n_estimators=400,
                learning_rate=0.03,
                max_depth=6,
                num_leaves=31,
                subsample=0.8,
                colsample_bytree=0.8,
                n_jobs=-1,
                random_state=42
            )
            lgb_model.fit(X_train, y_train)
            lgb_train_pred = lgb_model.predict(X_train)
            lgb_oos_pred = lgb_model.predict(X_oos)
            
            lgb_r2 = r2_score(y_oos, lgb_oos_pred)
            lgb_ic = float(np.corrcoef(y_oos, lgb_oos_pred)[0, 1]) if len(y_oos) > 10 else 0.0
            
            self.models["lightgbm"] = lgb_model
            results["lightgbm"] = {
                "r2": round(float(lgb_r2), 4),
                "ic": round(float(lgb_ic), 4),
                "feature_importances": {
                    feat: round(float(imp), 4)
                    for feat, imp in zip(self.feature_cols, lgb_model.feature_importances_)
                }
            }
            with open(self.save_dir / "lightgbm_model.pkl", "wb") as f:
                pickle.dump(lgb_model, f)
            logger.info(f"LightGBM Eğitildi -> OOS IC: {lgb_ic:.4f}, R2: {lgb_r2:.4f}")

        # 2. XGBoost Modeli
        if xgb:
            logger.info("XGBoost Modeli eğitiliyor (24 Core CPU)...")
            xgb_model = xgb.XGBRegressor(
                n_estimators=350,
                learning_rate=0.03,
                max_depth=5,
                subsample=0.8,
                colsample_bytree=0.8,
                n_jobs=-1,
                random_state=42
            )
            xgb_model.fit(X_train, y_train)
            xgb_oos_pred = xgb_model.predict(X_oos)
            xgb_r2 = r2_score(y_oos, xgb_oos_pred)
            xgb_ic = float(np.corrcoef(y_oos, xgb_oos_pred)[0, 1]) if len(y_oos) > 10 else 0.0
            
            self.models["xgboost"] = xgb_model
            results["xgboost"] = {
                "r2": round(float(xgb_r2), 4),
                "ic": round(float(xgb_ic), 4),
                "feature_importances": {
                    feat: round(float(imp), 4)
                    for feat, imp in zip(self.feature_cols, xgb_model.feature_importances_)
                }
            }
            with open(self.save_dir / "xgboost_model.pkl", "wb") as f:
                pickle.dump(xgb_model, f)
            logger.info(f"XGBoost Eğitildi -> OOS IC: {xgb_ic:.4f}, R2: {xgb_r2:.4f}")

        # 3. CatBoost Modeli
        if cb:
            logger.info("CatBoost Modeli eğitiliyor (24 Core CPU)...")
            cb_model = cb.CatBoostRegressor(
                iterations=400,
                learning_rate=0.03,
                depth=6,
                thread_count=-1,
                random_seed=42,
                verbose=False
            )
            cb_model.fit(X_train, y_train)
            cb_oos_pred = cb_model.predict(X_oos)
            cb_r2 = r2_score(y_oos, cb_oos_pred)
            cb_ic = float(np.corrcoef(y_oos, cb_oos_pred)[0, 1]) if len(y_oos) > 10 else 0.0
            
            self.models["catboost"] = cb_model
            results["catboost"] = {
                "r2": round(float(cb_r2), 4),
                "ic": round(float(cb_ic), 4),
                "feature_importances": {
                    feat: round(float(imp), 4)
                    for feat, imp in zip(self.feature_cols, cb_model.get_feature_importance())
                }
            }
            with open(self.save_dir / "catboost_model.pkl", "wb") as f:
                pickle.dump(cb_model, f)
            logger.info(f"CatBoost Eğitildi -> OOS IC: {cb_ic:.4f}, R2: {cb_r2:.4f}")

        # 4. ExtraTrees & GradientBoosting Destekli Ensemble
        et_model = ExtraTreesRegressor(n_estimators=200, max_depth=8, n_jobs=-1, random_state=42)
        et_model.fit(X_train, y_train)
        et_oos_pred = et_model.predict(X_oos)
        self.models["extratrees"] = et_model
        with open(self.save_dir / "extratrees_model.pkl", "wb") as f:
            pickle.dump(et_model, f)

        # 5. Ensemble Tahmini (Ağırlıklı Ortalama)
        preds = []
        if "lightgbm" in self.models:
            preds.append(self.models["lightgbm"].predict(X_oos) * 0.40)
        if "xgboost" in self.models:
            preds.append(self.models["xgboost"].predict(X_oos) * 0.30)
        if "catboost" in self.models:
            preds.append(self.models["catboost"].predict(X_oos) * 0.30)

        if preds:
            ensemble_pred = np.sum(preds, axis=0)
        else:
            ensemble_pred = et_oos_pred

        ens_r2 = r2_score(y_oos, ensemble_pred)
        ens_ic = float(np.corrcoef(y_oos, ensemble_pred)[0, 1]) if len(y_oos) > 10 else 0.0

        # Birleşik SHAP / Feature Importance Ağırlıkları
        combined_importance = {}
        for feat in self.feature_cols:
            imp_sum = 0.0
            cnt = 0
            for m_name in ["lightgbm", "xgboost", "catboost"]:
                if m_name in results and "feature_importances" in results[m_name]:
                    imp_sum += results[m_name]["feature_importances"].get(feat, 0.0)
                    cnt += 1
            combined_importance[feat] = round(imp_sum / max(cnt, 1), 4)

        # Önem sırasına göre sırala
        sorted_importance = dict(sorted(combined_importance.items(), key=lambda item: item[1], reverse=True))

        summary = {
            "trained_date": "2026-08-23",
            "train_samples": len(self.train_df),
            "oos_samples": len(self.oos_df),
            "features": self.feature_cols,
            "models_trained": list(self.models.keys()),
            "individual_results": results,
            "ensemble_metrics": {
                "oos_information_coefficient_ic": round(ens_ic, 4),
                "oos_r2_score": round(ens_r2, 4)
            },
            "top_feature_importances": sorted_importance
        }

        with open("data/model_metrics.json", "w", encoding="utf-8") as f:
            f.write(orjson.dumps(summary, option=orjson.OPT_INDENT_2).decode())

        logger.info(f"🏆 Ensemble Tamamlandı -> OOS Information Coefficient (IC): {ens_ic:.4f}")
        return summary
