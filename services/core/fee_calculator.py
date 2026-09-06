"""ALPHA BIST — Borsa ve Aracı Kurum İşlem Maliyeti Hesaplayıcı (Fee Calculator).

Bu modül, Borsa İstanbul (BIST) Pay Piyasası, VİOP ve Varant işlemleri için
SPK ve Borsa İstanbul mevzuatına tam uyumlu işlem maliyeti, aracı kurum komisyonu,
borsa payı, MKK saklama payı, BSMV ve başa baş (break-even) fiyat analizlerini gerçekleştirir.

Mevzuat ve Oran Standartları:
- Broker Komisyonu: Değişken (Varsayılan on binde 3 = %0.03, kademeli hacim baremleri desteklenir).
- Minimum Komisyon: İşlem başına taban tutar (Varsayılan 1.00 TL).
- BIST Pay Piyasası Borsa Payı: %0.0056 (yüz binde 5.6 = 0.000056).
- VİOP Borsa Payı: %0.0040 (yüz binde 4.0 = 0.00004).
- MKK Tescil/Saklama Payı: %0.00109 (yüz binde 1.09 = 0.0000109).
- BSMV: 6802 sayılı Gider Vergileri Kanunu uyarınca sadece aracı kurum komisyonu
  üzerinden %5 (0.05). BIST ve MKK payları matraha dahil edilmez.
"""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.bist_tick_size import round_to_bist_tick
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# ==============================================================================
# Standart Mevzuat ve Yapılandırma Sabitleri (GEMINI.md Kural 4)
# ==============================================================================

DEFAULT_BROKER_RATE: Final[float] = 0.0003  # On binde 3 (%0.03)
DEFAULT_BIST_FEE_RATE: Final[float] = 0.000056  # %0.0056 (BIST Pay Piyasası Borsa Payı)
DEFAULT_VIOP_FEE_RATE: Final[float] = 0.00004  # %0.0040 (BIST VİOP Borsa Payı)
DEFAULT_MKK_FEE_RATE: Final[float] = 0.0000109  # %0.00109 (MKK Tescil ve Saklama Payı)
DEFAULT_BSMV_RATE: Final[float] = 0.05  # %5.0 (Komisyon üzerinden BSMV)
DEFAULT_MIN_COMMISSION: Final[float] = 1.0  # Minimum 1.00 TL işlem komisyonu

DEFAULT_FEE_DB_PATH: Final[str] = "data/fee_audit.duckdb"

VALID_SIDES: Final[frozenset[str]] = frozenset({"BUY", "SELL", "UNKNOWN"})
VALID_INSTRUMENT_TYPES: Final[frozenset[str]] = frozenset({"equity", "viop", "warrant"})


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Float değerleri güvenle dönüştürür; None/NaN/Inf veya str hatalarında default döner."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return default


# ==============================================================================
# Veri Modelleri
# ==============================================================================


@dataclass(slots=True)
class FeeBreakdown:
    """İşlem maliyeti detay dökümü.

    Attributes:
        amount: İşlem brüt hacmi (fiyat × adet, TL).
        broker_fee: Aracı kurum komisyonu (TL).
        bist_fee: Borsa İstanbul borsa payı (TL).
        mkk_fee: Merkezi Kayıt Kuruluşu tescil/saklama payı (TL).
        bsmv: Banka ve Sigorta Muameleleri Vergisi (TL).
        total: Toplam işlem maliyeti (TL).
        effective_rate: Efektif maliyet yüzdesi (%).
        side: İşlem yönü ("BUY", "SELL", "UNKNOWN").
        instrument_type: Enstrüman sınıfı ("equity", "viop", "warrant").
        net_amount: Net nakit akışı (Alışta amount + total, Satışta amount - total, TL).
    """

    amount: float
    broker_fee: float
    bist_fee: float
    mkk_fee: float
    bsmv: float
    total: float
    effective_rate: float
    side: str = "UNKNOWN"
    instrument_type: str = "equity"
    net_amount: float = 0.0

    def __post_init__(self) -> None:
        """Net tutarı ve yönü normalize et."""
        if self.side not in VALID_SIDES:
            object.__setattr__(self, "side", "UNKNOWN")
        if self.instrument_type not in VALID_INSTRUMENT_TYPES:
            object.__setattr__(self, "instrument_type", "equity")
        if self.net_amount == 0.0 and self.amount > 0.0:
            if self.side == "BUY":
                object.__setattr__(self, "net_amount", round(self.amount + self.total, 4))
            elif self.side == "SELL":
                object.__setattr__(self, "net_amount", max(0.0, round(self.amount - self.total, 4)))
            else:
                object.__setattr__(self, "net_amount", round(self.amount, 4))

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "amount": round(self.amount, 2),
            "broker_fee": round(self.broker_fee, 4),
            "bist_fee": round(self.bist_fee, 4),
            "mkk_fee": round(self.mkk_fee, 4),
            "bsmv": round(self.bsmv, 4),
            "total": round(self.total, 4),
            "effective_rate": round(self.effective_rate, 4),
            "side": self.side,
            "instrument_type": self.instrument_type,
            "net_amount": round(self.net_amount, 2),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi (GEMINI.md Kural 5)."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"FeeBreakdown(tutar={self.amount:.2f}TL, toplam_maliyet={self.total:.2f}TL, "
            f"efektif_oran=%{self.effective_rate:.4f}, yon={self.side}, "
            f"net_tutar={self.net_amount:.2f}TL, enstruman={self.instrument_type})"
        )


@dataclass(slots=True)
class BreakEvenAnalysis:
    """Pozisyon başa baş (Break-Even) fiyat ve getiri analizi.

    Attributes:
        entry_price: Pozisyon alış fiyatı (TL).
        quantity: İşlem adedi (lot).
        entry_fee: Alış anında oluşan maliyet dökümü.
        break_even_price: Masraflar sonrası sıfır kâr/zarar sağlayan teorik satış fiyatı (TL).
        break_even_return_pct: Masrafları kurtarmak için gereken asgari brüt getiri oranı (%).
        tick_aligned_price: BIST fiyat kademesine yukarı yuvarlanmış (CEIL) güvenli satış fiyatı (TL).
        estimated_exit_fee: Başa baş fiyattan satış anında ödenecek tahmini toplam masraf (TL).
    """

    entry_price: float
    quantity: float
    entry_fee: FeeBreakdown
    break_even_price: float
    break_even_return_pct: float
    tick_aligned_price: float
    estimated_exit_fee: float

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "entry_price": round(self.entry_price, 4),
            "quantity": self.quantity,
            "entry_fee": self.entry_fee.to_dict(),
            "break_even_price": round(self.break_even_price, 4),
            "break_even_return_pct": round(self.break_even_return_pct, 4),
            "tick_aligned_price": round(self.tick_aligned_price, 4),
            "estimated_exit_fee": round(self.estimated_exit_fee, 4),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi (GEMINI.md Kural 5)."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"BreakEvenAnalysis(giris_fiyati={self.entry_price:.2f}TL, adet={self.quantity}, "
            f"basa_bas_fiyat={self.break_even_price:.4f}TL, kademe_uyumlu={self.tick_aligned_price:.2f}TL, "
            f"gereken_getiri=%{self.break_even_return_pct:.3f})"
        )


# ==============================================================================
# Hesaplayıcı Çekirdek Sınıfı
# ==============================================================================


class FeeCalculator:
    """BIST işlem maliyetleri, vergi ve komisyon hesaplayıcı.

    Borsa İstanbul Pay Piyasası, VİOP ve Varant işlemleri için komisyon, borsa payı,
    MKK tescil/saklama payı ve BSMV hesaplamalarını gerçekleştirir. Thread-safe
    mimariye, Polars vektörizasyonuna ve DuckDB denetim kaydına sahiptir.
    """

    def __init__(
        self,
        broker_rate: float = DEFAULT_BROKER_RATE,
        bist_fee_rate: float = DEFAULT_BIST_FEE_RATE,
        viop_fee_rate: float = DEFAULT_VIOP_FEE_RATE,
        mkk_fee_rate: float = DEFAULT_MKK_FEE_RATE,
        bsmv_rate: float = DEFAULT_BSMV_RATE,
        min_commission: float = DEFAULT_MIN_COMMISSION,
        tiered_rates: list[tuple[float, float]] | None = None,
    ) -> None:
        """FeeCalculator başlatıcı.

        Args:
            broker_rate: Varsayılan aracı kurum komisyon oranı (örn: 0.0003 = %0.03).
            bist_fee_rate: BIST Pay Piyasası borsa payı oranı (varsayılan: 0.000056).
            viop_fee_rate: VİOP borsa payı oranı (varsayılan: 0.00004).
            mkk_fee_rate: MKK tescil ve saklama payı oranı (varsayılan: 0.0000109).
            bsmv_rate: BSMV oranı (varsayılan: 0.05).
            min_commission: Asgari işlem komisyonu (varsayılan: 1.00 TL).
            tiered_rates: Hacim baremlerine göre komisyon oranları [(ust_limit, oran), ...].
        """
        self._lock = threading.RLock()
        self.broker_rate = max(0.0, float(broker_rate))
        self.bist_fee_rate = max(0.0, float(bist_fee_rate))
        self.viop_fee_rate = max(0.0, float(viop_fee_rate))
        self.mkk_fee_rate = max(0.0, float(mkk_fee_rate))
        self.bsmv_rate = max(0.0, float(bsmv_rate))
        self.min_commission = max(0.0, float(min_commission))

        # Sıralı kademeli oranlar: [(limit_1, rate_1), (limit_2, rate_2), ...]
        self._tiered_rates: list[tuple[float, float]] = []
        if tiered_rates:
            self.set_tiered_rates(tiered_rates)

    def set_broker_rate(self, new_rate: float) -> None:
        """Aracı kurum komisyon oranını dinamik ve thread-safe güncelle.

        Args:
            new_rate: Yeni komisyon oranı (0.0 <= new_rate <= 1.0).

        Raises:
            ValueError: Oran sınırların dışındaysa veya sayısal değilse fırlatılır.
        """
        if math.isnan(new_rate) or math.isinf(new_rate) or new_rate < 0.0 or new_rate > 1.0:
            raise ValueError(f"Geçersiz komisyon oranı: {new_rate}. Oran [0.0, 1.0] aralığında olmalıdır.")
        with self._lock:
            self.broker_rate = float(new_rate)
            logger.info("komisyon_orani_guncellendi", yeni_oran=new_rate)

    def set_tiered_rates(self, tiers: list[tuple[float, float]]) -> None:
        """Kademeli işlem hacmi komisyon baremlerini tanımla.

        Args:
            tiers: [(hacim_tavanı, oran), ...] listesi.
        """
        cleaned_tiers: list[tuple[float, float]] = []
        for upper_bound, rate in tiers:
            if math.isnan(upper_bound) or math.isnan(rate) or upper_bound <= 0.0 or rate < 0.0:
                continue
            cleaned_tiers.append((float(upper_bound), float(rate)))
        cleaned_tiers.sort(key=lambda x: x[0])

        with self._lock:
            self._tiered_rates = cleaned_tiers
            logger.info("kademeli_komisyon_baremleri_guncellendi", barem_sayisi=len(self._tiered_rates))

    def _get_effective_broker_rate(self, amount: float) -> float:
        """İşlem tutarına göre geçerli broker komisyon oranını belirle."""
        with self._lock:
            if not self._tiered_rates:
                return self.broker_rate
            for upper_limit, rate in self._tiered_rates:
                if amount <= upper_limit:
                    return rate
            # Tüm baremleri aşarsa son baremdeki en avantajlı oran kullanılır
            return self._tiered_rates[-1][1]

    @otel_trace("fee_calculator.calculate")
    def calculate(
        self,
        amount: float,
        side: str = "UNKNOWN",
        instrument_type: str = "equity",
    ) -> FeeBreakdown:
        """İşlem maliyet dökümünü hesapla.

        Args:
            amount: İşlem brüt tutarı (fiyat × adet, TL).
            side: İşlem yönü ("BUY", "SELL", "UNKNOWN").
            instrument_type: Enstrüman sınıfı ("equity", "viop", "warrant").

        Returns:
            FeeBreakdown: Tüm maliyet bileşenlerini içeren detaylı döküm.
        """
        amt = _safe_float(amount, 0.0)
        # Sınır ve sayısal doğrulama (Fail-Closed)
        if amt <= 0.0:
            return FeeBreakdown(
                amount=0.0,
                broker_fee=0.0,
                bist_fee=0.0,
                mkk_fee=0.0,
                bsmv=0.0,
                total=0.0,
                effective_rate=0.0,
                side=side if side in VALID_SIDES else "UNKNOWN",
                instrument_type=instrument_type if instrument_type in VALID_INSTRUMENT_TYPES else "equity",
                net_amount=0.0,
            )

        inst_type = instrument_type.lower().strip() if instrument_type else "equity"
        if inst_type not in VALID_INSTRUMENT_TYPES:
            inst_type = "equity"

        side_norm = side.upper().strip() if side else "UNKNOWN"
        if side_norm not in VALID_SIDES:
            side_norm = "UNKNOWN"

        with self._lock:
            broker_rate = self._get_effective_broker_rate(amt)
            min_comm = self.min_commission
            bsmv_rate = self.bsmv_rate

            if inst_type == "viop":
                bist_rate = self.viop_fee_rate
                mkk_rate = 0.0  # VİOP takas ve tescil Takasbank nezdindedir, standart hisse MKK payı alınmaz
            else:
                bist_rate = self.bist_fee_rate
                mkk_rate = self.mkk_fee_rate

        # 1. Broker Komisyonu (Minimum tutar guard'ı ile)
        raw_broker_fee = amt * broker_rate
        broker_fee = round(max(raw_broker_fee, min_comm), 4)

        # 2. Borsa İstanbul Borsa Payı
        bist_fee = round(amt * bist_rate, 4)

        # 3. MKK Tescil ve Saklama Payı
        mkk_fee = round(amt * mkk_rate, 4)

        # 4. BSMV (6802 sayılı Kanun gereği yalnızca aracı kurum komisyonu matrahtır)
        bsmv = round(broker_fee * bsmv_rate, 4)

        # 5. Toplam Maliyet ve Efektif Oran
        total = round(broker_fee + bist_fee + mkk_fee + bsmv, 4)
        effective_rate = round((total / amt) * 100.0, 6) if amt > 0.0 else 0.0

        # 6. Net Nakit Akışı
        if side_norm == "BUY":
            net_amount = round(amt + total, 4)
        elif side_norm == "SELL":
            net_amount = max(0.0, round(amt - total, 4))
        else:
            net_amount = round(amt, 4)

        return FeeBreakdown(
            amount=amt,
            broker_fee=broker_fee,
            bist_fee=bist_fee,
            mkk_fee=mkk_fee,
            bsmv=bsmv,
            total=total,
            effective_rate=effective_rate,
            side=side_norm,
            instrument_type=inst_type,
            net_amount=net_amount,
        )

    def calculate_net_amount(
        self,
        amount: float,
        side: str,
        instrument_type: str = "equity",
    ) -> float:
        """Yöne göre net nakit akışını hesapla.

        Args:
            amount: İşlem brüt tutarı (TL).
            side: İşlem yönü ("BUY" veya "SELL").
            instrument_type: Enstrüman sınıfı.

        Returns:
            float: Alışta ödenen toplam tutar, satışta tahsil edilen net tutar.
        """
        breakdown = self.calculate(amount=amount, side=side, instrument_type=instrument_type)
        return breakdown.net_amount

    @otel_trace("fee_calculator.calculate_break_even")
    def calculate_break_even(
        self,
        entry_price: float,
        quantity: float,
        instrument_type: str = "equity",
        round_to_tick: bool = True,
    ) -> BreakEvenAnalysis:
        """Alış pozisyonu için başa baş (Break-Even) satış fiyatını hesapla.

        Komisyon, BIST payı, MKK payı ve BSMV düşüldükten sonra net kâr/zararın
        sıfır olacağı teorik ve BIST işlem kademesine uyumlu fiyatı türetir.

        Args:
            entry_price: Alış fiyatı (TL).
            quantity: İşlem adedi (lot).
            instrument_type: Enstrüman tipi ("equity", "viop", "warrant").
            round_to_tick: BIST fiyat adımına yukarı (CEIL) yuvarlansın mı.

        Returns:
            BreakEvenAnalysis: Başa baş fiyat, gereken getiri oranı ve detaylar.

        Raises:
            ValueError: Fiyat veya adet sıfır veya negatifse fırlatılır.
        """
        e_price = _safe_float(entry_price, 0.0)
        qty = _safe_float(quantity, 0.0)

        if e_price <= 0.0 or qty <= 0.0:
            raise ValueError(
                f"Geçersiz giriş parametreleri: entry_price={entry_price}, quantity={quantity}. "
                "Pozitif ve sonlu değerler girilmelidir."
            )

        # 1. Alış maliyet dökümü
        buy_amount = e_price * qty
        entry_fee = self.calculate(amount=buy_amount, side="BUY", instrument_type=instrument_type)
        total_invested = entry_fee.net_amount  # buy_amount + entry_fee.total

        with self._lock:
            broker_rate = self._get_effective_broker_rate(buy_amount)
            min_comm = self.min_commission
            bsmv_rate = self.bsmv_rate
            if instrument_type == "viop":
                bist_rate = self.viop_fee_rate
                mkk_rate = 0.0
            else:
                bist_rate = self.bist_fee_rate
                mkk_rate = self.mkk_fee_rate

        # 2. Satışta başa baş brüt tutarı (A_sell) çözümü:
        # A_sell - Fee_sell(A_sell) = total_invested
        # Durum A: Oransal komisyon bölgesi (A_sell * broker_rate >= min_comm)
        # Fee_rate_linear = broker_rate * (1 + bsmv_rate) + bist_rate + mkk_rate
        linear_rate = (broker_rate * (1.0 + bsmv_rate)) + bist_rate + mkk_rate
        denominator_a = 1.0 - linear_rate
        if denominator_a <= 0.0:
            raise ValueError(f"Aşırı yüksek komisyon/vergi oranı nedeniyle başa baş hesaplanamaz: {linear_rate:.4f}")

        a_sell_candidate = total_invested / denominator_a

        if a_sell_candidate * broker_rate >= min_comm:
            break_even_amount = a_sell_candidate
        else:
            # Durum B: Minimum komisyon bölgesi (broker_fee = min_comm)
            # A_sell - [min_comm * (1 + bsmv_rate) + A_sell * (bist_rate + mkk_rate)] = total_invested
            fixed_fee_part = min_comm * (1.0 + bsmv_rate)
            denominator_b = 1.0 - bist_rate - mkk_rate
            if denominator_b <= 0.0:
                raise ValueError(
                    f"Aşırı yüksek borsa/MKK oranı nedeniyle başa baş hesaplanamaz: {bist_rate + mkk_rate:.4f}"
                )
            break_even_amount = (total_invested + fixed_fee_part) / denominator_b

        raw_break_even_price = break_even_amount / qty
        break_even_return_pct = ((raw_break_even_price - e_price) / e_price) * 100.0

        # 3. BIST Fiyat Kademe Uyumu
        if round_to_tick and instrument_type == "equity":
            # Başa baş satış fiyatında zarara düşmemek için daima tavan (CEIL) yönlü yuvarlanır
            tick_aligned_price = round_to_bist_tick(raw_break_even_price, mode="CEIL")
        else:
            tick_aligned_price = round(raw_break_even_price, 4)

        # 4. Başa baş fiyattaki tahmini çıkış maliyeti
        exit_fee = self.calculate(
            amount=tick_aligned_price * qty,
            side="SELL",
            instrument_type=instrument_type,
        )

        return BreakEvenAnalysis(
            entry_price=e_price,
            quantity=qty,
            entry_fee=entry_fee,
            break_even_price=raw_break_even_price,
            break_even_return_pct=break_even_return_pct,
            tick_aligned_price=tick_aligned_price,
            estimated_exit_fee=exit_fee.total,
        )

    def calculate_batch(
        self,
        amounts: list[float],
        side: str = "UNKNOWN",
        instrument_type: str = "equity",
    ) -> list[FeeBreakdown]:
        """Çoklu işlem tutarı listesi için maliyet dökümlerini hesapla.

        Args:
            amounts: İşlem tutarları listesi.
            side: İşlem yönü.
            instrument_type: Enstrüman sınıfı.

        Returns:
            list[FeeBreakdown]: Hesaplanan maliyet dökümleri.
        """
        return [self.calculate(amt, side=side, instrument_type=instrument_type) for amt in amounts]

    def calculate_polars(
        self,
        df: pl.DataFrame,
        amount_col: str = "amount",
        side_col: str | None = None,
        instrument_col: str | None = None,
    ) -> pl.DataFrame:
        """Polars DataFrame üzerinde vektörize komisyon ve net tutar hesapla (GEMINI.md Kural 2).

        Args:
            df: İşlem verilerini içeren Polars DataFrame.
            amount_col: Tutar kolon adı.
            side_col: Opsiyonel işlem yönü kolonu ("BUY" / "SELL").
            instrument_col: Opsiyonel enstrüman kolonu.

        Returns:
            pl.DataFrame: Komisyon, BIST payı, MKK payı, BSMV, toplam ve net_amount eklenmiş DataFrame.
        """
        if amount_col not in df.columns:
            raise ValueError(f"'{amount_col}' kolonu DataFrame içinde bulunamadı.")

        with self._lock:
            broker_rate = self.broker_rate
            min_comm = self.min_commission
            bist_rate = self.bist_fee_rate
            mkk_rate = self.mkk_fee_rate
            bsmv_rate = self.bsmv_rate

        # Vektörize Polars ifadeleri (Null ve NaN güvenli)
        amt = pl.col(amount_col)

        # Broker komisyonu (null/NaN/negatif guard'ı ile)
        raw_broker = amt * broker_rate
        broker_fee_expr = (
            pl.when(amt.is_null() | amt.is_nan() | (amt <= 0.0))
            .then(0.0)
            .when(raw_broker < min_comm)
            .then(min_comm)
            .otherwise(raw_broker)
            .alias("broker_fee")
        )

        bist_fee_expr = (
            pl.when(amt.is_null() | amt.is_nan() | (amt <= 0.0))
            .then(0.0)
            .otherwise(amt * bist_rate)
            .alias("bist_fee")
        )
        mkk_fee_expr = (
            pl.when(amt.is_null() | amt.is_nan() | (amt <= 0.0))
            .then(0.0)
            .otherwise(amt * mkk_rate)
            .alias("mkk_fee")
        )
        bsmv_expr = (broker_fee_expr * bsmv_rate).alias("bsmv")

        total_fee_expr = (broker_fee_expr + bist_fee_expr + mkk_fee_expr + bsmv_expr).alias("total_fee")
        effective_rate_expr = (
            pl.when(amt.is_null() | amt.is_nan() | (amt <= 0.0))
            .then(0.0)
            .otherwise((total_fee_expr / amt) * 100.0)
            .alias("effective_rate")
        )

        # Net tutar hesabı
        if side_col and side_col in df.columns:
            side_expr = pl.col(side_col).str.to_uppercase()
            net_amount_expr = (
                pl.when(amt.is_null() | amt.is_nan() | (amt <= 0.0))
                .then(0.0)
                .when(side_expr == "BUY")
                .then(amt + total_fee_expr)
                .when(side_expr == "SELL")
                .then(pl.max_horizontal(0.0, amt - total_fee_expr))
                .otherwise(amt)
                .alias("net_amount")
            )
        else:
            net_amount_expr = amt.alias("net_amount")

        return df.with_columns(
            [
                broker_fee_expr,
                bist_fee_expr,
                mkk_fee_expr,
                bsmv_expr,
                total_fee_expr,
                effective_rate_expr,
                net_amount_expr,
            ]
        )

    def export_breakdowns_to_polars(self, breakdowns: list[FeeBreakdown]) -> pl.DataFrame:
        """Hesaplanan maliyet dökümlerini sıfır kopyalı Polars DataFrame'e dönüştür (GEMINI.md Kural 2).

        Args:
            breakdowns: FeeBreakdown listesi.

        Returns:
            pl.DataFrame: Analitik ve raporlama için optimize edilmiş DataFrame.
        """
        empty_schema = {
            "amount": pl.Float64,
            "broker_fee": pl.Float64,
            "bist_fee": pl.Float64,
            "mkk_fee": pl.Float64,
            "bsmv": pl.Float64,
            "total": pl.Float64,
            "effective_rate": pl.Float64,
            "side": pl.Utf8,
            "instrument_type": pl.Utf8,
            "net_amount": pl.Float64,
        }
        if not breakdowns:
            return pl.DataFrame(schema=empty_schema)

        data = [b.to_dict() for b in breakdowns]
        return pl.DataFrame(data, schema=empty_schema)

    def export_to_duckdb(
        self,
        breakdowns: list[FeeBreakdown],
        db_path: str = DEFAULT_FEE_DB_PATH,
    ) -> int:
        """Maliyet dökümlerini denetim izi için DuckDB tablosuna kaydet (GEMINI.md Kural 5).

        Args:
            breakdowns: Kaydedilecek döküm listesi.
            db_path: DuckDB veritabanı dosya yolu.

        Returns:
            int: Başarıyla kaydedilen satır sayısı.
        """
        if not breakdowns:
            return 0

        target_file = Path(db_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        rows = []
        for b in breakdowns:
            rows.append(
                (
                    uuid.uuid4().hex,
                    b.amount,
                    b.broker_fee,
                    b.bist_fee,
                    b.mkk_fee,
                    b.bsmv,
                    b.total,
                    b.effective_rate,
                    b.side,
                    b.instrument_type,
                    b.net_amount,
                    orjson.dumps(b.to_dict(), default=str).decode("utf-8"),
                )
            )

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS fee_audit_log (
                        id VARCHAR PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        amount DOUBLE,
                        broker_fee DOUBLE,
                        bist_fee DOUBLE,
                        mkk_fee DOUBLE,
                        bsmv DOUBLE,
                        total DOUBLE,
                        effective_rate DOUBLE,
                        side VARCHAR,
                        instrument_type VARCHAR,
                        net_amount DOUBLE,
                        metadata_json VARCHAR
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO fee_audit_log (
                        id, amount, broker_fee, bist_fee, mkk_fee, bsmv, total,
                        effective_rate, side, instrument_type, net_amount, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

        logger.info("ucret_denetim_kayitlari_duckdb_aktarildi", kaydedilen_adet=len(rows), db_path=db_path)
        return len(rows)

    def query_fee_audit_duckdb(
        self,
        db_path: str = DEFAULT_FEE_DB_PATH,
        side: str | None = None,
        instrument_type: str | None = None,
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB'de saklanan işlem maliyeti denetim izini filtrelenmiş Polars DataFrame olarak döner.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            side: İsteğe bağlı işlem yönü filtresi ("BUY", "SELL").
            instrument_type: İsteğe bağlı enstrüman filtresi ("equity", "viop").
            limit: Maksimum satır sayısı.

        Returns:
            pl.DataFrame: Filtrelenmiş maliyet denetim tablosu.
        """
        empty_schema = {
            "id": pl.Utf8,
            "created_at": pl.Datetime("us", "UTC"),
            "amount": pl.Float64,
            "broker_fee": pl.Float64,
            "bist_fee": pl.Float64,
            "mkk_fee": pl.Float64,
            "bsmv": pl.Float64,
            "total": pl.Float64,
            "effective_rate": pl.Float64,
            "side": pl.Utf8,
            "instrument_type": pl.Utf8,
            "net_amount": pl.Float64,
            "metadata_json": pl.Utf8,
        }
        target_file = Path(db_path)
        if not target_file.exists():
            return pl.DataFrame(schema=empty_schema)

        with self._lock:
            try:
                with duckdb.connect(str(target_file), read_only=True) as conn:
                    query = """
                        SELECT id, created_at, amount, broker_fee, bist_fee, mkk_fee,
                               bsmv, total, effective_rate, side, instrument_type,
                               net_amount, metadata_json
                        FROM fee_audit_log
                    """
                    conditions: list[str] = []
                    params: list[Any] = []
                    if side:
                        conditions.append("side = ?")
                        params.append(str(side).upper().strip())
                    if instrument_type:
                        conditions.append("instrument_type = ?")
                        params.append(str(instrument_type).lower().strip())

                    if conditions:
                        query += " WHERE " + " AND ".join(conditions)

                    query += " ORDER BY created_at DESC LIMIT ?"
                    params.append(max(1, limit))

                    return conn.execute(query, params).pl()
            except Exception as exc:
                logger.error("fee_audit_sorgulama_hatasi", error=str(exc))
                return pl.DataFrame(schema=empty_schema)

    def __enter__(self) -> FeeCalculator:
        """Context manager giriş protokolü."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager çıkış protokolü."""
        pass

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"FeeCalculator(broker_orani=%{self.broker_rate * 100:.3f}, "
            f"bist_orani=%{self.bist_fee_rate * 100:.4f}, "
            f"mkk_orani=%{self.mkk_fee_rate * 100:.5f}, "
            f"bsmv_orani=%{self.bsmv_rate * 100:.1f}, "
            f"min_komisyon={self.min_commission:.2f}TL, "
            f"kademeli_barem_sayisi={len(self._tiered_rates)})"
        )


# ==============================================================================
# Global Singleton ve Kolaylık Fonksiyonları (GEMINI.md Kural 6)
# ==============================================================================

fee_calculator: FeeCalculator = FeeCalculator()


def get_fee_calculator() -> FeeCalculator:
    """Aktif FeeCalculator singleton nesnesini döndürür."""
    return fee_calculator


def calculate_fee(
    amount: float,
    side: str = "UNKNOWN",
    instrument_type: str = "equity",
) -> FeeBreakdown:
    """İşlem maliyet dökümünü tek satırda hesaplar.

    Args:
        amount: İşlem brüt tutarı (TL).
        side: İşlem yönü ("BUY", "SELL", "UNKNOWN").
        instrument_type: Enstrüman sınıfı ("equity", "viop", "warrant").

    Returns:
        FeeBreakdown: Maliyet dökümü.
    """
    return fee_calculator.calculate(amount=amount, side=side, instrument_type=instrument_type)


def calculate_break_even_price(
    entry_price: float,
    quantity: float,
    instrument_type: str = "equity",
    round_to_tick: bool = True,
) -> BreakEvenAnalysis:
    """Alış pozisyonu için başa baş satış fiyatını hesaplar.

    Args:
        entry_price: Alış fiyatı (TL).
        quantity: İşlem adedi (lot).
        instrument_type: Enstrüman tipi.
        round_to_tick: BIST fiyat kademesine yuvarlama yapılsın mı.

    Returns:
        BreakEvenAnalysis: Başa baş analiz sonuçları.
    """
    return fee_calculator.calculate_break_even(
        entry_price=entry_price,
        quantity=quantity,
        instrument_type=instrument_type,
        round_to_tick=round_to_tick,
    )


def calculate_net_cash_flow(
    amount: float,
    side: str,
    instrument_type: str = "equity",
) -> float:
    """Yöne göre net nakit akışını döner.

    Args:
        amount: İşlem brüt tutarı (TL).
        side: İşlem yönü ("BUY", "SELL").
        instrument_type: Enstrüman sınıfı.

    Returns:
        float: Net tutar (TL).
    """
    return fee_calculator.calculate_net_amount(amount=amount, side=side, instrument_type=instrument_type)


def calculate_polars(
    df: pl.DataFrame,
    amount_col: str = "amount",
    side_col: str | None = None,
    instrument_col: str | None = None,
) -> pl.DataFrame:
    """Polars DataFrame üzerinde vektörize komisyon ve net tutar hesaplar (GEMINI.md Kural 2).

    Args:
        df: İşlem verilerini içeren Polars DataFrame.
        amount_col: Tutar kolon adı.
        side_col: Opsiyonel işlem yönü kolonu ("BUY" / "SELL").
        instrument_col: Opsiyonel enstrüman kolonu.

    Returns:
        pl.DataFrame: Komisyon ve maliyet sütunları eklenmiş Polars DataFrame.
    """
    return fee_calculator.calculate_polars(
        df=df,
        amount_col=amount_col,
        side_col=side_col,
        instrument_col=instrument_col,
    )


def calculate_fee_polars(
    df: pl.DataFrame,
    amount_col: str = "amount",
    side_col: str | None = None,
    instrument_col: str | None = None,
) -> pl.DataFrame:
    """calculate_polars için takma ad."""
    return calculate_polars(df=df, amount_col=amount_col, side_col=side_col, instrument_col=instrument_col)


def export_breakdowns_to_polars(breakdowns: list[FeeBreakdown]) -> pl.DataFrame:
    """export_fees_to_polars için takma ad."""
    return fee_calculator.export_breakdowns_to_polars(breakdowns)


def export_fees_to_polars(breakdowns: list[FeeBreakdown]) -> pl.DataFrame:
    """Maliyet dökümlerini Polars DataFrame olarak döner.

    Args:
        breakdowns: Döküm listesi.

    Returns:
        pl.DataFrame: Polars tablosu.
    """
    return fee_calculator.export_breakdowns_to_polars(breakdowns)


def export_fees_to_duckdb(breakdowns: list[FeeBreakdown], db_path: str = DEFAULT_FEE_DB_PATH) -> int:
    """Maliyet dökümlerini DuckDB denetim tablosuna kaydeder.

    Args:
        breakdowns: Döküm listesi.
        db_path: DuckDB dosya yolu.

    Returns:
        int: Kaydedilen kayıt sayısı.
    """
    return fee_calculator.export_to_duckdb(breakdowns=breakdowns, db_path=db_path)


def query_fee_audit_duckdb(
    db_path: str = DEFAULT_FEE_DB_PATH,
    side: str | None = None,
    instrument_type: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu Polars DataFrame olarak sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        side: İşlem yönü filtresi.
        instrument_type: Enstrüman sınıfı filtresi.
        limit: Maksimum satır limiti.

    Returns:
        pl.DataFrame: Filtrelenmiş maliyet denetim tablosu.
    """
    return fee_calculator.query_fee_audit_duckdb(
        db_path=db_path,
        side=side,
        instrument_type=instrument_type,
        limit=limit,
    )


__all__: Final[list[str]] = [
    # Sabitler
    "DEFAULT_BIST_FEE_RATE",
    "DEFAULT_BROKER_RATE",
    "DEFAULT_BSMV_RATE",
    "DEFAULT_FEE_DB_PATH",
    "DEFAULT_MIN_COMMISSION",
    "DEFAULT_MKK_FEE_RATE",
    "DEFAULT_VIOP_FEE_RATE",
    "VALID_INSTRUMENT_TYPES",
    "VALID_SIDES",
    # Modeller
    "BreakEvenAnalysis",
    "FeeBreakdown",
    "FeeCalculator",
    # Singleton
    "fee_calculator",
    # Kolaylık Fonksiyonları
    "calculate_break_even_price",
    "calculate_fee",
    "calculate_fee_polars",
    "calculate_net_cash_flow",
    "calculate_polars",
    "export_breakdowns_to_polars",
    "export_fees_to_duckdb",
    "export_fees_to_polars",
    "get_fee_calculator",
    "query_fee_audit_duckdb",
]
