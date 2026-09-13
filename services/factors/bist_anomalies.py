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
            Şu an kullanılmıyor, ileriye dönük rezerved.

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

    # Piyasa Koşullandırma Çarpanları (Market Conditioning Factors)
    fx_multiplier = 1.0
    inf_multiplier = 1.0
    liq_multiplier = 1.0
    index_excess_mom = 0.0
    foreign_flow_bonus = 0.0

    if market_data and isinstance(market_data, dict):
        # 1. Döviz Şoku Koşullandırması: USDTRY yükseliyorsa ihracatçı primi artar
        fx_change = _safe_float(market_data.get("usdtry_change") or market_data.get("fx_change"), default=0.0)
        if fx_change > 0:
            fx_multiplier = 1.0 + min(1.0, fx_change / 5.0)

        # 2. Enflasyon Rejimi Koşullandırması: Yüksek enflasyonda fiyatlama gücü primi
        market_cpi = _safe_float(market_data.get("inflation_rate") or market_data.get("cpi_annual"), default=0.0)
        if market_cpi > 30.0:
            inf_multiplier = 1.0 + min(1.0, (market_cpi - 30.0) / 70.0)

        # 3. Piyasa Likidite Sıkışıklığı: Piyasa hacmi düştüğünde likit olmayan hisselere iskonto
        market_vol = _safe_float(market_data.get("market_volume") or market_data.get("total_turnover"), default=0.0)
        benchmark_vol = _safe_float(market_data.get("avg_market_volume"), default=50_000_000_000.0)
        if 0 < market_vol < benchmark_vol:
            liq_multiplier = 1.0 + min(0.5, (benchmark_vol - market_vol) / benchmark_vol)

        # 4. Endekse Göre Göreli Sektör Momentumu (Saf Alfa Ayrışması)
        index_ret = _safe_float(market_data.get("bist100_return") or market_data.get("index_return"), default=0.0)
        index_excess_mom = index_ret

        # 5. Yabancı Yatırımcı Akış Momentumu
        foreign_inflow = _safe_float(market_data.get("foreign_net_flow") or market_data.get("foreign_flow_million_usd"), default=0.0)
        if foreign_inflow > 0:
            foreign_flow_bonus = min(0.3, foreign_inflow / 1000.0)

    # 1. Temettü anomalisi
    div_yield = _safe_float(stock.get("dividend_yield"), default=0.0, name="dividend_yield")
    anomalies["dividend_yield"] = round(min(max(div_yield / _DIVISOR_DIVIDEND, 0.0), 1.0), 4)

    # 2. Likidite anomalisi (Piyasa likidite sıkışıklığı ile dinamik ölçekli)
    avg_vol = _safe_float(stock.get("avg_volume"), default=0.0, name="avg_volume")
    raw_liq = 1.0 - min(avg_vol / _DIVISOR_VOLUME, 1.0)
    anomalies["liquidity_premium"] = round(min(1.0, raw_liq * liq_multiplier), 4)

    # 3. Kur hassasiyeti (Piyasa döviz kuru şok rejimi ile dinamik ölçekli)
    fx_beta = _safe_float(stock.get("usdtry_beta"), default=0.0, name="usdtry_beta")
    raw_fx = min(max(fx_beta / _DIVISOR_BETA, 0.0), 1.0)
    anomalies["fx_sensitivity"] = round(min(1.0, raw_fx * fx_multiplier), 4)

    # 4. Enflasyon hassasiyeti (Piyasa makro enflasyon seviyesi ile dinamik ölçekli)
    inf_beta = _safe_float(stock.get("inflation_beta"), default=0.0, name="inflation_beta")
    raw_inf = min(max(inf_beta / _DIVISOR_BETA, 0.0), 1.0)
    anomalies["inflation_sensitivity"] = round(min(1.0, raw_inf * inf_multiplier), 4)

    # 5. Faiz hassasiyeti — negatif beta = faiz artarken düşer (riskli)
    rate_beta = _safe_float(stock.get("rate_beta"), default=0.0, name="rate_beta")
    anomalies["rate_sensitivity"] = round(min(max(-rate_beta / _DIVISOR_BETA, 0.0), 1.0), 4)

    # 6. Sektör momentum (Endeks getirisinden arındırılmış bağıl sektör gücü)
    sector_mom = _safe_float(stock.get("sector_momentum"), default=0.0, name="sector_momentum")
    excess_sec_mom = sector_mom - index_excess_mom
    anomalies["sector_momentum"] = round(min(max(excess_sec_mom / _DIVISOR_MOMENTUM, -1.0), 1.0), 4)

    # 7. KAP sentiment
    kap_sent = _safe_float(stock.get("kap_sentiment"), default=0.0, name="kap_sentiment")
    anomalies["kap_sentiment"] = round(min(max(kap_sent, -1.0), 1.0), 4)

    # 8. Yabancı yatırımcı (Akış bonusu ile desteklenmiş)
    foreign = _safe_float(stock.get("foreign_ownership"), default=0.0, name="foreign_ownership")
    raw_foreign = min(foreign / _DIVISOR_FOREIGN, 1.0)
    anomalies["foreign_ownership"] = round(min(1.0, raw_foreign + foreign_flow_bonus), 4)

    return anomalies


# Bilinmeyen anomaly'ler için varsayılan (tek instance)
_DEFAULT_ANOMALY: MappingProxyType[str, Any] = MappingProxyType({"direction": 1})


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

    w = weights if weights is not None else {k: v["weight"] for k, v in ANOMALY_DEFINITIONS.items()}
    total_weight = sum(w.values())

    score = 0.0
    for name, value in anomalies.items():
        safe_value = _safe_float(value, default=0.0, name=f"anomaly.{name}")
        weight = w.get(name, 0)
        direction = ANOMALY_DEFINITIONS.get(name, _DEFAULT_ANOMALY)["direction"]

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
