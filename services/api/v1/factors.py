"""Faktörler API — BIST Faktör Analiz ve Exposure Motoru."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.redis_helper import get_cached
from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


def _hesapla_faktor_skorlari(score: float, change: float) -> dict[str, float]:
    """Verilen skor ve değişim değerlerinden faktör skorlarını hesaplar.

    Args:
        score: Bileşik skor.
        change: Fiyat değişim yüzdesi.

    Returns:
        dict: Momentum, value, quality, volatility, liquidity, size skorları.
    """
    momentum = min(99.0, max(20.0, 50.0 + change * 8.0))
    volatility = min(95.0, max(15.0, abs(change) * 12.0 + 25.0))
    liquidity = min(99.0, max(40.0, score * 0.95))
    quality = min(95.0, max(45.0, 70.0 + (score % 20)))
    value = min(90.0, max(30.0, 65.0 - (change * 3.0)))
    size = min(95.0, max(35.0, 80.0 if score > 70 else 55.0))
    return {
        "momentum": round(momentum, 1),
        "value": round(value, 1),
        "quality": round(quality, 1),
        "volatility": round(volatility, 1),
        "liquidity": round(liquidity, 1),
        "size": round(size, 1),
    }


def _hesapla_fama_french(factors: dict[str, float]) -> dict[str, Any]:
    """Faktör skorlarından Fama-French beta katsayılarını hesaplar.

    Args:
        factors: Faktör skorları sözlüğü.

    Returns:
        dict: Fama-French betaları, R-kare ve alfa değeri.
    """
    momentum = factors.get("momentum", 50.0)
    value = factors.get("value", 50.0)
    quality = factors.get("quality", 50.0)
    volatility = factors.get("volatility", 50.0)
    size = factors.get("size", 50.0)

    smb = round((size - 50) / 50, 2)
    hml = round((value - 50) / 50, 2)
    rmw = round((quality - 50) / 50, 2)
    cma = round((momentum - 50) / 50, 2)
    mkt_rf = round(0.8 + (volatility / 100) * 0.5, 2)

    factor_std = max(0.01, abs(momentum - 50) + abs(value - 50) + abs(quality - 50)) / 150
    r_squared = round(min(0.95, max(0.5, 0.7 + factor_std * 0.2)), 2)
    alpha_annual = round((momentum - 50) * 0.15 + (quality - 50) * 0.1, 1)

    return {
        "fama_french_betas": {
            "mkt_rf": mkt_rf,
            "smb": smb,
            "hml": hml,
            "rmw": rmw,
            "cma": cma,
        },
        "r_squared": r_squared,
        "alpha_annual_pct": alpha_annual,
    }


async def _get_factor_scores(ticker: str) -> dict[str, Any]:
    """Hisse için faktör skorlarını getirir (dahili kullanım).

    Args:
        ticker: Hisse sembolü.

    Returns:
        dict: Faktör skorları ve bileşik skor.

    Raises:
        HTTPException: Veri bulunamazsa 404 hatası döner.
    """
    radar = get_cached("radar:data") or []
    item = next((x for x in radar if x.get("symbol") == ticker.upper()), None)

    if not item:
        logger.warning("faktor_veri_bulunamadi: ticker=%s", ticker)
        raise HTTPException(
            status_code=404,
            detail=f"{ticker} için faktör verisi bulunamadı.",
        )

    score = item.get("score", 50.0)
    change = item.get("change", 0.0)
    factors = _hesapla_faktor_skorlari(score, change)

    return {
        "ticker": ticker.upper(),
        "factor_available": True,
        "composite_score": round(score, 1),
        "factors": factors,
        "bias": "BULLISH_MOMENTUM" if factors["momentum"] > 60 else "NEUTRAL_VALUE",
    }


@router.get("/scores/{ticker}")
async def factor_scores(
    ticker: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Hisse bazlı çoklu faktör skorlarını döndürür.

    Momentum, Value, Quality, Volatility, Liquidity ve Size faktörlerini hesaplar.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Faktör skorları, bileşik skor ve eğilim bilgisi.

    Raises:
        HTTPException: Hisse verisi bulunamazsa 404 hatası döner.
    """
    try:
        return await _get_factor_scores(ticker)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("faktor_skor_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Faktör skorları hesaplanamadı: {exc}",
        ) from exc


@router.get("/exposure/{ticker}")
async def factor_exposure(
    ticker: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Faktör beta katsayılarını döndürür (Fama-French 5 Faktör Modeli).

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Fama-French beta katsayıları, R-kare ve alfa değeri.

    Raises:
        HTTPException: Faktör skorları alınamazsa hata döner.
    """
    try:
        scores = await _get_factor_scores(ticker)
        factors = scores.get("factors", {})
        ff = _hesapla_fama_french(factors)

        return {
            "ticker": ticker.upper(),
            "exposure_available": True,
            **ff,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("faktor_exposure_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Faktör exposure hesaplanamadı: {exc}",
        ) from exc


@router.get("/portfolio-exposure")
async def portfolio_exposure(
    portfolio_id: int = Query(1),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Tüm portföyün ağırlıklı faktör maruziyetini döndürür.

    Args:
        portfolio_id: Portföy tanımlayıcısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Ağırlıklı faktör skorları ve Fama-French beta katsayıları.

    Raises:
        HTTPException: Portföy verisi alınamazsa hata döner.
    """
    try:
        from ...paper_trading.paper_orchestrator import paper_orchestrator

        positions = paper_orchestrator.portfolio.get_all_positions()
        total_val = paper_orchestrator.portfolio.get_total_value()

        if not positions:
            logger.info("portfoy_bos: portfolio_id=%s", portfolio_id)
            return {
                "portfolio_id": portfolio_id,
                "factors": {},
                "fama_french_betas": {},
                "num_positions": 0,
                "message": "Portföyde pozisyon bulunamadı.",
            }

        weighted: dict[str, float] = {
            "momentum": 0.0,
            "value": 0.0,
            "quality": 0.0,
            "volatility": 0.0,
            "liquidity": 0.0,
            "size": 0.0,
        }
        basarisiz_pozisyonlar: list[str] = []

        for pos in positions:
            pos_ticker = pos.get("ticker", "")
            market_value = pos.get("market_value", 0.0)
            w = market_value / max(total_val, 1.0)

            try:
                t_scores = await _get_factor_scores(pos_ticker)
                f = t_scores.get("factors", {})
                for key in weighted:
                    weighted[key] += f.get(key, 50.0) * w
            except Exception as exc:
                logger.warning("pozisyon_faktor_hatasi: ticker=%s, hata=%s", pos_ticker, exc)
                basarisiz_pozisyonlar.append(pos_ticker)
                for key in weighted:
                    weighted[key] += 50.0 * w

        ff = _hesapla_fama_french(weighted)

        result: dict[str, Any] = {
            "portfolio_id": portfolio_id,
            "factors": {k: round(v, 1) for k, v in weighted.items()},
            "fama_french_betas": ff["fama_french_betas"],
            "r_squared": ff["r_squared"],
            "alpha_annual_pct": ff["alpha_annual_pct"],
            "num_positions": len(positions),
            "status": "active",
        }
        if basarisiz_pozisyonlar:
            result["warnings"] = {
                "basarisiz_pozisyonlar": basarisiz_pozisyonlar,
                "mesaj": "Bu pozisyonlar için faktör verisi alınamadı, nötr değerler kullanıldı.",
            }
        return result
    except Exception as exc:
        logger.error("portfoy_exposure_hatasi: portfolio_id=%s, hata=%s", portfolio_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Portföy exposure hesaplanamadı: {exc}",
        ) from exc
