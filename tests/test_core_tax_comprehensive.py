"""ALPHA BIST — services/core/tax kapsamlı test suite.

Test edilen bileşenler:
- TaxResult: Vergi sonucu veri modeli
- TaxCalculator: Ana vergi hesaplama motoru
  - calculate_tax(): Tekil işlem vergi hesabı
  - calculate_tax_polars(): Toplu Polars hesabı
  - export_tax_audit_to_polars(): DuckDB denetim kayıtları
  - _get_income_tax_rate(): Gelir vergisi dilim hesabı
- INCOME_TAX_BRACKETS: Vergi dilimleri
- DEFAULT_TAX_RATES: Mevzuat stopaj oranları
- Fail-Closed sayısal guard'lar
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import orjson
import polars as pl
import pytest

from services.core.tax import (
    DEFAULT_TAX_RATES,
    HOLDING_PERIOD_THRESHOLD,
    INCOME_TAX_BRACKETS,
    TaxCalculator,
    TaxResult,
)


# ==============================================================================
# Mevzuat sabiti doğrulama testleri
# ==============================================================================


class TestRegulatoryConstants:
    """Vergi mevzuatı sabitlerinin doğrulanması."""

    def test_bist_stock_zero_tax(self) -> None:
        """BIST hisse senetleri GVK Geçici 67 kapsamında %0 stopaj."""
        assert DEFAULT_TAX_RATES["stock_bist"] == pytest.approx(0.0)

    def test_dividend_withholding_tax(self) -> None:
        """Temettü stopajı %15."""
        assert DEFAULT_TAX_RATES["dividend"] == pytest.approx(0.15)

    def test_bond_withholding_tax(self) -> None:
        """Tahvil/bono stopajı %10."""
        assert DEFAULT_TAX_RATES["bond"] == pytest.approx(0.10)

    def test_fund_equity_zero_tax(self) -> None:
        """Hisse yoğun fon muafiyeti %0."""
        assert DEFAULT_TAX_RATES["fund_equity"] == pytest.approx(0.0)

    def test_repo_tax(self) -> None:
        """Repo stopajı %10."""
        assert DEFAULT_TAX_RATES["repo"] == pytest.approx(0.10)

    def test_viop_zero_tax(self) -> None:
        """VİOP pay ve endeks kontratları %0 stopaj."""
        assert DEFAULT_TAX_RATES["viop"] == pytest.approx(0.0)

    def test_holding_period_threshold(self) -> None:
        """Uzun vadeli elde tutma eşiği 180 gün."""
        assert HOLDING_PERIOD_THRESHOLD == 180

    def test_income_tax_brackets_structure(self) -> None:
        """Vergi dilimleri doğru sırada ve geçerli oranlarda."""
        prev_threshold = 0.0
        for threshold, rate in INCOME_TAX_BRACKETS:
            assert rate > 0.0
            assert rate <= 0.40
            if threshold != float("inf"):
                assert threshold > prev_threshold
                prev_threshold = threshold


# ==============================================================================
# TaxResult veri modeli testleri
# ==============================================================================


class TestTaxResult:
    """TaxResult dataclass veri modeli testleri."""

    def _make_result(
        self,
        profit: float = 10000.0,
        tax_rate: float = 0.15,
        tax: float = 1500.0,
        net_profit: float = 8500.0,
        holding_days: int = 30,
        is_long_term: bool = False,
        asset_type: str = "stock_bist",
    ) -> TaxResult:
        return TaxResult(
            profit=profit,
            tax_rate=tax_rate,
            tax=tax,
            net_profit=net_profit,
            holding_days=holding_days,
            is_long_term=is_long_term,
            asset_type=asset_type,
        )

    def test_creation_and_fields(self) -> None:
        tr = self._make_result()
        assert tr.profit == pytest.approx(10000.0)
        assert tr.tax_rate == pytest.approx(0.15)
        assert tr.asset_type == "stock_bist"

    def test_calculated_at_set(self) -> None:
        tr = self._make_result()
        assert tr.calculated_at is not None
        assert isinstance(tr.calculated_at, datetime)

    def test_to_dict(self) -> None:
        tr = self._make_result()
        d = tr.to_dict()
        assert "profit" in d
        assert "tax_rate" in d
        assert "tax" in d
        assert "net_profit" in d
        assert "calculated_at" in d

    def test_to_orjson_bytes(self) -> None:
        tr = self._make_result()
        raw = tr.to_orjson_bytes()
        assert isinstance(raw, bytes)
        parsed = orjson.loads(raw)
        assert "profit" in parsed

    def test_repr(self) -> None:
        tr = self._make_result()
        r = repr(tr)
        assert "TaxResult" in r
        assert "stock_bist" in r


# ==============================================================================
# TaxCalculator.calculate_tax() testleri
# ==============================================================================


@pytest.fixture
def tax_calc() -> TaxCalculator:
    """In-memory DuckDB ile TaxCalculator örneği."""
    return TaxCalculator(duckdb_path=":memory:")


class TestCalculateTax:
    """TaxCalculator.calculate_tax() ana hesaplama metodu testleri."""

    def test_bist_stock_zero_withholding(self, tax_calc: TaxCalculator) -> None:
        """BIST hissesi alım-satım kârı %0 stopaj → vergi sıfır."""
        result = tax_calc.calculate_tax(
            buy_price=100.0,
            sell_price=120.0,
            quantity=100,
            holding_days=30,
            asset_type="stock_bist",
        )
        assert result.tax == pytest.approx(0.0)
        assert result.tax_rate == pytest.approx(0.0)
        assert result.profit == pytest.approx(2000.0)  # (120-100) * 100
        assert result.net_profit == pytest.approx(2000.0)

    def test_bist_stock_loss_no_tax(self, tax_calc: TaxCalculator) -> None:
        """Zarar durumunda vergi doğmaz."""
        result = tax_calc.calculate_tax(
            buy_price=120.0,
            sell_price=100.0,
            quantity=100,
            holding_days=30,
            asset_type="stock_bist",
        )
        assert result.tax == pytest.approx(0.0)
        assert result.profit == pytest.approx(-2000.0)
        assert result.net_profit == pytest.approx(-2000.0)

    def test_dividend_withholding(self, tax_calc: TaxCalculator) -> None:
        """Temettü geliri %15 stopaj."""
        # Temettü hesaplamasında buy_price sıfır olamaz — bir nominal değer kullan
        result = tax_calc.calculate_tax(
            buy_price=1.0,
            sell_price=6.0,  # 5 TL temettü geliri (1 adet × 1000 adet)
            quantity=1000,
            asset_type="dividend",
        )
        assert result.tax_rate == pytest.approx(0.15)
        assert result.tax > 0.0

    def test_bond_withholding(self, tax_calc: TaxCalculator) -> None:
        """Tahvil faiz geliri %10 stopaj."""
        result = tax_calc.calculate_tax(
            buy_price=95.0,
            sell_price=100.0,
            quantity=100,
            asset_type="bond",
        )
        assert result.tax_rate == pytest.approx(0.10)

    def test_stock_foreign_declared_income(self, tax_calc: TaxCalculator) -> None:
        """Yabancı hisse senedi → gelir vergisi dilimi uygulanır."""
        result = tax_calc.calculate_tax(
            buy_price=10.0,
            sell_price=15.0,
            quantity=1000,
            asset_type="stock_foreign",
            annual_income=50000.0,
        )
        assert result.tax_rate > 0.0  # Vergi uygulanmalı
        assert result.tax > 0.0

    def test_long_term_holding_discount(self, tax_calc: TaxCalculator) -> None:
        """180+ gün elde tutma → uzun vadeli avantajı."""
        short = tax_calc.calculate_tax(
            buy_price=100.0,
            sell_price=200.0,
            quantity=100,
            holding_days=30,
            asset_type="stock_foreign",
            is_declared_income=True,
        )
        long = tax_calc.calculate_tax(
            buy_price=100.0,
            sell_price=200.0,
            quantity=100,
            holding_days=200,
            asset_type="stock_foreign",
            is_declared_income=True,
        )
        # Uzun vadede vergi matraha dahil edilecek kâr %50 olduğundan daha düşük vergi
        assert long.tax <= short.tax

    def test_is_long_term_flag(self, tax_calc: TaxCalculator) -> None:
        """180 gün eşiği doğru is_long_term değeri atar."""
        short = tax_calc.calculate_tax(buy_price=100.0, sell_price=110.0, quantity=10, holding_days=179)
        long = tax_calc.calculate_tax(buy_price=100.0, sell_price=110.0, quantity=10, holding_days=180)
        assert short.is_long_term is False
        assert long.is_long_term is True

    def test_zero_profit_no_tax(self, tax_calc: TaxCalculator) -> None:
        """Başa baş senaryoda vergi sıfırdır."""
        result = tax_calc.calculate_tax(
            buy_price=100.0,
            sell_price=100.0,
            quantity=100,
            asset_type="bond",
        )
        assert result.tax == pytest.approx(0.0)

    # --- Fail-Closed / Sayısal Guard testleri ---

    def test_zero_buy_price_invalid(self, tax_calc: TaxCalculator) -> None:
        """Sıfır alış fiyatı geçersiz parametredir."""
        result = tax_calc.calculate_tax(
            buy_price=0.0,
            sell_price=100.0,
            quantity=100,
        )
        assert result.tax_bracket == "Gecersiz Parametre"

    def test_negative_buy_price_invalid(self, tax_calc: TaxCalculator) -> None:
        result = tax_calc.calculate_tax(
            buy_price=-10.0,
            sell_price=100.0,
            quantity=100,
        )
        assert result.tax_bracket == "Gecersiz Parametre"

    def test_zero_quantity_invalid(self, tax_calc: TaxCalculator) -> None:
        result = tax_calc.calculate_tax(
            buy_price=100.0,
            sell_price=110.0,
            quantity=0,
        )
        assert result.tax_bracket == "Gecersiz Parametre"

    def test_nan_buy_price_invalid(self, tax_calc: TaxCalculator) -> None:
        result = tax_calc.calculate_tax(
            buy_price=float("nan"),
            sell_price=100.0,
            quantity=100,
        )
        assert result.tax_bracket == "Gecersiz Parametre"

    def test_inf_sell_price_invalid(self, tax_calc: TaxCalculator) -> None:
        result = tax_calc.calculate_tax(
            buy_price=100.0,
            sell_price=float("inf"),
            quantity=100,
        )
        assert result.tax_bracket == "Gecersiz Parametre"

    def test_negative_quantity_invalid(self, tax_calc: TaxCalculator) -> None:
        result = tax_calc.calculate_tax(
            buy_price=100.0,
            sell_price=110.0,
            quantity=-10,
        )
        assert result.tax_bracket == "Gecersiz Parametre"


# ==============================================================================
# TaxCalculator._get_income_tax_rate() testleri
# ==============================================================================


class TestGetIncomeTaxRate:
    """Gelir vergisi dilimi hesaplama testleri (2025-2026 dilimleri)."""

    def test_first_bracket(self, tax_calc: TaxCalculator) -> None:
        """110,000 TL altı → %15."""
        rate = tax_calc._get_income_tax_rate(50000.0)
        assert rate == pytest.approx(0.15)

    def test_second_bracket(self, tax_calc: TaxCalculator) -> None:
        """110,001 - 230,000 → %20."""
        rate = tax_calc._get_income_tax_rate(150000.0)
        assert rate == pytest.approx(0.20)

    def test_third_bracket(self, tax_calc: TaxCalculator) -> None:
        """230,001 - 580,000 → %27."""
        rate = tax_calc._get_income_tax_rate(400000.0)
        assert rate == pytest.approx(0.27)

    def test_fourth_bracket(self, tax_calc: TaxCalculator) -> None:
        """580,001 - 3,000,000 → %35."""
        rate = tax_calc._get_income_tax_rate(1000000.0)
        assert rate == pytest.approx(0.35)

    def test_fifth_bracket(self, tax_calc: TaxCalculator) -> None:
        """3,000,001 TL üzeri → %40."""
        rate = tax_calc._get_income_tax_rate(5000000.0)
        assert rate == pytest.approx(0.40)

    def test_zero_income_returns_first_bracket(self, tax_calc: TaxCalculator) -> None:
        rate = tax_calc._get_income_tax_rate(0.0)
        assert rate == pytest.approx(0.15)

    def test_negative_income_returns_first_bracket(self, tax_calc: TaxCalculator) -> None:
        rate = tax_calc._get_income_tax_rate(-5000.0)
        assert rate == pytest.approx(0.15)

    def test_nan_income_returns_first_bracket(self, tax_calc: TaxCalculator) -> None:
        rate = tax_calc._get_income_tax_rate(float("nan"))
        assert rate == pytest.approx(0.15)


# ==============================================================================
# TaxCalculator.calculate_tax_polars() testleri
# ==============================================================================


class TestCalculateTaxPolars:
    """Toplu Polars vektörize vergi hesaplama testleri."""

    def test_basic_polars_calculation(self, tax_calc: TaxCalculator) -> None:
        """Temel Polars DataFrame vergi hesabı."""
        df = pl.DataFrame({
            "buy_price": [100.0, 95.0, 200.0],
            "sell_price": [120.0, 90.0, 250.0],
            "quantity": [100, 100, 50],
            "holding_days": [30, 30, 200],
            "asset_type": ["stock_bist", "dividend", "bond"],
        })
        result = tax_calc.calculate_tax_polars(df)
        assert isinstance(result, pl.DataFrame)
        assert "profit" in result.columns
        assert "tax_rate" in result.columns
        assert "tax" in result.columns
        assert "net_profit" in result.columns
        assert len(result) == 3

    def test_missing_required_columns_returns_empty(self, tax_calc: TaxCalculator) -> None:
        """Gerekli sütunlar eksikse boş DataFrame döner."""
        df = pl.DataFrame({"random_col": [1.0, 2.0]})
        result = tax_calc.calculate_tax_polars(df)
        assert result.is_empty() or len(result) == 0

    def test_empty_dataframe_returns_empty(self, tax_calc: TaxCalculator) -> None:
        """Boş DataFrame boş sonuç döner."""
        df = pl.DataFrame({
            "buy_price": pl.Series([], dtype=pl.Float64),
            "sell_price": pl.Series([], dtype=pl.Float64),
            "quantity": pl.Series([], dtype=pl.Float64),
        })
        result = tax_calc.calculate_tax_polars(df)
        assert result.is_empty()

    def test_bist_stock_zero_tax_polars(self, tax_calc: TaxCalculator) -> None:
        """BIST hisse senetleri Polars hesabında %0 vergi."""
        df = pl.DataFrame({
            "buy_price": [100.0, 100.0],
            "sell_price": [120.0, 120.0],
            "quantity": [100, 100],
            "asset_type": ["stock_bist", "stock_bist"],
        })
        result = tax_calc.calculate_tax_polars(df)
        assert result["tax_rate"].to_list() == [0.0, 0.0]

    def test_loss_produces_zero_tax_polars(self, tax_calc: TaxCalculator) -> None:
        """Zarar işlemlerinde Polars hesabında vergi sıfır."""
        df = pl.DataFrame({
            "buy_price": [120.0],
            "sell_price": [100.0],
            "quantity": [100],
        })
        result = tax_calc.calculate_tax_polars(df)
        assert result["tax"][0] == pytest.approx(0.0)

    def test_default_asset_type_applied(self, tax_calc: TaxCalculator) -> None:
        """asset_type sütunu yoksa varsayılan 'stock_bist' uygulanır."""
        df = pl.DataFrame({
            "buy_price": [100.0],
            "sell_price": [110.0],
            "quantity": [100],
        })
        result = tax_calc.calculate_tax_polars(df)
        assert "asset_type" in result.columns
        assert result["asset_type"][0] == "stock_bist"


# ==============================================================================
# DuckDB denetim kaydı testleri
# ==============================================================================


class TestDuckDBAudit:
    """DuckDB vergi denetim kaydı testleri."""

    def test_audit_record_inserted(self) -> None:
        """Hesaplama sonrası DuckDB'ye kayıt eklenir."""
        calc = TaxCalculator(duckdb_path=":memory:")
        calc.calculate_tax(
            buy_price=100.0,
            sell_price=120.0,
            quantity=100,
            asset_type="dividend",
        )
        audit_df = calc.export_tax_audit_to_polars()
        assert isinstance(audit_df, pl.DataFrame)
        assert len(audit_df) >= 1

    def test_audit_record_has_correct_fields(self) -> None:
        """Denetim kaydı beklenen sütunları içerir."""
        calc = TaxCalculator(duckdb_path=":memory:")
        calc.calculate_tax(buy_price=100.0, sell_price=130.0, quantity=50, asset_type="bond")
        audit_df = calc.export_tax_audit_to_polars()
        expected_cols = {"asset_type", "buy_price", "sell_price", "quantity", "profit", "tax"}
        assert expected_cols.issubset(set(audit_df.columns))

    def test_loss_also_audited(self) -> None:
        """Zarar işlemleri de denetim kaydına eklenir."""
        calc = TaxCalculator(duckdb_path=":memory:")
        calc.calculate_tax(buy_price=120.0, sell_price=100.0, quantity=100)
        audit_df = calc.export_tax_audit_to_polars()
        assert len(audit_df) >= 1

    def test_invalid_params_not_audited(self) -> None:
        """Geçersiz parametre içeren hesaplamalar audit'e eklenmez."""
        calc = TaxCalculator(duckdb_path=":memory:")
        calc.calculate_tax(buy_price=0.0, sell_price=100.0, quantity=100)
        audit_df = calc.export_tax_audit_to_polars()
        # Geçersiz hesaplama audit'e kaydedilmez
        assert len(audit_df) == 0


# ==============================================================================
# Uçtan uca senaryo testleri
# ==============================================================================


class TestEndToEndScenarios:
    """Gerçek BIST yatırımcısı senaryolarını kapsayan testler."""

    def test_bist_stock_trader_scenario(self, tax_calc: TaxCalculator) -> None:
        """Tipik BIST hisse yatırımcısı: kâr sıfır vergidir."""
        result = tax_calc.calculate_tax(
            buy_price=50.0,
            sell_price=75.0,
            quantity=500,
            holding_days=90,
            asset_type="stock_bist",
        )
        assert result.profit == pytest.approx(12500.0)
        assert result.tax == pytest.approx(0.0)
        assert result.net_profit == pytest.approx(12500.0)

    def test_dividend_investor_scenario(self, tax_calc: TaxCalculator) -> None:
        """Temettü yatırımcısı: %15 stopaj düşülür."""
        result = tax_calc.calculate_tax(
            buy_price=1.0,
            sell_price=6.0,  # 5 TL temettü geliri (1 adet)
            quantity=10000,
            asset_type="dividend",
        )
        assert result.tax_rate == pytest.approx(0.15)
        assert result.tax > 0.0
        assert result.net_profit < result.profit

    def test_portfolio_of_mixed_assets(self, tax_calc: TaxCalculator) -> None:
        """Karma portföy: birden fazla varlık tipi."""
        df = pl.DataFrame({
            "buy_price": [100.0, 95.0, 1000.0],
            "sell_price": [120.0, 105.0, 980.0],
            "quantity": [1000, 500, 10],
            "asset_type": ["stock_bist", "bond", "stock_bist"],
            "holding_days": [90, 180, 30],
        })
        result = tax_calc.calculate_tax_polars(df)
        assert len(result) == 3
        # BIST hisse kârları → sıfır vergi
        bist_rows = result.filter(pl.col("asset_type") == "stock_bist")
        assert all(v == 0.0 for v in bist_rows["tax_rate"].to_list())

    def test_large_portfolio_performance(self, tax_calc: TaxCalculator) -> None:
        """1000 işlemlik büyük portföyde Polars performansı."""
        import random
        random.seed(42)
        n = 1000
        df = pl.DataFrame({
            "buy_price": [random.uniform(10, 500) for _ in range(n)],
            "sell_price": [random.uniform(10, 600) for _ in range(n)],
            "quantity": [random.randint(1, 1000) for _ in range(n)],
            "asset_type": ["stock_bist"] * n,
        })
        result = tax_calc.calculate_tax_polars(df)
        assert len(result) == n
        assert "profit" in result.columns
