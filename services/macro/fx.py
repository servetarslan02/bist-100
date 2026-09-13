"""
ALPHA BIST — FX Features v2.0

Döviz kuru feature'ları:
- usdtry: USD/TRY kuru
- eurtry: EUR/TRY kuru
- usdtry_change: Günlük değişim
- usdtry_volatility: Volatilite
- eurtry_usdtry_ratio: EUR/USD paritesi
- usdtry_regime: Kur rejimi (değer kazanma/kayıp/stabil)
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Kur rejim sabitleri (%)
DEFAULT_FX_REGIME_SHOCK: float = 8.0
DEFAULT_FX_REGIME_STRONG_WEAKENING: float = 4.0
DEFAULT_FX_REGIME_MILD_WEAKENING: float = 1.5
DEFAULT_FX_REGIME_STABLE: float = 0.0
DEFAULT_FX_REGIME_STRENGTHENING: float = -2.0


def compute_fx_features(fx_data: dict[str, Any]) -> dict[str, float]:
    """Döviz kuru seviye, döviz sepeti, momentum, ivme, oynaklık ve stres rejimlerini hesaplar.

    Hesaplanan Temel Göstergeler:
    - fx_usdtry_level: USD/TRY spot seviyesi
    - fx_eurtry_level: EUR/TRY spot seviyesi
    - fx_basket_level: Türkiye Döviz Sepeti (0.5 USD + 0.5 EUR)
    - fx_basket_change_pct: Sepet günlük yüzde değişimi
    - fx_eurtry_usdtry_ratio: EUR/USD çapraz kuru
    - fx_usdtry_momentum_20d: 20 günlük momentum
    - fx_usdtry_acceleration: Kur değişim ivmesi (2. türev)
    - fx_usdtry_volatility_20d: 20 günlük yıllıklandırılmış oynaklık (%)
    - fx_usdtry_volatility_5d: 5 günlük ani oynaklık
    - fx_usdtry_zscore: 60 günlük ortalamaya göre Z-Skoru
    - fx_usdtry_regime: 0 (Kuvvetli TL) ile 4 (Akut Devalüasyon Şoku) arası rejim kodu

    Args:
        fx_data: USD/TRY, EUR/TRY, önceki seviyeler, tarihsel fiyat serisi ve TÜFE verilerini içeren sözlük.

    Returns:
        dict[str, float]: Hesaplanmış döviz analitik feature sözlüğü.
    """
    features: dict[str, float] = {}

    try:
        usdtry_val = fx_data.get("usdtry")
        eurtry_val = fx_data.get("eurtry")

        usdtry = float(usdtry_val) if usdtry_val and float(usdtry_val) > 0 else None
        eurtry = float(eurtry_val) if eurtry_val and float(eurtry_val) > 0 else None

        # 1. USD/TRY Spot ve Günlük Değişim
        if usdtry is not None:
            features["fx_usdtry_level"] = round(usdtry, 4)

            usdtry_prev = fx_data.get("usdtry_previous")
            if usdtry_prev and float(usdtry_prev) > 0:
                change = (usdtry / float(usdtry_prev) - 1.0) * 100.0
                features["fx_usdtry_change_pct"] = round(change, 4)
                features["fx_usdtry_change_direction"] = 1.0 if change > 0.05 else (-1.0 if change < -0.05 else 0.0)

        # 2. EUR/TRY Spot ve Çapraz Kur
        if eurtry is not None:
            features["fx_eurtry_level"] = round(eurtry, 4)
            if usdtry is not None and usdtry > 0:
                features["fx_eurtry_usdtry_ratio"] = round(eurtry / usdtry, 4)

        # 3. Türkiye Döviz Sepeti (0.5 USD + 0.5 EUR)
        if usdtry is not None and eurtry is not None:
            basket = 0.5 * usdtry + 0.5 * eurtry
            features["fx_basket_level"] = round(basket, 4)

            usd_prev = float(fx_data.get("usdtry_previous") or 0.0)
            eur_prev = float(fx_data.get("eurtry_previous") or 0.0)
            if usd_prev > 0 and eur_prev > 0:
                basket_prev = 0.5 * usd_prev + 0.5 * eur_prev
                basket_chg = (basket / basket_prev - 1.0) * 100.0
                features["fx_basket_change_pct"] = round(basket_chg, 4)

        # 4. Tarihsel Analiz, Momentum, Oynaklık ve Z-Skoru
        history = fx_data.get("usdtry_history", [])
        if isinstance(history, list) and len(history) >= 20 and usdtry is not None:
            hist = np.array(history, dtype=np.float64)
            hist = hist[hist > 0]

            if len(hist) >= 20:
                # 60 günlük pencerede Z-skor (yoksa mevcut veri uzunluğu)
                window_len = min(len(hist), 60)
                mean = float(np.mean(hist[-window_len:]))
                std = float(np.std(hist[-window_len:]))
                if std > 0:
                    features["fx_usdtry_zscore"] = round((usdtry - mean) / std, 4)

                # 20 günlük momentum
                m_20 = (usdtry / hist[-20] - 1.0) * 100.0
                features["fx_usdtry_momentum_20d"] = round(m_20, 2)

                # 5 günlük kısa vade momentum
                if len(hist) >= 5:
                    m_5 = (usdtry / hist[-5] - 1.0) * 100.0
                    features["fx_usdtry_change_5d"] = round(m_5, 2)
                    # İvme (2. Türev: Son 5 gün momentumu vs önceki 5 gün)
                    if len(hist) >= 10:
                        prev_5 = (hist[-5] / hist[-10] - 1.0) * 100.0
                        features["fx_usdtry_acceleration"] = round(m_5 - prev_5, 4)

                # Yüzdelik dilim (Percentile rank)
                features["fx_usdtry_percentile"] = round(float(np.sum(hist <= usdtry) / len(hist)), 4)

                # 20 günlük yıllıklandırılmış oynaklık
                if len(hist) >= 21:
                    log_ret_20 = np.diff(np.log(hist[-21:]))
                    vol_20 = float(np.std(log_ret_20) * np.sqrt(252) * 100.0)
                    features["fx_usdtry_volatility_20d"] = round(vol_20, 2)

                # 5 günlük ani volatilite
                if len(hist) >= 6:
                    log_ret_5 = np.diff(np.log(hist[-6:]))
                    vol_5 = float(np.std(log_ret_5) * np.sqrt(252) * 100.0)
                    features["fx_usdtry_volatility_5d"] = round(vol_5, 2)

                # 5. Kur Rejimi Sınıflandırması
                momentum = features.get("fx_usdtry_momentum_20d", 0.0)
                volatility = features.get("fx_usdtry_volatility_20d", 0.0)

                if momentum > DEFAULT_FX_REGIME_SHOCK or volatility > 35.0:
                    regime = 4.0  # AKUT KUR ŞOKU / DEVALÜASYON BASKISI
                elif momentum > DEFAULT_FX_REGIME_STRONG_WEAKENING:
                    regime = 3.0  # HIZLI TL DEĞER KAYBI
                elif momentum > DEFAULT_FX_REGIME_MILD_WEAKENING:
                    regime = 2.0  # KONTROLLÜ / ILIMLI DEĞER KAYBI
                elif momentum < DEFAULT_FX_REGIME_STRENGTHENING:
                    regime = 0.0  # GÜÇLÜ TL KAZANIMI (DEZENFLASYON)
                else:
                    regime = 1.0  # STABİL / YATAY KUR

                features["fx_usdtry_regime"] = regime

        # 6. Reel Değerlenme / Enflasyon Farkı (REER Proxy)
        inflation_yoy = fx_data.get("inflation_yoy")
        if inflation_yoy is not None and "fx_usdtry_momentum_20d" in features:
            try:
                # 20 günlük kur değişimi yıllıklandırılarak enflasyonla kıyaslanır
                ann_fx_change = ((1.0 + features["fx_usdtry_momentum_20d"] / 100.0) ** (252 / 20) - 1.0) * 100.0
                reer_gap = ann_fx_change - float(inflation_yoy)
                features["fx_real_depreciation_gap"] = round(reer_gap, 2)
            except (ValueError, OverflowError):
                pass

    except Exception as e:
        logger.error("Döviz analitik feature hesaplaması başarısız oldu", error=str(e))

    return features


__all__ = [
    "DEFAULT_FX_REGIME_SHOCK",
    "DEFAULT_FX_REGIME_STRONG_WEAKENING",
    "DEFAULT_FX_REGIME_MILD_WEAKENING",
    "DEFAULT_FX_REGIME_STABLE",
    "DEFAULT_FX_REGIME_STRENGTHENING",
    "compute_fx_features",
]


