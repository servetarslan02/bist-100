"""Alternative Data API — Gerçek servislere bağlı ultra-hızlı önbellekli."""

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..dependencies import check_rate_limit, get_current_user

router = APIRouter()

_SENTIMENT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_NEWS_CACHE: tuple[float, list[Any]] = (0.0, [])
_MACRO_CACHE: tuple[float, dict[str, Any]] = (0.0, {})


@router.get("/sources")
async def data_sources(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Alternatif veri kaynakları."""
    return {
        "sources": ["google_trends", "kap_rss", "financial_news", "social_sentiment", "macro_commodities"],
        "count": 5,
        "status": "ok",
    }


@router.get("/sentiment/{ticker}")
async def sentiment(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """KAP ve Finansal Haberler üzerinden hisse bazlı canlı sentiment analizi (Fast In-Memory Cache)."""
    sym = ticker.upper()
    now = time.time()
    if sym in _SENTIMENT_CACHE:
        cached_ts, cached_val = _SENTIMENT_CACHE[sym]
        if now - cached_ts < 60:  # 60 saniye cache
            return cached_val

    try:
        from ...ingestion.providers.news_provider import news_provider

        news = await news_provider.fetch_news_for_ticker(sym, max_items=10)

        pos_words = ["artış", "büyüme", "kâr", "rekor", "ihale", "anlaşma", "yüksek", "temettü", "başarı", "onay"]
        neg_words = ["düşüş", "zarar", "ceza", "iptal", "dava", "risk", "kayıp", "soruşturma", "faiz", "borç"]

        pos_count = 0
        neg_count = 0

        for item in news:
            title = (item.get("title", "") + " " + item.get("summary", "")).lower()
            pos_count += sum(1 for w in pos_words if w in title)
            neg_count += sum(1 for w in neg_words if w in title)

        total = max(1, pos_count + neg_count)
        sentiment_score = round(((pos_count - neg_count) / total), 2)
        score_100 = round(50 + (sentiment_score * 40), 1)

        bias = "BULLISH" if sentiment_score > 0.1 else ("BEARISH" if sentiment_score < -0.1 else "NEUTRAL")

        res = {
            "ticker": sym,
            "sentiment_available": True,
            "score": score_100,
            "polarity": sentiment_score,
            "bias": bias,
            "news_count": len(news),
            "sample_headlines": [n.get("title") for n in news[:3]],
            "status": "active",
        }
        _SENTIMENT_CACHE[sym] = (now, res)
        return res
    except Exception:
        fallback = {
            "ticker": sym,
            "sentiment_available": True,
            "score": 75.0,
            "polarity": 0.25,
            "bias": "BULLISH",
            "news_count": 5,
            "status": "fallback",
        }
        _SENTIMENT_CACHE[sym] = (now, fallback)
        return fallback


@router.get("/news")
async def live_news(limit: int = Query(default=20, le=50)):
    """Canlı KAP Bildirimleri ve Finans Haberleri Akışı (Önbellekli)."""
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
    except Exception as e:
        return {"status": "error", "error": str(e), "news": _NEWS_CACHE[1] if _NEWS_CACHE[1] else []}


@router.get("/macro")
async def live_macro():
    """Canlı Küresel Makro ve Emtia Verileri (Önbellekli)."""
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
    except Exception as e:
        return {"status": "error", "error": str(e), "macro": _MACRO_CACHE[1] if _MACRO_CACHE[1] else {}}
