"""Alternatif Veri API — Gerçek servislere bağlı, önbellekli uç noktalar."""

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

_SENTIMENT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_NEWS_CACHE: tuple[float, list[Any]] = (0.0, [])
_MACRO_CACHE: tuple[float, dict[str, Any]] = (0.0, {})

# Gerçek veri kaynakları — servis mevcut olduğunda dinamik olarak sorgulanabilir
_MEVCUT_KAYNAKLAR: list[str] = [
    "google_trends",
    "kap_rss",
    "financial_news",
    "social_sentiment",
    "macro_commodities",
]


@router.get("/sources")
async def data_sources(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Mevcut alternatif veri kaynaklarını listeler.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Kaynak listesi ve durum bilgisi.
    """
    try:
        return {
            "sources": _MEVCUT_KAYNAKLAR,
            "count": len(_MEVCUT_KAYNAKLAR),
            "status": "ok",
        }
    except Exception as exc:
        logger.error("kaynak_listesi_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Kaynak listesi alınamadı: {exc}",
        ) from exc


@router.get("/sentiment/{ticker}")
async def sentiment(
    ticker: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """KAP ve finansal haberler üzerinden hisse bazlı sentiment analizi döndürür.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sentiment skoru, polarite, eğilim ve haber sayısı.

    Raises:
        HTTPException: Haber verisi alınamazsa 503 hatası döner.
    """
    sym = ticker.upper()
    now = time.time()

    if sym in _SENTIMENT_CACHE:
        cached_ts, cached_val = _SENTIMENT_CACHE[sym]
        if now - cached_ts < 60:
            return cached_val

    try:
        from ...ingestion.providers.news_provider import news_provider

        news = await news_provider.fetch_news_for_ticker(sym, max_items=10)
    except Exception as exc:
        logger.error("sentiment_haber_alinamadi: ticker=%s, hata=%s", sym, exc)
        raise HTTPException(
            status_code=503,
            detail=f"{sym} için haber verisi alınamadı: {exc}",
        ) from exc

    pos_words = [
        "artış", "büyüme", "kâr", "rekor", "ihale",
        "anlaşma", "yüksek", "temettü", "başarı", "onay",
    ]
    neg_words = [
        "düşüş", "zarar", "ceza", "iptal", "dava",
        "risk", "kayıp", "soruşturma", "faiz", "borç",
    ]

    pos_count = 0
    neg_count = 0

    for item in news:
        title = (item.get("title", "") + " " + item.get("summary", "")).lower()
        pos_count += sum(1 for w in pos_words if w in title)
        neg_count += sum(1 for w in neg_words if w in title)

    total = max(1, pos_count + neg_count)
    sentiment_score = round(((pos_count - neg_count) / total), 2)
    score_100 = round(50 + (sentiment_score * 40), 1)

    if sentiment_score > 0.1:
        bias = "BULLISH"
    elif sentiment_score < -0.1:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    result: dict[str, Any] = {
        "ticker": sym,
        "sentiment_available": True,
        "score": score_100,
        "polarity": sentiment_score,
        "bias": bias,
        "news_count": len(news),
        "sample_headlines": [n.get("title") for n in news[:3]],
        "status": "active",
    }
    _SENTIMENT_CACHE[sym] = (now, result)
    return result


@router.get("/news")
async def live_news(
    limit: int = Query(default=20, le=50),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Canlı KAP bildirimleri ve finans haberlerini döndürür.

    Args:
        limit: Maksimum haber sayısı (en fazla 50).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Haber listesi ve durum bilgisi.
    """
    global _NEWS_CACHE
    now = time.time()

    if _NEWS_CACHE[1] and (now - _NEWS_CACHE[0] < 30):
        return {
            "status": "success",
            "count": len(_NEWS_CACHE[1][:limit]),
            "news": _NEWS_CACHE[1][:limit],
        }

    try:
        from ...ingestion.providers.news_provider import news_provider

        news_items = await news_provider.fetch_financial_news_rss(max_items=limit)
        _NEWS_CACHE = (now, news_items)
        return {
            "status": "success",
            "count": len(news_items),
            "news": news_items,
        }
    except Exception as exc:
        logger.error("live_news_hatasi: hata=%s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "news": _NEWS_CACHE[1] if _NEWS_CACHE[1] else [],
        }


@router.get("/macro")
async def live_macro(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Canlı küresel makro ve emtia verilerini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Makro veriler ve durum bilgisi.
    """
    global _MACRO_CACHE
    now = time.time()

    if _MACRO_CACHE[1] and (now - _MACRO_CACHE[0] < 30):
        return {
            "status": "success",
            "macro": _MACRO_CACHE[1],
        }

    try:
        from ...ingestion.providers.macro_provider import MacroProvider

        macro_prov = MacroProvider()
        data = await macro_prov.fetch_yahoo_macro()
        _MACRO_CACHE = (now, data)
        return {
            "status": "success",
            "macro": data,
        }
    except Exception as exc:
        logger.error("live_macro_hatasi: hata=%s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "macro": _MACRO_CACHE[1] if _MACRO_CACHE[1] else {},
        }
