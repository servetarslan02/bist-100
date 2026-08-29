"""
ALPHA BIST — Official Borsa Istanbul Tick Size (Fiyat Adımı) Motoru v2.0 (Enterprise-Grade)

BIST Pay Piyasası Fiyat Adımı Tablosu (Standart):
- 0.01 - 19.99 TL   -> 0.01 TL
- 20.00 - 49.98 TL  -> 0.02 TL
- 50.00 - 99.95 TL  -> 0.05 TL
- 100.00 TL ve üstü -> 0.10 TL

Özel Durumlar:
- Varant/Sertifika: 0.001 TL
- Yeni halka arz: İlk günlerde farklı adımlar olabilir
"""

from __future__ import annotations

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.bist_tick_size")

# Özel fiyat adımı tablosu (enstrüman tipine göre)
SPECIAL_TICK_SIZES: dict[str, float] = {
    "warrant": 0.001,  # Varant
    "certificate": 0.001,  # Sertifika
    "fund": 0.001,  # Yatırım fonu katılma payı
}


def get_bist_tick_size(price: float, instrument_type: str = "stock") -> float:
    """Fiyat seviyesine ve enstrüman tipine göre BIST resmi minimum fiyat adımını döndürür."""
    # Özel enstrüman tipleri
    if instrument_type in SPECIAL_TICK_SIZES:
        return SPECIAL_TICK_SIZES[instrument_type]

    # Standart pay piyasası
    if price < 20.0:
        return 0.01
    elif price < 50.0:
        return 0.02
    elif price < 100.0:
        return 0.05
    else:
        return 0.10


def round_to_bist_tick(price: float, side: str = "BUY", instrument_type: str = "stock") -> float:
    """Fiyatı en yakın geçerli BIST fiyat adımına yuvarlar."""
    with tracer.start_as_current_span("bist_tick_size.round_to_bist_tick") as span:
        if price <= 0:
            return 0.0
        tick = get_bist_tick_size(price, instrument_type)
        # Alışta yukarı, satışta aşağı yuvarlama veya en yakın adıma yuvarlama
        steps = round(price / tick)
        rounded = steps * tick
        # 4 basamak yuvarlama ile float hassasiyetini temizle
        result = round(rounded, 2 if tick >= 0.01 else 4)

        span.set_attribute("price.original", price)
        span.set_attribute("price.rounded", result)
        span.set_attribute("price.tick", tick)
        return result


def is_valid_bist_tick(price: float, tolerance: float = 1e-4, instrument_type: str = "stock") -> bool:
    """Fiyatın geçerli bir BIST fiyat adımına uyup uymadığını kontrol eder."""
    with tracer.start_as_current_span("bist_tick_size.is_valid_bist_tick") as span:
        if price <= 0:
            return False
        tick = get_bist_tick_size(price, instrument_type)
        remainder = abs(price % tick)
        is_valid = remainder < tolerance or abs(remainder - tick) < tolerance

        span.set_attribute("price", price)
        span.set_attribute("is_valid", is_valid)
        return is_valid
