"""ALPHA BIST — BIST-Specific Anomalies & Factors (Nihai).

8 anomaly/faktör: temettü, likidite, kur, enflasyon, faiz, sektör momentum,
KAP sentiment, yabancı yatırımcı.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "ANOMALY_DEFINITIONS",
    "calculate_anomaly_score",
    "calculate_bist_anomalies",
    "calculate_bist_anomalies_batch",
]

# Normalize sabitleri — magic number yok
_DIVISOR_DIVIDEND: float = 10.0      # %10 temettü verimi = 1.0 skor
_DIVISOR_VOLUME: float = 10_000_000  # 10M hacim = 0.0 likidite premium
_DIVISOR_BETA: float = 2.0           # Beta normalize çarpanı
_DIVISOR_MOMENTUM: float = 20.0      # Sektör momentum normalize çarpanı
_DIVISOR_FOREIGN: float = 50.0       # %50 yabancı sahiplik = 1.0 skor

# Anomaly tanımları — immutable
ANOMALY_DEFINITIONS: MappingProxyType[str, MappingProxyType[str, Any]] = MappingProxyType({
    "dividend_yield": MappingProxyType({
        "description": "Yüksek temettü verimi → excess return",
        "direction": 1,  # Pozitif = yüksek getiri
        "weight": 0.15,
    }),
    "liquidity_premium": MappingProxyType({
        "description": "Düşük likidite → likidite premium",
        "direction": -1,  # Düşük likidite = yüksek premium
        "weight": 0.10,
    }),
    "fx_sensitivity": MappingProxyType({
        "description": "USDTRY hassasiyeti → FX premium",
        "direction": -1,  # Düşük hassasiyet = tercih edilen
        "weight": 0.15,
    }),
    "inflation_sensitivity": MappingProxyType({
        "description": "Enflasyon hassasiyeti → inflation hedge",
        "direction": 1,  # Yüksek hassasiyet = enflasyon hedge
        "weight": 0.10,
    }),
    "rate_sensitivity": MappingProxyType({
        "description": "Faiz hassasiyeti → rate risk premium",
        "direction": -1,  # Düşük hassasiyet = tercih edilen
        "weight": 0.10,
    }),
    "sector_momentum": MappingProxyType({
        "description": "Sektör rotasyonu → momentum",
        "direction": 1,
        "weight": 0.15,
    }),
    "kap_sentiment": MappingProxyType({
        "description": "KAP açıklamaları sentiment",
        "direction": 1,
        "weight": 0.10,
    }),
    "foreign_ownership": MappingProxyType({
        "description": "Yabancı yatırımcı oranı → foreign premium",
        "direction": 1,
        "weight": 0.15,
    }),
})


def _safe_float(value: Any, default: float = 0.0, name: str = "unknown") -> float:
    """Değeri güvenli float'a çevirir; None, NaN veya Inf için varsayılan döndürür.

    Args:
        value: Dönüştürülecek değer.
        default: Hata durumunda dönecek varsayılan değer.
        name: Loglama için alan adı.

    Returns:
        Güvenli float değeri.
    """
    if value is None:
        logger.warning("bist_anomalies_none_value", field=name, default=default)
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            logger.warning("bist_anomalies_nan_or_inf", field=name, value=value, default=default)
            return default
        return result
    except (ValueError, TypeError) as exc:
        logger.warning(
            "bist_anomalies_type_conversion_failed",
            field=name, value=value, error=str(exc), default=default,
        )
        return default


def calculate_bist_anomalies(
    stock: dict[str, Any] | None,
    market_data: dict[str, Any] | None = None,
) -> dict[str, float]:
    """BIST'e özgü anomaly/faktör skorları.

    Args:
        stock: Hisse verileri sözlüğü. Beklenen anahtarlar:
            dividend_yield, avg_volume, usdtry_beta, inflation_beta,
            rate_beta, sector_momentum, kap_sentiment, foreign_ownership
        market_data: Piyasa verileri (opsiyonel, gelecekte kullanım için).

    Returns:
        8 anomaly skoru sözlüğü (çoğu 0-1, sector_momentum ve kap_sentiment -1 ile 1 arası).

    Raises:
        TypeError: stock None veya dict değilse.
    """
    if stock is None:
        raise TypeError("stock parametresi None olamaz")
    if not isinstance(stock, dict):
        raise TypeError(f"stock dict olmalı, alınan tip: {type(stock).__name__}")

    anomalies: dict[str, float] = {}

    # 1. Temettü anomalisi
    div_yield = _safe_float(stock.get("dividend_yield"), default=0.0, name="dividend_yield")
    anomalies["dividend_yield"] = min(max(div_yield / _DIVISOR_DIVIDEND, 0.0), 1.0)

    # 2. Likidite anomalisi
    avg_vol = _safe_float(stock.get("avg_volume"), default=0.0, name="avg_volume")
    anomalies["liquidity_premium"] = 1.0 - min(avg_vol / _DIVISOR_VOLUME, 1.0)

    # 3. Kur hassasiyeti
    # Pozitif beta = USDTRY artarken hisse de artar (ihracatçı → tercih edilen)
    # Negatif beta = USDTRY artarken hisse düşer (ithalatçı → riskli)
    fx_beta = _safe_float(stock.get("usdtry_beta"), default=0.0, name="usdtry_beta")
    anomalies["fx_sensitivity"] = min(max(fx_beta / _DIVISOR_BETA, 0.0), 1.0)

    # 4. Enflasyon hassasiyeti — pozitif beta = enflasyon hedge
    inf_beta = _safe_float(stock.get("inflation_beta"), default=0.0, name="inflation_beta")
    anomalies["inflation_sensitivity"] = min(max(inf_beta / _DIVISOR_BETA, 0.0), 1.0)

    # 5. Faiz hassasiyeti — negatif beta = faiz artarken düşer (riskli)
    rate_beta = _safe_float(stock.get("rate_beta"), default=0.0, name="rate_beta")
    anomalies["rate_sensitivity"] = min(max(-rate_beta / _DIVISOR_BETA, 0.0), 1.0)

    # 6. Sektör momentum
    sector_mom = _safe_float(stock.get("sector_momentum"), default=0.0, name="sector_momentum")
    anomalies["sector_momentum"] = min(max(sector_mom / _DIVISOR_MOMENTUM, -1.0), 1.0)

    # 7. KAP sentiment
    kap_sent = _safe_float(stock.get("kap_sentiment"), default=0.0, name="kap_sentiment")
    anomalies["kap_sentiment"] = min(max(kap_sent, -1.0), 1.0)

    # 8. Yabancı yatırımcı
    foreign = _safe_float(stock.get("foreign_ownership"), default=0.0, name="foreign_ownership")
    anomalies["foreign_ownership"] = min(foreign / _DIVISOR_FOREIGN, 1.0)

    return anomalies


def calculate_anomaly_score(
    anomalies: dict[str, float] | None,
    weights: dict[str, float] | None = None,
) -> float:
    """Ağırlıklı anomaly skoru (0-100).

    Args:
        anomalies: Anomaly skorları sözlüğü.
        weights: Ağırlıklar (opsiyonel). None ise ANOMALY_DEFINITIONS kullanılır.

    Returns:
        Ağırlıklı toplam skor (0-100).

    Raises:
        TypeError: anomalies None veya dict değilse.
    """
    if anomalies is None:
        raise TypeError("anomalies parametresi None olamaz")
    if not isinstance(anomalies, dict):
        raise TypeError(f"anomalies dict olmalı, alınan tip: {type(anomalies).__name__}")

    w = weights or {k: v["weight"] for k, v in ANOMALY_DEFINITIONS.items()}
    total_weight = sum(w.values())

    score = 0.0
    for name, value in anomalies.items():
        safe_value = _safe_float(value, default=0.0, name=f"anomaly.{name}")
        weight = w.get(name, 0)
        direction = ANOMALY_DEFINITIONS.get(name, MappingProxyType({"direction": 1}))["direction"]

        # Yön düzeltmesi
        adjusted_value = safe_value if direction > 0 else (1 - safe_value)
        score += adjusted_value * weight

    return round(score / max(total_weight, 0.001) * 100, 1)


def calculate_bist_anomalies_batch(
    universe: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Tüm evren için toplu anomaly hesaplama.

    Args:
        universe: Hisse listesi.

    Returns:
        Anomaly skorları eklenmiş hisse listesi.
        Girdi listesi doğrudan değiştirilir (in-place).

    Raises:
        TypeError: universe None veya list değilse.
    """
    if universe is None:
        raise TypeError("universe parametresi None olamaz")
    if not isinstance(universe, list):
        raise TypeError(f"universe list olmalı, alınan tip: {type(universe).__name__}")

    for stock in universe:
        anomalies = calculate_bist_anomalies(stock)
        stock["bist_anomalies"] = anomalies
        stock["anomaly_score"] = calculate_anomaly_score(anomalies)
    return universe
