"""Makro API — Canlı küresel makro veri motoru (DXY, VIX, Altın, Brent, USD/TRY, ABD 10Y)."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

_CACHE_TTL = 120
_last_macro_fetch = 0.0
_cached_macro_data: dict[str, Any] = {}

# Makro sembolleri
MAKRO_SEMBOLLERI: dict[str, str] = {
    "usd_try": "USDTRY=X",
    "eur_try": "EURTRY=X",
    "gold_ounce": "GC=F",
    "brent_crude": "BZ=F",
    "vix": "^VIX",
    "us10y": "^TNX",
    "dxy": "DX-Y.NYB",
}


def _fetch_live_macro_data() -> dict[str, Any]:
    """Canlı makro verileri yfinance'den çeker ve önbelleğe alır.

    Returns:
        dict: DXY, VIX, altın, brent, USD/TRY, ABD 10Y ve türev metrikler.
    """
    global _last_macro_fetch, _cached_macro_data
    now = time.time()

    if _cached_macro_data and (now - _last_macro_fetch < _CACHE_TTL):
        return _cached_macro_data

    _last_macro_fetch = now

    result: dict[str, Any] = {
        "updated_at": datetime.now(UTC).isoformat(),
        "indicators": ["USDTRY", "EURTRY", "CDS", "VIX", "DXY", "BRENT", "GOLD", "US10Y"],
    }

    try:
        tickers = yf.Tickers(" ".join(MAKRO_SEMBOLLERI.values()))
        for key, sym in MAKRO_SEMBOLLERI.items():
            try:
                t = tickers.tickers.get(sym)
                if t:
                    fi = t.fast_info
                    last = getattr(fi, "last_price", None) or getattr(fi, "previous_close", None)
                    prev = getattr(fi, "previous_close", last)
                    if last is not None:
                        result[key] = round(float(last), 2 if key not in ["gold_ounce", "turkey_cds_5y"] else 1)
                        if prev and last:
                            chg = ((last - prev) / prev) * 100
                            result[f"{key}_change_pct"] = round(float(chg), 2)
            except Exception as item_err:
                logger.warning("makro_sembol_hatasi: sembol=%s, hata=%s", sym, item_err)

        # VIX'ten türetilen canlı risk iştahı hesaplaması
        vix_val = result.get("vix", 15.0)
        result["vix_level"] = vix_val
        result["global_risk_appetite"] = round(max(0.1, min(0.95, 1.0 - (vix_val / 45.0))), 2)
        result["em_risk_appetite"] = round(max(0.1, min(0.95, result["global_risk_appetite"] * 0.9)), 2)

        # Frontend için anahtar eşlemesi
        if "gold_ounce_change_pct" in result:
            result["gold_change_pct"] = result["gold_ounce_change_pct"]
        if "brent_crude_change_pct" in result:
            result["brent_change_pct"] = result["brent_crude_change_pct"]

        # UI Mapping & Dinamik Rejim Yorumu
        result["usd_strength"] = round(max(0.0, min(1.0, (result.get("dxy", 100) - 90) / 20)), 2)
        result["oil_pressure"] = round(max(0.0, min(1.0, (result.get("brent_crude", 80) - 60) / 60)), 2)

        # Dinamik Makro Yorum ve BIST Etki Puanı
        dxy_v = result.get("dxy", 100)
        brent_v = result.get("brent_crude", 85)

        commentary_parts: list[str] = []
        if dxy_v > 103:
            commentary_parts.append(
                "Dolar küresel çapta güçlü (Gelişmekte olan piyasalara sermaye akışı baskı altında)."
            )
        else:
            commentary_parts.append("Dolar endeksi stabil (Gelişmekte olan piyasalar için nötr-pozitif ortam).")

        if brent_v > 90:
            commentary_parts.append(
                f"Brent petrol ({brent_v:.1f} $) yüksek (Cari denge ve sanayi marjları üzerinde maliyet baskısı)."
            )
        else:
            commentary_parts.append(f"Brent petrol ({brent_v:.1f} $) dengeli seviyelerde.")

        result["macro_commentary"] = " ".join(commentary_parts)
        result["bist_macro_bias"] = "POZİTİF" if dxy_v < 104 else "NÖTR"

        _cached_macro_data = result
        _last_macro_fetch = now
    except Exception as exc:
        logger.warning("makro_veri_hatasi: hata=%s", exc)
        if not _cached_macro_data:
            _cached_macro_data = result

    return _cached_macro_data


@router.get("/overview")
@router.get("/world")
@router.get("/state")
@router.get("/indicators")
async def macro_overview(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Küresel makro piyasa durumu ve risk faktörlerini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Makro göstergeler, risk iştahı ve yorum.
    """
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, _fetch_live_macro_data)
        return data
    except Exception as exc:
        logger.error("makro_overview_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Makro veriler alınamadı: {exc}",
        ) from exc


@router.get("/impact/{ticker}")
async def macro_impact(
    ticker: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Hisse bazlı makro etki ve duyarlılık analizini döndürür.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Faiz, döviz ve enflasyon duyarlılık katsayıları.

    Raises:
        HTTPException: Duyarlılık verisi bulunamazsa 404 hatası döner.
    """
    try:
        from ...intelligence.macro_sensitivity import MacroSensitivityEngine

        engine = MacroSensitivityEngine()
        result = engine.get_company_sensitivity(ticker) if hasattr(engine, "get_company_sensitivity") else {}
        if result:
            return {"ticker": ticker, "macro_available": True, **result}
    except Exception as exc:
        logger.warning("makro_duyarlilik_hatasi: ticker=%s, hata=%s", ticker, exc)

    raise HTTPException(
        status_code=404,
        detail=f"{ticker} için makro duyarlılık verisi bulunamadı.",
    )


@router.get("/sensitivity/{sector}")
async def sector_sensitivity(
    sector: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Sektör makro duyarlılık katsayılarını döndürür.

    Args:
        sector: Sektör adı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sektör duyarlılık katsayıları ve veri kaynağı.

    Raises:
        HTTPException: Sektör verisi bulunamazsa 404 hatası döner.
    """
    try:
        from ...intelligence.macro_sensitivity import MacroSensitivityEngine

        engine = MacroSensitivityEngine()
        result = engine.get_sector_sensitivity(sector) if hasattr(engine, "get_sector_sensitivity") else {}
        if result:
            return {"sector": sector, "sensitivity": result, "source": "macro_sensitivity_engine"}
    except Exception as exc:
        logger.warning("sektor_duyarlilik_hatasi: sector=%s, hata=%s", sector, exc)

    raise HTTPException(
        status_code=404,
        detail=f"{sector} sektörü için duyarlılık verisi bulunamadı.",
    )
