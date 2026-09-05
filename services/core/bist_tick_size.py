"""ALPHA BIST — Borsa İstanbul Resmî Fiyat Adımı (Tick Size) Motoru.

Bu modül, Borsa İstanbul Pay Piyasası Yönergesi ve SPK düzenlemelerine uygun olarak:
- Fiyat seviyesine göre dinamik fiyat adımı belirleme (0.01 TL, 0.02 TL, 0.05 TL, 0.10 TL)
- Özel enstrüman tipleri (Varant, Sertifika, Yatırım Fonu vb.) desteği
- Float hassasiyeti güvenliğinde fiyata en yakın veya yöne bağlı (side-aware) adım yuvarlama
- IEEE 754 modulo hatalarından arındırılmış fiyat adımı geçerlilik denetimi
- Kademeler arası dinamik adım ekleme/çıkarma (dynamic tick traversal)
- İki fiyat arasındaki kademe farkı (spread in ticks) hesaplama işlemlerini yürütür.

BIST Pay Piyasası Fiyat Adımı Kademeleri:
- 0.01 TL - 19.99 TL   -> 0.01 TL
- 20.00 TL - 49.98 TL  -> 0.02 TL
- 50.00 TL - 99.95 TL  -> 0.05 TL
- 100.00 TL ve üzeri   -> 0.10 TL
"""

from __future__ import annotations

import math
from typing import Final

import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Tolerans ve Enstrüman Sabitleri
DEFAULT_TICK_TOLERANCE: Final[float] = 1e-4
DEFAULT_INSTRUMENT_TYPE: Final[str] = "stock"

# Özel fiyat adımı tablosu (enstrüman tipine göre)
SPECIAL_TICK_SIZES: Final[dict[str, float]] = {
    "warrant": 0.001,  # Varant
    "certificate": 0.001,  # Sertifika
    "fund": 0.001,  # Yatırım fonu katılma payı
    "etf": 0.01,  # Borsa yatırım fonu
}

VALID_ROUNDING_MODES: Final[frozenset[str]] = frozenset(
    {"NEAREST", "FLOOR", "CEIL", "DOWN", "UP", "SIDE", "SIDE_AWARE"}
)


@otel_trace("bist_tick_size.get_bist_tick_size")
def get_bist_tick_size(price: float, instrument_type: str = DEFAULT_INSTRUMENT_TYPE) -> float:
    """Fiyat seviyesine ve enstrüman tipine göre BIST resmî minimum fiyat adımını döndürür.

    Args:
        price: Fiyat seviyesi (TL).
        instrument_type: Enstrüman tipi ('stock', 'warrant', 'certificate', 'fund', 'etf').

    Returns:
        float: Uygulanması gereken minimum fiyat adımı (TL).
    """
    norm_type = instrument_type.lower().strip() if isinstance(instrument_type, str) else DEFAULT_INSTRUMENT_TYPE

    # Özel enstrüman tipleri
    if norm_type in SPECIAL_TICK_SIZES:
        return SPECIAL_TICK_SIZES[norm_type]

    # Geçersiz, sıfır veya sayısal olmayan fiyatlarda fail-closed gereği en küçük pay adımı döner
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return 0.01

    # BIST Standart Pay Piyasası Kademeleri
    if price < 20.0:
        return 0.01
    elif price < 50.0:
        return 0.02
    elif price < 100.0:
        return 0.05
    else:
        return 0.10


@otel_trace("bist_tick_size.round_to_bist_tick")
def round_to_bist_tick(
    price: float,
    side: str = "BUY",
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
    mode: str = "NEAREST",
) -> float:
    """Fiyatı geçerli en yakın veya yöne bağlı BIST fiyat adımına yuvarlar.

    Args:
        price: Yuvarlanacak fiyat (TL).
        side: Emir yönü ('BUY' | 'SELL'). Yöne duyarlı modlarda kullanılır.
        instrument_type: Enstrüman kategorisi.
        mode: Yuvarlama modu ('NEAREST', 'FLOOR', 'CEIL', 'SIDE_AWARE').

    Returns:
        float: BIST fiyat adımına tam oturan yuvarlanmış fiyat.
    """
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return 0.0

    tick = get_bist_tick_size(price, instrument_type)
    norm_mode = mode.upper().strip() if isinstance(mode, str) else "NEAREST"
    norm_side = side.upper().strip() if isinstance(side, str) else "BUY"

    # Mod doğrulaması ve adım hesabı
    if norm_mode in ("FLOOR", "DOWN"):
        steps = math.floor(round(price / tick, 6))
    elif norm_mode in ("CEIL", "UP"):
        steps = math.ceil(round(price / tick, 6))
    elif norm_mode in ("SIDE", "SIDE_AWARE"):
        # Alış emrinde bütçeyi aşmamak için aşağı (floor), satış emrinde ucuza vermemek için yukarı (ceil)
        if norm_side == "BUY":
            steps = math.floor(round(price / tick, 6))
        else:
            steps = math.ceil(round(price / tick, 6))
    else:
        # Varsayılan: En yakın fiyata yuvarlama (Half-way to even float guard ile)
        steps = round(price / tick)

    # 0 veya negatif fiyata yuvarlanmayı engelle (en az 1 tick olmalıdır)
    if steps <= 0:
        steps = 1

    rounded = steps * tick
    precision = 4 if tick < 0.01 else 2
    return round(rounded, precision)


@otel_trace("bist_tick_size.is_valid_bist_tick")
def is_valid_bist_tick(
    price: float,
    tolerance: float = DEFAULT_TICK_TOLERANCE,
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
) -> bool:
    """Fiyatın geçerli bir BIST fiyat adımına uygun olup olmadığını denetler.

    IEEE 754 float modulo hatasını önlemek için doğrudan fark mesafesi yöntemi kullanılır.

    Args:
        price: Denetlenecek fiyat değeri.
        tolerance: Sayısal fark kabul toleransı.
        instrument_type: Enstrüman tipi.

    Returns:
        bool: Fiyat BIST adımına tam uyuyorsa True, aksi halde False.
    """
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return False

    tick = get_bist_tick_size(price, instrument_type)
    steps = round(price / tick)
    expected_price = round(steps * tick, 4 if tick < 0.01 else 2)
    return abs(price - expected_price) < tolerance


@otel_trace("bist_tick_size.add_bist_ticks")
def add_bist_ticks(
    price: float,
    ticks: int,
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
) -> float:
    """Belirtilen fiyata BIST kademelerini dinamik olarak atlayarak kademe ekler veya çıkarır.

    Fiyat kademe sınırlarını (örneğin 19.99 TL -> 20.00 TL) geçerken değişen adım boyutunu
    otomatik olarak dikkate alır.

    Args:
        price: Başlangıç fiyatı.
        ticks: Eklenecek (pozitif) veya çıkarılacak (negatif) kademe sayısı.
        instrument_type: Enstrüman kategorisi.

    Returns:
        float: Kademeler geçildikten sonraki nihai fiyat.
    """
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return 0.0
    if ticks == 0:
        return round_to_bist_tick(price, instrument_type=instrument_type)

    current_price = round_to_bist_tick(price, instrument_type=instrument_type)
    step_direction = 1 if ticks > 0 else -1
    remaining_ticks = abs(ticks)

    for _ in range(remaining_ticks):
        tick_size = get_bist_tick_size(current_price, instrument_type)
        # Eğer aşağı iniyorsak ve tam kademe sınırındaysak bir alt kademe tick'ini kullan
        if step_direction < 0:
            candidate = round(current_price - 0.0001, 4)
            if candidate > 0:
                tick_size = get_bist_tick_size(candidate, instrument_type)

        next_price = current_price + (step_direction * tick_size)
        precision = 4 if tick_size < 0.01 else 2
        current_price = round(next_price, precision)

        if current_price <= 0.0:
            current_price = get_bist_tick_size(0.01, instrument_type)
            break

    return current_price


@otel_trace("bist_tick_size.get_bist_tick_count_between")
def get_bist_tick_count_between(
    price_from: float,
    price_to: float,
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
) -> int:
    """İki fiyat seviyesi arasındaki geçerli BIST kademe (tick) farkını hesaplar.

    Args:
        price_from: Başlangıç fiyatı.
        price_to: Bitiş fiyatı.
        instrument_type: Enstrüman kategorisi.

    Returns:
        int: Kademe sayısı (price_to > price_from ise pozitif, küçükse negatif).
    """
    if price_from <= 0.0 or price_to <= 0.0:
        return 0
    if math.isnan(price_from) or math.isnan(price_to):
        return 0
    if math.isinf(price_from) or math.isinf(price_to):
        return 0

    p_start = round_to_bist_tick(price_from, instrument_type=instrument_type)
    p_end = round_to_bist_tick(price_to, instrument_type=instrument_type)

    if p_start == p_end:
        return 0

    direction = 1 if p_end > p_start else -1
    low, high = (p_start, p_end) if direction == 1 else (p_end, p_start)

    count = 0
    curr = low
    while curr < high:
        tick = get_bist_tick_size(curr, instrument_type)
        curr = round(curr + tick, 4 if tick < 0.01 else 2)
        count += 1

    return count * direction


__all__ = [
    "DEFAULT_INSTRUMENT_TYPE",
    "DEFAULT_TICK_TOLERANCE",
    "SPECIAL_TICK_SIZES",
    "VALID_ROUNDING_MODES",
    "add_bist_ticks",
    "get_bist_tick_count_between",
    "get_bist_tick_size",
    "is_valid_bist_tick",
    "round_to_bist_tick",
]
