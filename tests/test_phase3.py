import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — FAZ 3 Test Suite

World State, Regime Engine, Macro Sensitivity testleri.
"""

import sys


def test_world_state() -> Any:
    """World State testleri."""
    from services.intelligence.world_state import WorldStateManager

    passed = 0
    failed = 0

    wsm = WorldStateManager()

    # 1. Başlangıç değerleri 0.5
    state = wsm.current_state
    assert state.global_risk_appetite == 0.5
    assert state.usd_strength == 0.5
    passed += 1
    logger.info("  ✓ Başlangıç değerleri 0.5")

    # 2. Event update
    delta = wsm.update_from_event("FED_RATE_HIKE", {})
    assert len(delta) > 0
    assert wsm.current_state.us_rate_pressure > 0.5
    passed += 1
    logger.info("  ✓ Event update")

    # 3. Decay
    state.global_risk_appetite = 0.8
    state.apply_decay(1)  # 1 saat
    assert 0.7 < state.global_risk_appetite < 0.8
    passed += 1
    logger.info("  ✓ Decay")

    # 4. VIX normalize (0-1 state ile karışmamalı)
    state.vix_level = 35.0
    vec = state.to_vector()
    assert abs(vec[8] - 0.35) < 0.01  # 35/100 = 0.35
    passed += 1
    logger.info("  ✓ VIX normalize")

    # 5. Invariant (0-1 arası)
    vec = state.to_vector()
    vec[0] = 1.5  # Geçersiz
    state.from_vector(vec)
    assert state.global_risk_appetite <= 1.0
    passed += 1
    logger.info("  ✓ Invariant (clamp)")

    # 6. Macro update
    wsm.update_from_macro(
        {
            "USD/TRY": {"price": 48.0},
            "VIX": {"price": 18.0},
            "Oil": {"change_pct": 5.0},
        }
    )
    state = wsm.current_state
    assert state.vix_level == 18.0
    passed += 1
    logger.info("  ✓ Macro update")

    # 7. State dict
    d = wsm.get_state_dict()
    assert "global_risk_appetite" in d
    assert "usd_strength" in d
    passed += 1
    logger.info("  ✓ State dict")

    # 8. State vector
    v = wsm.get_state_vector()
    assert len(v) == 10
    passed += 1
    logger.info("  ✓ State vector")

    return passed, failed


def test_regime_engine() -> Any:
    """Regime Engine testleri."""
    from services.intelligence.regime import Regime, regime_engine

    passed = 0
    failed = 0

    # 1. Bull regime
    features = {
        "breadth_pct": 72,
        "momentum_avg": 8,
        "volatility_avg": 18,
        "rsi_avg": 65,
        "risk_appetite": 0.75,
        "usdtry_momentum": 1,
        "vix_level": 12,
        "global_momentum": 3,
    }
    result = regime_engine.detect_regime(features)
    assert result.regime in [Regime.BULL, Regime.RISK_ON, Regime.MOMENTUM_EXPANSION], f"Got: {result.regime}"
    assert result.confidence >= 0  # 0 olabilir (eşit rejimler)
    passed += 1
    logger.info(f"  ✓ Bull detection: {result.regime.value} (confidence={result.confidence})")

    # 2. Bear regime
    features = {
        "breadth_pct": 25,
        "momentum_avg": -8,
        "volatility_avg": 35,
        "rsi_avg": 30,
        "risk_appetite": 0.25,
        "usdtry_momentum": 8,
        "vix_level": 30,
        "global_momentum": -5,
    }
    result = regime_engine.detect_regime(features)
    assert result.regime in [Regime.BEAR, Regime.RISK_OFF, Regime.CRISIS, Regime.MOMENTUM_CONTRACTION], (
        f"Got: {result.regime}"
    )
    passed += 1
    logger.info(f"  ✓ Bear detection: {result.regime.value}")

    # 3. Crisis regime
    features = {
        "breadth_pct": 15,
        "momentum_avg": -15,
        "volatility_avg": 50,
        "rsi_avg": 20,
        "risk_appetite": 0.15,
        "usdtry_momentum": 15,
        "vix_level": 45,
        "global_momentum": -10,
    }
    result = regime_engine.detect_regime(features)
    assert result.regime in [Regime.CRISIS, Regime.BEAR], f"Got: {result.regime}"
    passed += 1
    logger.info(f"  ✓ Crisis detection: {result.regime.value}")

    # 4. Sideways regime
    features = {
        "breadth_pct": 50,
        "momentum_avg": 0.5,
        "volatility_avg": 18,
        "rsi_avg": 50,
        "risk_appetite": 0.5,
        "usdtry_momentum": 0,
        "vix_level": 15,
        "global_momentum": 0,
    }
    result = regime_engine.detect_regime(features)
    assert result.regime in [Regime.SIDEWAYS, Regime.LOW_VOLATILITY], f"Got: {result.regime}"
    passed += 1
    logger.info(f"  ✓ Sideways detection: {result.regime.value}")

    # 5. Regime weights
    weights = regime_engine.get_regime_weights(Regime.BULL)
    assert weights.get("momentum", 0) > weights.get("defensive", 0)
    weights = regime_engine.get_regime_weights(Regime.CRISIS)
    assert weights.get("defensive", 0) > weights.get("momentum", 0)
    passed += 1
    logger.info("  ✓ Regime weights")

    # 6. Transition matrix
    matrix = regime_engine.get_transition_matrix()
    assert isinstance(matrix, dict)
    passed += 1
    logger.info("  ✓ Transition matrix")

    # 7. History
    history = regime_engine.get_history()
    assert len(history) >= 4
    passed += 1
    logger.info(f"  ✓ History ({len(history)} entries)")

    return passed, failed


def test_macro_sensitivity() -> Any:
    """Macro Sensitivity testleri."""
    from services.intelligence.macro_sensitivity import macro_sensitivity_engine

    passed = 0
    failed = 0

    # 1. Sector sensitivity
    bank_sens = macro_sensitivity_engine.get_sector_sensitivity("BANK")
    assert bank_sens.get("interest_rate", 0) > 0.7
    assert bank_sens.get("usdtry", 0) < bank_sens.get("interest_rate", 0)
    passed += 1
    logger.info("  ✓ Bank sector sensitivity")

    # 2. Aviation sensitivity (negatif değerler = şirket için olumsuz)
    avia_sens = macro_sensitivity_engine.get_sector_sensitivity("AVIATION")
    assert abs(avia_sens.get("oil", 0)) > 0.7  # |−0.9| > 0.7
    assert abs(avia_sens.get("usdtry", 0)) > 0.5  # |−0.8| > 0.5
    assert avia_sens.get("oil", 0) < 0  # Petrol artışı havacılık için negatif
    passed += 1
    logger.info("  ✓ Aviation sector sensitivity")

    # 3. Macro impact calculation
    impact = macro_sensitivity_engine.compute_macro_impact(
        "THYAO", "AVIATION", {"usdtry_change": 0.10, "oil_change": 0.20}
    )
    assert impact.get("usdtry_impact", 0) < 0  # USDTRY artış = negatif (yakıt maliyeti)
    assert impact.get("oil_impact", 0) < 0  # Petrol artış = negatif
    assert impact.get("total_macro_impact", 0) < 0
    passed += 1
    logger.info(f"  ✓ THYAO macro impact: {impact.get('total_macro_impact')}")

    # 4. Bank interest rate sensitivity
    impact = macro_sensitivity_engine.compute_macro_impact("AKBNK", "BANK", {"interest_rate_change": 0.05})
    assert impact.get("interest_rate_impact", 0) > 0  # Faiz artışı = bankalar için pozitif
    passed += 1
    logger.info(f"  ✓ AKBNK interest impact: {impact.get('interest_rate_impact')}")

    # 5. Scenario impact
    impact = macro_sensitivity_engine.compute_scenario_impact("THYAO", "AVIATION", "OIL_SHOCK_20_PCT")
    assert impact.get("oil_impact", 0) < 0
    passed += 1
    logger.info(f"  ✓ Oil shock scenario: {impact.get('oil_impact')}")

    # 6. Company override
    macro_sensitivity_engine.set_company_sensitivity("CUSTOM", {"usdtry": 0.99, "interest_rate": 0.01})
    sens = macro_sensitivity_engine.get_company_sensitivity("CUSTOM", "BANK")
    assert sens.get("usdtry") == 0.99
    passed += 1
    logger.info("  ✓ Company sensitivity override")

    # 7. Unknown sector fallback
    sens = macro_sensitivity_engine.get_sector_sensitivity("UNKNOWN_SECTOR")
    assert sens == macro_sensitivity_engine.get_sector_sensitivity("OTHER")
    passed += 1
    logger.info("  ✓ Unknown sector fallback")

    return passed, failed


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("  FAZ 3 — Test Suite")
    logger.info("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("World State", test_world_state),
        ("Regime Engine", test_regime_engine),
        ("Macro Sensitivity", test_macro_sensitivity),
    ]

    for name, test_func in tests:
        logger.info(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            logger.info(f"  ✗ Test crashed: {e}")
            import traceback

            traceback.print_exc()
            total_failed += 1

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    logger.info(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
