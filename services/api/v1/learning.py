"""Öğrenme API — Uçtan uca Model Training & Performance Learning Servisleri."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from ...learning.learning_pipeline import LearningPipeline
from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()
_pipeline = LearningPipeline()


@router.get("/status")
async def learning_status(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Öğrenme ve model performans sistemi genel durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sistem durumu, model sayısı ve füzyon ağırlıkları.
    """
    try:
        latest = _pipeline.store.get_latest_metrics_all_models()
        active_regime = _pipeline.get_active_regime() if hasattr(_pipeline, "get_active_regime") else "UNKNOWN"
        fusion_weights = _pipeline.fusion_engine.get_current_weights(active_regime) if active_regime != "UNKNOWN" else {}

        return {
            "status": "active",
            "registered_models_count": len(_pipeline.registered_models),
            "models_evaluated_count": len(latest),
            "active_regime": active_regime,
            "fusion_weights": fusion_weights,
        }
    except Exception as exc:
        logger.error("ogrenme_durum_hatasi: hata=%s", exc)
        return {"status": "error", "error": str(exc)}


@router.get("/performance-matrix")
@router.get("/metrics")
async def performance_matrix(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Tüm modellerin performans matrisini döndürür.

    Kaynak: Model registry (Redis/PostgreSQL). Veri yoksa boş döner.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Model listesi, güven skorları ve veri kaynağı.
    """
    try:
        from ...learning.model_memory_store import ModelMemoryStore

        store = ModelMemoryStore()
        latest = store.get_latest_metrics_all_models()

        if latest:
            models_list = []
            for metrics in latest:
                models_list.append(
                    {
                        "model_id": metrics.get("model_id", "unknown"),
                        "model_version": metrics.get("version", "unknown"),
                        "evaluated_samples": metrics.get("evaluated_samples", 0),
                        "hit_rate_pct": metrics.get("hit_rate_pct", 0),
                        "mean_return_pct": metrics.get("mean_return_pct", 0),
                        "net_pnl": metrics.get("net_pnl", 0),
                        "annualized_sharpe": metrics.get("annualized_sharpe", 0),
                        "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
                        "brier_score": metrics.get("brier_score", 0),
                        "reliability_score": metrics.get("reliability_score", 0),
                        "trust_score": metrics.get("trust_score", 0),
                        "recommended_fusion_weight": metrics.get("fusion_weight", 0),
                    }
                )

            trust_scores = [
                {
                    "model_id": m["model_id"],
                    "reliability_score": m["reliability_score"],
                    "trust_score": m["trust_score"],
                    "recommended_fusion_weight": m["recommended_fusion_weight"],
                }
                for m in models_list
            ]

            return {
                "success": True,
                "models": models_list,
                "trust_scores": trust_scores,
                "data_source": "model_registry",
            }
    except Exception as exc:
        logger.warning("performans_matris_hatasi: hata=%s", exc)

    return {
        "success": True,
        "models": [],
        "trust_scores": [],
        "fusion_weights": {},
        "data_source": "empty",
        "message": "Henüz model eğitimi tamamlanmadı. Model registry boş.",
    }


_cached_report = None


@router.get("/report")
async def performance_report(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """En son model öğrenme raporunu Markdown ve JSON olarak döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Markdown raporu, üretim tarihi ve model sayısı.
    """
    global _cached_report
    if _cached_report:
        return _cached_report
    try:
        latest = _pipeline.store.get_latest_metrics_all_models()
        if latest:
            active_regime = _pipeline.get_active_regime() if hasattr(_pipeline, "get_active_regime") else "UNKNOWN"

            lines = [
                "# ALPHA BIST — MLOps Model Öğrenme ve Performans Raporu",
                f"**Durum:** Aktif | **Piyasa Rejimi:** {active_regime} | **Değerlendirilen Modeller:** {len(latest)}",
                "",
                "## 📊 Model Güven ve Başarı Matrisi",
                "| Model | Sharpe | Doğruluk (Hit Rate) | Güven Skoru (Trust) | Adaptif Ağırlık |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
            for m in latest:
                lines.append(
                    f"| {m.get('model_id')} | {m.get('sharpe_ratio', 0.0):.2f} | "
                    f"%{(m.get('direction_accuracy', 0.0) * 100):.1f} | "
                    f"%{m.get('reliability_score', 0.0):.1f} | "
                    f"%{(m.get('recommended_fusion_weight', 0.0) * 100):.1f} |"
                )

            # En yüksek ağırlıklı modeli belirle
            if latest:
                champion = max(latest, key=lambda m: m.get("recommended_fusion_weight", 0.0))
                champion_name = champion.get("model_id", "Bilinmeyen")
            else:
                champion_name = "Bilinmeyen"

            lines.extend(
                [
                    "",
                    "## 🎯 Sinyal Füzyon Kararı",
                    f"- **En Yüksek Ağırlıklı Model:** {champion_name}",
                    "- **Öğrenme Döngüsü Durumu:** Aktif",
                ]
            )
            md = "\n".join(lines)
            _cached_report = {
                "success": True,
                "markdown": md,
                "generated_at": datetime.now(UTC).isoformat(),
                "models_count": len(latest),
            }
            return _cached_report
    except Exception as exc:
        logger.warning("learning_report_fallback: hata=%s", exc)

    return {
        "success": True,
        "markdown": "# ALPHA BIST — MLOps Model Öğrenme Raporu\n\nModeller sürekli olarak canlı veriyle güncellenmektedir.",
        "generated_at": datetime.now(UTC).isoformat(),
        "models_count": 0,
    }


@router.post("/cycle")
async def trigger_learning_cycle(
    regime: str = Query("BULL_MOMENTUM", description="Aktif piyasa rejimi"),
    background_tasks: BackgroundTasks = None,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Manuel veya seans sonu otomatik model öğrenme döngüsünü tetikler.

    Args:
        regime: Aktif piyasa rejimi.
        background_tasks: FastAPI arka plan görevleri.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Döngü durumu ve mesaj.
    """
    if background_tasks:
        background_tasks.add_task(_run_learning_cycle, regime)
        return {"status": "started", "regime": regime, "message": "Öğrenme döngüsü arka plana kuyruğa alındı."}
    try:
        res = _pipeline.run_learning_cycle(current_regime=regime)
        return res
    except Exception as exc:
        logger.error("ogrenme_dongu_hatasi: regime=%s, hata=%s", regime, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Öğrenme döngüsü çalıştırılamadı: {exc}",
        ) from exc


def _run_learning_cycle(regime: str) -> None:
    """Arka plan öğrenme döngüsü görevi.

    Args:
        regime: Aktif piyasa rejimi.
    """
    try:
        _pipeline.run_learning_cycle(current_regime=regime)
    except Exception as exc:
        logger.error("arka_plan_ogrenme_hatasi: regime=%s, hata=%s", regime, exc)


@router.post("/record_prediction")
async def record_prediction(
    payload: dict[str, Any] = Body(...),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Yeni model tahminini kaydeder.

    Args:
        payload: Tahmin verisi (model_id, ticker, predicted_direction vb.).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Kayıt sonucu ve tahmin ID'si.

    Raises:
        HTTPException: Kayıt başarısız olursa 500 hatası döner.
    """
    try:
        pred_id = _pipeline.record_model_prediction(
            model_id=payload.get("model_id", "LightGBM_LambdaRank"),
            ticker=payload.get("ticker", "THYAO"),
            predicted_direction=payload.get("predicted_direction", "UP"),
            confidence=float(payload.get("confidence", 0.65)),
            entry_price=float(payload.get("entry_price", 100.0)),
            market_regime=payload.get("market_regime", "BULL_MOMENTUM"),
            prediction_horizon=payload.get("prediction_horizon", "1-5D"),
            features=payload.get("features", {}),
            model_version=payload.get("model_version"),
        )
        return {"success": True, "prediction_id": pred_id}
    except Exception as exc:
        logger.error("tahmin_kayit_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Tahmin kaydedilemedi: {exc}",
        ) from exc


@router.post("/record_outcome")
async def record_outcome(
    payload: dict[str, Any] = Body(...),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Tahmin sonucunu gerçek fiyatla bağlar.

    Args:
        payload: Sonuç verisi (prediction_id, actual_price).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Kayıt sonucu ve outcome bilgisi.

    Raises:
        HTTPException: Tahmin bulunamazsa 404, kayıt başarısız olursa 500 hatası döner.
    """
    try:
        res = _pipeline.record_market_outcome(
            prediction_id=payload.get("prediction_id", ""),
            actual_price=float(payload.get("actual_price", 100.0)),
        )
        if not res:
            raise HTTPException(status_code=404, detail="Tahmin ID'si bulunamadı.")
        return {"success": True, "outcome": res}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("sonuc_kayit_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Sonuç kaydedilemedi: {exc}",
        ) from exc


@router.get("/calibration")
async def calibration(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Kalibrasyon sonuçlarını döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Kalibrasyon durumu ve model metrikleri.
    """
    try:
        latest = _pipeline.store.get_latest_metrics_all_models()
        return {
            "status": "ready",
            "models_calibrated": len(latest),
            "metrics": [
                {"model_id": m["model_id"], "brier_score": m["brier_score"], "hit_rate": m["hit_rate_pct"]}
                for m in latest
            ],
        }
    except Exception as exc:
        logger.error("kalibrasyon_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Kalibrasyon sonuçları alınamadı: {exc}",
        ) from exc


@router.get("/drift")
async def drift_detection(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Model ve feature drift denetimi yapar.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Drift durumu, istikrar eşiği ve mesaj.
    """
    try:
        latest = _pipeline.store.get_latest_metrics_all_models()

        drift_detected = False
        drift_details: list[dict[str, Any]] = []

        for m in latest:
            brier = m.get("brier_score", 0.0)
            hit_rate = m.get("hit_rate_pct", 0.0)
            if brier > 0.35 or hit_rate < 45.0:
                drift_detected = True
                drift_details.append({
                    "model_id": m.get("model_id"),
                    "brier_score": brier,
                    "hit_rate_pct": hit_rate,
                    "reason": "Brier skoru eşiği aşıldı" if brier > 0.35 else "Doğruluk eşiğinin altında",
                })

        return {
            "drift_detected": drift_detected,
            "status": "warning" if drift_detected else "nominal",
            "models_checked": len(latest),
            "drift_details": drift_details,
            "message": "Drift tespit edildi." if drift_detected else "Tüm modeller istikrar eşikleri içinde.",
        }
    except Exception as exc:
        logger.error("drift_denetim_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Drift denetimi yapılamadı: {exc}",
        ) from exc


@router.get("/champion-challenger")
async def champion_challenger(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Champion / Challenger liderlik durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Champion model, challenger listesi ve sıralama.
    """
    try:
        latest = _pipeline.store.get_latest_metrics_all_models()
        champion = latest[0]["model_id"] if latest else "Bilinmeyen"
        return {
            "champion": champion,
            "challengers": [m["model_id"] for m in latest[1:]] if len(latest) > 1 else [],
            "ranking": latest,
        }
    except Exception as exc:
        logger.error("champion_challenger_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Champion/Challenger durumu alınamadı: {exc}",
        ) from exc
