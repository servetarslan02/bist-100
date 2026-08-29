from typing import Any
"""Bölüm 23 — BIST Piyasa Kuralları Testleri."""

import pytest

from services.core.compliance import ComplianceChecker
from services.core.fee_calculator import FeeCalculator
from services.core.gross_settlement import GrossSettlementMonitor
from services.core.halt_monitor import HaltMonitor
from services.core.price_limits import PriceLimitMonitor
from services.core.short_selling import ShortSellingMonitor
from services.core.viop_monitor import VIOPMonitor


class TestShortSelling:
    """Otomatik eklendi."""
    def test_non_bist30_rejected(self) -> Any:
        """Otomatik eklendi."""
        m = ShortSellingMonitor()
        m._bist30_cache = ["THYAO", "GARAN", "AKBNK"]
        r = m.can_short_sell("ASELS")
        assert not r.allowed
        assert "BIST-30" in r.reason

    def test_bist30_allowed(self) -> Any:
        """Otomatik eklendi."""
        m = ShortSellingMonitor()
        m._bist30_cache = ["THYAO", "GARAN"]
        r = m.can_short_sell("THYAO", 300, 295)
        assert r.allowed

    def test_uptick_rule(self) -> Any:
        """Otomatik eklendi."""
        m = ShortSellingMonitor()
        m._bist30_cache = ["THYAO"]
        r = m.can_short_sell("THYAO", 290, 300)
        assert not r.allowed
        assert "Uptick" in r.reason

    def test_gross_settlement_blocked(self) -> Any:
        """Otomatik eklendi."""
        m = ShortSellingMonitor()
        m._bist30_cache = ["THYAO"]
        m.set_gross_settlement(["THYAO"])
        r = m.can_short_sell("THYAO")
        assert not r.allowed
        assert "brüt" in r.reason

    def test_spk_banned(self) -> Any:
        """Otomatik eklendi."""
        m = ShortSellingMonitor()
        m._bist30_cache = ["THYAO"]
        m.set_spk_banned(["THYAO"])
        r = m.can_short_sell("THYAO")
        assert not r.allowed
        assert "SPK" in r.reason


class TestFeeCalculator:
    """Otomatik eklendi."""
    def test_basic_fee(self) -> Any:
        """Otomatik eklendi."""
        c = FeeCalculator(broker_rate=0.0003)
        f = c.calculate(100000)
        assert f.broker_fee == pytest.approx(30.0, abs=0.01)
        assert f.bist_fee > 0
        assert f.mkk_fee > 0
        assert f.bsmv > 0
        assert f.total > f.broker_fee

    def test_minimum_commission(self) -> Any:
        """Otomatik eklendi."""
        c = FeeCalculator(broker_rate=0.0003)
        f = c.calculate(100)  # Çok küçük tutar
        assert f.broker_fee >= 1.0  # Minimum ₺1

    def test_zero_amount(self) -> Any:
        """Otomatik eklendi."""
        c = FeeCalculator()
        f = c.calculate(0)
        assert f.total == 0

    def test_negative_amount(self) -> Any:
        """Otomatik eklendi."""
        c = FeeCalculator()
        f = c.calculate(-100)
        assert f.total == 0

    def test_fee_structure(self) -> Any:
        """Otomatik eklendi."""
        c = FeeCalculator()
        f = c.calculate(1000000)
        d = f.to_dict()
        assert "broker_fee" in d
        assert "bist_fee" in d
        assert "mkk_fee" in d
        assert "bsmv" in d
        assert "total" in d


class TestPriceLimits:
    """Otomatik eklendi."""
    def test_no_limit_hit(self) -> Any:
        """Otomatik eklendi."""
        m = PriceLimitMonitor()
        r = m.check_price_limit("THYAO", 105, 100)
        assert not r.limit_hit

    @pytest.mark.parametrize(
        "price,expected_direction",
        [
            (110, "UP"),
            (90, "DOWN"),
        ],
    )
    def test_price_limit_hit_direction(self, price, expected_direction) -> Any:
        """Otomatik eklendi."""
        m = PriceLimitMonitor()
        r = m.check_price_limit("THYAO", price, 100)
        assert r.limit_hit
        assert r.direction == expected_direction

    def test_custom_limit(self) -> Any:
        """Otomatik eklendi."""
        m = PriceLimitMonitor()
        m.set_custom_limit("VOLATIL", 5.0)
        r = m.check_price_limit("VOLATIL", 104, 100)
        assert not r.limit_hit  # %4 < %5 limit
        r2 = m.check_price_limit("VOLATIL", 106, 100)
        assert r2.limit_hit  # %6 > %5 limit

    def test_zero_price(self) -> Any:
        """Otomatik eklendi."""
        m = PriceLimitMonitor()
        r = m.check_price_limit("THYAO", 0, 100)
        assert not r.limit_hit


class TestHaltMonitor:
    """Otomatik eklendi."""
    def test_not_halted(self) -> Any:
        """Otomatik eklendi."""
        m = HaltMonitor()
        r = m.check_halt("THYAO")
        assert not r.halted

    def test_halted(self) -> Any:
        """Otomatik eklendi."""
        m = HaltMonitor()
        m.add_halt("THYAO", "KAP açıklaması", "KAP")
        r = m.check_halt("THYAO")
        assert r.halted
        assert "KAP" in r.reason

    def test_remove_halt(self) -> Any:
        """Otomatik eklendi."""
        m = HaltMonitor()
        m.add_halt("THYAO", "test")
        m.remove_halt("THYAO")
        assert not m.is_halted("THYAO")

    def test_get_all_halted(self) -> Any:
        """Otomatik eklendi."""
        m = HaltMonitor()
        m.add_halt("A", "test1")
        m.add_halt("B", "test2")
        assert len(m.get_all_halted()) == 2


class TestGrossSettlement:
    """Otomatik eklendi."""
    def test_not_gross(self) -> Any:
        """Otomatik eklendi."""
        m = GrossSettlementMonitor()
        r = m.check_gross_settlement("THYAO")
        assert not r.is_gross

    def test_gross(self) -> Any:
        """Otomatik eklendi."""
        m = GrossSettlementMonitor()
        m.set_gross_tickers(["THYAO"])
        r = m.check_gross_settlement("THYAO")
        assert r.is_gross
        assert "NO_SHORT_SELL" in r.effect

    def test_add_remove(self) -> Any:
        """Otomatik eklendi."""
        m = GrossSettlementMonitor()
        m.add_gross_ticker("X")
        assert "X" in m.get_all_gross()
        m.remove_gross_ticker("X")
        assert "X" not in m.get_all_gross()


class TestVIOPMonitor:
    """Otomatik eklendi."""
    def test_no_margin_call(self) -> Any:
        """Otomatik eklendi."""
        m = VIOPMonitor()
        r = m.check_viop_margin(100000, 50000)
        assert not r.margin_call
        assert r.action == "OK"

    def test_margin_call(self) -> Any:
        """Otomatik eklendi."""
        m = VIOPMonitor()
        r = m.check_viop_margin(100000, 5000)  # Çok düşük teminat
        assert r.margin_call
        assert r.action == "MARGIN_CALL"

    def test_custom_margin_rate(self) -> Any:
        """Otomatik eklendi."""
        m = VIOPMonitor()
        m.set_margin_rate("XU030", 0.20)
        r = m.check_viop_margin(100000, 15000, "XU030")
        assert r.margin_call  # %15 < %20

    def test_zero_position(self) -> Any:
        """Otomatik eklendi."""
        m = VIOPMonitor()
        r = m.check_viop_margin(0, 50000)
        assert not r.margin_call


class TestCompliance:
    """Otomatik eklendi."""
    @pytest.mark.parametrize(
        "amount,expected_action,expected_flag",
        [
            (10000, "OK", None),
            (60000, "NOTIFY", "notification_required"),
            (110000, "BLOCK", "violation"),
        ],
    )
    def test_spk_compliance_thresholds(self, amount, expected_action, expected_flag) -> Any:
        """Otomatik eklendi."""
        c = ComplianceChecker()
        r = c.check_spk_compliance("BUY", "THYAO", amount, 1000000, 0)
        assert r.action == expected_action
        if expected_flag:
            assert getattr(r, expected_flag)
        else:
            assert not r.notification_required and not r.violation

    def test_zero_portfolio(self) -> Any:
        """Otomatik eklendi."""
        c = ComplianceChecker()
        r = c.check_spk_compliance("BUY", "THYAO", 10000, 0, 0)
        assert r.action == "OK"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
