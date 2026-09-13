from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Enflasyon rejimi eşik sabitleri (Yıllık TÜFE %)
DEFAULT_INF_REGIME_HYPER: float = 60.0
DEFAULT_INF_REGIME_VERY_HIGH: float = 40.0
DEFAULT_INF_REGIME_HIGH: float = 20.0
DEFAULT_INF_REGIME_MODERATE: float = 8.0
DEFAULT_INF_SURPRISE_THRESHOLD: float = 0.5
DEFAULT_INF_TREND_THRESHOLD: float = 0.5


def compute_inflation_features(inflation_data: dict[str, Any]) -> dict[str, float]:
    """Enflasyon dinamikleri, çekirdek göstergeler, yayılım endeksi ve maliyet geçişkenliği analitiklerini hesaplar.

    Hesaplanan Kurumsal Göstergeler:
    - inf_cpi_level: Yıllık manşet TÜFE (%)
    - inf_ppi_level: Yıllık Yİ-ÜFE (%)
    - inf_core_cpi: Çekirdek TÜFE (C-Endeksi: enerji, gıda, tütün hariç)
    - inf_core_headline_spread: Çekirdek - Manşet farkı (yapışkanlık/geçicilik göstergesi)
    - inf_cpi_ppi_spread: ÜFE - TÜFE makası (Şirket brüt kâr marjı sıkışması baskısı)
    - inf_cpi_monthly: Aylık TÜFE değişimi (%)
    - inf_cpi_annualized: Aylık oranın bileşik yıllıklandırılmış karşılığı
    - inf_diffusion_index: Fiyat Yayılım Endeksi (sepetin yüzde kaçında fiyatlar artıyor?)
    - inf_trimmed_mean: Budanmış ortalama enflasyon (aşırı uç fiyat hareketlerinden arındırılmış)
    - inf_producer_margin_squeeze_ratio: Üretici girdi maliyetinin tüketiciye yansıtılamama oranı
    - inf_surprise: Beklentiye göre gerçekleşen enflasyon sürprizi (bps)
    - inf_trend: Önceki aya göre yıllık enflasyon trend yönü
    - inf_regime: 0 (Düşük) ile 4 (Hiper/Ekstrem Yapışkanlık) arası rejim kodu

    Args:
        inflation_data: TÜFE, ÜFE, çekirdek, aylık seriler, anket beklentileri ve alt endeks verilerini içeren sözlük.

    Returns:
        dict[str, float]: Hesaplanmış kantitatif enflasyon göstergeleri sözlüğü.
    """
    features: dict[str, float] = {}

    if not inflation_data:
        return features

    try:
        # 1. Manşet TÜFE ve Rejim Sınıflandırması
        cpi_yoy = inflation_data.get("cpi_yoy") or inflation_data.get("cpi_annual") or inflation_data.get("inflation_rate")
        if cpi_yoy is not None:
            cpi_val = float(cpi_yoy)
            features["inf_cpi_level"] = round(cpi_val, 2)

            if cpi_val > DEFAULT_INF_REGIME_HYPER:
                regime = 4.0  # HİPER / EKSTREM YAPIŞKANLIK
            elif cpi_val > DEFAULT_INF_REGIME_VERY_HIGH:
                regime = 3.0  # ÇOK YÜKSEK
            elif cpi_val > DEFAULT_INF_REGIME_HIGH:
                regime = 2.0  # YÜKSEK
            elif cpi_val > DEFAULT_INF_REGIME_MODERATE:
                regime = 1.0  # ORTA / ILIMLI
            else:
                regime = 0.0  # DÜŞÜK / HEDEFE UYUMLU

            features["inf_regime"] = regime

        # 2. Üretici Fiyat Endeksi (Yİ-ÜFE) ve Maliyet Baskısı Makası
        ppi_yoy = inflation_data.get("ppi_yoy") or inflation_data.get("ppi_annual")
        if ppi_yoy is not None:
            ppi_val = float(ppi_yoy)
            features["inf_ppi_level"] = round(ppi_val, 2)

            if cpi_yoy is not None:
                cpi_ppi_gap = float(cpi_yoy) - ppi_val
                features["inf_cpi_ppi_spread"] = round(cpi_ppi_gap, 2)
                # Marj sıkışma rasyosu (PPI / CPI)
                features["inf_producer_margin_squeeze_ratio"] = round(ppi_val / max(float(cpi_yoy), 0.1), 3)

        # 3. Çekirdek Enflasyon (Özel Kapsamlı TÜFE Göstergeleri - C Endeksi)
        core_cpi = inflation_data.get("core_cpi") or inflation_data.get("core_cpi_annual")
        if core_cpi is not None:
            core_val = float(core_cpi)
            features["inf_core_cpi"] = round(core_val, 2)
            if cpi_yoy is not None:
                features["inf_core_headline_spread"] = round(core_val - float(cpi_yoy), 2)

        # 4. Aylık Değişim ve Bileşik Yıllıklandırılmış Oran
        cpi_monthly = inflation_data.get("cpi_monthly")
        if cpi_monthly is not None:
            m_rate = float(cpi_monthly)
            features["inf_cpi_monthly"] = round(m_rate, 2)
            # Bileşik formül: ((1 + m_rate/100)^12 - 1) * 100
            features["inf_cpi_annualized"] = round(((1.0 + (m_rate / 100.0)) ** 12 - 1.0) * 100.0, 2)

        # 5. Fiyat Yayılım Endeksi (Diffusion Index) & Budanmış Ortalama (Trimmed Mean)
        diff_index = inflation_data.get("diffusion_index")
        if diff_index is not None:
            features["inf_diffusion_index"] = round(float(diff_index), 2)
        elif cpi_monthly is not None:
            # Yayılım endeksi verisi doğrudan yoksa, aylık artış hızına göre dinamik tahmin proxy'si
            features["inf_diffusion_index"] = round(min(95.0, max(20.0, 45.0 + (float(cpi_monthly) * 8.0))), 2)

        trimmed_val = inflation_data.get("trimmed_mean")
        if trimmed_val is not None:
            features["inf_trimmed_mean"] = round(float(trimmed_val), 2)

        # 6. Enflasyon Sürprizi (Piyasa Katılımcıları Anketi vs Gerçekleşen)
        cpi_expected = inflation_data.get("cpi_expected")
        if cpi_yoy is not None and cpi_expected is not None:
            surprise = float(cpi_yoy) - float(cpi_expected)
            features["inf_surprise"] = round(surprise, 4)
            features["inf_surprise_pct"] = round(surprise / max(abs(float(cpi_expected)), 0.01), 4)
            features["inf_surprise_direction"] = (
                1.0 if surprise > DEFAULT_INF_SURPRISE_THRESHOLD
                else (-1.0 if surprise < -DEFAULT_INF_SURPRISE_THRESHOLD else 0.0)
            )

        # 7. Yıllık Enflasyon Trendi ve İvmesi
        cpi_previous = inflation_data.get("cpi_previous")
        if cpi_yoy is not None and cpi_previous is not None:
            trend = float(cpi_yoy) - float(cpi_previous)
            features["inf_trend"] = round(trend, 4)
            features["inf_trend_direction"] = (
                1.0 if trend > DEFAULT_INF_TREND_THRESHOLD
                else (-1.0 if trend < -DEFAULT_INF_TREND_THRESHOLD else 0.0)
            )

    except Exception as e:
        logger.error("Enflasyon kurumsal analitik hesaplaması başarısız oldu", error=str(e))

    return features


__all__ = [
    "DEFAULT_INF_REGIME_HYPER",
    "DEFAULT_INF_REGIME_VERY_HIGH",
    "DEFAULT_INF_REGIME_HIGH",
    "DEFAULT_INF_REGIME_MODERATE",
    "DEFAULT_INF_SURPRISE_THRESHOLD",
    "DEFAULT_INF_TREND_THRESHOLD",
    "compute_inflation_features",
]


