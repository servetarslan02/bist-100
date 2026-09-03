"""Tatil Yönetimi API — BIST tatil günleri yönetim uç noktaları."""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Ulusal tatil tarihleri (ay, gün)
ULUSAL_TATILLER: set[tuple[int, int]] = {
    (1, 1),   # Yılbaşı
    (4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    (5, 1),   # Emek ve Dayanışma Günü
    (5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    (7, 15),  # Demokrasi ve Millî Birlik Günü
    (8, 30),  # Zafer Bayramı
    (10, 29), # Cumhuriyet Bayramı
}


# =====================================================
# İstek/Yanıt Modelleri
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


class RemoveResponse(BaseModel):
    """Tatil kaldırma yanıtı."""

    success: bool
    message: str


# =====================================================
# Yardımcı Fonksiyonlar
# =====================================================


def _belirle_kaynak(tatil_tarihi: date, holiday_manager: Any) -> str:
    """Tatil gününün kaynağını belirler.

    Args:
        tatil_tarihi: Tatil tarihi.
        holiday_manager: Tatil yöneticisi örneği.

    Returns:
        str: Kaynak türü ("sudden", "national", "religious").
    """
    try:
        sudden = holiday_manager.get_sudden_holidays()
        if tatil_tarihi in sudden:
            return "sudden"
    except Exception:
        pass

    if (tatil_tarihi.month, tatil_tarihi.day) in ULUSAL_TATILLER:
        return "national"
    return "religious"


def _get_holiday_name_safe(holiday_manager: Any, d: date) -> str:
    """Tatil gününün adını güvenli şekilde getirir.

    Args:
        holiday_manager: Tatil yöneticisi örneği.
        d: Tatil tarihi.

    Returns:
        str: Tatil adı veya "Bilinmeyen tatil".
    """
    try:
        return holiday_manager.get_holiday_name(d)
    except AttributeError:
        try:
            return holiday_manager._get_holiday_name(d)
        except Exception:
            return "Bilinmeyen tatil"
    except Exception:
        return "Bilinmeyen tatil"


# =====================================================
# Uç Noktalar
# =====================================================


@router.get("/", response_model=HolidayListResponse)
async def list_holidays(
    year: int | None = Query(None, description="Yıl (varsayılan: mevcut yıl)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Tüm tatil günlerini listeler.

    Args:
        year: Filtrelenecek yıl (None ise mevcut yıl).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Tatil listesi, yarım günler ve toplam sayısı.
    """
    try:
        from ...core.holiday_manager import holiday_manager

        if year is None:
            year = date.today().year

        holidays = holiday_manager.get_holidays(year)
        half_days = holiday_manager.get_half_days(year)

        result = []
        for d in sorted(holidays):
            name = _get_holiday_name_safe(holiday_manager, d)
            is_half = d in half_days
            source = _belirle_kaynak(d, holiday_manager)

            result.append(
                HolidayResponse(
                    date=d.isoformat(),
                    name=name,
                    is_half_day=is_half,
                    source=source,
                )
            )

        return {
            "year": year,
            "holidays": result,
            "half_days": [d.isoformat() for d in sorted(half_days)],
            "total": len(result),
        }
    except Exception as exc:
        logger.error("tatil_listesi_hatasi: year=%s, hata=%s", year, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Tatil listesi alınamadı: {exc}",
        ) from exc


@router.get("/today", response_model=HolidayStatusResponse)
async def today_status(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Bugünün tatil durumunu kontrol eder.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Tatil durumu, yarım gün, işlem günü ve hafta sonu bilgisi.
    """
    try:
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
            name = _get_holiday_name_safe(holiday_manager, today)

        return {
            "date": today.isoformat(),
            "is_holiday": is_holiday,
            "is_half_day": is_half,
            "is_trading_day": is_trading,
            "is_weekend": is_weekend,
            "name": name,
        }
    except Exception as exc:
        logger.error("bugun_durum_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Bugünün tatil durumu alınamadı: {exc}",
        ) from exc


@router.get("/{year}", response_model=HolidayListResponse)
async def list_holidays_by_year(
    year: int,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Belirli bir yılın tatil günlerini listeler.

    Args:
        year: Yıl.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Tatil listesi, yarım günler ve toplam sayısı.
    """
    try:
        from ...core.holiday_manager import holiday_manager

        holidays = holiday_manager.get_holidays(year)
        half_days = holiday_manager.get_half_days(year)

        result = []
        for d in sorted(holidays):
            name = _get_holiday_name_safe(holiday_manager, d)
            is_half = d in half_days
            source = _belirle_kaynak(d, holiday_manager)

            result.append(
                HolidayResponse(
                    date=d.isoformat(),
                    name=name,
                    is_half_day=is_half,
                    source=source,
                )
            )

        return {
            "year": year,
            "holidays": result,
            "half_days": [d.isoformat() for d in sorted(half_days)],
            "total": len(result),
        }
    except Exception as exc:
        logger.error("yil_tatil_hatasi: year=%s, hata=%s", year, exc)
        raise HTTPException(
            status_code=500,
            detail=f"{year} yılı tatil listesi alınamadı: {exc}",
        ) from exc


@router.post("/", response_model=HolidayResponse)
async def add_holiday(
    req: HolidayAddRequest,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Manuel tatil ekler (anlık ilan edilen tatiller için).

    Args:
        req: Tatil ekleme isteği.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Eklenen tatil bilgisi.

    Raises:
        HTTPException: Geçersiz tarih veya çakışma durumunda hata döner.
    """
    try:
        from ...core.holiday_manager import holiday_manager

        try:
            d = date.fromisoformat(req.date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz tarih formatı. YYYY-MM-DD kullanın.") from None

        if holiday_manager.is_holiday(d):
            raise HTTPException(status_code=409, detail=f"{req.date} zaten tatil olarak kayıtlı.")

        holiday_manager.add_manual_holiday(d, req.reason)

        return {
            "date": d.isoformat(),
            "name": _get_holiday_name_safe(holiday_manager, d),
            "is_half_day": holiday_manager.is_half_day(d),
            "source": "manual",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("tatil_ekleme_hatasi: date=%s, hata=%s", req.date, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Tatil eklenemedi: {exc}",
        ) from exc


@router.delete("/{date_str}", response_model=RemoveResponse)
async def remove_holiday(
    date_str: str,
    reason: str = Query("", description="Kaldırma nedeni"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Tatil gününü kaldırır (iptal edilen tatiller için).

    Args:
        date_str: Tatil tarihi (YYYY-MM-DD).
        reason: Kaldırma nedeni.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Kaldırma sonucu ve mesaj.

    Raises:
        HTTPException: Geçersiz tarih veya tatil bulunamazsa hata döner.
    """
    try:
        from ...core.holiday_manager import holiday_manager

        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz tarih formatı. YYYY-MM-DD kullanın.") from None

        if not holiday_manager.is_holiday(d):
            raise HTTPException(status_code=404, detail=f"{date_str} tatil olarak kayıtlı değil.")

        holiday_manager.remove_holiday(d, reason)

        return {"success": True, "message": f"{date_str} tatil listesinden kaldırıldı."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("tatil_kaldirma_hatasi: date=%s, hata=%s", date_str, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Tatil kaldırılamadı: {exc}",
        ) from exc


@router.post("/sync", response_model=SyncResponse)
async def sync_holidays(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """BIST/KAP tatil takvimini senkronize eder.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Senkronizasyon sonucu, kaynak ve bulunan tatil sayısı.
    """
    try:
        from ...core.holiday_manager import holiday_manager

        synced = await holiday_manager.sync_from_bist()
        if synced:
            return {
                "success": True,
                "source": "BIST",
                "holidays_found": len(holiday_manager.get_holidays(date.today().year)),
                "message": "BIST tatil takvimi senkronize edildi.",
            }

        kap_holidays = await holiday_manager.check_kap_for_holidays()
        if kap_holidays:
            return {
                "success": True,
                "source": "KAP",
                "holidays_found": len(kap_holidays),
                "message": f"KAP'tan {len(kap_holidays)} tatil duyurusu bulundu.",
            }

        return {
            "success": False,
            "source": "none",
            "holidays_found": 0,
            "message": "Hiçbir kaynaktan tatil bilgisi çekilemedi. Proxy ayarlarını kontrol edin.",
        }
    except Exception as exc:
        logger.error("tatil_senkron_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Tatil senkronizasyonu başarısız: {exc}",
        ) from exc


@router.get("/audit/log")
async def get_audit_log(
    limit: int = Query(50, description="Son N kayıt"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Tatil değişiklik loglarını getirir (audit trail).

    Args:
        limit: Maksimum kayıt sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Audit log kayıtları ve toplam sayısı.
    """
    try:
        from ...core.holiday_manager import holiday_manager

        log = holiday_manager.get_audit_log(limit)
        return {"entries": log, "total": len(log)}
    except Exception as exc:
        logger.error("audit_log_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Audit log alınamadı: {exc}",
        ) from exc
