"""
ALPHA BIST — FAZ 4 Test Suite

Valuation Engine (Multiples, DCF, Scenarios) testleri.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_valuation_engine():
    """Valuation Engine testleri."""
    from services.intelligence.valuation.engine import valuation_engine

    passed = 0
    failed = 0

    # 1. Multiples valuation
    company = {"pe": 8.5, "pb": 1.4, "ev_ebitda": 5.1}
    sector = {
        "pe": {"median": 11.0, "avg": 12.5},
        "pb": {"median": 1.8, "avg": 2.0},
        "ev_ebitda": {"median": 7.0, "avg": 7.5},
    }
    multiples = valuation_engine.compute_multiples_valuation(
        "THYAO", 305.25, company, sector
    )
    assert len(multiples) == 3
    pe_result = [m for m in multiples if m.metric == "PE"][0]
    assert pe_result.company_value == 8.5
    assert pe_result.sector_median == 11.0
    assert pe_result.upside_pct > 0  # P/E 8.5 vs sektör 11 → upside
    passed += 1
    print(f"  ✓ Multiples valuation (P/E upside: {pe_result.upside_pct:.1f}%)")

    # 2. DCF (gerçekçi verilerle)
    dcf = valuation_engine.compute_dcf(
        ticker="THYAO",
        current_price=305.25,
        revenue_forecast=[60e9, 70e9, 80e9, 90e9, 100e9],
        margin_forecast=[0.10, 0.11, 0.12, 0.12, 0.13],
        capex_forecast=[2e9, 2.5e9, 3e9, 3.5e9, 4e9],
        wc_change_forecast=[0.5e9, 0.5e9, 0.5e9, 0.5e9, 0.5e9],
        shares_outstanding=1_373_278_203,
        total_debt=5e9,   # Daha düşük borç
        total_cash=10e9,  # Yüksek nakit
    )
    assert dcf.implied_price > 0
    assert dcf.enterprise_value > 0
    assert dcf.equity_value > 0
    assert len(dcf.pv_fcfs) == 5
    assert dcf.terminal_value > 0
    assert len(dcf.sensitivity_table) > 0
    passed += 1
    print(f"  ✓ DCF (implied: {dcf.implied_price:.2f}, upside: {dcf.upside_pct:.1f}%)")

    # 3. Valuation scenarios
    scenarios = valuation_engine.compute_valuation_scenarios(
        ticker="THYAO",
        current_price=305.25,
        base_assumptions={"revenue_growth": 0.10, "margin": 0.12, "wacc": 0.20, "terminal_growth": 0.03, "base_revenue": 60e9},
        bear_adjustments={"revenue_growth": -0.05, "margin": -0.03, "wacc": 0.03},
        bull_adjustments={"revenue_growth": 0.05, "margin": 0.03, "wacc": -0.02},
        shares_outstanding=1_373_278_203,
        total_debt=5e9,
        total_cash=10e9,
    )
    assert len(scenarios) == 3
    bear = [s for s in scenarios if s.name == "BEAR"][0]
    base = [s for s in scenarios if s.name == "BASE"][0]
    bull = [s for s in scenarios if s.name == "BULL"][0]
    assert bear.implied_price < base.implied_price < bull.implied_price
    assert bear.probability == 0.25
    assert base.probability == 0.50
    assert bull.probability == 0.25
    passed += 1
    print(f"  ✓ Scenarios (Bear: {bear.implied_price:.0f}, Base: {base.implied_price:.0f}, Bull: {bull.implied_price:.0f})")

    # 4. Expected value
    ev = valuation_engine.compute_expected_value(scenarios)
    assert ev > 0
    assert bear.implied_price < ev < bull.implied_price
    passed += 1
    print(f"  ✓ Expected value: {ev:.2f}")

    # 5. Valuation summary
    summary = valuation_engine.compute_valuation_summary(
        "THYAO", 305.25, multiples, dcf, scenarios
    )
    assert summary.ticker == "THYAO"
    assert summary.current_price == 305.25
    assert summary.overall_view in ["UNDERVALUED", "FAIR", "OVERVALUED"]
    assert summary.expected_value > 0
    passed += 1
    print(f"  ✓ Valuation summary: {summary.overall_view} (upside: {summary.overall_upside_pct:.1f}%)")

    # 6. Negative DCF (wacc < terminal_growth → edge case)
    dcf2 = valuation_engine.compute_dcf(
        ticker="TEST", current_price=100,
        revenue_forecast=[100e6], margin_forecast=[0.10],
        capex_forecast=[0], wc_change_forecast=[0],
        shares_outstanding=1000000,
        wacc=0.02, terminal_growth=0.05,  # wacc < tg
    )
    assert dcf2.terminal_value == 0  # Edge case: wacc < tg
    passed += 1
    print("  ✓ DCF edge case (wacc < terminal_growth)")

    # 7. Empty multiples
    empty_multiples = valuation_engine.compute_multiples_valuation("TEST", 100, {}, {})
    assert len(empty_multiples) == 0
    passed += 1
    print("  ✓ Empty multiples handled")

    return passed, failed


def test_fundamental_integration():
    """Fundamental Provider + Valuation Engine entegrasyon."""
    from services.ingestion.providers.fundamental_provider import fundamental_provider
    from services.intelligence.valuation.engine import valuation_engine

    passed = 0
    failed = 0

    # 1. THYAO gerçek veri ile değerleme
    fund = fundamental_provider.fetch_fundamentals("THYAO")
    if fund and fund.get("price", 0) > 0:
        price = fund["price"]

        # Multiples
        company = {}
        if fund.get("pe_ratio") and fund["pe_ratio"] > 0:
            company["pe"] = fund["pe_ratio"]
        if fund.get("pb_ratio") and fund["pb_ratio"] > 0:
            company["pb"] = fund["pb_ratio"]
        if fund.get("ev_ebitda") and fund["ev_ebitda"] > 0:
            company["ev_ebitda"] = fund["ev_ebitda"]

        # Sektör varsayılanları (gerçek sektör verisi daha sonra)
        sector = {
            "pe": {"median": 11.0, "avg": 12.5},
            "pb": {"median": 1.8, "avg": 2.0},
            "ev_ebitda": {"median": 7.0, "avg": 7.5},
        }

        multiples = valuation_engine.compute_multiples_valuation("THYAO", price, company, sector)
        assert len(multiples) > 0
        passed += 1
        print(f"  ✓ THYAO multiples: {len(multiples)} metrics")

        # Scenarios
        scenarios = valuation_engine.compute_valuation_scenarios(
            ticker="THYAO",
            current_price=price,
            base_assumptions={"revenue_growth": 0.15, "margin": 0.10, "wacc": 0.20, "terminal_growth": 0.03, "base_revenue": 6e9},
            bear_adjustments={"revenue_growth": -0.05, "margin": -0.03, "wacc": 0.03},
            bull_adjustments={"revenue_growth": 0.05, "margin": 0.03, "wacc": -0.02},
            shares_outstanding=fund.get("shares_outstanding", 1_373_278_203) or 1_373_278_203,
            total_debt=fund.get("total_debt", 0) or 0,
            total_cash=fund.get("total_cash", 0) or 0,
        )
        assert len(scenarios) == 3
        passed += 1
        print(f"  ✓ THYAO scenarios: Bear={scenarios[0].implied_price:.0f}, Base={scenarios[1].implied_price:.0f}, Bull={scenarios[2].implied_price:.0f}")
    else:
        failed += 2
        print("  ✗ THYAO fundamental data not available")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 4 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Valuation Engine", test_valuation_engine),
        ("Fundamental Integration", test_fundamental_integration),
    ]

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            print(f"  ✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            total_failed += 1

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
