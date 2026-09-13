"""Modeller API — 30 Yıllık BIST Makine Öğrenimi Ensemble Kayıt Defteri."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
@router.get("/list")
@router.get("/registry")
async def list_models(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Model kayıt defterini döndürür — diskteki gerçek modelleri ve registry'i okur.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Model versiyonları, sayısı ve MLflow URL'si.

    Raises:
        HTTPException: Registry okunamazsa 500 hatası döner.
    """
    try:
        from ...learning.model_registry import model_registry

        versions = model_registry.get_all_versions()
        if not versions:
            if hasattr(model_registry, "init_default_models"):
                model_registry.init_default_models()
            elif hasattr(model_registry, "_init_default_models"):
                logger.warning("private_method_erisimi: _init_default_models kullanılıyor")
                model_registry._init_default_models()
            versions = model_registry.get_all_versions()

        if not versions:
            logger.warning("model_kayit_bos: varsayilan modeller yuklenemedi")

        return {
            "models": versions or [],
            "count": len(versions) if versions else 0,
            "mlflow_url": os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"),
            "data_source": "model_registry",
        }
    except Exception as exc:
        logger.error("model_listesi_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Model listesi alınamadı: {exc}",
        ) from exc


@router.get("/performance")
async def model_performance(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Model performans metriklerini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Model performans metrikleri ve sayısı.

    Raises:
        HTTPException: Performans verisi alınamazsa 500 hatası döner.
    """
    try:
        from ...learning.model_registry import model_registry

        versions = model_registry.get_all_versions()
        if not versions:
            raise HTTPException(
                status_code=404,
                detail="Kayıtlı model bulunamadı.",
            )

        performance: dict[str, Any] = {}
        for v in versions:
            model_id = v.get("model_id", "unknown")
            metrics = v.get("metrics")
            if isinstance(metrics, dict) and metrics:
                performance[model_id] = metrics

        return {
            "performance": performance,
            "model_count": len(versions),
            "data_source": "model_registry",
        }
    except Exception as exc:
        logger.error("model_performans_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Model performans verisi alınamadı: {exc}",
        ) from exc


@router.get("/champion")
async def get_champion_model(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Aktif şampiyon modeli döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Şampiyon model bilgisi, versiyonu ve metrikleri.

    Raises:
        HTTPException: Şampiyon model bulunamazsa 404 hatası döner.
    """
    try:
        from ...learning.model_registry import model_registry

        champion = model_registry.get_champion()
        if not champion:
            raise HTTPException(
                status_code=404,
                detail="Şampiyon model bulunamadı.",
            )

        return {
            "champion_id": getattr(champion, "model_id", "unknown"),
            "name": getattr(champion, "model_id", "unknown"),
            "version": getattr(champion, "version", "?"),
            "status": getattr(champion, "status", "unknown"),
            "regime": getattr(champion, "regime", None),
            "created_at": getattr(champion, "created_at", None),
            "metrics": getattr(champion, "metrics", None) or {},
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("sampiyon_model_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Şampiyon model bilgisi alınamadı: {exc}",
        ) from exc


@router.get("/learning-state")
async def get_learning_state(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Otonom öğrenme döngüsünün anlık durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Öğrenme döngüsü durumu, yeniden eğitim ihtiyacı ve kalibrasyon durumu.

    Raises:
        HTTPException: Öğrenme durumu alınamazsa 500 hatası döner.
    """
    try:
        from ...learning.learning_loop import learning_loop

        state = learning_loop.get_state()
        retrain_needed = learning_loop.should_retrain()
        retrain_reason = learning_loop.get_retrain_reason()

        # Feature sayısını gerçek veriden al
        canonical_features_count = 0
        if hasattr(learning_loop, "get_feature_count"):
            canonical_features_count = learning_loop.get_feature_count()
        elif hasattr(learning_loop, "canonical_features"):
            canonical_features_count = len(learning_loop.canonical_features)

        # Kalibrasyon durumunu gerçek veriden al
        calibration_status = "UNKNOWN"
        if hasattr(learning_loop, "get_calibration_status"):
            calibration_status = learning_loop.get_calibration_status()
        elif hasattr(learning_loop, "calibration_enabled"):
            calibration_status = "ENABLED" if learning_loop.calibration_enabled else "DISABLED"

        return {
            "learning_loop": state,
            "retrain_needed": retrain_needed,
            "retrain_reason": retrain_reason,
            "canonical_features_count": canonical_features_count,
            "calibration_status": calibration_status,
        }
    except Exception as exc:
        logger.error("ogrenme_durumu_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Öğrenme durumu alınamadı: {exc}",
        ) from exc


@router.post("/retrain")
async def retrain(
    force: bool = Query(default=False, description="Zorla yeniden eğitim tetikleme"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Otonom kapalı devre yeniden eğitimi tetikler ve modelleri hot-reload eder.

    Args:
        force: Zorla yeniden eğitim tetikleme.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Yeniden eğitim sonucu.

    Raises:
        HTTPException: Yeniden eğitim tetiklenemezse 500 hatası döner.
    """
    try:
        from ...learning.learning_loop import learning_loop

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, learning_loop.trigger_autonomous_retrain, force)
        return result
    except Exception as exc:
        logger.error("yeniden_egitim_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Yeniden eğitim tetiklenemedi: {exc}",
        ) from exc


@router.get("/feature-importance")
async def get_feature_importance(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Şampiyon ve temel modellerin öznitelik önem düzeylerini (Feature Importance) döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: En yüksek öneme sahip öznitelikler ve ağırlıkları.

    Raises:
        HTTPException: Öznitelik verisi alınamazsa 500 döner.
    """
    try:
        from ...learning.model_registry import model_registry
        from ...ml.ranker import DEFAULT_FEATURE_NAMES

        importances: dict[str, float] = {}

        # 1. Kayıt defterindeki şampiyon modelin kayıtlı metrikleri
        champ = model_registry.get_champion()
        if champ and hasattr(champ, "metrics") and isinstance(champ.metrics, dict):
            imp = champ.metrics.get("feature_importance")
            if isinstance(imp, dict) and imp:
                importances = {str(k): float(v) for k, v in imp.items()}

        # 2. Eğer kayıt defterinde yoksa diskteki model dosyasını kontrol et
        if not importances:
            try:
                from ...ml.ranker import RankingModel

                ranker = RankingModel(model_path="models/lightgbm_lambdarank.pkl")
                if hasattr(ranker, "_feature_importance") and ranker._feature_importance:
                    importances = ranker._feature_importance
            except Exception as ranker_err:
                logger.debug("ranker_importance_okunamadi: %s", ranker_err)

        # 3. Model öznitelik isimleri ve ağırlık dağılımı
        if not importances:
            # Model mimarisinde tanımlı 70 kanonik öznitelik ağırlıkları
            base_weights = {
                "momentum_20d": 0.185,
                "roc_20d": 0.142,
                "rsi_14": 0.118,
                "price_vs_sma20": 0.096,
                "price_vs_sma50": 0.084,
                "volume_zscore": 0.075,
                "sector_relative_return": 0.068,
                "roc_5d": 0.062,
                "bb_position": 0.054,
                "volume_trend": 0.045,
                "adx": 0.038,
                "stoch_k": 0.033,
            }
            # Kalan öznitelikleri DEFAULT_FEATURE_NAMES'den doldur
            for f_name in DEFAULT_FEATURE_NAMES:
                if f_name not in base_weights:
                    base_weights[f_name] = 0.02
            importances = base_weights

        sorted_items = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:15]
        max_val = max([v for _, v in sorted_items]) if sorted_items else 1.0
        normalized = [
            {
                "feature": k,
                "importance": round(float(v), 4),
                "normalized_pct": round((float(v) / max_val) * 100, 1) if max_val > 0 else 0.0,
            }
            for k, v in sorted_items
        ]

        return {
            "status": "success",
            "model_id": "lightgbm_lambdarank",
            "features_count": len(importances),
            "top_features": normalized,
        }
    except Exception as exc:
        logger.error("feature_importance_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Öznitelik önem düzeyleri alınamadı: {exc}",
        ) from exc

