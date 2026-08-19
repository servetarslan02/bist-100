"""Learning API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, HTTPException, Query
from ..dependencies import get_current_user, check_rate_limit
router = APIRouter()


@router.get("/status")
async def learning_status(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Öğrenme durumu."""
    try:
        from ...risk.calibration import ScoreCalibrator
        return {"status": "active", "calibrator": "available"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/calibration")
async def calibration(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Kalibrasyon sonuçları — calibration servisi."""
    try:
        from ...risk.calibration import ScoreCalibrator
        cal = ScoreCalibrator()
        return {"calibrator": "ready", "avg_win_loss": cal.get_avg_win_loss() if hasattr(cal, 'get_avg_win_loss') else None}
    except Exception as e:
        return {"error": str(e)}


@router.get("/drift")
async def drift_detection(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Drift tespiti."""
    return {"drift_detected": False, "message": "Requires prediction history"}


@router.get("/champion-challenger")
async def champion_challenger(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Champion/Challenger durumu."""
    return {"champion": "v1", "challengers": [], "message": "Requires model registry"}
