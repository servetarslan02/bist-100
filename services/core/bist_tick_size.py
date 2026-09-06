"""ALPHA BIST — Borsa İstanbul Resmî Fiyat Adımı (Tick Size) Motoru.

Bu modül, Borsa İstanbul Pay Piyasası Yönergesi ve SPK düzenlemelerine uygun olarak:
- Fiyat seviyesine göre dinamik fiyat adımı belirleme (0.01 TL, 0.02 TL, 0.05 TL, 0.10 TL)
- Özel enstrüman tipleri (Varant, Sertifika, Yatırım Fonu, BYF vb.) desteği
- Float hassasiyeti güvenliğinde fiyata en yakın veya yöne bağlı (side-aware) adım yuvarlama
- IEEE 754 modulo anomalilerinden arındırılmış fiyat adımı geçerlilik denetimi
- Kademeler arası O(1) analitik hızlı adım ekleme/çıkarma (analytical tick traversal)
- İki fiyat arasındaki kademe farkını O(1) analitik hesaplama (spread in ticks)
- BIST resmî limit bandı (taban/tavan) hesaplama
- Polars Series düzeyinde yüksek hızlı toplu vektörize yuvarlama motoru
- DuckDB üzerinde kural referans tablosu kalıcı saklama ve analitik sorgulama işlemlerini yürütür.

BIST Pay Piyasası Fiyat Adımı Kademeleri:
- 0.01 TL - 19.99 TL   -> 0.01 TL
- 20.00 TL - 49.98 TL  -> 0.02 TL
- 50.00 TL - 99.95 TL  -> 0.05 TL
- 100.00 TL ve üzeri   -> 0.10 TL
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import duckdb
import polars as pl
import structlog

from services.core.otel import otel_trace

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = structlog.get_logger(__name__)

# Tolerans, Veritabanı ve Enstrüman Sabitleri
DEFAULT_TICK_TOLERANCE: Final[float] = 1e-4
DEFAULT_INSTRUMENT_TYPE: Final[str] = "stock"
DEFAULT_TICK_DB_PATH: Final[str] = "data/bist_tick_rules.duckdb"
DEFAULT_PRICE_LIMIT_RATIO: Final[float] = 0.10

# Özel fiyat adımı tablosu (enstrüman tipine göre)
SPECIAL_TICK_SIZES: Final[dict[str, float]] = {
    "warrant": 0.001,  # Varant
    "certificate": 0.001,  # Sertifika
    "fund": 0.001,  # Yatırım fonu katılma payı
    "etf": 0.01,  # Borsa yatırım fonu (BYF)
}

VALID_ROUNDING_MODES: Final[frozenset[str]] = frozenset(
    {"NEAREST", "FLOOR", "CEIL", "DOWN", "UP", "SIDE", "SIDE_AWARE"}
)


@dataclass(slots=True)
class BISTTickTier:
    """BIST fiyat adımı kademe tanımı modeli."""

    tier_name: str
    min_price: float
    max_price: float
    tick_size: float
    description: str

    def to_dict(self) -> dict[str, str | float]:
        """Kademe verisini sözlük formatında döner."""
        return {
            "tier_name": self.tier_name,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "tick_size": self.tick_size,
            "description": self.description,
        }

    def __repr__(self) -> str:
        """Kademe modelinin açıklayıcı metin temsilini döner."""
        return (
            f"BISTTickTier(kademe='{self.tier_name}', min={self.min_price}, "
            f"maks={self.max_price}, adim={self.tick_size})"
        )


def _safe_float(val: object, default: float = 0.0) -> float:
    """Girdiyi güvenli şekilde float tipine dönüştürür."""
    if val is None:
        return default
    try:
        f = float(val)  # type: ignore[arg-type]
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


@otel_trace("bist_tick_size.get_bist_tick_size")
def get_bist_tick_size(price: float, instrument_type: str = DEFAULT_INSTRUMENT_TYPE) -> float:
    """Fiyat seviyesine ve enstrüman tipine göre BIST resmî minimum fiyat adımını döndürür.

    Args:
        price: Fiyat seviyesi (TL).
        instrument_type: Enstrüman tipi ('stock', 'warrant', 'certificate', 'fund', 'etf').

    Returns:
        float: Uygulanması gereken minimum fiyat adımı (TL).
    """
    safe_p = _safe_float(price, 0.0)
    norm_type = instrument_type.lower().strip() if isinstance(instrument_type, str) else DEFAULT_INSTRUMENT_TYPE

    # Özel enstrüman tipleri
    if norm_type in SPECIAL_TICK_SIZES:
        return SPECIAL_TICK_SIZES[norm_type]

    # Geçersiz, sıfır veya sayısal olmayan fiyatlarda fail-closed gereği en küçük pay adımı döner
    if safe_p <= 0.0:
        return 0.01

    # BIST Standart Pay Piyasası Kademeleri
    if safe_p < 20.0:
        return 0.01
    elif safe_p < 50.0:
        return 0.02
    elif safe_p < 100.0:
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
    safe_p = _safe_float(price, 0.0)
    if safe_p <= 0.0:
        return 0.0

    tick = get_bist_tick_size(safe_p, instrument_type)
    norm_mode = mode.upper().strip() if isinstance(mode, str) else "NEAREST"
    norm_side = side.upper().strip() if isinstance(side, str) else "BUY"

    ratio = round(safe_p / tick, 6)

    # Mod doğrulaması ve adım hesabı
    if norm_mode in ("FLOOR", "DOWN"):
        steps = math.floor(ratio)
    elif norm_mode in ("CEIL", "UP"):
        steps = math.ceil(ratio)
    elif norm_mode in ("SIDE", "SIDE_AWARE"):
        # Alış emrinde bütçeyi aşmamak için aşağı (floor), satış emrinde ucuza vermemek için yukarı (ceil)
        steps = math.floor(ratio) if norm_side == "BUY" else math.ceil(ratio)
    else:
        # Varsayılan: En yakın fiyata yuvarlama
        steps = round(safe_p / tick)

    # 0 veya negatif fiyata yuvarlanmayı engelle (en az 1 tick olmalıdır)
    steps = max(1, steps)

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
    safe_p = _safe_float(price, 0.0)
    if safe_p <= 0.0:
        return False

    tick = get_bist_tick_size(safe_p, instrument_type)
    steps = round(safe_p / tick)
    expected_price = round(steps * tick, 4 if tick < 0.01 else 2)
    return abs(safe_p - expected_price) < tolerance


@otel_trace("bist_tick_size.add_bist_ticks")
def add_bist_ticks(
    price: float,
    ticks: int,
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
) -> float:
    """Belirtilen fiyata BIST kademelerini dinamik ve analitik O(1) olarak ekler veya çıkarır.

    Fiyat kademe sınırlarını (örneğin 19.99 TL -> 20.00 TL) geçerken değişen adım boyutunu
    O(1) süre karmaşıklığında ve IEEE 754 yuvarlama güvencesiyle hesaplar.

    Args:
        price: Başlangıç fiyatı.
        ticks: Eklenecek (pozitif) veya çıkarılacak (negatif) kademe sayısı.
        instrument_type: Enstrüman kategorisi.

    Returns:
        float: Kademeler geçildikten sonraki nihai fiyat.
    """
    safe_p = _safe_float(price, 0.0)
    if safe_p <= 0.0:
        return 0.0
    if ticks == 0:
        return round_to_bist_tick(safe_p, instrument_type=instrument_type)

    curr = round_to_bist_tick(safe_p, instrument_type=instrument_type)
    norm_type = instrument_type.lower().strip() if isinstance(instrument_type, str) else DEFAULT_INSTRUMENT_TYPE

    # Özel enstrümanlar için sabit kademe analitik hesabı
    if norm_type in ("warrant", "certificate", "fund"):
        res = curr + (ticks * 0.001)
        return round(max(0.001, res), 4)
    if norm_type == "etf":
        res = curr + (ticks * 0.01)
        return round(max(0.01, res), 2)

    # Standart Pay Piyasası Kademeleri (Analitik Kademe Geçişi)
    rem = abs(ticks)
    if ticks > 0:
        while rem > 0:
            if curr < 20.0:
                t_to_b = round((20.0 - curr) / 0.01)
                if rem >= t_to_b:
                    curr = 20.0
                    rem -= t_to_b
                else:
                    curr = round(curr + rem * 0.01, 2)
                    rem = 0
            elif curr < 50.0:
                t_to_b = round((50.0 - curr) / 0.02)
                if rem >= t_to_b:
                    curr = 50.0
                    rem -= t_to_b
                else:
                    curr = round(curr + rem * 0.02, 2)
                    rem = 0
            elif curr < 100.0:
                t_to_b = round((100.0 - curr) / 0.05)
                if rem >= t_to_b:
                    curr = 100.0
                    rem -= t_to_b
                else:
                    curr = round(curr + rem * 0.05, 2)
                    rem = 0
            else:
                curr = round(curr + rem * 0.10, 2)
                rem = 0
    else:
        while rem > 0:
            if curr > 100.0:
                t_to_b = round((curr - 100.0) / 0.10)
                if rem >= t_to_b:
                    curr = 100.0
                    rem -= t_to_b
                else:
                    curr = round(curr - rem * 0.10, 2)
                    rem = 0
            elif curr > 50.0:
                t_to_b = round((curr - 50.0) / 0.05)
                if rem >= t_to_b:
                    curr = 50.0
                    rem -= t_to_b
                else:
                    curr = round(curr - rem * 0.05, 2)
                    rem = 0
            elif curr > 20.0:
                t_to_b = round((curr - 20.0) / 0.02)
                if rem >= t_to_b:
                    curr = 20.0
                    rem -= t_to_b
                else:
                    curr = round(curr - rem * 0.02, 2)
                    rem = 0
            else:
                t_to_min = round((curr - 0.01) / 0.01)
                if rem >= t_to_min:
                    curr = 0.01
                    rem = 0
                else:
                    curr = round(curr - rem * 0.01, 2)
                    rem = 0

    return curr


@otel_trace("bist_tick_size.get_bist_tick_count_between")
def get_bist_tick_count_between(
    price_from: float,
    price_to: float,
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
) -> int:
    """İki fiyat seviyesi arasındaki geçerli BIST kademe (tick) farkını analitik O(1) olarak hesaplar.

    Args:
        price_from: Başlangıç fiyatı.
        price_to: Bitiş fiyatı.
        instrument_type: Enstrüman kategorisi.

    Returns:
        int: Kademe sayısı (price_to > price_from ise pozitif, küçükse negatif).
    """
    p_from_safe = _safe_float(price_from, 0.0)
    p_to_safe = _safe_float(price_to, 0.0)

    if p_from_safe <= 0.0 or p_to_safe <= 0.0:
        return 0

    p_start = round_to_bist_tick(p_from_safe, instrument_type=instrument_type)
    p_end = round_to_bist_tick(p_to_safe, instrument_type=instrument_type)

    if p_start == p_end:
        return 0

    direction = 1 if p_end > p_start else -1
    low, high = (p_start, p_end) if direction == 1 else (p_end, p_start)

    norm_type = instrument_type.lower().strip() if isinstance(instrument_type, str) else DEFAULT_INSTRUMENT_TYPE

    # Özel enstrümanlar
    if norm_type in ("warrant", "certificate", "fund"):
        return int(round((high - low) / 0.001)) * direction
    if norm_type == "etf":
        return int(round((high - low) / 0.01)) * direction

    # Standart Pay Piyasası Analitik Parçalı Kademe Hesabı O(1)
    ticks = 0
    # Kademe 1: [0.01, 20.00) @ 0.01
    if low < 20.0:
        seg_high = min(high, 20.0)
        ticks += round((seg_high - low) / 0.01)
    # Kademe 2: [20.00, 50.00) @ 0.02
    if high > 20.0 and low < 50.0:
        seg_low = max(low, 20.0)
        seg_high = min(high, 50.0)
        ticks += round((seg_high - seg_low) / 0.02)
    # Kademe 3: [50.00, 100.00) @ 0.05
    if high > 50.0 and low < 100.0:
        seg_low = max(low, 50.0)
        seg_high = min(high, 100.0)
        ticks += round((seg_high - seg_low) / 0.05)
    # Kademe 4: [100.00, inf) @ 0.10
    if high > 100.0:
        seg_low = max(low, 100.0)
        ticks += round((high - seg_low) / 0.10)

    return ticks * direction


@otel_trace("bist_tick_size.calculate_bist_price_limits")
def calculate_bist_price_limits(
    base_price: float,
    limit_ratio: float = DEFAULT_PRICE_LIMIT_RATIO,
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
) -> tuple[float, float]:
    """BIST resmî fiyat marjı (±%10 limit bandı) doğrultusunda geçerli taban ve tavan fiyatlarını hesaplar.

    Tavan fiyat bütçeyi/marjı aşmamak için 'FLOOR' (aşağı) adımına,
    Taban fiyat ise izin verilen marjın altına inmemek için 'CEIL' (yukarı) adımına yuvarlanır.

    Args:
        base_price: Baz fiyat / Önceki kapanış fiyatı (TL).
        limit_ratio: Fiyat marj oranı (Varsayılan %10 = 0.10).
        instrument_type: Enstrüman kategorisi.

    Returns:
        tuple[float, float]: (taban_fiyat, tavan_fiyat) ikilisi.
    """
    safe_base = _safe_float(base_price, 0.0)
    if safe_base <= 0.0:
        return (0.0, 0.0)

    raw_ratio = _safe_float(limit_ratio, DEFAULT_PRICE_LIMIT_RATIO)
    safe_ratio = max(0.01, min(1.0, raw_ratio))

    raw_lower = safe_base * (1.0 - safe_ratio)
    raw_upper = safe_base * (1.0 + safe_ratio)

    # Taban fiyat tabanın altına inemez -> CEIL
    floor_price = round_to_bist_tick(raw_lower, instrument_type=instrument_type, mode="CEIL")
    # Tavan fiyat tavanı aşamaz -> FLOOR
    ceiling_price = round_to_bist_tick(raw_upper, instrument_type=instrument_type, mode="FLOOR")

    # Taban fiyat en az minimum adım kadar olmalıdır
    min_tick = get_bist_tick_size(0.01, instrument_type=instrument_type)
    floor_price = max(min_tick, floor_price)
    ceiling_price = max(floor_price, ceiling_price)

    return (floor_price, ceiling_price)


def round_prices_to_bist_ticks(
    prices: Sequence[float],
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
    mode: str = "NEAREST",
) -> list[float]:
    """Toplu fiyat dizisini BIST fiyat adımlarına hızlıca yuvarlar (Batch Helper).

    Args:
        prices: Fiyat listesi veya sayı dizisi.
        instrument_type: Enstrüman kategorisi.
        mode: Yuvarlama modu.

    Returns:
        list[float]: Yuvarlanmış fiyatlar listesi.
    """
    return [round_to_bist_tick(p, instrument_type=instrument_type, mode=mode) for p in prices]


def round_polars_series_to_bist_ticks(
    series: pl.Series,
    instrument_type: str = DEFAULT_INSTRUMENT_TYPE,
    mode: str = "NEAREST",
) -> pl.Series:
    """Polars Series düzeyinde yüksek hızlı vektörize BIST fiyat adımı yuvarlaması yapar.

    Args:
        series: Fiyat sütunu (pl.Series).
        instrument_type: Enstrüman kategorisi.
        mode: Yuvarlama modu ('NEAREST', 'FLOOR', 'CEIL').

    Returns:
        pl.Series: BIST adımlarına uyumlu yuvarlanmış yeni seri.
    """
    norm_type = instrument_type.lower().strip() if isinstance(instrument_type, str) else DEFAULT_INSTRUMENT_TYPE
    norm_mode = mode.upper().strip() if isinstance(mode, str) else "NEAREST"

    # Özel enstrüman tipleri
    if norm_type in SPECIAL_TICK_SIZES:
        fixed_tick = SPECIAL_TICK_SIZES[norm_type]
        prec = 4 if fixed_tick < 0.01 else 2
        df_special = pl.DataFrame({"p": series})
        expr = pl.col("p") / fixed_tick
        if norm_mode in ("FLOOR", "DOWN"):
            steps_expr = expr.floor()
        elif norm_mode in ("CEIL", "UP"):
            steps_expr = expr.ceil()
        else:
            steps_expr = expr.round(0)

        df_special = df_special.with_columns(
            pl.when(pl.col("p").is_null() | pl.col("p").is_nan() | (pl.col("p") <= 0.0))
            .then(0.0)
            .otherwise((steps_expr * fixed_tick).round(prec))
            .alias("rounded")
        )
        return df_special["rounded"]

    # Standart Pay Piyasası Kademe İfadesi
    tick_expr = (
        pl.when(pl.col("p") < 20.0)
        .then(0.01)
        .when(pl.col("p") < 50.0)
        .then(0.02)
        .when(pl.col("p") < 100.0)
        .then(0.05)
        .otherwise(0.10)
    )

    df = pl.DataFrame({"p": series})
    ratio_expr = pl.col("p") / tick_expr

    if norm_mode in ("FLOOR", "DOWN"):
        steps = ratio_expr.floor()
    elif norm_mode in ("CEIL", "UP"):
        steps = ratio_expr.ceil()
    else:
        steps = ratio_expr.round(0)

    df = df.with_columns(
        pl.when(pl.col("p").is_null() | pl.col("p").is_nan() | (pl.col("p") <= 0.0))
        .then(0.0)
        .otherwise((steps * tick_expr).round(2))
        .alias("rounded")
    )
    return df["rounded"]


def get_bist_tick_schedule() -> pl.DataFrame:
    """Borsa İstanbul resmî fiyat adımı kademelerini Polars DataFrame olarak döndürür.

    Returns:
        pl.DataFrame: Kademe ve kural tablosu.
    """
    data = [
        {
            "instrument_type": "stock",
            "tier_name": "PAY_KADEME_1",
            "min_price": 0.01,
            "max_price": 19.99,
            "tick_size": 0.01,
            "description": "0.01 TL - 19.99 TL arası Pay Piyasası fiyat adımı",
        },
        {
            "instrument_type": "stock",
            "tier_name": "PAY_KADEME_2",
            "min_price": 20.00,
            "max_price": 49.98,
            "tick_size": 0.02,
            "description": "20.00 TL - 49.98 TL arası Pay Piyasası fiyat adımı",
        },
        {
            "instrument_type": "stock",
            "tier_name": "PAY_KADEME_3",
            "min_price": 50.00,
            "max_price": 99.95,
            "tick_size": 0.05,
            "description": "50.00 TL - 99.95 TL arası Pay Piyasası fiyat adımı",
        },
        {
            "instrument_type": "stock",
            "tier_name": "PAY_KADEME_4",
            "min_price": 100.00,
            "max_price": 999999.0,
            "tick_size": 0.10,
            "description": "100.00 TL ve üzeri Pay Piyasası fiyat adımı",
        },
        {
            "instrument_type": "warrant",
            "tier_name": "VARANT_KADEME",
            "min_price": 0.001,
            "max_price": 999999.0,
            "tick_size": 0.001,
            "description": "Varantlar için sabit fiyat adımı",
        },
        {
            "instrument_type": "certificate",
            "tier_name": "SERTIFIKA_KADEME",
            "min_price": 0.001,
            "max_price": 999999.0,
            "tick_size": 0.001,
            "description": "Sertifikalar için sabit fiyat adımı",
        },
        {
            "instrument_type": "fund",
            "tier_name": "FON_KADEME",
            "min_price": 0.001,
            "max_price": 999999.0,
            "tick_size": 0.001,
            "description": "Yatırım fonu katılma payları için sabit fiyat adımı",
        },
        {
            "instrument_type": "etf",
            "tier_name": "BYF_KADEME",
            "min_price": 0.01,
            "max_price": 999999.0,
            "tick_size": 0.01,
            "description": "Borsa yatırım fonları (BYF) için fiyat adımı",
        },
    ]
    return pl.DataFrame(data)


def export_tick_rules_to_duckdb(db_path: str = DEFAULT_TICK_DB_PATH) -> int:
    """BIST fiyat adımı kademe kurallarını kalıcı DuckDB veritabanına aktarır.

    Args:
        db_path: Hedef DuckDB dosya yolu.

    Returns:
        int: Kaydedilen kural satırı sayısı.
    """
    df = get_bist_tick_schedule()
    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(path_obj)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bist_tick_rules (
                instrument_type VARCHAR,
                tier_name VARCHAR,
                min_price DOUBLE,
                max_price DOUBLE,
                tick_size DOUBLE,
                description VARCHAR,
                PRIMARY KEY (instrument_type, tier_name)
            )
            """
        )
        conn.register("tmp_tick_rules", df)
        conn.execute("DELETE FROM bist_tick_rules")
        conn.execute("INSERT INTO bist_tick_rules SELECT * FROM tmp_tick_rules")
        total = len(df)

    logger.info("bist_tick_rules_duckdb_guncellendi", db_path=str(path_obj), satir=total)
    return total


class BISTTickSizeEngine:
    """BIST fiyat adımı ve limit hesaplamalarını yöneten nesne tabanlı motor."""

    def __init__(self, default_instrument: str = DEFAULT_INSTRUMENT_TYPE) -> None:
        """Motor örneğini başlatır.

        Args:
            default_instrument: Varsayılan enstrüman türü.
        """
        self.default_instrument: str = default_instrument

    def get_tick_size(self, price: float, instrument_type: str | None = None) -> float:
        """Fiyat adımı boyutunu döner."""
        return get_bist_tick_size(price, instrument_type or self.default_instrument)

    def round_tick(
        self,
        price: float,
        side: str = "BUY",
        instrument_type: str | None = None,
        mode: str = "NEAREST",
    ) -> float:
        """Fiyatı BIST adımına yuvarlar."""
        return round_to_bist_tick(
            price=price,
            side=side,
            instrument_type=instrument_type or self.default_instrument,
            mode=mode,
        )

    def is_valid_tick(
        self,
        price: float,
        tolerance: float = DEFAULT_TICK_TOLERANCE,
        instrument_type: str | None = None,
    ) -> bool:
        """Fiyatın geçerliliğini denetler."""
        return is_valid_bist_tick(
            price=price,
            tolerance=tolerance,
            instrument_type=instrument_type or self.default_instrument,
        )

    def add_ticks(
        self,
        price: float,
        ticks: int,
        instrument_type: str | None = None,
    ) -> float:
        """Kademe ekler veya çıkarır."""
        return add_bist_ticks(
            price=price,
            ticks=ticks,
            instrument_type=instrument_type or self.default_instrument,
        )

    def get_tick_count_between(
        self,
        price_from: float,
        price_to: float,
        instrument_type: str | None = None,
    ) -> int:
        """İki fiyat arasındaki kademe farkını döner."""
        return get_bist_tick_count_between(
            price_from=price_from,
            price_to=price_to,
            instrument_type=instrument_type or self.default_instrument,
        )

    def calculate_price_limits(
        self,
        base_price: float,
        limit_ratio: float = DEFAULT_PRICE_LIMIT_RATIO,
        instrument_type: str | None = None,
    ) -> tuple[float, float]:
        """Fiyat taban ve tavan limitlerini hesaplar."""
        return calculate_bist_price_limits(
            base_price=base_price,
            limit_ratio=limit_ratio,
            instrument_type=instrument_type or self.default_instrument,
        )

    def round_series(
        self,
        series: pl.Series,
        instrument_type: str | None = None,
        mode: str = "NEAREST",
    ) -> pl.Series:
        """Polars serisini vektörize yuvarlar."""
        return round_polars_series_to_bist_ticks(
            series=series,
            instrument_type=instrument_type or self.default_instrument,
            mode=mode,
        )

    def __repr__(self) -> str:
        """Motorun metin temsilini döner."""
        return f"<BISTTickSizeEngine(varsayilan_enstruman='{self.default_instrument}')>"


# Global singleton motor örneği
bist_tick_engine: Final[BISTTickSizeEngine] = BISTTickSizeEngine()


__all__ = [
    "DEFAULT_INSTRUMENT_TYPE",
    "DEFAULT_PRICE_LIMIT_RATIO",
    "DEFAULT_TICK_DB_PATH",
    "DEFAULT_TICK_TOLERANCE",
    "SPECIAL_TICK_SIZES",
    "VALID_ROUNDING_MODES",
    "BISTTickSizeEngine",
    "BISTTickTier",
    "add_bist_ticks",
    "bist_tick_engine",
    "calculate_bist_price_limits",
    "export_tick_rules_to_duckdb",
    "get_bist_tick_count_between",
    "get_bist_tick_schedule",
    "get_bist_tick_size",
    "is_valid_bist_tick",
    "round_polars_series_to_bist_ticks",
    "round_prices_to_bist_ticks",
    "round_to_bist_tick",
]
