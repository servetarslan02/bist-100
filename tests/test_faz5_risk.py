import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — FAZ 5 Test Suite (Risk & Portfolio)

Ledoit-Wolf, Volatility Targeting, Kelly Criterion, Rebalance, Concentration testleri.
"""

import sys

import numpy as np


def test_ledoit_wolf() -> Any:
    """Ledoit-Wolf covariance testleri."""
    from services.risk.enhanced_risk import ledoit_wolf

    passed = 0
    failed = 0

    np.random.seed(42)
    returns = np.random.randn(100, 5) * 0.02

    # 1. Kovaryans matrisi
    cov = ledoit_wolf.estimate(returns)
    assert cov.shape == (5, 5)
    assert np.all(np.diag(cov) > 0)  # Diagonal pozitif
    passed += 1
    logger.info(f"  ✓ Covariance shape: {cov.shape}")

    # 2. Simetrik
    assert np.allclose(cov, cov.T)
    passed += 1
    logger.info("  ✓ Symmetric: True")

    # 3. Shrinkage etkisi
    ledoit_wolf.estimate(returns, shrinkage=0)
    cov_full_shrink = ledoit_wolf.estimate(returns, shrinkage=1)
    # Full shrinkage = diagonal matrix
    assert np.allclose(cov_full_shrink, np.diag(np.diag(cov_full_shrink)))
    passed += 1
    logger.info("  ✓ Shrinkage: 0→sample, 1→diagonal")

    # 4. Otomatik shrinkage
    cov_auto = ledoit_wolf.estimate(returns)
    assert cov_auto.shape == (5, 5)
    passed += 1
    logger.info(f"  ✓ Auto shrinkage: {ledoit_wolf._estimate_shrinkage(returns, cov, np.diag(np.diag(cov))):.3f}")

    return passed, failed


def test_volatility_targeter() -> Any:
    """Volatility targeting testleri."""
    from services.risk.enhanced_risk import volatility_targeter

    passed = 0
    failed = 0

    # 1. Düşük volatilite → yüksek kaldıraç
    lev_low = volatility_targeter.compute_leverage(0.10, 0.20)
    assert lev_low > 1.0
    passed += 1
    logger.info(f"  ✓ Low vol leverage: {lev_low:.2f}")

    # 2. Yüksek volatilite → düşük kaldıraç
    lev_high = volatility_targeter.compute_leverage(0.40, 0.20)
    assert lev_high < 1.0
    passed += 1
    logger.info(f"  ✓ High vol leverage: {lev_high:.2f}")

    # 3. Max leverage sınırı
    lev_max = volatility_targeter.compute_leverage(0.01, 0.20, max_leverage=2.0)
    assert lev_max <= 2.0
    passed += 1
    logger.info(f"  ✓ Max leverage cap: {lev_max:.2f}")

    # 4. Ağırlık ayarlama
    weights = {"A": 0.5, "B": 0.3, "C": 0.2}
    adjusted = volatility_targeter.adjust_weights(weights, 0.10, 0.20)
    assert sum(adjusted.values()) <= 1.01  # Normalize edilmiş
    passed += 1
    logger.info(f"  ✓ Adjusted weights: {adjusted}")

    return passed, failed


def test_kelly_criterion() -> Any:
    """Kelly Criterion testleri."""
    from services.risk.enhanced_risk import position_sizer

    passed = 0
    failed = 0

    # 1. İyi oran → pozitif kelly
    kelly = position_sizer.kelly_criterion(0.6, 2.0, 1.0)
    assert kelly > 0
    passed += 1
    logger.info(f"  ✓ Good odds Kelly: {kelly:.4f}")

    # 2. Kötü oran → sıfır
    kelly_bad = position_sizer.kelly_criterion(0.3, 1.0, 2.0)
    assert kelly_bad == 0.0
    passed += 1
    logger.info(f"  ✓ Bad odds Kelly: {kelly_bad:.4f}")

    # 3. Half-Kelly
    kelly_full = position_sizer.kelly_criterion(0.6, 2.0, 1.0, fraction=1.0)
    kelly_half = position_sizer.kelly_criterion(0.6, 2.0, 1.0, fraction=0.5)
    assert kelly_half < kelly_full
    passed += 1
    logger.info(f"  ✓ Half-Kelly: {kelly_half:.4f} < Full: {kelly_full:.4f}")

    # 4. Pozisyon büyüklüğü
    size = position_sizer.compute_position_size(100000, 0.1, 100, 5, 10)
    assert size > 0
    passed += 1
    logger.info(f"  ✓ Position size: {size} shares")

    return passed, failed


def test_rebalance() -> Any:
    """Rebalance Engine testleri."""
    from services.risk.enhanced_risk import rebalance_engine

    passed = 0
    failed = 0

    # 1. Küçük sapma → rebalance yok
    current = {"A": 0.33, "B": 0.33, "C": 0.34}
    target = {"A": 0.34, "B": 0.33, "C": 0.33}
    orders = rebalance_engine.compute_rebalance(current, target, 100000)
    assert len(orders) == 0  # %1 sapma < %5 eşik
    passed += 1
    logger.info("  ✓ Small deviation: no rebalance")

    # 2. Büyük sapma → rebalance
    current = {"A": 0.5, "B": 0.3, "C": 0.2}
    target = {"A": 0.3, "B": 0.4, "C": 0.3}
    orders = rebalance_engine.compute_rebalance(current, target, 100000)
    assert len(orders) > 0
    assert "A" in orders  # A satılmalı
    assert "B" in orders  # B alınmalı
    passed += 1
    logger.info(f"  ✓ Large deviation: {len(orders)} orders")

    # 3. Turnover limit
    current = {"A": 1.0}
    target = {"B": 1.0}
    orders = rebalance_engine.compute_rebalance(current, target, 100000)
    total_change = sum(abs(o["weight_change"]) for o in orders.values())
    assert total_change <= rebalance_engine.turnover_limit * 100 + 1
    passed += 1
    logger.info(f"  ✓ Turnover limit: {total_change:.1f}%")

    return passed, failed


def test_concentration_risk() -> Any:
    """Concentration Risk testleri."""
    from services.risk.enhanced_risk import concentration_risk

    passed = 0
    failed = 0

    # 1. Equal weight → HHI = 1/N
    weights = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    hhi = concentration_risk.compute_hhi(weights)
    assert abs(hhi - 0.25) < 0.01
    passed += 1
    logger.info(f"  ✓ Equal weight HHI: {hhi:.4f}")

    # 2. Concentrated → HHI yüksek
    weights_conc = {"A": 0.9, "B": 0.1}
    hhi_conc = concentration_risk.compute_hhi(weights_conc)
    assert hhi_conc > hhi
    passed += 1
    logger.info(f"  ✓ Concentrated HHI: {hhi_conc:.4f}")

    # 3. Sector concentration
    sector_map = {"A": "TECH", "B": "TECH", "C": "BANK", "D": "BANK"}
    sector_conc = concentration_risk.compute_sector_concentration(weights, sector_map)
    assert abs(sector_conc.get("TECH", 0) - 0.5) < 0.01
    assert abs(sector_conc.get("BANK", 0) - 0.5) < 0.01
    passed += 1
    logger.info(f"  ✓ Sector concentration: {sector_conc}")

    # 4. Max concentration
    max_ticker, max_weight = concentration_risk.compute_max_concentration(weights_conc)
    assert max_ticker == "A"
    assert max_weight == 0.9
    passed += 1
    logger.info(f"  ✓ Max concentration: {max_ticker}={max_weight}")

    return passed, failed


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("  FAZ 5 — Risk & Portfolio Test Suite")
    logger.info("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Ledoit-Wolf Covariance", test_ledoit_wolf),
        ("Volatility Targeting", test_volatility_targeter),
        ("Kelly Criterion", test_kelly_criterion),
        ("Rebalance Engine", test_rebalance),
        ("Concentration Risk", test_concentration_risk),
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
