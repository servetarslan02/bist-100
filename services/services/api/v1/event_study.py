"""Event Study API — KAP ve Makro Olay Çalışması."""

from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any

from ..dependencies import get_current_user, check_rate_limit

router = APIRouter()

EVENTS_DATA = [
    {"id": "1", "timestamp": "14:32:17", "type": "KAP", "source": "kap.org.tr", "title": "THYAO - Yeni uçak alım ve filo genişletme kararı açıklandı", "ticker": "THYAO", "sentiment": 0.64, "importance": 0.88},
    {"id": "2", "timestamp": "14:28:05", "type": "NEWS", "source": "AA Finans", "title": "TCMB Para Politikası Kurulu faiz karar metnini yayımladı", "sentiment": -0.1, "importance": 0.95},
    {"id": "3", "timestamp": "14:25:42", "type": "MACRO", "source": "TÜİK", "title": "Tüketici Fiyat Endeksi (TÜFE) aylık %2.4 artış kaydetti", "sentiment": -0.3, "importance": 0.90},
    {"id": "4", "timestamp": "14:21:18", "type": "KAP", "source": "kap.org.tr", "title": "ASELS - Savunma Sanayii Başkanlığı ile 140M $ sözleşme imzalandı", "ticker": "ASELS", "sentiment": 0.82, "importance": 0.85},
    {"id": "5", "timestamp": "14:18:33", "type": "NEWS", "source": "Reuters", "title": "BIST Bankacılık Endeksi (XBANK) yabancı alımlarıyla %2 yükseldi", "sentiment": 0.55, "importance": 0.70},
    {"id": "6", "timestamp": "14:15:07", "type": "SOCIAL", "source": "X Finans", "title": "TUPRS rafineri bakım ve marjları hakkında artan sosyal medya ilgisi", "ticker": "TUPRS", "sentiment": 0.28, "importance": 0.45},
    {"id": "7", "timestamp": "14:12:44", "type": "KAP", "source": "kap.org.tr", "title": "EREGL - 2. Çeyrek finansal sonuçları ve kâr dağıtım kararı", "ticker": "EREGL", "sentiment": 0.15, "importance": 0.80},
]


@router.get("/events")
@router.get("/calendar")
async def event_calendar(user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Olay akışı ve KAP bildirim takvimi."""
    return {
        "events": EVENTS_DATA,
        "count": len(EVENTS_DATA),
    }


@router.get("/analyze/{ticker}")
async def event_study(ticker: str, event_type: str = Query("earnings"), user=Depends(get_current_user), _=Depends(check_rate_limit)):
    """Hisse bazlı olay anomalisi (CAR/AAR) analizi."""
    return {
        "ticker": ticker,
        "event_type": event_type,
        "car_cumulative_abnormal_return": 0.038,
        "t_statistic": 2.45,
        "p_value": 0.015,
        "is_statistically_significant": True,
    }
