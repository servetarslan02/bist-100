"""ALPHA BIST — BIST-Specific Anomalies & Factors (Nihai).

8+ anomaly/faktör: temettü, likidite, kur, enflasyon, faiz, sektör momentum,
KAP sentiment, yabancı yatırımcı.
"""
from typing import Dict, Any, List, Optional
import numpy as np
import structlog

logger = structlog.get_logger()

# Anomaly tanımları
ANOMALY_DEFINITIONS = {
    "dividend_yield": {
        "description": "Yüksek temettü verimi → excess return",
        "direction": 1,  # Pozitif = yüksek getiri
        "weight": 0.15,
    },
    "liquidity_premium": {
        "description": "Düşük likidite → likidite premium",
        "direction": -1,  # Düşük likidite = yüksek premium
        "weight": 0.10,
    },
    "fx_sensitivity": {
        "description": "USDTRY hassasiyeti → FX premium",
        "direction": -1,  # Düşük hassasiyet = tercih edilen
        "weight": 0.15,
    },
    "inflation_sensitivity": {
        "description": "Enflasyon hassasiyeti → inflation hedge",
        "direction": 1,  # Yüksek hassasiyet = enflasyon hedge
        "weight": 0.10,
    },
    "rate_sensitivity": {
        "description": "Faiz hassasiyeti → rate risk premium",
        "direction": -1,  # Düşük hassasiyet = tercih edilen
        "weight": 0.10,
    },
    "sector_momentum": {
        "description": "Sektör rotasyonu → momentum",
        "direction": 1,
        "weight": 0.15,
    },
    "kap_sentiment": {
        "description": "KAP açıklamaları sentiment",
        "direction": 1,
        "weight": 0.10,
    },
    "foreign_ownership": {
        "description": "Yabancı yatırımcı oranı → foreign premium",
        "direction": 1,
        "weight": 0.15,
    },
}


def calculate_bist_anomalies(
    stock: Dict[str, Any],
    market_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """BIST'e özgü anomaly/faktör skorları.

    Args:
        stock: Hisse verileri
        market_data: Piyasa verileri (opsiyonel)

    Returns:
        Dict with anomaly scores (0-1 arası)
    """
    anomalies = {}

    # 1. Temettü anomalisi
    div_yield = stock.get("dividend_yield", 0)
    anomalies["dividend_yield"] = min(div_yield / 10.0, 1.0)  # Normalize: %10 = 1.0

    # 2. Likidite anomalisi
    avg_vol = stock.get("avg_volume", 0)
    anomalies["liquidity_premium"] = 1.0 - min(avg_vol / 10_000_000, 1.0)

    # 3. Kur hassasiyeti
    # Düzeltme (v2.1): abs() kaldırıldı — yön önemli
    # Pozitif beta = USDTRY artarken hisse de artar (ihracatçı → tercih edilen)
    # Negatif beta = USDTRY artarken hisse düşer (ithalatçı → riskli)
    # abs() kullanmak ihracatçı ve ithalatçı şirketleri aynı skorluyordu
    fx_beta = stock.get("usdtry_beta", 0)
    anomalies["fx_sensitivity"] = min(max(fx_beta / 2.0, 0.0), 1.0)

    # 4. Enflasyon hassasiyeti
    # Düzeltme (v2.1): abs() kaldırıldı — pozitif beta = enflasyon hedge
    inf_beta = stock.get("inflation_beta", 0)
    anomalies["inflation_sensitivity"] = min(max(inf_beta / 2.0, 0.0), 1.0)

    # 5. Faiz hassasiyeti
    # Düzeltme (v2.1): abs() kaldırıldı — negatif beta = faiz artarken düşer (riskli)
    rate_beta = stock.get("rate_beta", 0)
    anomalies["rate_sensitivity"] = min(max(-rate_beta / 2.0, 0.0), 1.0)

    # 6. Sektör momentum
    anomalies["sector_momentum"] = min(max(stock.get("sector_momentum", 0) / 20.0, -1.0), 1.0)

    # 7. KAP sentiment
    anomalies["kap_sentiment"] = min(max(stock.get("kap_sentiment", 0), -1.0), 1.0)

    # 8. Yabancı yatırımcı
    anomalies["foreign_ownership"] = min(stock.get("foreign_ownership", 0) / 50.0, 1.0)

    return anomalies


def calculate_anomaly_score(
    anomalies: Dict[str, float],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Ağırlıklı anomaly skoru (0-100).

    Args:
        anomalies: Anomaly skorları
        weights: Ağırlıklar (opsiyonel)

    Returns:
        Ağırlıklı toplam skor (0-100)
    """
    w = weights or {k: v["weight"] for k, v in ANOMALY_DEFINITIONS.items()}
    total_weight = sum(w.values())

    score = 0.0
    for name, value in anomalies.items():
        weight = w.get(name, 0)
        direction = ANOMALY_DEFINITIONS.get(name, {}).get("direction", 1)

        # Yön düzeltmesi
        adjusted_value = value if direction > 0 else (1 - value)
        score += adjusted_value * weight

    return round(score / max(total_weight, 0.001) * 100, 1)


def calculate_bist_anomalies_batch(
    universe: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Tüm evren için toplu anomaly hesaplama.

    Args:
        universe: Hisse listesi

    Returns:
        Anomaly skorları eklenmiş hisse listesi
    """
    for stock in universe:
        anomalies = calculate_bist_anomalies(stock)
        stock["bist_anomalies"] = anomalies
        stock["anomaly_score"] = calculate_anomaly_score(anomalies)
    return universe
