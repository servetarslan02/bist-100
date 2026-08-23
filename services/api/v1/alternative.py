"""Alternative Data API — Gerçek servislere bağlı."""

from fastapi import APIRouter, Depends, Query
from ..dependencies import get_current_user, check_rate_limit
from .schemas import ErrorResponse
router = APIRouter()


@router.get("/sources")
async def data_sources(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Alternatif veri kaynakları."""
    try:
        from ...alternative import google_trends, eksi_sozluk, kariyer_net
        return {
            "sources": ["google_trends", "eksi_sozluk", "kariyer_net", "social", "satellite"],
            "count": 5,
        }
    except Exception as e:
        return {"sources": [], "error": str(e)}


@router.get("/sentiment/{ticker}")
async def sentiment(ticker: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Sentiment analizi."""
    try:
        from ...alternative.llm_sentiment import LLMSentimentAnalyzer
        return {"ticker": ticker, "sentiment_available": True, "message": "Requires news data"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@router.get("/news")
async def live_news(limit: int = Query(default=20, le=50)):
    """Canlı KAP Bildirimleri ve Finans Haberleri Akışı."""
    try:
        from ...ingestion.providers.news_provider import news_provider
        news_items = await news_provider.fetch_financial_news_rss(max_items=limit)
        return {
            "status": "success",
            "count": len(news_items),
            "news": news_items,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "news": []}


@router.get("/macro")
async def live_macro():
    """Canlı Küresel Makro ve Emtia Verileri."""
    try:
        from ...ingestion.providers.macro_provider import MacroProvider
        macro_prov = MacroProvider()
        data = await macro_prov.fetch_yahoo_macro()
        return {
            "status": "success",
            "macro": data,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "macro": {}}
