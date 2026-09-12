"""ALPHA BIST — services/core/fee_calculator kapsamlı test suite.

Test edilen bileşenler:
- FeeBreakdown: İşlem maliyeti detay dökümü veri modeli
- BreakEvenAnalysis: Başa baş analizi veri modeli
- FeeCalculator: Ana hesaplayıcı sınıf
  - calculate(): Maliyet döküm hesaplama
  - calculate_net_amount(): Net nakit akışı
  - set_broker_rate(): Dinamik oran güncelleme
  - set_tiered_rates(): Kademeli barem yönetimi
  - batch_calculate_polars(): Polars vektörize hesaplama
  - calculate_break_even(): Başa baş analizi
- _safe_float: Guard fonksiyonu
- Mevzuat sabitleri doğrulama
"""

from __future__ import annotations

import math
import threading

import polars as pl
import pytest

from services.core.fee_calculator import (
    DEFAULT_BIST_FEE_RATE,
    DEFAULT_BSMV_RATE,
    DEFAULT_BROKER_RATE,
    DEFAULT_MIN_COMMISSION,
    DEFAULT_MKK_FEE_RATE,
    DEFAULT_VIOP_FEE_RATE,
    BreakEvenAnalysis,
    FeeBreakdown,
    FeeCalculator,
    _safe_float,
)


# ==============================================================================
# Sabit doğrulama testleri (Mevzuat)
# ==============================================================================


class TestRegulatoryConstants:
    """Yasal mevzuata uygun oran sabitleri doğrulama testleri."""

    def test_broker_rate_default(self) -> None:
        """Varsayılan broker komisyonu on binde 3 (%0.03)."""
        assert DEFAULT_BROKER_RATE == pytest.approx(0.0003)

    def test_bist_fee_rate(self) -> None:
        """BIST borsa payı %0.0056 (yüz binde 5.6)."""
        assert DEFAULT_BIST_FEE_RATE == pytest.approx(0.000056)

    def test_viop_fee_rate(self) -> None:
        """VİOP borsa payı %0.0040."""
        assert DEFAULT_VIOP_FEE_RATE == pytest.approx(0.00004)

    def test_mkk_fee_rate(self) -> None:
        """MKK tescil/saklama payı %0.00109."""
        assert DEFAULT_MKK_FEE_RATE == pytest.approx(0.0000109)

    def test_bsmv_rate(self) -> None:
        """BSMV oranı %5."""
        assert DEFAULT_BSMV_RATE == pytest.approx(0.05)

    def test_min_commission(self) -> None:
        """Minimum komisyon 1.00 TL."""
        assert DEFAULT_MIN_COMMISSION == pytest.approx(1.00)


# ==============================================================================
# _safe_float testleri
# ==============================================================================


class TestSafeFloat:
    """_safe_float yardımcı fonksiyonu için birim testleri."""

    def test_valid_float(self) -> None:
        assert _safe_float(100.0) == pytest.approx(100.0)

    def test_none_returns_default(self) -> None:
        assert _safe_float(None) == 0.0

    def test_nan_returns_default(self) -> None:
        assert _safe_float(float("nan")) == 0.0

    def test_inf_returns_default(self) -> None:
        assert _safe_float(float("inf")) == 0.0

    def test_string_numeric(self) -> None:
        assert _safe_float("50.5") == pytest.approx(50.5)

    def test_custom_default(self) -> None:
        assert _safe_float(None, default=-1.0) == -1.0


# ==============================================================================
# FeeBreakdown veri modeli testleri
# ==============================================================================


class TestFeeBreakdown:
    """FeeBreakdown dataclass veri modeli testleri."""

    def _make_breakdown(
        self,
        amount: float = 10000.0,
        broker_fee: float = 3.0,
        bist_fee: float = 0.56,
        mkk_fee: float = 0.109,
        bsmv: float = 0.15,
        total: float = 3.819,
        effective_rate: float = 0.03819,
        side: str = "BUY",
        instrument_type: str = "equity",
    ) -> FeeBreakdown:
        return FeeBreakdown(
            amount=amount,
            broker_fee=broker_fee,
            bist_fee=bist_fee,
            mkk_fee=mkk_fee,
            bsmv=bsmv,
            total=total,
            effective_rate=effective_rate,
            side=side,
            instrument_type=instrument_type,
        )

    def test_creation_and_fields(self) -> None:
        fb = self._make_breakdown()
        assert fb.amount == pytest.approx(10000.0)
        assert fb.side == "BUY"
        assert fb.instrument_type == "equity"

    def test_net_amount_buy_calculated(self) -> None:
        """BUY işleminde net_amount = amount + total olarak otomatik hesaplanır."""
        fb = self._make_breakdown(side="BUY", amount=10000.0, total=3.819)
        assert fb.net_amount == pytest.approx(10003.819, abs=0.001)

    def test_net_amount_sell_calculated(self) -> None:
        """SELL işleminde net_amount = amount - total olarak otomatik hesaplanır."""
        fb = self._make_breakdown(side="SELL", amount=10000.0, total=3.819)
        assert fb.net_amount == pytest.approx(9996.181, abs=0.001)

    def test_invalid_side_normalizes(self) -> None:
        """Geçersiz side 'UNKNOWN' olarak normalize edilir."""
        fb = self._make_breakdown(side="INVALID")
        assert fb.side == "UNKNOWN"

    def test_invalid_instrument_type_normalizes(self) -> None:
        """Geçersiz instrument_type 'equity' olarak normalize edilir."""
        fb = self._make_breakdown(instrument_type="xyz")
        assert fb.instrument_type == "equity"

    def test_to_dict(self) -> None:
        fb = self._make_breakdown()
        d = fb.to_dict()
        assert "amount" in d
        assert "broker_fee" in d
        assert "total" in d
        assert "side" in d
        assert "net_amount" in d

    def test_to_orjson_bytes(self) -> None:
        import orjson

        fb = self._make_breakdown()
        raw = fb.to_orjson_bytes()
        assert isinstance(raw, bytes)
        parsed = orjson.loads(raw)
        assert parsed["side"] == "BUY"

    def test_repr(self) -> None:
        fb = self._make_breakdown()
        r = repr(fb)
        assert "FeeBreakdown" in r
        assert "BUY" in r


# ==============================================================================
# FeeCalculator.calculate() testleri
# ==============================================================================


class TestFeeCalculatorCalculate:
    """FeeCalculator.calculate() ana hesaplama metodu testleri."""

    @pytest.fixture
    def calc(self) -> FeeCalculator:
        return FeeCalculator()

    def test_standard_equity_buy(self, calc: FeeCalculator) -> None:
        """10000 TL equity alışında standart maliyet hesabı."""
        fb = calc.calculate(10000.0, side="BUY", instrument_type="equity")
        assert fb.amount == pytest.approx(10000.0)
        assert fb.broker_fee >= DEFAULT_MIN_COMMISSION
        assert fb.bist_fee == pytest.approx(10000.0 * DEFAULT_BIST_FEE_RATE, abs=0.001)
        assert fb.mkk_fee == pytest.approx(10000.0 * DEFAULT_MKK_FEE_RATE, abs=0.001)
        assert fb.bsmv == pytest.approx(fb.broker_fee * DEFAULT_BSMV_RATE, abs=0.001)
        assert fb.total > 0.0
        assert fb.side == "BUY"

    def test_standard_equity_sell(self, calc: FeeCalculator) -> None:
        """10000 TL equity satışında net_amount < amount."""
        fb = calc.calculate(10000.0, side="SELL", instrument_type="equity")
        assert fb.net_amount < fb.amount

    def test_viop_instrument(self, calc: FeeCalculator) -> None:
        """VİOP işleminde MKK payı sıfırdır."""
        fb = calc.calculate(10000.0, side="BUY", instrument_type="viop")
        assert fb.mkk_fee == pytest.approx(0.0)
        assert fb.bist_fee == pytest.approx(10000.0 * DEFAULT_VIOP_FEE_RATE, abs=0.001)

    def test_warrant_instrument(self, calc: FeeCalculator) -> None:
        """Varant işleminde standart equity oranları uygulanır."""
        fb = calc.calculate(5000.0, side="BUY", instrument_type="warrant")
        assert fb.instrument_type == "warrant"
        assert fb.total > 0.0

    def test_zero_amount_returns_empty(self, calc: FeeCalculator) -> None:
        """Sıfır işlem tutarında boş FeeBreakdown döner."""
        fb = calc.calculate(0.0)
        assert fb.amount == 0.0
        assert fb.total == 0.0

    def test_negative_amount_returns_empty(self, calc: FeeCalculator) -> None:
        """Negatif tutar boş FeeBreakdown döner."""
        fb = calc.calculate(-1000.0)
        assert fb.total == 0.0

    def test_nan_amount_returns_empty(self, calc: FeeCalculator) -> None:
        fb = calc.calculate(float("nan"))
        assert fb.total == 0.0

    def test_minimum_commission_applied(self, calc: FeeCalculator) -> None:
        """Çok küçük işlemlerde minimum komisyon uygulanır."""
        fb = calc.calculate(1.0, side="BUY")  # 1 TL × 0.0003 = 0.0003 < 1.0 TL minimum
        assert fb.broker_fee == pytest.approx(DEFAULT_MIN_COMMISSION, abs=0.001)

    def test_effective_rate_calculation(self, calc: FeeCalculator) -> None:
        """Efektif oran toplam maliyetin tutara oranıdır."""
        fb = calc.calculate(10000.0, side="BUY")
        expected_rate = (fb.total / fb.amount) * 100.0
        assert fb.effective_rate == pytest.approx(expected_rate, rel=1e-4)

    def test_invalid_side_normalized(self, calc: FeeCalculator) -> None:
        fb = calc.calculate(5000.0, side="WRONG")
        assert fb.side == "UNKNOWN"

    def test_invalid_instrument_normalized(self, calc: FeeCalculator) -> None:
        fb = calc.calculate(5000.0, instrument_type="unknown")
        assert fb.instrument_type == "equity"

    def test_case_insensitive_side(self, calc: FeeCalculator) -> None:
        fb = calc.calculate(5000.0, side="buy")
        assert fb.side == "BUY"

    def test_case_insensitive_instrument(self, calc: FeeCalculator) -> None:
        fb = calc.calculate(5000.0, instrument_type="EQUITY")
        assert fb.instrument_type == "equity"


# ==============================================================================
# FeeCalculator.set_broker_rate() testleri
# ==============================================================================


class TestSetBrokerRate:
    """Dinamik broker oranı güncelleme testleri."""

    def test_valid_rate_update(self) -> None:
        calc = FeeCalculator()
        calc.set_broker_rate(0.001)
        assert calc.broker_rate == pytest.approx(0.001)

    def test_zero_rate(self) -> None:
        calc = FeeCalculator()
        calc.set_broker_rate(0.0)
        assert calc.broker_rate == pytest.approx(0.0)

    def test_max_rate(self) -> None:
        calc = FeeCalculator()
        calc.set_broker_rate(1.0)
        assert calc.broker_rate == pytest.approx(1.0)

    def test_negative_rate_raises(self) -> None:
        calc = FeeCalculator()
        with pytest.raises(ValueError):
            calc.set_broker_rate(-0.001)

    def test_above_one_raises(self) -> None:
        calc = FeeCalculator()
        with pytest.raises(ValueError):
            calc.set_broker_rate(1.5)

    def test_nan_rate_raises(self) -> None:
        calc = FeeCalculator()
        with pytest.raises(ValueError):
            calc.set_broker_rate(float("nan"))

    def test_rate_affects_calculation(self) -> None:
        calc = FeeCalculator()
        fb1 = calc.calculate(10000.0, side="BUY")
        calc.set_broker_rate(0.001)
        fb2 = calc.calculate(10000.0, side="BUY")
        assert fb2.broker_fee > fb1.broker_fee


# ==============================================================================
# FeeCalculator.set_tiered_rates() testleri
# ==============================================================================


class TestTieredRates:
    """Kademeli hacim komisyonu barem testleri."""

    def test_tiered_rate_applied_below_threshold(self) -> None:
        """Küçük işlem → yüksek oran baremini alır."""
        calc = FeeCalculator(
            tiered_rates=[
                (50000.0, 0.0005),   # 50K TL altı → %0.05
                (200000.0, 0.0003),  # 50K-200K arası → %0.03
                (float("inf"), 0.0001),  # 200K üzeri → %0.01
            ]
        )
        fb = calc.calculate(10000.0, side="BUY")
        expected_broker = max(10000.0 * 0.0005, DEFAULT_MIN_COMMISSION)
        assert fb.broker_fee == pytest.approx(expected_broker, abs=0.001)

    def test_tiered_rate_applied_above_threshold(self) -> None:
        """Büyük işlem → en düşük oran baremini alır."""
        calc = FeeCalculator(
            tiered_rates=[
                (50000.0, 0.0005),
                (200000.0, 0.0003),
                (float("inf"), 0.0001),
            ]
        )
        fb = calc.calculate(500000.0, side="BUY")
        expected_broker = max(500000.0 * 0.0001, DEFAULT_MIN_COMMISSION)
        assert fb.broker_fee == pytest.approx(expected_broker, abs=0.001)

    def test_invalid_tiers_skipped(self) -> None:
        """Negatif hacim veya oran içeren baremler atlanır."""
        calc = FeeCalculator(tiered_rates=[(-1.0, 0.001), (0.0, 0.001)])
        assert len(calc._tiered_rates) == 0


# ==============================================================================
# Thread-safety testleri
# ==============================================================================


class TestThreadSafety:
    """FeeCalculator thread-safe davranış testleri."""

    def test_concurrent_calculations(self) -> None:
        """Eş zamanlı hesaplamalar tutarlı sonuç verir."""
        calc = FeeCalculator()
        results = []
        errors = []

        def worker() -> None:
            try:
                fb = calc.calculate(10000.0, side="BUY")
                results.append(fb.total)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20
        # Tüm sonuçlar aynı olmalı
        assert all(abs(r - results[0]) < 0.001 for r in results)

    def test_concurrent_rate_update_and_calculate(self) -> None:
        """Eş zamanlı oran güncelleme ve hesaplama race condition vermez."""
        calc = FeeCalculator()
        errors = []

        def updater() -> None:
            for rate in [0.0003, 0.0005, 0.0003]:
                try:
                    calc.set_broker_rate(rate)
                except Exception as e:
                    errors.append(str(e))

        def calculator() -> None:
            for _ in range(10):
                try:
                    calc.calculate(10000.0)
                except Exception as e:
                    errors.append(str(e))

        threads = [threading.Thread(target=updater), threading.Thread(target=calculator)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ==============================================================================
# Polars vektörize hesaplama testleri
# ==============================================================================


class TestBatchCalculatePolars:
    """Toplu Polars DataFrame hesaplama testleri."""

    def test_batch_calculate_basic(self) -> None:
        """Temel Polars batch hesaplama çalışır."""
        calc = FeeCalculator()
        # batch_calculate_polars metodu mevcutsa test et
        if not hasattr(calc, "batch_calculate_polars"):
            pytest.skip("batch_calculate_polars metodu mevcut değil")

        df = pl.DataFrame({
            "amount": [10000.0, 20000.0, 50000.0],
            "side": ["BUY", "SELL", "BUY"],
            "instrument_type": ["equity", "equity", "viop"],
        })
        result = calc.batch_calculate_polars(df)
        assert isinstance(result, pl.DataFrame)
        assert "total" in result.columns
        assert len(result) == 3


# ==============================================================================
# BreakEvenAnalysis testleri
# ==============================================================================


class TestBreakEvenAnalysis:
    """Başa baş analizi testleri."""

    def test_calculate_break_even(self) -> None:
        """Başa baş hesaplama mevcutsa test et."""
        calc = FeeCalculator()
        if not hasattr(calc, "calculate_break_even"):
            pytest.skip("calculate_break_even metodu mevcut değil")

        result = calc.calculate_break_even(
            entry_price=100.0,
            quantity=100,
        )
        assert isinstance(result, BreakEvenAnalysis)
        assert result.break_even_price > result.entry_price  # Maliyet nedeniyle yüksek

    def test_break_even_repr(self) -> None:
        """BreakEvenAnalysis modelinin repr'i çalışır."""
        calc = FeeCalculator()
        entry_fee = calc.calculate(10000.0, side="BUY")
        bea = BreakEvenAnalysis(
            entry_price=100.0,
            quantity=100,
            entry_fee=entry_fee,
            break_even_price=100.5,
            break_even_return_pct=0.5,
            tick_aligned_price=100.50,
            estimated_exit_fee=entry_fee.total,
        )
        r = repr(bea)
        assert "BreakEvenAnalysis" in r


# ==============================================================================
# Sayısal doğruluk testleri
# ==============================================================================


class TestNumericalAccuracy:
    """SPK mevzuatına göre sayısal doğruluk testleri."""

    def test_bist_fee_calculation_accuracy(self) -> None:
        """10000 TL işlemde borsa payı doğruluğu."""
        calc = FeeCalculator()
        fb = calc.calculate(10000.0)
        # 10000 × 0.000056 = 0.56 TL
        assert fb.bist_fee == pytest.approx(0.56, abs=0.001)

    def test_mkk_fee_calculation_accuracy(self) -> None:
        """10000 TL işlemde MKK payı doğruluğu."""
        calc = FeeCalculator()
        fb = calc.calculate(10000.0)
        # 10000 × 0.0000109 = 0.109 TL
        assert fb.mkk_fee == pytest.approx(0.109, abs=0.001)

    def test_bsmv_on_broker_fee_only(self) -> None:
        """BSMV yalnızca broker komisyonu üzerinden hesaplanır (BIST + MKK hariç)."""
        calc = FeeCalculator()
        fb = calc.calculate(100000.0, side="BUY")
        expected_bsmv = fb.broker_fee * DEFAULT_BSMV_RATE
        assert fb.bsmv == pytest.approx(expected_bsmv, abs=0.001)

    def test_large_transaction_accuracy(self) -> None:
        """1 milyon TL işlemde maliyet tutarlılığı."""
        calc = FeeCalculator()
        fb = calc.calculate(1_000_000.0, side="BUY")
        assert fb.total > 0.0
        assert fb.total < fb.amount * 0.01  # Toplam maliyet işlem tutarının %1'inden az

    def test_total_equals_sum_of_parts(self) -> None:
        """total = broker_fee + bist_fee + mkk_fee + bsmv olmalı."""
        calc = FeeCalculator()
        fb = calc.calculate(50000.0, side="BUY")
        expected_total = fb.broker_fee + fb.bist_fee + fb.mkk_fee + fb.bsmv
        assert fb.total == pytest.approx(expected_total, abs=0.001)
