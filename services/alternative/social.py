"""
ALPHA BIST — Social Media Features & Adapter v2.0

Sosyal medya duygu analizi, hacim metrikleri ve manipülasyon sinyalleri adapter altyapısı.
Twitter/X, Reddit, Ekşi Sözlük, Investing ve Telegram gibi kanalların birleşik feature'larını üretir.

Features:
- social_sentiment: Genel duygu skoru (-1 ile +1)
- social_volume: Sosyal medya toplam mesaj hacmi
- social_viral: Viral aktivite sinyali (0 veya 1)
- social_positive_ratio: Pozitif içerik oranı (0 ile 1)
- social_mention_count: Bahsedilme sayısı
- social_engagement: Etkileşim oranı (beğeni/paylaşım)
- social_sentiment_momentum: Duygu değişim ivmesi
- social_manipulation_score: Bot/manipülasyon riski skoru (0 ile 1)
- social_{platform}_sentiment: Platform bazlı duygu
- social_{platform}_volume: Platform bazlı hacim
"""

from __future__ import annotations

from typing import Any

import structlog

from .base import BaseAdapter

logger = structlog.get_logger(__name__)

__all__ = [
    "SocialMediaAdapter",
    "compute_social_features",
    "social_adapter",
]


def _clamp(value: float | None, min_val: float, max_val: float) -> float:
    """Değeri belirli aralıkta sınırla.

    Args:
        value: Sınırlandırılacak değer.
        min_val: Minimum değer.
        max_val: Maximum değer.

    Returns:
        Sınırlandırılmış float değer.
    """
    if value is None:
        return 0.0
    try:
        return max(min_val, min(max_val, float(value)))
    except (TypeError, ValueError):
        return 0.0


def compute_social_features(social_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """Sosyal medya verisinden feature sözlüğü hesapla.

    Args:
        social_data: Sosyal medya ham/işlenmiş verisi.
        ticker: Hisse kodu.

    Returns:
        Hesaplanan float feature dict.
    """
    features: dict[str, float] = {}

    if not social_data:
        return features

    # Temel feature'lar
    features["social_sentiment"] = _clamp(social_data.get("sentiment", 0), -1.0, 1.0)
    features["social_volume"] = float(social_data.get("volume", 0))
    features["social_viral"] = 1.0 if social_data.get("viral", False) else 0.0
    features["social_positive_ratio"] = _clamp(social_data.get("positive_ratio", 0.5), 0.0, 1.0)
    features["social_mention_count"] = float(social_data.get("mention_count", 0))

    # Gelişmiş feature'lar
    features["social_engagement"] = _clamp(social_data.get("engagement", 0), 0.0, 1.0)
    try:
        features["social_sentiment_momentum"] = float(social_data.get("sentiment_momentum", 0.0))
    except (TypeError, ValueError):
        features["social_sentiment_momentum"] = 0.0

    manipulation_score = _clamp(social_data.get("manipulation_score", 0), 0.0, 1.0)
    features["social_manipulation_score"] = manipulation_score

    # 1. Manipülasyon İndirimli Gerçek Duygu (Bot/Pump filtresi)
    # Manipülasyon riski arttıkça ham duygu sıfıra bastırılır
    sentiment = features["social_sentiment"]
    features["social_manipulation_adjusted_sentiment"] = round(sentiment * (1.0 - manipulation_score), 4)

    # 2. Bireysel Yatırımcı Coşku (FOMO) ve Panik Satış Skorları (0 - 100 bazında)
    pos_ratio = features["social_positive_ratio"]
    engagement = features["social_engagement"]
    is_viral = features["social_viral"] > 0.5
    vol = features["social_volume"]

    # FOMO: Yüksek pozitiflik, viral yayılma, yüksek hacim ve yüksek etkileşim kombinasyonu
    vol_bonus = min(20.0, (vol / 100.0) * 10.0) if vol > 0 else 0.0
    fomo_intensity = (pos_ratio * 40.0) + (engagement * 30.0) + vol_bonus + (10.0 if is_viral else 0.0)
    features["social_fomo_score"] = round(min(100.0, max(0.0, fomo_intensity)) if sentiment > 0.2 else 0.0, 2)

    # Panik Satış: Aşırı negatif oran ve yüksek hacimli panik etkileşimi
    panic_intensity = ((1.0 - pos_ratio) * 60.0) + (engagement * 40.0)
    features["social_panic_score"] = round(min(100.0, max(0.0, panic_intensity)) if sentiment < -0.2 else 0.0, 2)

    # Platform bazlı dağılım ve Platformlar Arası Mutabakat (Consensus)
    platform_sentiments: list[float] = []
    platforms = social_data.get("platforms", {})
    if isinstance(platforms, dict):
        for platform in ["twitter", "reddit", "eksi", "investing", "telegram"]:
            if platform in platforms and isinstance(platforms[platform], dict):
                plat_data = platforms[platform]
                plat_sent = _clamp(plat_data.get("sentiment", 0), -1.0, 1.0)
                features[f"social_{platform}_sentiment"] = plat_sent
                platform_sentiments.append(plat_sent)
                try:
                    features[f"social_{platform}_volume"] = float(plat_data.get("volume", 0))
                except (TypeError, ValueError):
                    features[f"social_{platform}_volume"] = 0.0

    # 3. Platformlar Arası Konsensüs ve Dağılım Skoru
    if len(platform_sentiments) >= 2:
        import numpy as np
        dispersion = float(np.std(platform_sentiments))
        consensus = max(0.0, min(1.0, 1.0 - (dispersion / 1.0)))
    else:
        consensus = 1.0 if platform_sentiments else 0.5
    features["social_cross_platform_consensus"] = round(consensus, 4)

    # 4. Kurumsal Güven Skoru (Retail Conviction Score: 0 - 100)
    conviction = (abs(sentiment) * 40.0) + (engagement * 30.0) + (consensus * 30.0)
    features["social_retail_conviction_score"] = round(min(100.0, max(0.0, conviction)), 2)

    return features


class SocialMediaAdapter(BaseAdapter):
    """Kurumsal Sosyal Medya ve Retail Sinyalleri Adapter'ı.

    BaseAdapter ile rate limit, circuit breaker ve kalite güvencesi sağlar.
    """

    source_name: str = "social"
    rate_limit: int = 60

    def __init__(self, data_provider: Any = None):
        """SocialMediaAdapter başlat.

        Args:
            data_provider: Harici sosyal medya sağlayıcısı (opsiyonel).
        """
        super().__init__()
        self._data_provider = data_provider

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Sosyal medya verisi topla.

        Args:
            ticker: Hisse sembolü.
            **kwargs: Ek parametreler (pencereler, platform filtreleri).

        Returns:
            Ham veri veya veri yoksa None.
        """
        if self._data_provider and hasattr(self._data_provider, "get_social_signals"):
            try:
                data = await self._data_provider.get_social_signals(ticker=ticker, **kwargs)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.warning("Custom social data provider error", ticker=ticker, error=str(e))
                return None

        # Harici sağlayıcı yoksa sahte veri üretme, None dön
        return None

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Sosyal medya verisinden feature'ları hesapla.

        Args:
            data: Ham sosyal veri.
            ticker: Hisse sembolü.

        Returns:
            Hesaplanan feature sözlüğü.
        """
        return compute_social_features(data, ticker)

    def __repr__(self) -> str:
        return f"SocialMediaAdapter(source={self.source_name!r}, rate_limit={self.rate_limit})"


# Singleton instance
social_adapter = SocialMediaAdapter()
