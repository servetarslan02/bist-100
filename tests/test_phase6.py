"""
ALPHA BIST — FAZ 6 Test Suite

Scenario Engine, Stress Test Engine testleri.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_scenario_engine():
    """Scenario Engine testleri."""
    from services.intelligence.scenario import (
        scenario_engine, ScenarioInput, PREDEFINED_SCENARIOS,
    )
    from services.intelligence.macro_sensitivity import macro_sensitivity_engine

    passed = 0
    failed = 0

    positions = [
        {"ticker": "THYAO", "sector": "AVIATION", "value": 10000, "price": 305},
        {"ticker": "AKBNK", "sector": "BANK", "value": 8000, "price": 45},
        {"ticker": "TUPRS", "sector": "ENERGY", "value": 7000, "price": 180},
        {"ticker": "ASELS", "sector": "TECH", "value": 5000, "price": 380},
    ]

    # 1. Basic scenario
    scenario = ScenarioInput(name="Test", usdtry_change=0.10, bist_change=-0.05)
    result = scenario_engine.run_scenario(scenario, positions, macro_sensitivity_engine)
    assert result.portfolio_impact_pct != 0
    assert len(result.asset_impacts) == 4
    assert len(result.sector_impacts) > 0
    passed += 1
    print(f"  ✓ Basic scenario (impact: {result.portfolio_impact_pct:.2f}%)")

    # 2. Predefined scenarios
    zero_count = 0
    for name, scenario in PREDEFINED_SCENARIOS.items():
        result = scenario_engine.run_scenario(scenario, positions, macro_sensitivity_engine)
        if result.portfolio_impact_pct == 0:
            zero_count += 1
    # Çoğu senaryo etki üretmeli
    assert zero_count < len(PREDEFINED_SCENARIOS) / 2
    passed += 1
    print(f"  ✓ {len(PREDEFINED_SCENARIOS)} predefined scenarios ({zero_count} zero impact)")

    # 3. THYAO en çok etkilenmeli (USDTRY + petrol)
    scenario = ScenarioInput(name="FX+Oil", usdtry_change=0.10, oil_change=0.20)
    result = scenario_engine.run_scenario(scenario, positions, macro_sensitivity_engine)
    thyao_impact = [a for a in result.asset_impacts if a.ticker == "THYAO"][0]
    asels_impact = [a for a in result.asset_impacts if a.ticker == "ASELS"][0]
    # THYAO (AVIATION) ASELS'ten (TECH) daha çok etkilenmeli
    assert thyao_impact.estimated_impact_pct < asels_impact.estimated_impact_pct
    passed += 1
    print(f"  ✓ THYAO most affected (THYAO={thyao_impact.estimated_impact_pct:.1f}%, ASELS={asels_impact.estimated_impact_pct:.1f}%)")

    # 4. Sektör etkileri
    assert "AVIATION" in result.sector_impacts
    assert "BANK" in result.sector_impacts
    passed += 1
    print(f"  ✓ Sector impacts: {result.sector_impacts}")

    # 5. Stress test
    stress_results = scenario_engine.run_stress_test(
        positions, PREDEFINED_SCENARIOS, macro_sensitivity_engine
    )
    assert len(stress_results) == len(PREDEFINED_SCENARIOS)
    worst = min(stress_results, key=lambda r: r.portfolio_loss_pct)
    assert worst.portfolio_loss_pct < 0
    passed += 1
    print(f"  ✓ Stress test ({len(stress_results)} scenarios, worst: {worst.scenario_name})")

    # 6. Breaking point
    bp = scenario_engine.find_breaking_point(
        positions, "usdtry_change", max_change=2.0, loss_threshold_pct=20.0,
        sector_sensitivity=macro_sensitivity_engine,
    )
    assert bp.breaking_value > 0
    assert bp.change_pct > 0
    passed += 1
    print(f"  ✓ Breaking point: {bp.description}")

    # 7. Empty positions
    empty_result = scenario_engine.run_scenario(
        ScenarioInput(name="Empty"), [], macro_sensitivity_engine
    )
    assert empty_result.portfolio_impact_pct == 0
    passed += 1
    print("  ✓ Empty positions handled")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 6 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    print(f"\n--- Scenario Engine ---")
    try:
        p, f = test_scenario_engine()
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
