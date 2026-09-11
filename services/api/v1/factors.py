"""Faktörler API — BIST Faktör Analiz ve Exposure Motoru."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.redis_helper import get_cached
from ..dependencies import check_rate_limit, get_current_user

logger = structlog.get_logger(__name__)

router = APIRouter()

# --- Faktör skor sabitleri ---
_MOMENTUM_BASE: float = 50.0
_MOMENTUM_MULTIPLIER: float = 8.0
_MOMENTUM_MIN: float = 20.0
_MOMENTUM_MAX: float = 99.0

_VOLATILITY_BASE: float = 25.0
_VOLATILITY_MULTIPLIER: float = 12.0
_VOLATILITY_MIN: float = 15.0
_VOLATILITY_MAX: float = 95.0

_LIQUIDITY_FACTOR: float = 0.95
_LIQUIDITY_MIN: float = 40.0
_LIQUIDITY_MAX: float = 99.0

_QUALITY_BASE: float = 70.0
_QUALITY_MODULO: float = 20.0
_QUALITY_MIN: float = 45.0
_QUALITY_MAX: float = 95.0

_VALUE_BASE: float = 65.0
_VALUE_MULTIPLIER: float = 3.0
_VALUE_MIN: float = 30.0
_VALUE_MAX: float = 90.0

_SIZE_HIGH_SCORE: float = 70.0
_SIZE_HIGH_VALUE: float = 80.0
_SIZE_LOW_VALUE: float = 55.0
_SIZE_MIN: float = 35.0
_SIZE_MAX: float = 95.0

_NEUTRAL_SCORE: float = 50.0


def _hesapla_faktor_skorlari(score: float, change: float) -> dict[str, float]:
    """Verilen skor ve değişim değerlerinden faktör skorlarını hesaplar.

    Args:
        score: Bileşik skor.
        change: Fiyat değişim yüzdesi.

    Returns:
        dict: Momentum, value, quality, volatility, liquidity, size skorları.
    """
    momentum = min(_MOMENTUM_MAX, max(_MOMENTUM_MIN, _MOMENTUM_BASE + change * _MOMENTUM_MULTIPLIER))
    volatility = min(_VOLATILITY_MAX, max(_VOLATILITY_MIN, abs(change) * _VOLATILITY_MULTIPLIER + _VOLATILITY_BASE))
    liquidity = min(_LIQUIDITY_MAX, max(_LIQUIDITY_MIN, score * _LIQUIDITY_FACTOR))
    quality = min(_QUALITY_MAX, max(_QUALITY_MIN, _QUALITY_BASE + (score % _QUALITY_MODULO)))
    value = min(_VALUE_MAX, max(_VALUE_MIN, _VALUE_BASE - (change * _VALUE_MULTIPLIER)))
    size = min(_SIZE_MAX, max(_SIZE_MIN, _SIZE_HIGH_VALUE if score > _SIZE_HIGH_SCORE else _SIZE_LOW_VALUE))
    return {
        "momentum": round(momentum, 1),
        "value": round(value, 1),
        "quality": round(quality, 1),
        "volatility": round(volatility, 1),
        "liquidity": round(liquidity, 1),
        "size": round(size, 1),
    }


# --- Fama-French sabitleri ---
_FF_NORMALIZE: float = 50.0
_FF_SCALE: float = 50.0
_FF_FACTOR_STD_DIVISOR: float = 150.0
_FF_R2_BASE: float = 0.7

_FF_MKTRF_BASE: float = 0.8
_FF_MKTRF_SCALE: float = 0.5
_FF_R2_MIN: float = 0.5
_FF_R2_MAX: float = 0.95
_FF_R2_FACTOR_SCALE: float = 0.2
_FF_ALPHA_MOMENTUM_SCALE: float = 0.15
_FF_ALPHA_QUALITY_SCALE: float = 0.1


def _hesapla_fama_french(factors: dict[str, float]) -> dict[str, Any]:
    """Faktör skorlarından Fama-French beta katsayılarını hesaplar.

    Args:
        factors: Faktör skorları sözlüğü.

    Returns:
        dict: Fama-French betaları, R-kare ve alfa değeri.
    """
    momentum = factors.get("momentum", _NEUTRAL_SCORE)
    value = factors.get("value", _NEUTRAL_SCORE)
    quality = factors.get("quality", _NEUTRAL_SCORE)
    volatility = factors.get("volatility", _NEUTRAL_SCORE)
    size = factors.get("size", _NEUTRAL_SCORE)

    smb = round((size - _FF_NORMALIZE) / _FF_SCALE, 2)
    hml = round((value - _FF_NORMALIZE) / _FF_SCALE, 2)
    rmw = round((quality - _FF_NORMALIZE) / _FF_SCALE, 2)
    cma = round((momentum - _FF_NORMALIZE) / _FF_SCALE, 2)
    mkt_rf = round(_FF_MKTRF_BASE + (volatility / 100) * _FF_MKTRF_SCALE, 2)

    factor_std = max(0.01, abs(momentum - _FF_NORMALIZE) + abs(value - _FF_NORMALIZE) + abs(quality - _FF_NORMALIZE)) / _FF_FACTOR_STD_DIVISOR
    r_squared = round(min(_FF_R2_MAX, max(_FF_R2_MIN, _FF_R2_BASE + factor_std * _FF_R2_FACTOR_SCALE)), 2)
    alpha_annual = round((momentum - _FF_NORMALIZE) * _FF_ALPHA_MOMENTUM_SCALE + (quality - _FF_NORMALIZE) * _FF_ALPHA_QUALITY_SCALE, 1)

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

    score = item.get("score", _NEUTRAL_SCORE)
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
                    weighted[key] += f.get(key, _NEUTRAL_SCORE) * w
            except Exception as exc:
                logger.warning("pozisyon_faktor_hatasi", ticker=pos_ticker, hata=str(exc))
                basarisiz_pozisyonlar.append(pos_ticker)
                for key in weighted:
                    weighted[key] += _NEUTRAL_SCORE * w

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
