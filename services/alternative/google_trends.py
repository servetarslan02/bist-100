"""
ALPHA BIST — Google Trends Adapter v1.0

Google Trends verisi çekme ve feature hesaplama.
pytrends kütüphanesi kullanır.

Ücretsiz API — rate limit: 10 istek/dakika.

Features:
- google_trends_score: Güncel arama ilgisi (0-100)
- google_trends_avg_30d: Son 30 gün ortalaması
- google_trends_momentum: 30 gün değişim
- google_trends_percentile: 90. percentil
- google_trends_volatility: Volatilite
- google_trends_relative: Endekse göre bağıl ilgi
"""

import asyncio
from typing import Any

import numpy as np
import structlog

from .base import BaseAdapter

logger = structlog.get_logger()


class GoogleTrendsAdapter(BaseAdapter):
    """Google Trends veri adapter'ı."""

    source_name = "google_trends"
    rate_limit = 10  # pytrends için düşük limit

    # BIST hisse → arama terimleri mapping
    TICKER_SEARCH_TERMS: dict[str, list[str]] = {
        "THYAO": ["thyao", "türk hava yolları", "turkish airlines"],
        "GARAN": ["garanti", "garanti bankası"],
        "AKBNK": ["akbank"],
        "ASELS": ["aselsan"],
        "BIMAS": ["bim", "bim market"],
        "EREGL": ["ereğli", "erdemir"],
        "KCHOL": ["koç holding", "koç"],
        "SAHOL": ["sabancı", "sabancı holding"],
        "SISE": ["şişe cam"],
        "TUPRS": ["tüpraş"],
        "PETKM": ["petkim"],
        "TOASO": ["togg", "tofaş"],
        "FROTO": ["ford", "ford otosan"],
        "TCELL": ["turkcell"],
        "TTKOM": ["türk telekom"],
        "HALKB": ["halkbank"],
        "VAKBN": ["vakıfbank"],
        "ISCTR": ["iş bankası"],
        "EKGYO": ["emlak konut"],
        "TAVHL": ["tav"],
    }

    def __init__(self):
        """Google Trends adapter'ı başlat."""
        super().__init__()
        self._pytrends = None

    def _get_pytrends(self):
        """pytrends instance'ı al (lazy init).

        Returns:
            TrendReq instance'ı veya None (yüklü değilse).
        """
        if self._pytrends is None:
            try:
                from pytrends.request import TrendReq

                self._pytrends = TrendReq(hl="tr-TR", tz=180)
            except ImportError:
                logger.warning("pytrends not installed. Install with: pip install pytrends")
                return None
        return self._pytrends

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Google Trends verisi çek.

        Args:
            ticker: Hisse sembolü.
            **kwargs: Ek parametreler.

        Returns:
            Ham trend verisi sözlüğü veya None.
        """
        pytrends = self._get_pytrends()
        if pytrends is None:
            return None

        search_terms = self.TICKER_SEARCH_TERMS.get(ticker.upper(), [ticker.lower()])
        if not search_terms:
            return None

        try:
            # Sync call'ı async context'te çalıştır
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._fetch_trends, pytrends, search_terms)
            return data
        except Exception as e:
            logger.warning("Google Trends fetch failed", ticker=ticker, error=str(e))
            return None

    def _fetch_trends(self, pytrends, search_terms: list[str]) -> dict[str, Any]:
        """pytrends ile veri çek (sync).

        Args:
            pytrends: TrendReq instance'ı.
            search_terms: Arama terimleri listesi.

        Returns:
            Ham trend verisi sözlüğü.
        """
        try:
            pytrends.build_payload(
                search_terms[:5],  # max 5 terim
                timeframe="today 3-m",
                geo="TR",
            )

            interest = pytrends.interest_over_time()
            if interest.empty:
                return {}

            # İlk terimi kullan (ana hisse kodu)
            main_term = search_terms[0]
            if main_term not in interest.columns:
                main_term = interest.columns[0]

            values = interest[main_term].values.astype(float)

            if len(values) < 7:
                return {}

            return {
                "score": float(values[-1]),
                "avg_7d": float(np.mean(values[-7:])),
                "avg_30d": float(np.mean(values[-30:])) if len(values) >= 30 else float(np.mean(values)),
                "momentum_7d": float(values[-1] - values[-7]),
                "momentum_30d": float(values[-1] - values[-30]) if len(values) >= 30 else 0.0,
                "percentile_90": float(np.percentile(values, 90)),
                "volatility": float(np.std(values)),
                "max_90d": float(np.max(values)),
                "min_90d": float(np.min(values)),
                "trend_direction": 1.0 if values[-1] > values[-7] else -1.0,
                "data_points": int(len(values)),
                "timestamp": str(interest.index[-1]),
            }
        except Exception as e:
            logger.warning("pytrends fetch error", error=str(e))
            return {}

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Google Trends feature'larını hesapla.

        Args:
            data: collect() ile döndürülen ham veri.
            ticker: Hisse sembolü.

        Returns:
            Feature sözlüğü.
        """
        if not data:
            return {}

        score = data.get("score", 0)
        avg_30d = data.get("avg_30d", 0)
        momentum_30d = data.get("momentum_30d", 0)
        volatility = data.get("volatility", 0)
        percentile_90 = data.get("percentile_90", 0)

        features = {
            "google_trends_score": float(score),
            "google_trends_avg_30d": float(avg_30d),
            "google_trends_momentum_7d": float(data.get("momentum_7d", 0)),
            "google_trends_momentum_30d": float(momentum_30d),
            "google_trends_volatility": float(volatility),
            "google_trends_percentile": float(percentile_90),
            "google_trends_relative": float(score / max(percentile_90, 1)),
            "google_trends_trend": float(data.get("trend_direction", 0)),
            "google_trends_zscore": float((score - avg_30d) / max(volatility, 1)) if volatility > 0 else 0.0,
        }

        return features


# Singleton
google_trends_adapter = GoogleTrendsAdapter()
