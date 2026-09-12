"""
ALPHA BIST — Credit Card Spending Features & Adapter v2.0

Kredi kartı ve tüketici harcama feature'ları ve kurumsal adapter altyapısı.
BKM ve perakende/tüketici harcama sinyallerini işler.

Features:
- cc_spend_growth: Harcama büyüme oranı
- cc_vs_sector: Sektöre göre karşılaştırma
- cc_seasonal_deviation: Mevsimsel sapma
- cc_online_ratio: Online harcama oranı
- cc_transaction_count: İşlem sayısı
- cc_avg_basket_size: Ortalama sepet tutarı
- cc_discretionary_ratio: İsteğe bağlı tüketim oranı
"""

from __future__ import annotations

from typing import Any

import structlog

from .base import BaseAdapter

logger = structlog.get_logger(__name__)

__all__ = [
    "CreditCardAdapter",
    "compute_cc_features",
    "credit_card_adapter",
]


def compute_cc_features(cc_data: dict[str, Any], ticker: str) -> dict[str, float]:
    """Kredi kartı harcama feature'larını hesapla.

    Geriye dönük uyumluluk ve hızlı hesaplama fonksiyonu.

    Args:
        cc_data: Kredi kartı ham verisi (BKM veya diğer kaynaklardan).
        ticker: Hisse sembolü.

    Returns:
        Feature sözlüğü. Her değer float tipindedir.
    """
    features: dict[str, float] = {}

    if not cc_data:
        return features

    key_feature_map = {
        "spend_growth": "cc_spend_growth",
        "vs_sector": "cc_vs_sector",
        "seasonal_deviation": "cc_seasonal_deviation",
        "online_ratio": "cc_online_ratio",
        "transaction_count": "cc_transaction_count",
        "avg_basket_size": "cc_avg_basket_size",
        "discretionary_ratio": "cc_discretionary_ratio",
    }
    for key, feature_name in key_feature_map.items():
        value = cc_data.get(key)
        if value is not None:
            try:
                features[feature_name] = float(value)
            except (TypeError, ValueError):
                logger.debug("Skipping non-numeric value", feature=feature_name, value=value)

    # İkincil türetilmiş alanlar
    if "total_spend" in cc_data and "transaction_count" in cc_data and "cc_avg_basket_size" not in features:
        try:
            tot = float(cc_data["total_spend"])
            cnt = float(cc_data["transaction_count"])
            if cnt > 0:
                features["cc_avg_basket_size"] = tot / cnt
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    return features


class CreditCardAdapter(BaseAdapter):
    """Kurumsal Kredi Kartı ve Tüketici Harcama Adapter'ı.

    BaseAdapter altyapısını miras alarak rate limiting, circuit breaking,
    kalite kontrolleri ve cache desteği sunar.
    """

    source_name: str = "credit_card"
    rate_limit: int = 30

    def __init__(self, data_provider: Any = None):
        """CreditCardAdapter başlat.

        Args:
            data_provider: Özel veri sağlayıcı nesnesi (opsiyonel).
        """
        super().__init__()
        self._data_provider = data_provider

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Kredi kartı ve harcama verisi topla.

        Args:
            ticker: Hisse sembolü.
            **kwargs: Ek sorgu parametreleri (örn: date_range, category).

        Returns:
            Ham veri sözlüğü veya veri yoksa None.
        """
        if self._data_provider and hasattr(self._data_provider, "get_spending_data"):
            try:
                data = await self._data_provider.get_spending_data(ticker=ticker, **kwargs)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.warning("Custom spending data provider error", ticker=ticker, error=str(e))
                return None

        # Harici sağlayıcı yoksa veya None döndüyse None dön (mock veri üretilmez)
        return None

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Ham veriden kredi kartı göstergelerini hesapla.

        Args:
            data: Ham harcama verisi.
            ticker: Hisse sembolü.

        Returns:
            Hesaplanan float feature sözlüğü.
        """
        return compute_cc_features(data, ticker)

    def __repr__(self) -> str:
        return f"CreditCardAdapter(source={self.source_name!r}, rate_limit={self.rate_limit})"


# Singleton instance
credit_card_adapter = CreditCardAdapter()
