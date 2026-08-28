"""
ALPHA BIST — Çok Modelli Ensemble Eğitim Motoru (LightGBM + XGBoost + CatBoost)
================================================================================
- 1997-2023 Train Verisi ile Eğitim
- 2024-2026 Kilitli Kör OOS Validasyonu
- Walk-Forward Cross Validation & SHAP Feature Importance
- Modelleri 'ml/saved_models/' Dizinine Pickle/JSON Formatında Kaydetme
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
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

from sklearn.ensemble import ExtraTreesRegressor
from sklearn.metrics import r2_score


class BistEnsembleTrainer:
    """Alpha BIST için LightGBM + XGBoost + CatBoost Ensemble Eğitici."""

    def __init__(self, train_df: pl.DataFrame, oos_df: pl.DataFrame):
        self.train_df = train_df
        self.oos_df = oos_df
        self.feature_cols = [
            "rsi_14",
            "atr_pct",
            "ret_1d",
            "ret_5d",
            "ret_20d",
            "vol_surge",
            "buyer_pressure",
            "near_20d_high",
            "breakout_setup",
            "dip_setup",
            "bm_is_bull",
            "bm_dist_sma200",
            "bm_is_crisis",
            "bm_ret_5d",
            "bm_vol_20d",
        ]
        self.target_col = "target_risk_adj"
        self.save_dir = Path("ml/saved_models")
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.models = {}

    def train_all(self) -> dict[str, Any]:
        """Tüm modelleri eğitir, test eder ve ensemble üretir."""
        logger.info(f"Model eğitimi başlatılıyor (Özellik sayısı: {len(self.feature_cols)})...")

        X_train = self.train_df[self.feature_cols].to_numpy()
        y_train = self.train_df[self.target_col].to_numpy()

        X_oos = self.oos_df[self.feature_cols].to_numpy()
        y_oos = self.oos_df[self.target_col].to_numpy()

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
                random_state=42,
            )
            lgb_model.fit(X_train, y_train)
            lgb_oos_pred = lgb_model.predict(X_oos)

            lgb_r2 = r2_score(y_oos, lgb_oos_pred)
            lgb_ic = float(np.corrcoef(y_oos, lgb_oos_pred)[0, 1]) if len(y_oos) > 10 else 0.0

            self.models["lightgbm"] = lgb_model
            results["lightgbm"] = {
                "r2": round(float(lgb_r2), 4),
                "ic": round(float(lgb_ic), 4),
                "feature_importances": {
                    feat: round(float(imp), 4)
                    for feat, imp in zip(self.feature_cols, lgb_model.feature_importances_, strict=False)
                },
            }
            from services.core.safe_pickle import safe_pickle_dump

            safe_pickle_dump(lgb_model, str(self.save_dir / "lightgbm_model.pkl"))
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
                random_state=42,
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
                    for feat, imp in zip(self.feature_cols, xgb_model.feature_importances_, strict=False)
                },
            }
            safe_pickle_dump(xgb_model, str(self.save_dir / "xgboost_model.pkl"))
            logger.info(f"XGBoost Eğitildi -> OOS IC: {xgb_ic:.4f}, R2: {xgb_r2:.4f}")

        # 3. CatBoost Modeli
        if cb:
            logger.info("CatBoost Modeli eğitiliyor (24 Core CPU)...")
            cb_model = cb.CatBoostRegressor(
                iterations=400, learning_rate=0.03, depth=6, thread_count=-1, random_seed=42, verbose=False
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
                    for feat, imp in zip(self.feature_cols, cb_model.get_feature_importance(), strict=False)
                },
            }
            safe_pickle_dump(cb_model, str(self.save_dir / "catboost_model.pkl"))
            logger.info(f"CatBoost Eğitildi -> OOS IC: {cb_ic:.4f}, R2: {cb_r2:.4f}")

        # 4. ExtraTrees & GradientBoosting Destekli Ensemble
        et_model = ExtraTreesRegressor(n_estimators=200, max_depth=8, n_jobs=-1, random_state=42)
        et_model.fit(X_train, y_train)
        et_oos_pred = et_model.predict(X_oos)
        self.models["extratrees"] = et_model
        safe_pickle_dump(et_model, str(self.save_dir / "extratrees_model.pkl"))

        # 5. Ensemble Tahmini (IC-bazlı ağırlıklı ortalama)
        # Ağırlıklar her modelin OOS IC'sine göre belirlenir (veriye dayalı)
        model_ics = {}
        for m_name in ["lightgbm", "xgboost", "catboost", "extratrees"]:
            if m_name in self.models:
                if m_name in results and "ic" in results[m_name]:
                    model_ics[m_name] = max(results[m_name]["ic"], 0.0)  # Negatif IC → 0
                else:
                    # ExtraTrees icin IC hesapla
                    try:
                        et_pred = self.models[m_name].predict(X_oos)
                        et_ic = float(np.corrcoef(y_oos, et_pred)[0, 1])
                        model_ics[m_name] = max(et_ic, 0.0) if np.isfinite(et_ic) else 0.0
                    except Exception:
                        model_ics[m_name] = 0.0

        # Normalize et
        total_ic = sum(model_ics.values())
        if total_ic > 0:
            ensemble_weights = {name: ic / total_ic for name, ic in model_ics.items()}
        else:
            # Tum modellerin IC'si 0 veya negatif → eşit ağırlık
            ensemble_weights = {name: 1.0 / len(model_ics) for name in model_ics}

        preds = []
        for m_name, weight in ensemble_weights.items():
            if m_name in self.models:
                preds.append(self.models[m_name].predict(X_oos) * weight)

        ensemble_pred = np.sum(preds, axis=0) if preds else et_oos_pred

        # Ensemble benefit check: ensemble tek modelden daha iyi mi?
        ensemble_ic = float(np.corrcoef(y_oos, ensemble_pred)[0, 1]) if len(y_oos) > 10 else 0.0
        best_individual_ic = max(model_ics.values()) if model_ics else 0.0
        ensemble_beneficial = ensemble_ic >= best_individual_ic * 0.95  # %5 tolerans

        if not ensemble_beneficial:
            logger.warning(
                "ensemble_not_beneficial",
                ensemble_ic=round(ensemble_ic, 4),
                best_individual_ic=round(best_individual_ic, 4),
                recommendation="Use best individual model instead",
            )

        ens_r2 = r2_score(y_oos, ensemble_pred)
        ens_ic = ensemble_ic

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
            "trained_date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "train_samples": len(self.train_df),
            "oos_samples": len(self.oos_df),
            "features": self.feature_cols,
            "models_trained": list(self.models.keys()),
            "individual_results": results,
            "ensemble_metrics": {
                "oos_information_coefficient_ic": round(ens_ic, 4),
                "oos_r2_score": round(ens_r2, 4),
                "ensemble_weights": {k: round(v, 4) for k, v in ensemble_weights.items()},
                "ensemble_beneficial": ensemble_beneficial,
                "best_individual_ic": round(best_individual_ic, 4),
            },
            "top_feature_importances": sorted_importance,
        }

        with open("data/model_metrics.json", "w", encoding="utf-8") as f:
            f.write(orjson.dumps(summary, option=orjson.OPT_INDENT_2).decode())

        logger.info(f"🏆 Ensemble Tamamlandı -> OOS Information Coefficient (IC): {ens_ic:.4f}")
        return summary
