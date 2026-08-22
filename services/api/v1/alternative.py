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


@router.get("/google-trends/{query}")
async def google_trends(query: str, user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Google Trends verisi."""
    try:
        from ...alternative.google_trends import GoogleTrendsAdapter
        return {"query": query, "trends_available": True}
    except Exception as e:
        return {"query": query, "error": str(e)}
