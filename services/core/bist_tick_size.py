"""
ALPHA BIST — Official Borsa Istanbul Tick Size (Fiyat Adımı) Motoru

BIST Pay Piyasası Fiyat Adımı Tablosu:
- 0.01 - 19.99 TL   -> 0.01 TL
- 20.00 - 49.98 TL  -> 0.02 TL
- 50.00 - 99.95 TL  -> 0.05 TL
- 100.00 TL ve üstü -> 0.10 TL
"""

import math
from typing import Tuple


def get_bist_tick_size(price: float) -> float:
    """Fiyat seviyesine göre BIST resmi minimum fiyat adımını döndürür."""
    if price < 20.0:
        return 0.01
    elif price < 50.0:
        return 0.02
    elif price < 100.0:
        return 0.05
    else:
        return 0.10


def round_to_bist_tick(price: float, side: str = "BUY") -> float:
    """Fiyatı en yakın geçerli BIST fiyat adımına yuvarlar."""
    if price <= 0:
        return 0.0
    tick = get_bist_tick_size(price)
    # Alışta yukarı, satışta aşağı yuvarlama veya en yakın adıma yuvarlama
    steps = round(price / tick)
    rounded = steps * tick
    # 4 basamak yuvarlama ile float hassasiyetini temizle
    return round(rounded, 2 if tick >= 0.01 else 4)


def is_valid_bist_tick(price: float, tolerance: float = 1e-4) -> bool:
    """Fiyatın geçerli bir BIST fiyat adımına uyup uymadığını kontrol eder."""
    if price <= 0:
        return False
    tick = get_bist_tick_size(price)
    remainder = abs(price % tick)
    return remainder < tolerance or abs(remainder - tick) < tolerance
