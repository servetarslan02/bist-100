from typing import Any

"""
ALPHA BIST — Holiday Management API v1

Tatil günleri yönetim endpoint'leri:
- GET  /holidays          — Tatil listesi
- GET  /holidays/{year}   — Yılın tatilleri
- GET  /holidays/today     — Bugün tatil mi?
- POST /holidays          — Manuel tatil ekle
- DELETE /holidays/{date}  — Tatil kaldır
- POST /holidays/sync     — BIST/KAP senkronizasyon
- GET  /holidays/audit    — Değişiklik logu
"""

from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..dependencies import check_rate_limit, get_current_user

logger = structlog.get_logger()
router = APIRouter()


# =====================================================
# Request/Response Models
# =====================================================


class HolidayAddRequest(BaseModel):
    """Manuel tatil ekleme isteği."""

    date: str = Field(..., description="Tatil tarihi (YYYY-MM-DD)", examples=["2026-12-31"])
    reason: str = Field("", description="Tatil nedeni", examples=["BIST anlık tatil ilanı"])


class HolidayRemoveRequest(BaseModel):
    """Tatil kaldırma isteği."""

    reason: str = Field("", description="Kaldırma nedeni", examples=["Tatil iptal edildi"])


class HolidayResponse(BaseModel):
    """Tatil yanıt modeli."""

    date: str
    name: str
    is_half_day: bool
    source: str  # "national", "religious", "manual", "sudden", "kap"


class HolidayListResponse(BaseModel):
    """Tatil listesi yanıtı."""

    year: int
    holidays: list[HolidayResponse]
    half_days: list[str]
    total: int


class HolidayStatusResponse(BaseModel):
    """Günlük tatil durumu."""

    date: str
    is_holiday: bool
    is_half_day: bool
    is_trading_day: bool
    is_weekend: bool
    name: str | None


class SyncResponse(BaseModel):
    """Senkronizasyon sonucu."""

    success: bool
    source: str
    holidays_found: int
    message: str


# =====================================================
# Endpoints
# =====================================================


@router.get("/", response_model=HolidayListResponse)
async def list_holidays(
    year: int | None = Query(None, description="Yıl (varsayılan: mevcut yıl)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Tüm tatil günlerini listele."""
    from ...core.holiday_manager import holiday_manager

    if year is None:
        year = date.today().year

    holidays = holiday_manager.get_holidays(year)
    half_days = holiday_manager.get_half_days(year)

    result = []
    for d in sorted(holidays):
        name = holiday_manager._get_holiday_name(d)
        is_half = d in half_days

        # Kaynağı belirle
        sudden = holiday_manager._sudden_detector.get_confirmed()
        if d in sudden:
            source = "sudden"
        elif (d.month, d.day) in [(1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29)]:
            source = "national"
        else:
            source = "religious"

        result.append(
            HolidayResponse(
                date=d.isoformat(),
                name=name,
                is_half_day=is_half,
                source=source,
            )
        )

    return HolidayListResponse(
        year=year,
        holidays=result,
        half_days=[d.isoformat() for d in sorted(half_days)],
        total=len(result),
    )


@router.get("/today", response_model=HolidayStatusResponse)
async def today_status(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Bugünün tatil durumunu kontrol et."""
    from ...core.holiday_manager import holiday_manager
    from ...core.market_calendar import get_market_calendar

    today = date.today()
    cal = get_market_calendar()

    is_holiday = holiday_manager.is_holiday(today)
    is_half = holiday_manager.is_half_day(today)
    is_trading = cal.is_trading_day(today)
    is_weekend = today.weekday() >= 5

    name = None
    if is_holiday:
        name = holiday_manager._get_holiday_name(today)

    return HolidayStatusResponse(
        date=today.isoformat(),
        is_holiday=is_holiday,
        is_half_day=is_half,
        is_trading_day=is_trading,
        is_weekend=is_weekend,
        name=name,
    )


@router.get("/{year}", response_model=HolidayListResponse)
async def list_holidays_by_year(
    year: int,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Belirli bir yılın tatil günlerini listele."""
    from ...core.holiday_manager import holiday_manager

    holidays = holiday_manager.get_holidays(year)
    half_days = holiday_manager.get_half_days(year)

    result = []
    for d in sorted(holidays):
        name = holiday_manager._get_holiday_name(d)
        is_half = d in half_days
        result.append(
            HolidayResponse(
                date=d.isoformat(),
                name=name,
                is_half_day=is_half,
                source="computed",
            )
        )

    return HolidayListResponse(
        year=year,
        holidays=result,
        half_days=[d.isoformat() for d in sorted(half_days)],
        total=len(result),
    )


@router.post("/", response_model=HolidayResponse)
async def add_holiday(
    req: HolidayAddRequest,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Manuel tatil ekle (anlık ilan edilen tatiller için)."""
    from ...core.holiday_manager import holiday_manager

    try:
        d = date.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz tarih formatı. YYYY-MM-DD kullanın.") from None

    if holiday_manager.is_holiday(d):
        raise HTTPException(status_code=409, detail=f"{req.date} zaten tatil olarak kayıtlı.")

    holiday_manager.add_manual_holiday(d, req.reason)

    return HolidayResponse(
        date=d.isoformat(),
        name=holiday_manager._get_holiday_name(d),
        is_half_day=holiday_manager.is_half_day(d),
        source="manual",
    )


@router.delete("/{date_str}")
async def remove_holiday(
    date_str: str,
    reason: str = Query("", description="Kaldırma nedeni"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Tatil gününü kaldır (iptal edilen tatiller için)."""
    from ...core.holiday_manager import holiday_manager

    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz tarih formatı. YYYY-MM-DD kullanın.") from None

    if not holiday_manager.is_holiday(d):
        raise HTTPException(status_code=404, detail=f"{date_str} tatil olarak kayıtlı değil.")

    holiday_manager.remove_holiday(d, reason)

    return {"success": True, "message": f"{date_str} tatil listesinden kaldırıldı."}


@router.post("/sync", response_model=SyncResponse)
async def sync_holidays(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """BIST/KAP tatil takvimini senkronize et."""
    from ...core.holiday_manager import holiday_manager

    # BIST web sitesinden çek
    synced = await holiday_manager.sync_from_bist()
    if synced:
        return SyncResponse(
            success=True,
            source="BIST",
            holidays_found=len(holiday_manager.get_holidays(date.today().year)),
            message="BIST tatil takvimi senkronize edildi.",
        )

    # KAP'tan çek
    kap_holidays = await holiday_manager.check_kap_for_holidays()
    if kap_holidays:
        return SyncResponse(
            success=True,
            source="KAP",
            holidays_found=len(kap_holidays),
            message=f"KAP'tan {len(kap_holidays)} tatil duyurusu bulundu.",
        )

    return SyncResponse(
        success=False,
        source="none",
        holidays_found=0,
        message="Hiçbir kaynaktan tatil bilgisi çekilemedi. Proxy ayarlarını kontrol edin.",
    )


@router.get("/audit/log")
async def get_audit_log(
    limit: int = Query(50, description="Son N kayıt"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Tatil değişiklik loglarını getir (audit trail)."""
    from ...core.holiday_manager import holiday_manager

    log = holiday_manager.get_audit_log(limit)
    return {"entries": log, "total": len(log)}
