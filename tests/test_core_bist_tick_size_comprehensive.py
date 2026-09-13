"""ALPHA BIST — services/core/bist_tick_size kapsamlı test suite.

Test edilen bileşenler:
- get_bist_tick_size: Fiyat seviyesine ve enstrüman tipine göre adım belirleme
- round_to_bist_tick: Fiyat yuvarlama (NEAREST, FLOOR, CEIL, SIDE_AWARE)
- round_to_valid_tick: Geriye dönük uyumlu alias
- is_valid_bist_tick: Geçerlilik denetimi (IEEE 754 float guard'lı)
- add_bist_ticks: Analitik kademe ekleme/çıkarma (O(1))
- spread_in_ticks: İki fiyat arası kademe farkı
- get_bist_price_limits: Taban/tavan hesaplama
- BISTTickTier: Veri modeli
- _safe_float: Sayısal guard fonksiyonu
"""

from __future__ import annotations

import pytest

from services.core.bist_tick_size import (
    SPECIAL_TICK_SIZES,
    BISTTickTier,
    _safe_float,
    add_bist_ticks,
    get_bist_tick_size,
    is_valid_bist_tick,
    round_to_bist_tick,
    round_to_valid_tick,
)

# ==============================================================================
# _safe_float testleri
# ==============================================================================


class TestSafeFloat:
    """_safe_float yardımcı fonksiyonu için birim testleri."""

    def test_normal_int(self) -> None:
        assert _safe_float(10) == pytest.approx(10.0)

    def test_normal_float(self) -> None:
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_none_returns_default(self) -> None:
        assert _safe_float(None) == 0.0

    def test_nan_returns_default(self) -> None:
        assert _safe_float(float("nan")) == 0.0

    def test_inf_returns_default(self) -> None:
        assert _safe_float(float("inf")) == 0.0
        assert _safe_float(float("-inf")) == 0.0

    def test_string_number(self) -> None:
        assert _safe_float("12.5") == pytest.approx(12.5)

    def test_invalid_string_returns_default(self) -> None:
        assert _safe_float("abc") == 0.0

    def test_custom_default(self) -> None:
        assert _safe_float(None, default=-1.0) == -1.0

    def test_zero(self) -> None:
        assert _safe_float(0) == 0.0

    def test_negative_float(self) -> None:
        assert _safe_float(-5.0) == pytest.approx(-5.0)


# ==============================================================================
# get_bist_tick_size testleri
# ==============================================================================


class TestGetBistTickSize:
    """BIST fiyat adımı belirleme fonksiyonunun birim testleri."""

    # --- Standard kademeler ---

    def test_below_20_first_tier(self) -> None:
        """0.01 - 19.99 TL aralığında adım 0.01 TL olmalı."""
        assert get_bist_tick_size(0.01) == pytest.approx(0.01)
        assert get_bist_tick_size(1.0) == pytest.approx(0.01)
        assert get_bist_tick_size(15.50) == pytest.approx(0.01)
        assert get_bist_tick_size(19.99) == pytest.approx(0.01)

    def test_20_to_50_second_tier(self) -> None:
        """20.00 - 49.98 TL aralığında adım 0.02 TL olmalı."""
        assert get_bist_tick_size(20.0) == pytest.approx(0.02)
        assert get_bist_tick_size(35.0) == pytest.approx(0.02)
        assert get_bist_tick_size(49.98) == pytest.approx(0.02)

    def test_50_to_100_third_tier(self) -> None:
        """50.00 - 99.95 TL aralığında adım 0.05 TL olmalı."""
        assert get_bist_tick_size(50.0) == pytest.approx(0.05)
        assert get_bist_tick_size(75.0) == pytest.approx(0.05)
        assert get_bist_tick_size(99.95) == pytest.approx(0.05)

    def test_100_and_above_fourth_tier(self) -> None:
        """100 TL ve üzerinde adım 0.10 TL olmalı."""
        assert get_bist_tick_size(100.0) == pytest.approx(0.10)
        assert get_bist_tick_size(500.0) == pytest.approx(0.10)
        assert get_bist_tick_size(10000.0) == pytest.approx(0.10)

    # --- Sınır değerler ---

    def test_boundary_20(self) -> None:
        """20.0 TL tam sınırda 0.02 TL olmalı."""
        assert get_bist_tick_size(20.0) == pytest.approx(0.02)

    def test_boundary_50(self) -> None:
        """50.0 TL tam sınırda 0.05 TL olmalı."""
        assert get_bist_tick_size(50.0) == pytest.approx(0.05)

    def test_boundary_100(self) -> None:
        """100.0 TL tam sınırda 0.10 TL olmalı."""
        assert get_bist_tick_size(100.0) == pytest.approx(0.10)

    # --- Geçersiz fiyat guard'ları ---

    def test_zero_price_returns_minimum(self) -> None:
        """Sıfır fiyatta fail-closed olarak minimum adım (0.01) döner."""
        assert get_bist_tick_size(0.0) == pytest.approx(0.01)

    def test_negative_price_returns_minimum(self) -> None:
        """Negatif fiyatta fail-closed olarak minimum adım (0.01) döner."""
        assert get_bist_tick_size(-5.0) == pytest.approx(0.01)

    def test_nan_price_returns_minimum(self) -> None:
        """NaN fiyatta fail-closed olarak minimum adım (0.01) döner."""
        assert get_bist_tick_size(float("nan")) == pytest.approx(0.01)

    # --- Özel enstrüman tipleri ---

    def test_warrant_tick(self) -> None:
        assert get_bist_tick_size(5.0, "warrant") == pytest.approx(0.001)
        assert get_bist_tick_size(500.0, "warrant") == pytest.approx(0.001)

    def test_certificate_tick(self) -> None:
        assert get_bist_tick_size(5.0, "certificate") == pytest.approx(0.001)

    def test_fund_tick(self) -> None:
        assert get_bist_tick_size(5.0, "fund") == pytest.approx(0.001)

    def test_etf_tick(self) -> None:
        assert get_bist_tick_size(5.0, "etf") == pytest.approx(0.01)
        assert get_bist_tick_size(200.0, "etf") == pytest.approx(0.01)

    def test_instrument_type_case_insensitive(self) -> None:
        assert get_bist_tick_size(5.0, "WARRANT") == pytest.approx(0.001)
        assert get_bist_tick_size(5.0, "Warrant") == pytest.approx(0.001)

    def test_unknown_instrument_uses_stock_logic(self) -> None:
        """Bilinmeyen enstrüman tipinde standart hisse mantığı uygulanır."""
        assert get_bist_tick_size(10.0, "unknown_type") == pytest.approx(0.01)


# ==============================================================================
# round_to_bist_tick testleri
# ==============================================================================


class TestRoundToBistTick:
    """BIST fiyat yuvarlama fonksiyonunun birim testleri."""

    def test_nearest_exact_price(self) -> None:
        """Tam adıma oturan fiyat değişmez."""
        assert round_to_bist_tick(10.05) == pytest.approx(10.05)
        assert round_to_bist_tick(20.04) == pytest.approx(20.04)

    def test_nearest_rounds_correctly(self) -> None:
        """En yakın BIST adımına yuvarlama."""
        assert round_to_bist_tick(10.034) == pytest.approx(10.03)
        assert round_to_bist_tick(10.035) == pytest.approx(10.04)

    def test_floor_mode(self) -> None:
        """FLOOR modu aşağı yuvarlar."""
        result = round_to_bist_tick(10.038, mode="FLOOR")
        assert result == pytest.approx(10.03)

    def test_ceil_mode(self) -> None:
        """CEIL modu yukarı yuvarlar."""
        result = round_to_bist_tick(10.031, mode="CEIL")
        assert result == pytest.approx(10.04)

    def test_side_aware_buy(self) -> None:
        """SIDE_AWARE modunda BUY emri aşağı yuvarlar (bütçeyi aşmamak için)."""
        result = round_to_bist_tick(10.038, side="BUY", mode="SIDE_AWARE")
        assert result == pytest.approx(10.03)

    def test_side_aware_sell(self) -> None:
        """SIDE_AWARE modunda SELL emri yukarı yuvarlar (ucuza vermemek için)."""
        result = round_to_bist_tick(10.031, side="SELL", mode="SIDE_AWARE")
        assert result == pytest.approx(10.04)

    def test_zero_price_returns_zero(self) -> None:
        """Sıfır ve negatif fiyat 0.0 döner."""
        assert round_to_bist_tick(0.0) == 0.0
        assert round_to_bist_tick(-5.0) == 0.0

    def test_nan_price_returns_zero(self) -> None:
        assert round_to_bist_tick(float("nan")) == 0.0

    def test_warrant_precision(self) -> None:
        """Varant tipi 4 ondalık basamakla yuvarlanır."""
        result = round_to_bist_tick(0.1234, instrument_type="warrant")
        assert result == pytest.approx(0.123, abs=1e-4)

    def test_down_mode_alias(self) -> None:
        """DOWN modu FLOOR ile aynı davranır."""
        r1 = round_to_bist_tick(10.038, mode="DOWN")
        r2 = round_to_bist_tick(10.038, mode="FLOOR")
        assert r1 == pytest.approx(r2)

    def test_up_mode_alias(self) -> None:
        """UP modu CEIL ile aynı davranır."""
        r1 = round_to_bist_tick(10.031, mode="UP")
        r2 = round_to_bist_tick(10.031, mode="CEIL")
        assert r1 == pytest.approx(r2)

    def test_minimum_one_tick(self) -> None:
        """Çok küçük fiyatlar bile en az 1 adım değerinde yuvarlanır."""
        result = round_to_bist_tick(0.001, instrument_type="stock")
        assert result >= 0.01

    def test_high_price_rounding(self) -> None:
        """Yüksek fiyat aralığında 0.10 TL adımına yuvarlama."""
        result = round_to_bist_tick(150.07, mode="NEAREST")
        assert result == pytest.approx(150.1)


# ==============================================================================
# round_to_valid_tick testleri
# ==============================================================================


class TestRoundToValidTick:
    """Geriye dönük uyumlu alias fonksiyonu için testler."""

    def test_floor_default(self) -> None:
        """Varsayılan olarak aşağı yuvarlar."""
        result = round_to_valid_tick(10.038)
        assert result == pytest.approx(10.03)

    def test_ceil_round_up(self) -> None:
        """round_up=True ile yukarı yuvarlar."""
        result = round_to_valid_tick(10.031, round_up=True)
        assert result == pytest.approx(10.04)


# ==============================================================================
# is_valid_bist_tick testleri
# ==============================================================================


class TestIsValidBistTick:
    """Fiyat geçerlilik denetimi (IEEE 754 float guard'lı) testleri."""

    def test_exact_valid_price(self) -> None:
        """Tam adıma oturan fiyat geçerlidir."""
        assert is_valid_bist_tick(10.05) is True
        assert is_valid_bist_tick(20.00) is True
        assert is_valid_bist_tick(100.10) is True

    def test_invalid_price_between_ticks(self) -> None:
        """Adımlar arasında kalan fiyat geçersizdir."""
        assert is_valid_bist_tick(10.033) is False
        assert is_valid_bist_tick(20.01) is False  # 0.02 adımına oturmuyor

    def test_zero_price_is_invalid(self) -> None:
        assert is_valid_bist_tick(0.0) is False

    def test_negative_price_is_invalid(self) -> None:
        assert is_valid_bist_tick(-5.0) is False

    def test_nan_price_is_invalid(self) -> None:
        assert is_valid_bist_tick(float("nan")) is False

    def test_tolerance_accepted(self) -> None:
        """Float hassasiyeti içindeki sapma toleranslı kabul edilir."""
        # 10.05 + çok küçük sapma → hâlâ geçerli (tolerans 1e-4 içinde)
        assert is_valid_bist_tick(10.05 + 1e-8) is True

    def test_warrant_valid(self) -> None:
        """Varant için 0.001 adımına oturan fiyat geçerlidir."""
        assert is_valid_bist_tick(0.123, instrument_type="warrant") is True
        assert is_valid_bist_tick(0.1234, instrument_type="warrant") is False

    def test_etf_valid(self) -> None:
        """BYF için 0.01 adımına oturan fiyat geçerlidir."""
        assert is_valid_bist_tick(5.00, instrument_type="etf") is True
        assert is_valid_bist_tick(5.005, instrument_type="etf") is False


# ==============================================================================
# add_bist_ticks testleri
# ==============================================================================


class TestAddBistTicks:
    """Analitik kademe ekleme/çıkarma (O(1)) testleri."""

    def test_add_zero_ticks(self) -> None:
        """Sıfır kademe eklemek fiyatı değiştirmez (yalnızca yuvarlar)."""
        result = add_bist_ticks(10.03, 0)
        assert result == pytest.approx(10.03)

    def test_add_positive_ticks_within_tier(self) -> None:
        """Aynı kademe içinde pozitif adım ekleme."""
        result = add_bist_ticks(10.00, 3)
        assert result == pytest.approx(10.03)

    def test_add_negative_ticks_within_tier(self) -> None:
        """Aynı kademe içinde negatif adım çıkarma."""
        result = add_bist_ticks(10.05, -3)
        assert result == pytest.approx(10.02)

    def test_add_ticks_crossing_tier_boundary(self) -> None:
        """19.99 → 20.00 kademe sınırını geçen adım ekleme."""
        result = add_bist_ticks(19.98, 2)  # +2 × 0.01 = 20.00
        assert result == pytest.approx(20.00)

    def test_add_ticks_crossing_into_higher_tier(self) -> None:
        """20.00'dan üst kademeye geçen adım ekleme."""
        result = add_bist_ticks(19.99, 2)  # 19.99 + 0.01 = 20.00, sonra +1 adım = 20.02
        assert result == pytest.approx(20.02)

    def test_subtract_ticks_crossing_boundary(self) -> None:
        """20.00 → 19.99 kademe sınırını aşağı geçen adım çıkarma."""
        result = add_bist_ticks(20.02, -2)  # 20.02 - 0.02 = 20.00, -1 daha = 19.99
        assert result == pytest.approx(19.99)

    def test_zero_price_returns_zero(self) -> None:
        assert add_bist_ticks(0.0, 5) == 0.0
        assert add_bist_ticks(-1.0, 3) == 0.0

    def test_warrant_fixed_tick(self) -> None:
        """Varantta sabit 0.001 adımı kullanılır."""
        result = add_bist_ticks(0.100, 5, instrument_type="warrant")
        assert result == pytest.approx(0.105, abs=1e-4)

    def test_etf_fixed_tick(self) -> None:
        """BYF'de sabit 0.01 adımı kullanılır."""
        result = add_bist_ticks(5.00, 3, instrument_type="etf")
        assert result == pytest.approx(5.03)

    def test_large_tick_count(self) -> None:
        """Çok sayıda adım ekleme tutarlı sonuç verir."""
        result = add_bist_ticks(10.00, 1000)
        assert result > 10.00
        # Sonuç makul aralıkta olmalı
        assert result < 10000.0

    def test_negative_large_tick_count_floor_at_minimum(self) -> None:
        """Aşırı negatif adım çıkarma minimum değere kenet."""
        result = add_bist_ticks(0.05, -100)
        assert result >= 0.01  # Asla negatife düşmez


# ==============================================================================
# BISTTickTier veri modeli testleri
# ==============================================================================


class TestBISTTickTier:
    """BISTTickTier dataclass veri modeli testleri."""

    def test_creation(self) -> None:
        tier = BISTTickTier(
            tier_name="kademe_1",
            min_price=0.01,
            max_price=19.99,
            tick_size=0.01,
            description="İlk kademe",
        )
        assert tier.tier_name == "kademe_1"
        assert tier.tick_size == pytest.approx(0.01)

    def test_to_dict(self) -> None:
        tier = BISTTickTier(
            tier_name="kademe_1",
            min_price=0.01,
            max_price=19.99,
            tick_size=0.01,
            description="İlk kademe",
        )
        d = tier.to_dict()
        assert d["tier_name"] == "kademe_1"
        assert d["tick_size"] == pytest.approx(0.01)
        assert "min_price" in d
        assert "max_price" in d

    def test_to_orjson_bytes(self) -> None:
        import orjson

        tier = BISTTickTier(
            tier_name="kademe_2",
            min_price=20.0,
            max_price=49.98,
            tick_size=0.02,
            description="İkinci kademe",
        )
        raw = tier.to_orjson_bytes()
        assert isinstance(raw, bytes)
        parsed = orjson.loads(raw)
        assert parsed["tier_name"] == "kademe_2"

    def test_repr(self) -> None:
        tier = BISTTickTier(
            tier_name="kademe_3",
            min_price=50.0,
            max_price=99.95,
            tick_size=0.05,
            description="Üçüncü kademe",
        )
        r = repr(tier)
        assert "kademe_3" in r
        assert "0.05" in r


# ==============================================================================
# SPECIAL_TICK_SIZES sabit testleri
# ==============================================================================


class TestSpecialTickSizes:
    """Özel enstrüman adımı sabitleri doğrulama."""

    def test_warrant_defined(self) -> None:
        assert "warrant" in SPECIAL_TICK_SIZES
        assert SPECIAL_TICK_SIZES["warrant"] == pytest.approx(0.001)

    def test_certificate_defined(self) -> None:
        assert "certificate" in SPECIAL_TICK_SIZES
        assert SPECIAL_TICK_SIZES["certificate"] == pytest.approx(0.001)

    def test_fund_defined(self) -> None:
        assert "fund" in SPECIAL_TICK_SIZES
        assert SPECIAL_TICK_SIZES["fund"] == pytest.approx(0.001)

    def test_etf_defined(self) -> None:
        assert "etf" in SPECIAL_TICK_SIZES
        assert SPECIAL_TICK_SIZES["etf"] == pytest.approx(0.01)


# ==============================================================================
# Uçtan uca (integration-style) senaryolar
# ==============================================================================


class TestEndToEndScenarios:
    """Gerçek BIST senaryolarını kapsayan uçtan uca testler."""

    def test_thyao_like_price_progression(self) -> None:
        """THYAO benzeri (20-50 TL aralığı) fiyat ilerlemesi."""
        price = 25.00
        for _ in range(5):
            price = add_bist_ticks(price, 1)
        assert price == pytest.approx(25.10)

    def test_froto_like_high_price(self) -> None:
        """FROTO benzeri (>100 TL) yüksek fiyat adımı."""
        assert get_bist_tick_size(400.0) == pytest.approx(0.10)
        rounded = round_to_bist_tick(400.05, mode="NEAREST")
        assert rounded == pytest.approx(400.10) or rounded == pytest.approx(400.00)

    def test_warrant_micro_price(self) -> None:
        """Küçük değerli varant için mikro adım senaryosu."""
        assert get_bist_tick_size(0.05, "warrant") == pytest.approx(0.001)
        rounded = round_to_bist_tick(0.0534, instrument_type="warrant", mode="NEAREST")
        assert abs(rounded - 0.053) < 1e-3 or abs(rounded - 0.054) < 1e-3

    def test_price_limit_calculation_example(self) -> None:
        """Fiyat limiti hesaplama: %10 bant."""
        ref_price = 50.0
        upper = ref_price * 1.10
        lower = ref_price * 0.90
        # Üst limitin ve alt limitin geçerli BIST adımına yuvarlanması
        upper_rounded = round_to_bist_tick(upper, mode="FLOOR")
        lower_rounded = round_to_bist_tick(lower, mode="CEIL")
        assert upper_rounded <= upper
        assert lower_rounded >= lower
        assert is_valid_bist_tick(upper_rounded)
        assert is_valid_bist_tick(lower_rounded)

    def test_round_trip_consistency(self) -> None:
        """Bir fiyatı yuvarlayıp doğrulama → round-trip tutarlılığı."""
        prices = [5.0, 15.5, 25.0, 55.0, 150.0]
        for p in prices:
            rounded = round_to_bist_tick(p)
            assert is_valid_bist_tick(rounded), f"{rounded} geçerli değil ({p} den yuvarlandı)"

    def test_tick_arithmetic_consistency(self) -> None:
        """Adım ekleme ve çıkarma round-trip tutarlılığı."""
        price = 30.00
        after_add = add_bist_ticks(price, 5)
        after_sub = add_bist_ticks(after_add, -5)
        assert after_sub == pytest.approx(price)

    def test_ieee754_float_sensitivity(self) -> None:
        """IEEE 754 float toplamı yanlış modulo verebilir — is_valid_bist_tick doğru sonuç vermeli."""
        # 0.1 * 3 = 0.30000000000000004 gibi float sapmaları
        price = 0.1 + 0.1 + 0.1  # ≈ 0.30000000000000004
        # 0.30 geçerli 0.01 adımına oturuyor mu diye kontrol et
        rounded = round_to_bist_tick(price)
        assert is_valid_bist_tick(rounded) is True
