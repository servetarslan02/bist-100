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
    """Kredi kartı ve BKM tüketici harcama ham verisinden kurumsal göstergeleri hesaplar.

    Hesaplanan Göstergeler:
    - cc_spend_growth: Nominal kartlı harcama yıllık/aylık büyüme oranı (%)
    - cc_real_spend_growth: Enflasyondan arındırılmış reel harcama büyümesi (%)
    - cc_spending_velocity: Harcama ivmesi (aylık büyüme hızındaki değişim)
    - cc_vs_sector: İlgili sektör ortalamasına göre bağıl harcama gücü
    - cc_seasonal_deviation: Mevsimsellikten arındırılmış sapma skoru
    - cc_online_ratio: Dijital / e-ticaret harcama oranı (%)
    - cc_transaction_count: İşlem adedi (hacim)
    - cc_avg_basket_size: İşlem başına ortalama sepet büyüklüğü (TL)
    - cc_discretionary_ratio: İsteğe bağlı vs temel tüketim harcama ayrışması
    - cc_retail_demand_regime: 0 (Şiddetli Daralma) ile 3 (Güçlü Tüketici Talebi) arası talep rejimi

    Args:
        cc_data: BKM veya ticari kart işlem verilerini içeren sözlük.
        ticker: İlgili BIST hisse sembolü.

    Returns:
        dict[str, float]: Hesaplanmış kantitatif tüketici göstergeleri sözlüğü.
    """
    features: dict[str, float] = {}

    if not cc_data:
        return features

    try:
        # 1. Nominal Harcama Büyümesi
        spend_growth = cc_data.get("spend_growth") or cc_data.get("cc_spend_growth")
        if spend_growth is not None:
            features["cc_spend_growth"] = round(float(spend_growth), 2)

            # 2. Enflasyondan Arındırılmış Reel Büyüme (TÜFE düşülerek)
            cpi_rate = cc_data.get("cpi_rate") or cc_data.get("inflation_rate")
            if cpi_rate is not None:
                real_growth = float(spend_growth) - float(cpi_rate)
                features["cc_real_spend_growth"] = round(real_growth, 2)
            else:
                features["cc_real_spend_growth"] = round(float(spend_growth), 2)

        # 3. Harcama İvmesi (Velocity - İkinci Türev)
        prev_growth = cc_data.get("prev_spend_growth")
        if spend_growth is not None and prev_growth is not None:
            features["cc_spending_velocity"] = round(float(spend_growth) - float(prev_growth), 2)

        # 4. Sektöre Göre Bağıl Güç
        vs_sector = cc_data.get("vs_sector") or cc_data.get("cc_vs_sector")
        if vs_sector is not None:
            features["cc_vs_sector"] = round(float(vs_sector), 2)

        # 5. Mevsimsel Sapma Skoru
        seasonal_dev = cc_data.get("seasonal_deviation") or cc_data.get("cc_seasonal_deviation")
        if seasonal_dev is not None:
            features["cc_seasonal_deviation"] = round(float(seasonal_dev), 4)

        # 6. Online / E-Ticaret Penetrasyon Oranı
        online_ratio = cc_data.get("online_ratio") or cc_data.get("cc_online_ratio")
        if online_ratio is not None:
            features["cc_online_ratio"] = round(float(online_ratio), 4)

        # 7. İşlem Adedi ve Ortalama Sepet Büyüklüğü
        tx_count = cc_data.get("transaction_count") or cc_data.get("cc_transaction_count")
        if tx_count is not None and float(tx_count) > 0:
            features["cc_transaction_count"] = round(float(tx_count), 0)

        total_spend = cc_data.get("total_spend")
        if total_spend is not None and tx_count is not None and float(tx_count) > 0:
            features["cc_avg_basket_size"] = round(float(total_spend) / float(tx_count), 2)
        elif cc_data.get("avg_basket_size") is not None:
            features["cc_avg_basket_size"] = round(float(cc_data["avg_basket_size"]), 2)

        # 8. İsteğe Bağlı Tüketim Oranı (Discretionary vs Staples)
        disc_ratio = cc_data.get("discretionary_ratio") or cc_data.get("cc_discretionary_ratio")
        if disc_ratio is not None:
            features["cc_discretionary_ratio"] = round(float(disc_ratio), 4)

        # 9. Tüketici Talep Rejimi
        growth_metric = features.get("cc_real_spend_growth", features.get("cc_spend_growth", 0.0))
        if growth_metric > 15.0:
            regime = 3.0  # GÜÇLÜ TALEP / TÜKETİCİ PATLAMASI
        elif growth_metric > 0.0:
            regime = 2.0  # ILIMLI / STABİL BÜYÜME
        elif growth_metric > -10.0:
            regime = 1.0  # TALEPTE DARALMA / FREN
        else:
            regime = 0.0  # ŞİDDETLİ TÜKETİCİ KÜÇÜLMESİ

        features["cc_retail_demand_regime"] = regime

    except Exception as e:
        logger.error("Kredi kartı gösterge hesaplaması başarısız oldu", ticker=ticker, error=str(e))

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
                logger.warning("Özel harcama veri sağlayıcısı hatası", ticker=ticker, error=str(e))
                return None

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


credit_card_adapter = CreditCardAdapter()

